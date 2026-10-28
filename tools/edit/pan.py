"""pan: an eased camera pan or push across a large plate, with parallax layers and holds, to MP4. $0, local.
The classic establishing move: hold on the wide, ease into a slow pan (slow in, slow out), arrive, hold, then cut
to the hero in action. Camera moves are drawn on ones.

    python tools/edit/pan.py pan.json -o pan.mp4
    python tools/edit/pan.py --demo DIR          # draws a 3-layer plate (sky, hills, foreground) and renders it

pan.json (paths relative to the file):
  {"size": [1080, 1920], "fps": 24, "ease": "inout",          # inout (cubic) | sine | linear
   "layers": [{"image": "sky.png", "parallax": 0.2},          # back to front; RGBA above the first layer
              {"image": "hills.png", "parallax": 0.6},
              {"image": "fg.png", "parallax": 1.4}],
   "keys": [{"t": 0.0, "x": 900, "y": 1100, "zoom": 1.0, "hold": 1.0},
            {"t": 5.0, "x": 2600, "y": 1050, "zoom": 1.15, "hold": 1.2}]}

  Layers share one coordinate space (the size of the first layer; others are resized to it). x, y = the point of
  that space at the centre of the frame; zoom 1 = one layer pixel per output pixel. "hold" (s) holds a key before
  the move to the next key starts, so a key's "t" is when the camera arrives. A layer with parallax p moves
  p times as far as the camera (1 = the reference layer; < 1 = far away; > 1 = foreground) and zooms 1 + (z-1)p.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ease(u, kind):
    u = min(max(u, 0.0), 1.0)
    if kind == "linear":
        return u
    if kind == "sine":
        return 0.5 - 0.5 * np.cos(np.pi * u)
    return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def camera(keys, t, kind):
    """(x, y, zoom) at time t. Key i is reached at keys[i].t, held for keys[i].hold, then eases to key i+1."""
    if t <= keys[0]["t"]:
        k = keys[0]
        return k["x"], k["y"], k.get("zoom", 1.0)
    for a, b in zip(keys, keys[1:]):
        start = a["t"] + a.get("hold", 0.0)
        if t < start:
            return a["x"], a["y"], a.get("zoom", 1.0)
        if t < b["t"]:
            u = ease((t - start) / max(1e-6, b["t"] - start), kind)
            za, zb = a.get("zoom", 1.0), b.get("zoom", 1.0)
            return (a["x"] + (b["x"] - a["x"]) * u, a["y"] + (b["y"] - a["y"]) * u,
                    float(np.exp(np.log(za) + (np.log(zb) - np.log(za)) * u)))     # zoom eased in log space
    k = keys[-1]
    return k["x"], k["y"], k.get("zoom", 1.0)


def load_layers(spec, base):
    out = []
    ref_size = None
    for i, L in enumerate(spec):
        im = cv2.imread(str(base / L["image"]), cv2.IMREAD_UNCHANGED)
        if im is None:
            raise SystemExit(f"cannot read layer {L['image']}")
        if im.ndim == 2:
            im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        if im.shape[2] == 3:
            im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
        if ref_size is None:
            ref_size = (im.shape[1], im.shape[0])
        elif (im.shape[1], im.shape[0]) != ref_size:
            im = cv2.resize(im, ref_size, interpolation=cv2.INTER_AREA)
        f = im[:, :, [2, 1, 0, 3]].astype(np.float32) / 255.0
        f[:, :, :3] *= f[:, :, 3:4]                      # premultiplied
        out.append((f, float(L.get("parallax", 1.0))))
    return out, ref_size


def render(spec_path, out):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    base = Path(spec_path).resolve().parent
    W, H = spec.get("size", [1080, 1920])
    fps = int(spec.get("fps", 24))
    keys = sorted(spec["keys"], key=lambda k: k["t"])
    layers, _ = load_layers(spec["layers"], base)
    kind = spec.get("ease", "inout")
    k0 = keys[0]
    dur = float(spec.get("duration", keys[-1]["t"] + keys[-1].get("hold", 0.0)))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=NOWIN)
    n = int(round(dur * fps))
    for fi in range(n):
        x, y, z = camera(keys, fi / fps, kind)
        canvas = np.zeros((H, W, 3), np.float32)
        for img, p in layers:
            lx = k0["x"] + (x - k0["x"]) * p
            ly = k0["y"] + (y - k0["y"]) * p
            lz = 1 + (z - 1) * p
            # output pixel (u, v) samples layer pixel (lx + (u - W/2)/lz, ly + (v - H/2)/lz)
            M = np.array([[1 / lz, 0, lx - W / 2 / lz], [0, 1 / lz, ly - H / 2 / lz]], np.float32)
            patch = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                   borderMode=cv2.BORDER_REFLECT)
            canvas = canvas * (1 - patch[:, :, 3:4]) + patch[:, :, :3]
        proc.stdin.write((np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    print(json.dumps(dict(out=str(out), frames=n, fps=fps, duration=round(dur, 3), layers=len(layers))))
    return n


def demo(d):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    W, H = 2400, 1600
    rng = np.random.default_rng(1)
    y = np.linspace(0, 1, H)[:, None, None]
    sky = (np.array([250, 190, 140]) * (1 - y) + np.array([255, 235, 200]) * y) * np.ones((1, W, 1))
    cv2.circle(sky, (700, 700), 90, (255, 248, 225), -1)                    # a low sun
    cv2.imwrite(str(d / "sky.png"), sky[:, :, ::-1].astype(np.uint8))
    hills = np.zeros((H, W, 4), np.uint8)
    xs = np.arange(W)
    top = (900 + 90 * np.sin(xs / 260) + 50 * np.sin(xs / 97)).astype(int)
    for x in xs:
        hills[top[x]:, x] = (95, 140, 110, 255)
    cv2.imwrite(str(d / "hills.png"), hills[:, :, [2, 1, 0, 3]])
    fg = np.zeros((H, W, 4), np.uint8)
    fg[1300:] = (60, 105, 55, 255)
    for _ in range(40):                                                      # foreground tufts and stones
        cx, cy = int(rng.uniform(0, W)), int(rng.uniform(1290, 1600))
        cv2.ellipse(fg, (cx, cy), (int(rng.uniform(20, 60)), int(rng.uniform(10, 30))), 0, 0, 360,
                    (40, 80, 40, 255) if rng.random() < 0.7 else (120, 115, 105, 255), -1)
    cv2.imwrite(str(d / "fg.png"), fg[:, :, [2, 1, 0, 3]])
    spec = {"size": [720, 1280], "fps": 24, "ease": "inout",
            "layers": [{"image": "sky.png", "parallax": 0.15}, {"image": "hills.png", "parallax": 0.6},
                       {"image": "fg.png", "parallax": 1.3}],
            "keys": [{"t": 0.0, "x": 700, "y": 950, "zoom": 1.0, "hold": 0.8},
                     {"t": 4.0, "x": 1500, "y": 1000, "zoom": 1.12, "hold": 0.8}]}
    sp = d / "pan.json"
    sp.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    n = render(sp, d / "pan-demo.mp4")
    a, b = camera(spec["keys"], 0.4, "inout"), camera(spec["keys"], 0.8 + 0.05, "inout")
    assert a[0] == 700 and b[0] - 700 < 1.0, "hold, then a slow start (ease in)"
    assert n == 115, n
    print("demo OK:", d / "pan-demo.mp4")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("spec", nargs="?")
    ap.add_argument("-o", "--out", default="pan.mp4")
    ap.add_argument("--demo", metavar="DIR")
    a = ap.parse_args()
    if a.demo:
        demo(a.demo)
    elif a.spec:
        render(a.spec, a.out)
    else:
        ap.error("give a pan.json or --demo DIR")


if __name__ == "__main__":
    sys.exit(main())
