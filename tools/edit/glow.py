"""glow: a pulsing coloured glow on a masked region (a knee, a back, a muscle) over a video or a frame sequence.

    python tools/edit/glow.py IN -o OUT (--mask mask.png | --mask-dir mattes/ | --key "#hex" [--tol 40])
           [--color "#ff3c3c"] [--start 0] [--end END] [--fade 0.2] [--pulse 1.6] [--strength 1.0] [--inside 0.38]
           [--soft 6] [--bloom 26] [--ghost] [--fps 24] [--crf 14]

  IN          a video, a folder of frames (sorted by name) or one image.
  OUT         .mp4 (audio copied from a video input, untouched) or a folder (one PNG per frame).
  Mask, one of:
    --mask      one PNG for every frame (white = glow). Any size; it is resized to the frame.
    --mask-dir  one PNG per frame, same names or the same order as the frames (a matte sequence from your matting
                step; the glow then follows the character).
    --key       a colour key: every pixel within --tol (RGB distance) of the colour, opened to drop specks. Cheap,
                but it will also catch any other thing of that colour (test it on a known-good frame first).
  --color     glow colour. Convention used here: red for the wrong form, green for the right one.
  --start/--end/--fade  when it shows, and how fast it comes up (seconds).
  --pulse     pulses per second (0 = steady). Strength swings 0.75..1.0, which reads as "look here" without flicker.
  --inside    how much the colour tints the region itself; the rest is an outer bloom.
  --ghost     X-ray ghost of the masked region instead of the solid drawing: the background (inpainted) shows through
              a pale fill and the outlines glow. Use it for "the wrong way", next to the solid "right way".

Everything is drawn on ones (every frame), so it never steps with the character's twos. Needs numpy, OpenCV,
ffmpeg/ffprobe.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
IMG = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def hex_bgr(h):
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return np.array([b, g, r], np.float32)


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate", "-of",
                        "json", str(p)], capture_output=True, text=True, creationflags=NOWIN)
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    n, dd = v["r_frame_rate"].split("/")
    return v["width"], v["height"], float(n) / float(dd), any(s["codec_type"] == "audio" for s in d["streams"])


def frames_in(path: Path):
    """Yield BGR uint8 frames from a video, a folder of images or one image."""
    if path.is_dir():
        for f in sorted(x for x in path.iterdir() if x.suffix.lower() in IMG):
            yield cv2.imread(str(f), cv2.IMREAD_COLOR)
    elif path.suffix.lower() in IMG:
        yield cv2.imread(str(path), cv2.IMREAD_COLOR)
    else:
        W, H, _, _ = probe(path)
        dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                               stdout=subprocess.PIPE, creationflags=NOWIN)
        n = W * H * 3
        while True:
            buf = dec.stdout.read(n)
            if len(buf) < n:
                break
            yield np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        dec.wait()


def key_mask(fr, color_bgr, tol):
    d = np.linalg.norm(fr.astype(np.float32) - color_bgr[None, None], axis=2)
    m = (d <= tol).astype(np.uint8) * 255
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))


def glow(f, region, color_bgr, strength, inside=0.38, soft=6.0, bloom=26.0):
    """f float32 0..1 BGR; region uint8 0..255. Tint inside the region + a soft outer bloom."""
    if strength <= 0.01 or not region.any():
        return f
    r = region.astype(np.float32) / 255
    s = cv2.GaussianBlur(r, (0, 0), soft)[..., None]
    b = cv2.GaussianBlur(r, (0, 0), bloom)[..., None]
    col = color_bgr[None, None] / 255
    f = f * (1 - s * inside * strength) + col * s * inside * strength
    return np.clip(f + col * b * 0.9 * strength, 0, 1)


def ghost(fr, body):
    """X-ray ghost: inpainted background through a pale fill, outlines glowing. fr uint8 BGR, body uint8 mask."""
    H, W = body.shape
    b = (body > 127).astype(np.uint8)
    small = cv2.resize(fr, (W // 2, H // 2))
    bs = cv2.dilate(cv2.resize(b, (W // 2, H // 2), interpolation=cv2.INTER_NEAREST), np.ones((9, 9), np.uint8))
    bg = cv2.resize(cv2.inpaint(small, bs * 255, 5, cv2.INPAINT_TELEA), (W, H), interpolation=cv2.INTER_CUBIC)
    bgf = bg.astype(np.float32) / 255
    lum = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    dark, pale = np.array([170, 120, 60], np.float32) / 255, np.array([255, 235, 190], np.float32) / 255
    g = bgf * 0.42 + (dark * (1 - lum[..., None]) + pale * lum[..., None]) * 0.58
    lines = cv2.dilate(((lum < 0.22) & (b > 0)).astype(np.float32), np.ones((2, 2), np.uint8))
    g = np.clip(g + np.array([255, 240, 170], np.float32) / 255 * cv2.GaussianBlur(lines, (0, 0), 5)[..., None] * 0.9, 0, 1)
    g = g * (1 - lines[..., None]) + np.array([255, 250, 230], np.float32) / 255 * lines[..., None]
    rim = cv2.GaussianBlur(cv2.morphologyEx(b.astype(np.float32), cv2.MORPH_GRADIENT, np.ones((5, 5), np.uint8)), (0, 0), 7)
    g = np.clip(g + np.array([255, 220, 120], np.float32) / 255 * rim[..., None] * 0.8, 0, 1)
    soft = cv2.GaussianBlur(b.astype(np.float32), (0, 0), 1.5)[..., None]
    return bgf * (1 - soft) + g * soft


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--mask", type=Path)
    g.add_argument("--mask-dir", type=Path)
    g.add_argument("--key")
    ap.add_argument("--tol", type=float, default=40.0)
    ap.add_argument("--color", default="#ff3c3c")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--fade", type=float, default=0.2)
    ap.add_argument("--pulse", type=float, default=1.6)
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--inside", type=float, default=0.38)
    ap.add_argument("--soft", type=float, default=6.0)
    ap.add_argument("--bloom", type=float, default=26.0)
    ap.add_argument("--ghost", action="store_true")
    ap.add_argument("--fps", type=float, default=24.0, help="for frame-folder input (a video keeps its own)")
    ap.add_argument("--crf", type=int, default=14)
    a = ap.parse_args(argv)

    is_video = a.input.is_file() and a.input.suffix.lower() not in IMG
    fps, audio = a.fps, False
    if is_video:
        _, _, fps, audio = probe(a.input)
    col = hex_bgr(a.color)
    static = cv2.imread(str(a.mask), cv2.IMREAD_GRAYSCALE) if a.mask else None
    if a.mask and static is None:
        sys.exit(f"cannot read mask {a.mask}")
    seq = sorted(x for x in a.mask_dir.iterdir() if x.suffix.lower() in IMG) if a.mask_dir else None
    keycol = hex_bgr(a.key) if a.key else None

    to_video = a.output.suffix.lower() in (".mp4", ".mov", ".m4v")
    enc, tmp = None, a.output.with_suffix(".video" + a.output.suffix) if to_video else None
    if not to_video:
        a.output.mkdir(parents=True, exist_ok=True)
    n, lit = 0, 0
    for fr in frames_in(a.input):
        H, W = fr.shape[:2]
        t = n / fps
        if static is not None:
            m = static if static.shape == (H, W) else cv2.resize(static, (W, H), interpolation=cv2.INTER_LINEAR)
        elif seq is not None:
            if n >= len(seq):
                sys.exit(f"--mask-dir has {len(seq)} masks; the input has more frames")
            m = cv2.imread(str(seq[n]), cv2.IMREAD_GRAYSCALE)
            m = m if m.shape == (H, W) else cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR)
        else:
            m = key_mask(fr, keycol, a.tol)
        on = t >= a.start and (a.end is None or t < a.end)
        f = fr.astype(np.float32) / 255
        if on:
            if a.ghost:
                f = ghost(fr, m)
            ramp = min(1.0, (t - a.start) / a.fade) if a.fade > 0 else 1.0
            pulse = 0.75 + 0.25 * math.sin(2 * math.pi * a.pulse * t) if a.pulse > 0 else 1.0
            f = glow(f, m, col, a.strength * ramp * pulse, a.inside, a.soft, a.bloom)
            lit += 1
        out = (np.clip(f, 0, 1) * 255).astype(np.uint8)
        if to_video:
            if enc is None:
                enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                                        f"{W}x{H}", "-r", f"{fps}", "-i", "-", "-c:v", "libx264", "-crf", str(a.crf),
                                        "-preset", "medium", "-pix_fmt", "yuv420p", str(tmp)],
                                       stdin=subprocess.PIPE, creationflags=NOWIN)
            enc.stdin.write(out.tobytes())
        else:
            cv2.imwrite(str(a.output / f"{n:05d}.png"), out)
        n += 1
    if n == 0:
        sys.exit("no frames read")
    if enc:
        enc.stdin.close(); enc.wait()
        if audio:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-i", str(a.input), "-map", "0:v", "-map",
                            "1:a", "-c", "copy", "-movflags", "+faststart", str(a.output)], check=True, creationflags=NOWIN)
            tmp.unlink()
        else:
            tmp.replace(a.output)
    print(json.dumps({"frames": n, "glow_frames": lit, "fps": fps, "audio": "copied" if audio else "none",
                      "output": str(a.output)}))


if __name__ == "__main__":
    main()
