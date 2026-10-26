"""Annotated storyboard sheet: frames in a grid, numbered, with motion arrows, camera-move end frames, eyelines and a
caption per shot (timing in beats at a BPM, the cut IN, the CAMera move, the action).

  python tools/storyboard/sheet.py storyboard.json                       -> <stem>-sheet.jpg beside the JSON
  python tools/storyboard/sheet.py storyboard.json --thirds              -> also <stem>-thirds.jpg (grid overlays)
  python tools/storyboard/sheet.py storyboard.json --thirds --thirds-json qa/thirds.json   (from thirds.py)
  python tools/storyboard/sheet.py storyboard.json -o board.png --panel-width 300

storyboard.json (paths relative to the JSON file; all coordinates are fractions of the frame, 0-1 from the top-left):
{
  "title": "...", "bpm": 90, "columns": 3, "notes": "footer line (screen direction, rules)",
  "legend": {"weather": "rain slant, always down-right"},        optional: relabel arrow kinds
  "shots": [
    {"id": "S1", "image": "frames/S1.png", "beats": 4,              or "seconds": 2.5
     "cut_in": "how we cut INTO this shot", "camera": "the camera move", "action": "what happens",
     "arrows": [{"kind": "act|cam|eye|weather|exit", "points": [[x, y], [x, y], ...], "label": "optional"}],
     "end_frame": {"x": 0.2, "y": 0.3, "w": 0.6} or null,          h defaults to w (keeps the frame's aspect)
     "composition": {"horizon_y": 0.66, "main_face": [0.33, 0.33], "secondary": [], "dead_foreground": 0.1}}
  ]
}

Arrow kinds: act = subject motion (yellow), cam = camera move (cyan; the end-frame box is cyan too), eye = eyeline
(white dashed), weather = rain/snow/wind slant (blue dashed), exit = exit / screen direction (orange).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thirds import font, judge, overlay  # noqa: E402

COL = {"act": (255, 214, 64), "cam": (80, 220, 255), "eye": (255, 255, 255), "weather": (170, 200, 255),
       "exit": (255, 140, 60)}
DASHED = {"eye", "weather"}
LEGEND = {"act": "subject motion", "cam": "camera move / end frame", "eye": "eyeline (dashed)",
          "weather": "weather slant (dashed)", "exit": "exit / screen direction"}
BG = (18, 16, 22)


def _dashed(d, pts, col, width, dash):
    """Dashes along a polyline, carrying the dash phase across corners."""
    on, left = True, dash
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < seg:
            step = min(left, seg - pos)
            if on:
                a, b = pos / seg, (pos + step) / seg
                d.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
                       fill=col, width=width)
            pos += step
            left -= step
            if left <= 1e-6:
                on, left = not on, dash
    return


def arrow(d, pts, kind, W, H, label=None):
    s = W / 360
    col = COL.get(kind, (255, 255, 255))
    P = [(x * W, y * H) for x, y in pts]
    width = max(2, round((5 if kind in DASHED else 6) * s))
    # dark under-stroke so the arrow reads on any frame
    d.line(P, fill=(0, 0, 0), width=width + max(2, round(3 * s)), joint="curve")
    if kind in DASHED:
        _dashed(d, P, col, width, 16 * s)
    else:
        d.line(P, fill=col, width=width, joint="curve")
    (xa, ya), (xb, yb) = P[-2], P[-1]
    ang, L = math.atan2(yb - ya, xb - xa), 22 * s
    head = [(xb, yb), (xb - L * math.cos(ang - 0.45), yb - L * math.sin(ang - 0.45)),
            (xb - L * math.cos(ang + 0.45), yb - L * math.sin(ang + 0.45))]
    d.polygon(head, fill=col, outline=(0, 0, 0))
    if label:
        F = font(round(15 * s), bold=True)
        d.text((P[0][0] + 6 * s, P[0][1] + 4 * s), label, fill=col, font=F, stroke_width=2, stroke_fill="black")


def panel(img: Image.Image, shot: dict, W: int, H: int) -> Image.Image:
    im = img.convert("RGB").resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    for a in shot.get("arrows") or []:
        if len(a.get("points") or []) >= 2:
            arrow(d, a["points"], a.get("kind", "act"), W, H, a.get("label"))
    ef = shot.get("end_frame")
    if ef:
        s = W / 360
        x0, y0, w = ef["x"], ef["y"], ef["w"]
        h = ef.get("h", w)
        box = [x0 * W, y0 * H, (x0 + w) * W, (y0 + h) * H]
        d.rectangle(box, outline=(0, 0, 0), width=max(3, round(7 * s)))
        d.rectangle(box, outline=COL["cam"], width=max(2, round(4 * s)))
        d.text((box[0] + 8 * s, box[1] + 6 * s), "end frame", fill=COL["cam"], font=font(round(18 * s), True),
               stroke_width=2, stroke_fill="black")
    return im


def wrap(text: str, F, maxw: float) -> list[str]:
    out, line = [], ""
    for w in text.split():
        t = (line + " " + w).strip()
        if line and F.getlength(t) > maxw:
            out.append(line)
            line = w
        else:
            line = t
    return out + ([line] if line else [])


def load(path: Path) -> dict:
    sb = json.loads(path.read_text(encoding="utf-8"))
    for s in sb["shots"]:
        s["_img"] = Image.open((path.parent / s["image"]).resolve())
    return sb


def build(sb: dict, mode: str, comps: dict | None = None, panel_w: int | None = None) -> Image.Image:
    shots = sb["shots"]
    cols = int(sb.get("columns") or min(5, len(shots)))
    rows = math.ceil(len(shots) / cols)
    iw, ih = shots[0]["_img"].size
    W = panel_w or (360 if ih > iw else 480)
    H = round(W * ih / iw)
    s = W / 360
    pad = round(16 * s)
    R, Rb = font(round(16 * s)), font(round(16 * s), True)
    lh = round(19 * s)
    bpm = float(sb.get("bpm") or 0)
    beat = 60 / bpm if bpm else None

    # captions first, so every row gets the height it needs
    caps, t = [], 0.0
    for sh in shots:
        dur = sh["seconds"] if "seconds" in sh else (sh.get("beats", 0) * beat if beat else 0)
        head = f"{t:.1f}-{t + dur:.1f} s" + (f"  ({sh['beats']} beats)" if "beats" in sh and beat else "")
        lines = [(head, "head")]
        if mode == "clean":
            for lab, key, kind in (("IN: ", "cut_in", "meta"), ("CAM: ", "camera", "meta"), ("", "action", "body")):
                if sh.get(key):
                    lines += [(l, kind) for l in wrap(lab + sh[key], R, W - 4)]
        else:
            c = (comps or {}).get(sh["id"]) or {}
            fl = c.get("flags")
            lines += [(l, "flag" if fl else "ok") for l in wrap("FLAG: " + "; ".join(fl) if fl else
                                                              ("OK" if c else "no composition data"), R, W - 4)]
        caps.append(lines)
        t += dur
    total = t
    cap_h = [max(len(c) for c in caps[r * cols:(r + 1) * cols]) * lh + round(10 * s) for r in range(rows)]

    tw = cols * (W + pad) + pad
    TF = font(round(28 * s), True)
    title = sb.get("title", "storyboard") + ("" if mode == "clean" else "  -  rule-of-thirds check")
    if mode == "clean":
        kinds = [k for k in COL if any(a.get("kind", "act") == k for sh in shots for a in sh.get("arrows") or [])
                 or (k == "cam" and any(sh.get("end_frame") for sh in shots))]
        legend = [(k, (sb.get("legend") or {}).get(k, LEGEND[k])) for k in kinds]
    else:
        legend = [("eye", "thirds lines + intersections"), ("cam", "horizon / ground line"),
                  ("act", "main face"), ("exit", "red tint = dead foreground")]
    notes = sb.get("notes") or ""
    if mode == "clean" and total:
        notes = (f"Total {total:.1f} s" + (f" at {bpm:g} bpm (every cut on a beat)." if beat else ".") + " " + notes).strip()
    note_lines = wrap(notes, R, tw - 2 * pad) if notes else []
    top = round(70 * s) + lh + pad
    height = top + sum(H + c + pad for c in cap_h) + len(note_lines) * lh + pad * 2
    sheet = Image.new("RGB", (tw, height), BG)
    d = ImageDraw.Draw(sheet)
    ts = round(28 * s)
    while ts > 12 and TF.getlength(title) > tw - 2 * pad:  # shrink a long title to fit the sheet
        ts -= 1
        TF = font(ts, True)
    d.text((pad, round(14 * s)), title, fill="white", font=TF)

    # legend: a short coloured stroke + label per kind
    x, y = pad, round(58 * s)
    for k, lab in legend:
        seg = round(30 * s)
        if k in DASHED and mode == "clean":
            _dashed(d, [(x, y + lh / 2), (x + seg, y + lh / 2)], COL[k], max(2, round(4 * s)), 7 * s)
        else:
            d.line([(x, y + lh / 2), (x + seg, y + lh / 2)], fill=COL[k], width=max(2, round(4 * s)))
        d.text((x + seg + 6 * s, y), lab, fill=(205, 205, 205), font=R)
        x += seg + 6 * s + R.getlength(lab) + 22 * s
        if x > tw - 200 * s:
            x, y = pad, y + lh

    NF = font(round(36 * s), True)
    colors = {"head": (255, 214, 64), "meta": (190, 220, 255), "body": (255, 255, 255), "flag": (255, 110, 110),
              "ok": (130, 240, 130)}
    y = top
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            if i >= len(shots):
                break
            sh = shots[i]
            x = pad + c * (W + pad)
            if mode == "clean":
                im = panel(sh["_img"], sh, W, H)
            else:
                im = overlay(sh["_img"].convert("RGB").resize((W, H), Image.LANCZOS), (comps or {}).get(sh["id"]) or {"flags": []})
            sheet.paste(im, (x, y))
            d.text((x + 8 * s, y + 4 * s), str(i + 1), fill=(255, 214, 64), font=NF, stroke_width=3, stroke_fill="black")
            d.text((x + W - 8 * s, y + 8 * s), sh["id"], fill="white", font=Rb, anchor="ra", stroke_width=2,
                   stroke_fill="black")
            yy = y + H + round(5 * s)
            for text, kind in caps[i]:
                d.text((x, yy), text, fill=colors[kind], font=Rb if kind == "head" else R)
                yy += lh
        y += H + cap_h[r] + pad
    for l in note_lines:
        d.text((pad, y), l, fill=(200, 200, 200), font=R)
        y += lh
    return sheet


def save(im: Image.Image, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        im.save(out, quality=88, optimize=True)
    else:
        im.save(out, optimize=True)
    print(f"-> {out}  ({im.size[0]}x{im.size[1]}, {out.stat().st_size // 1024} KB)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("storyboard")
    ap.add_argument("-o", "--out", help="output image (.jpg or .png); default <stem>-sheet.jpg beside the JSON")
    ap.add_argument("--thirds", action="store_true", help="also render the rule-of-thirds overlay sheet")
    ap.add_argument("--thirds-json", help="thirds.json from thirds.py; default: each shot's 'composition' block")
    ap.add_argument("--panel-width", type=int, help="pixel width of one frame on the sheet (default 360 for vertical, 480 for wide)")
    a = ap.parse_args(argv)
    p = Path(a.storyboard)
    sb = load(p)
    out = Path(a.out) if a.out else p.with_name(p.stem + "-sheet.jpg")
    save(build(sb, "clean", panel_w=a.panel_width), out)
    if a.thirds:
        if a.thirds_json:
            comps = json.loads(Path(a.thirds_json).read_text(encoding="utf-8"))
        else:
            comps = {s["id"]: judge(s["composition"]) for s in sb["shots"] if s.get("composition")}
        save(build(sb, "thirds", comps, a.panel_width), out.with_name(out.stem.replace("-sheet", "") + "-thirds" + out.suffix))


if __name__ == "__main__":
    main()
