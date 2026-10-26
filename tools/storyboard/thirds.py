"""Rule-of-thirds check for storyboard frames (vertical 9:16, horizontal 16:9, or any aspect).

For each frame we need four numbers, all as fractions of the frame (0-1, from the top-left):
  horizon_y        the main horizon, or the ground/floor line where the ground meets the far background (null if none)
  main_face        [x, y] centre between the eyes of the main subject (for a non-character subject, its centre)
  secondary        [[x, y], ...] other important subjects or faces
  dead_foreground  share of the frame height at the bottom that is empty ground / floor with nothing of interest

They come from a vision model or from you:
  --backend fal      any vision model on fal's OpenRouter vision endpoint (FAL_KEY); default google/gemini-3.5-flash
  --backend openai   any OpenAI-compatible chat endpoint with image input (THIRDS_OPENAI_BASE, THIRDS_OPENAI_KEY)
  --backend manual   no API at all: read the numbers from the storyboard JSON (each shot's "composition" block)
                     or from --manual FILE ({"S1": {...}, ...}); place them by eye

Code then flags (thresholds are flags you can change):
  horizon in the middle band (default 0.42-0.58): put it on a third instead
  main face farther than 0.10 from the nearest third line, or farther than 0.15 from every third intersection
  dead foreground over 0.25 of the frame height

Output: OUTDIR/<id>-grid.jpg (thirds lines, intersections, horizon in cyan, main face yellow, secondary white, dead
foreground tinted red, OK/FLAG line) and OUTDIR/thirds.json. sheet.py --thirds reads thirds.json.

  python tools/storyboard/thirds.py OUTDIR --storyboard storyboard.json --backend manual
  python tools/storyboard/thirds.py OUTDIR --storyboard storyboard.json --backend fal --max-cost 0.20
  python tools/storyboard/thirds.py OUTDIR frames/S1.png frames/S2.png --backend openai --model gpt-4.1-mini

Paid calls are added to the spend ledger (AMR_LEDGER, default ./spend-ledger.csv). An HTTP 401/402/403 stops the run;
it never falls back to another backend.
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.vision import env_key, _post  # noqa: E402  shared key lookup (.env too) and retrying POST

THIRDS = (1 / 3, 2 / 3)

# ---------------------------------------------------------------- fonts
_FONT_CANDIDATES = {
    True: ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"],
    False: ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf"],
}
_font_cache: dict = {}


def font(size: int, bold: bool = False):
    """First system font found (env STORYBOARD_FONT / STORYBOARD_FONT_BOLD win), else Pillow's built-in font."""
    key = (int(size), bold)
    if key in _font_cache:
        return _font_cache[key]
    names = [os.environ.get("STORYBOARD_FONT_BOLD" if bold else "STORYBOARD_FONT")] + _FONT_CANDIDATES[bold]
    f = None
    for n in names:
        if not n:
            continue
        try:
            f = ImageFont.truetype(n, int(size))
            break
        except OSError:
            continue
    if f is None:
        try:
            f = ImageFont.load_default(int(size))
        except TypeError:  # Pillow < 10.1
            f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# ---------------------------------------------------------------- the question
def question(w: int, h: int) -> str:
    shape = ("vertical 9:16" if h > w * 1.3 else "horizontal 16:9" if w > h * 1.3 else "near-square") + f" ({w}x{h})"
    return (f"You are checking film composition. This is a {shape} frame from a storyboard. Answer ONLY with JSON: "
            '{"horizon_y": <fraction 0-1 from the top of the main horizon OR the ground/floor line where the ground meets '
            'the building/wall/far background, or null if none is visible>, "main_subject": "<who/what the shot is about>", '
            '"main_face": [x, y] (fractions 0-1 from the top-left, the centre between the eyes of the main subject; for a '
            'non-character subject its centre), "secondary": [[x, y], ...] (centres of other important subjects/faces), '
            '"dead_foreground": <fraction of the frame height at the bottom that is empty ground/floor with nothing of '
            'interest>}. Be precise.')


def _jpeg_uri(p: Path) -> tuple[str, int, int]:
    im = Image.open(p).convert("RGB")
    w, h = im.size
    im.thumbnail((1024, 1024))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode(), w, h


def _json_from(text: str) -> dict:
    text = text[text.find("{"): text.rfind("}") + 1]
    return json.loads(text)


