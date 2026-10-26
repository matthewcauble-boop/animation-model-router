"""Breath pacer overlay: a small circle that grows on the in-breath and shrinks on the out-breath, burned onto a
workout, stretch or calm-down video. Free and local (ffmpeg + Pillow + numpy). Audio is copied untouched.

    python tools/breathpacer/pacer.py in.mp4 -o out.mp4 [--inhale 5.5 --exhale 5.5] [--color "#E8171C"]
           [--pos top-left|top-right|bottom] [--x 0.15 --y 0.085] [--size 0.11] [--style ring|glass]
           [--start 0] [--phase 0] [--label]

Look (style "ring", the default): a soft matte disc with a gentle glow (no outline), a thin full-size guide ring,
and a progress arc that sweeps the ring once per phase with a bright dot at its head. The disc tops out at 82% of
the ring, so the arc and dot always show. Style "glass" is a glossy sphere instead.
Motion: a smoothed triangle wave (--sharp 0 = sine, 0.97 default), so the circle moves at a steady speed and only
turns round in a quick soft reversal. A sine dwells at the ends and reads as the pacer stopping. Every frame is
drawn at 4x and downsampled, so the edge never steps.

RULE: the pacer must never sit over a character, a label chip or the subtitles. Look at frames across the whole
clip (or run tools/judge with the layout pack, which boxes both and computes the overlap in code) and move it with
--pos or --x/--y.

--size   ring diameter as a fraction of the frame width (default 0.11 on vertical video)
--start  when the pacer fades in (s); it runs to the end
--phase  seconds into the cycle at --start (0 = start of an in-breath, smallest)
--label  tiny "in" / "out" under the circle
Placement presets: top-left (9x16: centre x 15%, y 8.5%), top-right (x 78%, y 10%), bottom (x 50%, y 77%: just under
subtitles at ~70% and above the platform caption area). For 16x9: x 7% / 92% / 50%, y 12% / 12% / 89.5%.
"""
import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("inp"); ap.add_argument("-o", "--out", required=True)
ap.add_argument("--inhale", type=float, default=5.5); ap.add_argument("--exhale", type=float, default=5.5)
ap.add_argument("--phase", type=float, default=0); ap.add_argument("--size", type=float, default=0.11)
ap.add_argument("--start", type=float, default=0); ap.add_argument("--color", default="#E8171C")  # record-button red
ap.add_argument("--sharp", type=float, default=0.97)
ap.add_argument("--label", action="store_true")
ap.add_argument("--pos", default="top-left", choices=["top-left", "top-right", "bottom"])
ap.add_argument("--style", default="ring", choices=["ring", "glass"])
ap.add_argument("--x", type=float); ap.add_argument("--y", type=float)  # custom centre as frame fractions
a = ap.parse_args()

pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                                "-show_entries", "format=duration", "-of", "json", a.inp], capture_output=True, text=True, check=True,
                               creationflags=NOWIN).stdout)
W, H = pr["streams"][0]["width"], pr["streams"][0]["height"]
n, d = map(int, pr["streams"][0]["r_frame_rate"].split("/")); fps = n / d
dur = float(pr["format"]["duration"])
vert = H > W
D = int(W * a.size) if vert else int(W * a.size * 0.6)
cx, cy = {"top-left": ((W * .15, H * .085) if vert else (W * .07, H * .12)),
          "top-right": ((W * .78, H * .10) if vert else (W * .92, H * .12)),
          "bottom": ((W * .5, H * .77) if vert else (W * .5, H * .895))}[a.pos]
if a.x is not None:
    cx = W * a.x
if a.y is not None:
    cy = H * a.y
