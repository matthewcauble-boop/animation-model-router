"""vosync: does what is said match what is on screen, at that moment?

    python tools/vosync/vosync.py VIDEO --lines LINES.json [--timeline timeline.json] [--frames 5]
           [--backend none|fal|openai] [--model MODEL] [--kind exercise|explainer] [--judge pose] [--out DIR]
           [--max-cost 0.2]

The rule it enforces (every video with a narrator, see LESSONS.md): each line lands on the picture it describes;
a "switch sides" cue comes just before the switch; no line runs past its shot (hold the shot, never speed up the
voice); on-screen text says what the voice says at that moment.

LINES.json: a list of {"id", "start", "end", "text"} (seconds in the video), optionally
  "shot": the shot id the line is about;
  "kind": "switch" for an "other side / switch" cue that is meant to lead into the next shot;
  "screen_text": the caption or label that should be on screen while the line plays (checked by the vision pass).
A build timeline.json with a "vo" list (and "shots": [{"id", "start", "end"}]) is accepted as-is.

Output, in vosync-<stem>/ beside the video (or --out):
  sheet.jpg    one strip per line: 4-6 frames spread across the line, stamped with time and shot, the line's text
               above; a red divider = a cut between two frames, a pink header = the line has findings.
               A REVIEWER MUST OPEN THIS SHEET: code checks only catch timing; only eyes (or a vision backend)
               catch "the character isn't doing what the line says".
  strips/      one jpg per line       report.md / report.json
Exit code 1 if any P0.

Free code checks (need shots, from --timeline or the lines file):
  overlap        P0  two lines overlap
  crosses_cut    P1  a normal line runs past the end of the shot it starts in (the words land on the next move)
  early          P1  a line starts more than 0.3 s before its own shot (when "shot" is given)
  wrong_shot     P1  a line starts in a different shot from its "shot"
  switch_timing  P1  a switch cue must start 0.3-0.8 s before a cut and end within 0.9 s after it
Paid checks (only when you choose them):
  --backend fal|openai   a vision model sees the line's frames and text: does the move (or graphic) match the line
                         now, and does the on-screen text match "screen_text"? A confident no (>= 0.7) is P0, an
                         unsure no P1. About $0.001 per line on a flash-lite class model.
  --judge PACKS          tools/judge packs (default "pose") on lines that name a position (grip, hands, knee, leg,
                         fold, lunge, lean, palms, arms up/out), on the line's inner frames with the line as the label;
                         the line's best frame must pass. Clear fail = P0, unsure = P2.
An HTTP 401/402/403 from a provider (no key, empty balance, locked account) stops the run with a message.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FONTS = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
POSITION = re.compile(r"\b(grip|grips|hands|knee|knees|leg|legs|fold|lunge|lean|palms?|arms? (?:up|out|overhead))\b", re.I)


def font(sz):
    for f in FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


def env_key(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    env = Path(os.environ.get("AMR_ENV_FILE", ".env"))
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines() if env.exists() else []:
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"') or None
    return None


def duration(v):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(v)],
                                         creationflags=NOWIN))


def grab(v, t, w=270):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0, t):.3f}", "-i", str(v), "-frames:v", "1",
                        "-vf", f"scale={w}:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, creationflags=NOWIN)
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def load_lines(p):
    d = json.loads(Path(p).read_text(encoding="utf-8"))
    lines = d["vo"] if isinstance(d, dict) and "vo" in d else d["lines"] if isinstance(d, dict) else d
    shots = d.get("shots") if isinstance(d, dict) else None
    out = []
    for l in lines:
        if "end" not in l and "dur" in l:
            l = {**l, "end": l["start"] + l["dur"]}
        out.append({"id": str(l["id"]), "start": float(l["start"]), "end": float(l["end"]), "text": l.get("text", ""),
                    "shot": l.get("shot"), "kind": l.get("kind", "normal"), "screen_text": l.get("screen_text")})
    return sorted(out, key=lambda l: l["start"]), shots


def sid(s):
    return s.get("id", s.get("shot")) if s else None


def shot_at(shots, t):
    for s in shots or []:
        if s["start"] <= t < s["end"]:
            return s
    return (shots or [None])[-1]


def code_checks(lines, shots):
    f = []
    for a, b in zip(lines, lines[1:]):
        if b["start"] < a["end"] - 0.02:
            f.append({"line": b["id"], "sev": "P0", "check": "overlap", "detail": f"starts {b['start']:.2f} before {a['id']} ends {a['end']:.2f}"})
    if not shots:
        return f
    ids = [sid(s) for s in shots]
    for l in lines:
        s0 = shot_at(shots, l["start"])
        if l["kind"] == "switch":
            cut = min((s["start"] for s in shots if s["start"] > l["start"]), default=None)
            if cut is None or not (0.3 <= cut - l["start"] <= 0.8 + 1e-3) or l["end"] > cut + 0.9:
                f.append({"line": l["id"], "sev": "P1", "check": "switch_timing",
                          "detail": f"switch cue {l['start']:.2f}-{l['end']:.2f}, next cut {cut}: start 0.3-0.8 s before it, end <= cut + 0.9"})
            continue
        if l.get("shot") and l["shot"] in ids:
            own = shots[ids.index(l["shot"])]
            if sid(s0) != l["shot"]:
                f.append({"line": l["id"], "sev": "P1", "check": "wrong_shot", "detail": f"starts in shot {sid(s0)}, is about {l['shot']}"})
            if l["start"] < own["start"] - 0.3:
                f.append({"line": l["id"], "sev": "P1", "check": "early", "detail": f"starts {own['start'] - l['start']:.2f} s before its shot"})
        if l["end"] > s0["end"] + 0.05:
            f.append({"line": l["id"], "sev": "P1", "check": "crosses_cut",
                      "detail": f"runs {l['end'] - s0['end']:.2f} s past the end of shot {sid(s0)} ({s0['end']:.2f}): hold the shot longer"})
    return f


def http_json(url, body, headers, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            err = e.read().decode(errors="replace")[:300]
            if e.code in (401, 402, 403):
                raise SystemExit(f"STOP: {url.split('/')[2]} HTTP {e.code} (key, balance or account lock): {err}")
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (i + 1)); continue
            raise RuntimeError(f"HTTP {e.code}: {err}")
        except urllib.error.URLError:
            time.sleep(3 * (i + 1))
    raise RuntimeError("vision request failed")


def ask_vision(frames, line, backend, model, kind):
    def uri(im):
        im = im.copy(); im.thumbnail((640, 640))  # full-size 1080x1920 frames x6 in one request got the connection reset
        b = io.BytesIO(); im.save(b, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    what = ("an animated explainer video" if kind == "explainer" else "a cartoon exercise or how-to video")
    match = ("Does what is on screen (the graphic, label, numbers, or the characters talking or reacting) illustrate what is "
             "being said at this moment, rather than something unrelated or from a different line?" if kind == "explainer" else
             "Does the character's movement or position in these frames match this spoken instruction at this moment (the "
             "move described is the one being done in these frames, not the one before or after)?")
    txt = (f" Also: does the main on-screen text say the same thing as \"{line['screen_text']}\"?" if line.get("screen_text") else "")
    prompt = (f"These {len(frames)} frames come from {what}, in time order, spanning the moment a narrator says: \"{line['text']}\". "
              f"{match}{txt} Reply with JSON only: {{\"match\": \"yes\"|\"no\", \"confidence\": 0-1, "
              + ("\"text_match\": \"yes\"|\"no\", " if txt else "") + "\"reason\": \"<max 20 words>\"}")
    urls = [uri(im) for im in frames]
    if backend == "fal":
        key = env_key("FAL_KEY")
        if not key:
            raise SystemExit("STOP: FAL_KEY not set")
        body = {"model": model or "google/gemini-3.5-flash-lite", "prompt": prompt, "image_urls": urls, "temperature": 0}
        try:
            r = http_json("https://fal.run/openrouter/router/vision", body, {"Authorization": "Key " + key})
        except RuntimeError as e:  # some router models refuse without reasoning
            if "easoning" not in str(e):
                raise
            r = http_json("https://fal.run/openrouter/router/vision", dict(body, reasoning=True), {"Authorization": "Key " + key})
        out, cost = r.get("output", ""), float((r.get("usage") or {}).get("cost") or 0.0)
    else:
        base, key = os.environ.get("VOSYNC_OPENAI_BASE", "https://api.openai.com/v1"), env_key("VOSYNC_OPENAI_KEY") or ""
        content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": u}} for u in urls]
        r = http_json(base.rstrip("/") + "/chat/completions", {"model": model or "gpt-4.1-mini", "temperature": 0,
                                                               "messages": [{"role": "user", "content": content}]},
                      {"Authorization": "Bearer " + key} if key else {})
        out, cost = r["choices"][0]["message"]["content"], 0.0
    i, j = out.find("{"), out.rfind("}")
    try:
        return json.loads(out[i:j + 1]), cost
    except Exception:  # noqa: BLE001 - an unreadable answer is reported, never read as a match
        return {"match": "unknown", "confidence": 0, "reason": out[:120]}, cost


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video"); ap.add_argument("--lines", required=True); ap.add_argument("--timeline")
    ap.add_argument("--frames", type=int, default=5)
    ap.add_argument("--backend", default="none", choices=["none", "fal", "openai"])
    ap.add_argument("--model"); ap.add_argument("--out"); ap.add_argument("--max-cost", type=float, default=0.2)
    ap.add_argument("--kind", choices=["exercise", "explainer"], default="exercise")
    ap.add_argument("--judge", nargs="?", const="pose", default=None, help="tools/judge packs for lines that name a position")
    ap.add_argument("--judge-backend", default="jev")
    a = ap.parse_args()
    v = Path(a.video).resolve(); out = Path(a.out) if a.out else v.parent / f"vosync-{v.stem}"
    (out / "strips").mkdir(parents=True, exist_ok=True)
    lines, shots = load_lines(a.lines)
    if a.timeline:
        shots = json.loads(Path(a.timeline).read_text(encoding="utf-8")).get("shots", shots)
    D = duration(v); n = max(4, min(6, a.frames)); findings = code_checks(lines, shots); cost = 0.0
    J = None
    if a.judge:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "judge"))
        import judge as judgemod
        import types
        J = judgemod.Judge(types.SimpleNamespace(questions=str(Path(judgemod.HERE) / "questions"),
                                                 packs=str(Path(judgemod.HERE) / "packs.example.json"),
                                                 model_file=str(Path(judgemod.HERE) / "model.json"), ref=[], backend=a.judge_backend,
                                                 model=None, max_side=1024, max_cost=a.max_cost, dry_run=False))
    strips, tw = [], 270
    for l in lines:
        ts = [min(D - 0.05, max(0.0, l["start"] + (l["end"] - l["start"]) * k / (n - 1))) for k in range(n)]
        fr = [grab(v, t, tw) for t in ts]
        if a.backend != "none":
            if cost > a.max_cost:
                raise SystemExit(f"STOP: --max-cost {a.max_cost} reached")
            ans, c = ask_vision(fr, l, a.backend, a.model, a.kind); cost += c; l["vision"] = ans
            conf = float(ans.get("confidence") or 0)
            if str(ans.get("match", "")).lower().startswith("n"):
                findings.append({"line": l["id"], "sev": "P0" if conf >= 0.7 else "P1", "check": "picture_mismatch", "detail": ans.get("reason", "")})
            if str(ans.get("text_match", "")).lower().startswith("n"):
                findings.append({"line": l["id"], "sev": "P1", "check": "text_mismatch", "detail": f"on-screen text is not \"{l['screen_text']}\""})
        if J and POSITION.search(l["text"]):
            jd = out / "judge"; jd.mkdir(exist_ok=True); items = []
            for k, t in enumerate(ts[1:-1]):  # inner frames: the position should be showing while the line is said
                p = jd / f"{l['id']}_{k}.jpg"; grab(v, t, 1080).save(p, quality=90); items.append((str(p), t))
            best = {}
            for pk in a.judge.split(","):
                for r in J.run(items, pk.strip(), labels=[l["text"]] * len(items), prev=None):
                    for vn, vv in r["verdicts"].items():
                        if vv["call"] != "n/a" and vv["p_ok"] >= best.get(vn, (-1,))[0]:
                            best[vn] = (vv["p_ok"], vv["call"], r["t"])
            cost += J.spent; J.spent = 0.0
            l["judge"] = {vn: {"p_ok": b[0], "call": b[1], "t": b[2]} for vn, b in best.items()}
            for vn, (p_ok, call, t) in best.items():
                if call in ("fail", "unsure"):
                    findings.append({"line": l["id"], "sev": "P0" if call == "fail" else "P2", "check": f"judge:{vn}",
                                     "detail": f"best frame p_ok {p_ok:.2f} at {t:.2f}s"})
        hgt = fr[0].height; strip = Image.new("RGB", (tw * n, hgt + 70), "white"); d = ImageDraw.Draw(strip)
        bad = [x for x in findings if x["line"] == l["id"]]
        d.rectangle((0, 0, tw * n, 66), fill=(255, 225, 225) if bad else (235, 245, 255))
        d.text((8, 6), f"{l['id']}  {l['start']:.2f}-{l['end']:.2f}s  [{l.get('shot') or '-'}{' / switch' if l['kind'] == 'switch' else ''}]",
               font=font(20), fill=(20, 20, 60))
        d.text((8, 34), f"\"{l['text']}\"", font=font(22), fill=(140, 0, 80))
        for k, (im, t) in enumerate(zip(fr, ts)):
            strip.paste(im, (k * tw, 70)); s = shot_at(shots, t)
            d.rectangle((k * tw, 70, k * tw + 130, 96), fill=(0, 0, 0)); d.text((k * tw + 6, 72), f"{t:.2f}s {sid(s) or ''}", font=font(18), fill="white")
            if k and shots and shot_at(shots, ts[k - 1]) is not s:
                d.line((k * tw, 70, k * tw, 70 + hgt), fill=(255, 0, 0), width=6)  # a cut falls between these frames
        strip.save(out / "strips" / f"{l['id']}.jpg", quality=88); strips.append(strip)
    W = max(s.width for s in strips); sheet = Image.new("RGB", (W, sum(s.height + 8 for s in strips)), (90, 90, 90)); y = 0
    for s in strips:
        sheet.paste(s, (0, y)); y += s.height + 8
    sheet.save(out / "sheet.jpg", quality=86)
    p0 = sum(f["sev"] == "P0" for f in findings); p1 = sum(f["sev"] == "P1" for f in findings)
    md = [f"# vosync: {v.name}", "", f"{len(lines)} lines, {n} frames each, backend {a.backend}, cost ${cost:.4f}. "
          f"**{p0} P0, {p1} P1.** A red divider in a strip = a cut between those frames.", "",
          "Reviewer: open `sheet.jpg` and check every strip: does the character do what the line says, while it is said?", "",
          "| line | start-end | shot | text | findings |", "|---|---|---|---|---|"]
    for l in lines:
        fs = "; ".join(f"{f['sev']} {f['check']}: {f['detail']}" for f in findings if f["line"] == l["id"]) or "ok"
        md.append(f"| {l['id']} | {l['start']:.2f}-{l['end']:.2f} | {l.get('shot') or ''} | {l['text']} | {fs} |")
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps({"video": v.name, "lines": lines, "findings": findings, "cost_usd": cost}, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out), "lines": len(lines), "P0": p0, "P1": p1, "cost_usd": round(cost, 4)}))
    sys.exit(1 if p0 else 0)


if __name__ == "__main__":
    main()