def _stop_on_auth(e: Exception):
    s = str(e)
    if any(f"HTTP {c}" in s for c in (401, 402, 403)):
        sys.exit(f"STOP: the vision endpoint refused the call ({s[:160]}). Check the key or balance; not falling back.")
    raise e


def ask_fal(p: Path, model: str) -> tuple[dict, float]:
    key = env_key("FAL_KEY")
    if not key:
        sys.exit("FAL_KEY not set (or use --backend manual)")
    uri, w, h = _jpeg_uri(p)
    body = {"model": model, "prompt": question(w, h), "image_urls": [uri], "temperature": 0}
    try:
        try:
            r = _post("https://fal.run/openrouter/router/vision", body, {"Authorization": f"Key {key}"}, timeout=240)
        except RuntimeError as e:
            if "Reasoning is mandatory" not in str(e):
                raise
            body["reasoning"] = True
            r = _post("https://fal.run/openrouter/router/vision", body, {"Authorization": f"Key {key}"}, timeout=240)
    except RuntimeError as e:
        _stop_on_auth(e)
    return _json_from(r.get("output", "")), float((r.get("usage") or {}).get("cost") or 0.0)


def ask_openai(p: Path, model: str) -> tuple[dict, float]:
    base = os.environ.get("THIRDS_OPENAI_BASE", "https://api.openai.com/v1").rstrip("/")
    key = env_key("THIRDS_OPENAI_KEY") or env_key("OPENAI_API_KEY") or ""
    uri, w, h = _jpeg_uri(p)
    body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": question(w, h)}, {"type": "image_url", "image_url": {"url": uri}}]}]}
    try:
        r = _post(base + "/chat/completions", body, {"Authorization": f"Bearer {key}"} if key else {}, timeout=240)
    except RuntimeError as e:
        _stop_on_auth(e)
    return _json_from(r["choices"][0]["message"]["content"]), 0.0  # cost unknown on a generic endpoint


def ledger(usd: float, model: str, note: str):
    if usd <= 0:
        return
    p = Path(os.environ.get("AMR_LEDGER", "spend-ledger.csv"))
    new = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["date", "tool", "provider", "model", "units", "usd", "note"])
        w.writerow([dt.date.today().isoformat(), "thirds", "fal", model, 1, f"{usd:.5f}", note])


# ---------------------------------------------------------------- verdicts in code
def judge(d: dict, mid=(0.42, 0.58), line_tol=0.10, int_tol=0.15, dead_max=0.25) -> dict:
    d = dict(d)
    flags = []
    hy = d.get("horizon_y")
    if hy is not None and mid[0] <= hy <= mid[1]:
        flags.append(f"horizon mid-frame ({hy:.2f})")
    f = d.get("main_face")
    if f:
        x, y = f
        dline = min(min(abs(x - t) for t in THIRDS), min(abs(y - t) for t in THIRDS))
        dint = min(((x - a) ** 2 + (y - b) ** 2) ** 0.5 for a in THIRDS for b in THIRDS)
        d["face_to_line"], d["face_to_intersection"] = round(dline, 3), round(dint, 3)
        if dline > line_tol or dint > int_tol:
            flags.append(f"main subject off thirds (line {dline:.2f}, intersection {dint:.2f})")
    if (d.get("dead_foreground") or 0) > dead_max:
        flags.append(f"dead foreground {d['dead_foreground']:.2f}")
    d["flags"] = flags
    return d