PAD = int(D * .55); S = D + 2 * PAD
col = tuple(int(a.color[i:i + 2], 16) for i in (1, 3, 5))
CYC = a.inhale + a.exhale
font = None
if a.label:
    try:
        font = ImageFont.truetype("arialbd.ttf", max(12, D // 6))
    except OSError:
        font = ImageFont.load_default()


def soft_disc(R):
    """A soft matte glowing disc: lighter core, gentle edge falloff, no outline. Built once, scaled per frame."""
    N = 2 * R; yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    dd = np.sqrt(((xx - R + .5) / R) ** 2 + ((yy - R + .5) / R) ** 2)
    inside = np.clip((1 - dd) * R * .5, 0, 1)
    c = np.array(col, np.float32); core = np.minimum(c * 1.12 + 30, 255)
    k = np.clip(1 - dd, 0, 1)[..., None] ** .6
    body = c[None, None] * (1 - k) + core[None, None] * k
    return Image.fromarray(np.dstack([np.clip(body, 0, 255), inside * 255 * .96]).astype(np.uint8), "RGBA")


def glass_sphere(R):
    """A glossy sphere: radial body gradient lit from the top left, a soft caustic glow at the bottom, a wide blurred
    specular crescent, a thin glint and a faint white rim. Nearly opaque, so the background never tints it."""
    N = 2 * R; yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    dx, dy = (xx - R + .5) / R, (yy - R + .5) / R; dd = np.sqrt(dx * dx + dy * dy)
    inside = np.clip((1 - dd) * R * .7, 0, 1)
    c = np.array(col, np.float32)
    hi = np.minimum(c * np.array([1.08, 1.6, 1.6], np.float32) + np.array([18, 28, 28], np.float32), 255); lo = c * .70
    lk = np.clip(1 - np.sqrt((dx + .35) ** 2 + (dy + .45) ** 2) / 1.6, 0, 1)
    body = lo[None, None] + (hi - lo)[None, None] * (lk[..., None] ** 1.4)
    rim = np.clip((dd - .78) / .22, 0, 1)[..., None]
    body = body * (1 - .18 * rim)
    alpha = (.94 + .06 * rim[..., 0]) * inside
    im = Image.fromarray(np.dstack([np.clip(body, 0, 255), alpha * 255]).astype(np.uint8), "RGBA")
    mask = np.array(Image.fromarray((inside * 255).astype(np.uint8), "L"))

    def blob(box, rgba, blur):
        l = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(l).ellipse(box, fill=rgba)
        l = l.filter(ImageFilter.GaussianBlur(blur))
        l.putalpha(Image.fromarray(np.minimum(np.array(l.getchannel("A")), mask).astype(np.uint8), "L"))
        return l
    warm = tuple(int(min(255, v * 1.1 + 40)) for v in col) + (120,)
    im.alpha_composite(blob([R * .35, R * 1.25, R * 1.65, R * 1.9], warm, R * .14))
    im.alpha_composite(blob([R * .30, R * .16, R * 1.40, R * .74], (255, 255, 255, 170), R * .13))
    im.alpha_composite(blob([R * .50, R * .34, R * .80, R * .46], (255, 255, 255, 220), R * .035))
    ring = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([1, 1, N - 2, N - 2], outline=(255, 255, 255, 70), width=max(1, R // 30))
    im.alpha_composite(ring.filter(ImageFilter.GaussianBlur(max(1, R // 60))))
    return im


SPRITE = soft_disc(int(D * 2)) if a.style == "ring" else glass_sphere(int(D * 2))


def breath(t):
    """(k, phase, fraction): k 0 = smallest (breathed out), 1 = largest (breathed in)."""
    c = (t - a.start + a.phase) % CYC
    half = c / a.inhale * .5 if c < a.inhale else .5 + (c - a.inhale) / a.exhale * .5
    th = 2 * math.pi * half - math.pi / 2
    k = .5 + .5 * math.sin(th) if a.sharp <= 0 else .5 + math.asin(a.sharp * math.sin(th)) / (2 * math.asin(a.sharp))
    return k, ("in" if c < a.inhale else "out"), (c / a.inhale if c < a.inhale else (c - a.inhale) / a.exhale)


def frame(t):
    im = Image.new("RGBA", (S, S + (D // 3 if a.label else 0)), (0, 0, 0, 0))
    if t < a.start:
        return im
    fade = min(1, (t - a.start) / .6)
    k, ph, frac = breath(t)
    r = (D / 2) * ((.36 + .46 * k) if a.style == "ring" else (.45 + .55 * k))
    X = 4; big = Image.new("RGBA", (im.width * X, im.height * X), (0, 0, 0, 0)); bd = ImageDraw.Draw(big)
    C0 = S * X / 2; RR = (D / 2) * 1.02 * X
    g = Image.new("RGBA", im.size, (0, 0, 0, 0))
    gr = r * (1.25 if a.style == "ring" else 1.15)
    ImageDraw.Draw(g).ellipse([S / 2 - gr, S / 2 - gr, S / 2 + gr, S / 2 + gr], fill=col + (int((70 if a.style == "ring" else 55) * fade),))
    im.alpha_composite(g.filter(ImageFilter.GaussianBlur(D * .1)))
    if a.style == "ring":
        w = max(2, int(D * .022)) * X
        bd.ellipse([C0 - RR, C0 - RR, C0 + RR, C0 + RR], outline=(255, 255, 255, int(70 * fade)), width=max(X, w // 2))
        if frac > .002:
            bd.arc([C0 - RR, C0 - RR, C0 + RR, C0 + RR], -90, -90 + 360 * frac, fill=(255, 255, 255, int(235 * fade)), width=w)
        ang = math.radians(-90 + 360 * frac); hx, hy = C0 + RR * math.cos(ang), C0 + RR * math.sin(ang); dr = w * 1.4
        bd.ellipse([hx - dr, hy - dr, hx + dr, hy + dr], fill=(255, 255, 255, int(255 * fade)))
        im.alpha_composite(big.resize(im.size, Image.LANCZOS))
    sp = SPRITE.resize((max(2, int(math.ceil(2 * r)) + 2),) * 2, Image.LANCZOS)
    off = S / 2 - sp.width / 2; fr_ = off - math.floor(off)
    sp = sp.transform(sp.size, Image.AFFINE, (1, 0, -fr_, 0, 1, -fr_), Image.BICUBIC)  # sub-pixel centring
    if fade < 1:
        sp.putalpha(sp.getchannel("A").point(lambda v: int(v * fade)))
    im.alpha_composite(sp, (int(math.floor(off)), int(math.floor(off))))
    if a.label:
        ImageDraw.Draw(im).text((S / 2, S + D // 10), ph, font=font, fill=(255, 255, 255, int(255 * fade)), anchor="mt",
                                stroke_width=max(1, D // 40), stroke_fill=(31, 42, 85))
    return im


with tempfile.TemporaryDirectory() as td:
    ov = Path(td) / "ov.mov"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{S}x{frame(0).height}", "-r", f"{fps}",
                          "-i", "-", "-c:v", "qtrle", str(ov)], stdin=subprocess.PIPE, creationflags=NOWIN)
    for i in range(int(math.ceil(dur * fps)) + 1):
        p.stdin.write(frame(i / fps).tobytes())
    p.stdin.close(); p.wait()
    x, y = int(cx - S / 2), int(cy - S / 2)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.inp, "-i", str(ov), "-filter_complex", f"[0:v][1:v]overlay={x}:{y}:shortest=1[v]",
                    "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy",
                    a.out], check=True, creationflags=NOWIN)
print(a.out)