def overlay(im: Image.Image, d: dict) -> Image.Image:
    """Draw the thirds grid and the composition points onto a copy of im."""
    im = im.convert("RGB").copy()
    W, H = im.size
    s = min(W, H) / 720  # line widths scale with the frame
    lw = max(1, round(2 * s))
    dr = ImageDraw.Draw(im, "RGBA")
    for t in THIRDS:
        dr.line([(W * t, 0), (W * t, H)], fill=(255, 255, 255, 150), width=lw)
        dr.line([(0, H * t), (W, H * t)], fill=(255, 255, 255, 150), width=lw)
    r = 7 * s
    for a in THIRDS:
        for b in THIRDS:
            dr.ellipse([W * a - r, H * b - r, W * a + r, H * b + r], outline=(255, 255, 255, 210), width=lw)
    if d.get("dead_foreground"):
        dr.rectangle([0, H * (1 - d["dead_foreground"]), W, H], fill=(255, 0, 0, 45))
    if d.get("horizon_y") is not None:
        y = H * d["horizon_y"]
        dr.line([(0, y), (W, y)], fill=(0, 230, 255, 230), width=max(2, round(3 * s)))
    for p in d.get("secondary") or []:
        r = 10 * s
        dr.ellipse([W * p[0] - r, H * p[1] - r, W * p[0] + r, H * p[1] + r], outline=(255, 255, 255, 255), width=max(2, round(3 * s)))
    if d.get("main_face"):
        x, y = d["main_face"]
        r = 14 * s
        dr.ellipse([W * x - r, H * y - r, W * x + r, H * y + r], outline=(255, 220, 0, 255), width=max(2, round(4 * s)))
    fl = d.get("flags") or []
    txt = "OK" if not fl else "FLAG: " + "; ".join(fl)
    F = font(max(10, round(min(W, H) * 0.036)), bold=True)
    while F.getlength(txt) > W - 24 and len(txt) > 8:
        txt = txt[:-2]
    dr.text((12, H - F.size * 1.6), txt, fill=(120, 255, 120) if not fl else (255, 90, 90), font=F,
            stroke_width=max(1, round(2 * s)), stroke_fill="black")
    return im


# ---------------------------------------------------------------- CLI
def frames_from_storyboard(path: Path):
    sb = json.loads(path.read_text(encoding="utf-8"))
    for s in sb["shots"]:
        yield s["id"], (path.parent / s["image"]).resolve(), s.get("composition")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("images", nargs="*", help="frames to check (ids = file stems); or use --storyboard")
    ap.add_argument("--storyboard", help="storyboard.json: frames + optional per-shot 'composition' for --backend manual")
    ap.add_argument("--backend", choices=["fal", "openai", "manual"], default="manual")
    ap.add_argument("--model", help="vision model id (fal default google/gemini-3.5-flash, openai default gpt-4.1-mini)")
    ap.add_argument("--manual", help='JSON file {"<id>": {"horizon_y", "main_face", "secondary", "dead_foreground"}}')
    ap.add_argument("--mid", default="0.42,0.58", help="horizon 'middle band' to flag, as lo,hi")
    ap.add_argument("--line-tol", type=float, default=0.10)
    ap.add_argument("--int-tol", type=float, default=0.15)
    ap.add_argument("--dead-max", type=float, default=0.25)
    ap.add_argument("--max-cost", type=float, default=0.50, help="stop a paid run past this many USD")
    a = ap.parse_args(argv)

    items = []
    if a.storyboard:
        items += list(frames_from_storyboard(Path(a.storyboard)))
    items += [(Path(p).stem, Path(p), None) for p in a.images]
    if not items:
        ap.error("no frames: pass images or --storyboard")
    manual = json.loads(Path(a.manual).read_text(encoding="utf-8")) if a.manual else {}
    model = a.model or ("google/gemini-3.5-flash" if a.backend == "fal" else "gpt-4.1-mini")
    mid = tuple(float(v) for v in a.mid.split(","))
    od = Path(a.outdir)
    od.mkdir(parents=True, exist_ok=True)
    res, spent = {}, 0.0
    for sid, p, comp in items:
        if a.backend == "manual":
            raw = manual.get(sid) or comp
            if raw is None:
                print(f"{sid:8s} no manual composition data; skipped (add a 'composition' block or --manual)")
                continue
        else:
            if spent >= a.max_cost:
                sys.exit(f"STOP: --max-cost {a.max_cost} reached (${spent:.4f})")
            raw, usd = (ask_fal if a.backend == "fal" else ask_openai)(p, model)
            spent += usd
            ledger(usd, model, f"thirds {sid}")
        d = judge(raw, mid, a.line_tol, a.int_tol, a.dead_max)
        res[sid] = d
        overlay(Image.open(p), d).save(od / f"{sid}-grid.jpg", quality=88)
        print(f"{sid:8s} horizon {d.get('horizon_y')}  face {d.get('main_face')}  deadfg {d.get('dead_foreground')}  "
              f"{'; '.join(d['flags']) or 'OK'}", flush=True)
    (od / "thirds.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if spent:
        print(f"spent ${spent:.4f}")
    print(f"-> {od / 'thirds.json'}")


if __name__ == "__main__":
    main()
