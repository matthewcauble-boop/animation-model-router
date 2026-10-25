"""sheet: contact sheets for judging takes, and side-by-side strips for keyframe sets.

    python tools/bakeoff/sheet.py takes ROOT [moment ...]     # takes/<moment>/* -> sheets/<take>.jpg + <moment>-all.jpg
    python tools/bakeoff/sheet.py strip OUT.jpg S1.png S2.png ...   # keyframe continuity strip, labelled S1..Sn
    python tools/bakeoff/sheet.py dense OUT.jpg take.mp4 --every 0.5 [--labels labels.json]   # lip-sync sheet

A video take becomes 12 frames spread evenly over the clip (2 rows of 6), each stamped with its time, so a critic can
judge motion, drift and limb errors from one image. A keyframe strip puts every shot of a scene side by side, which is
the fastest way to see a prop move, a character change scale or the set change between shots. A dense sheet samples
every --every seconds; with --labels (a list of [start, end, "who is speaking"]) each tile is stamped with who is
really speaking in the audio, so a critic can check turn-taking in a lip-sync take.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VIDEO = (".mp4", ".mov", ".webm", ".mkv")
IMAGE = (".png", ".jpg", ".jpeg", ".webp")


def font(size):
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def duration(p: Path) -> float:
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(p)],
                       capture_output=True, text=True, creationflags=NOWIN)
    return float(json.loads(o.stdout)["format"]["duration"])


def grab(p: Path, t: float, h: int, tmp: Path, i: int) -> Image.Image:
    f = tmp / f"{i}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(p), "-frames:v", "1", "-vf", f"scale=-2:{h}",
                    "-y", str(f)], creationflags=NOWIN)
    return Image.open(f).convert("RGB")


def grid(tiles, cols, bg="black"):
    w, h = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (w * min(cols, len(tiles)), h * rows), bg)
    for i, im in enumerate(tiles):
        sheet.paste(im.resize((w, h)), ((i % cols) * w, (i // cols) * h))
    return sheet


def video_sheet(p: Path, out: Path, n=12, cols=6, h=420):
    d = duration(p)
    tmp = Path(tempfile.mkdtemp())
    tiles = []
    for i in range(n):
        t = min(d - 0.05, (i + 0.5) * d / n)
        im = grab(p, t, h, tmp, i)
        ImageDraw.Draw(im).text((6, 4), f"{t:.1f}s", fill="yellow", font=font(22), stroke_width=2, stroke_fill="black")
        tiles.append(im)
    shutil.rmtree(tmp, ignore_errors=True)
    s = grid(tiles, cols)
    s.save(out, quality=88)
    return s


def image_sheet(p: Path, out: Path, h=840):
    im = Image.open(p).convert("RGB")
    im = im.resize((int(im.width * h / im.height), h))
    im.save(out, quality=90)
    return im


def takes(root: Path, moments):
    sheets = root / "sheets"
    sheets.mkdir(exist_ok=True)
    moments = moments or sorted(d.name for d in (root / "takes").iterdir() if d.is_dir())
    for m in moments:
        made = []
        for p in sorted((root / "takes" / m).glob("*.*")):
            out = sheets / f"{p.stem}.jpg"
            if p.suffix.lower() in VIDEO:
                made.append((p.stem, video_sheet(p, out)))
            elif p.suffix.lower() in IMAGE:
                made.append((p.stem, image_sheet(p, out)))
        if not made:
            continue
        W = max(im.width for _, im in made)
        H = sum(im.height + 44 for _, im in made)
        allim = Image.new("RGB", (W, H), (30, 30, 30))
        y = 0
        for name, im in made:
            ImageDraw.Draw(allim).text((8, y + 4), name, fill="white", font=font(34))
            allim.paste(im, (0, y + 44))
            y += im.height + 44
        if H > 20000:
            allim = allim.resize((W * 20000 // H, 20000))
        allim.save(sheets / f"{m}-all.jpg", quality=85)
        print(m, len(made), "takes")


def strip(out: Path, frames, w=405, h=720):
    tiles = []
    for i, f in enumerate(frames, 1):
        p = Path(f)
        im = Image.open(p).convert("RGB").resize((w, h)) if p.exists() else Image.new("RGB", (w, h), (90, 90, 90))
        ImageDraw.Draw(im).text((8, 6), f"S{i}", fill="yellow", font=font(26), stroke_width=2, stroke_fill="black")
        tiles.append(im)
    grid(tiles, len(tiles)).save(out, quality=88)


def dense(out: Path, video: Path, every: float, labels, h=360, cols=8):
    d = duration(video)
    tmp = Path(tempfile.mkdtemp())
    tiles, t, i = [], 0.0, 0
    while t < d - 0.02:
        im = grab(video, t, h, tmp, i)
        who = next((x[2] for x in labels if x[0] <= t < x[1]), "silence")
        dr = ImageDraw.Draw(im)
        dr.text((6, 4), f"{t:.1f}s", fill="yellow", font=font(20), stroke_width=2, stroke_fill="black")
        dr.text((6, im.height - 28), f"audio: {who}", fill="white", font=font(18), stroke_width=2, stroke_fill="black")
        tiles.append(im)
        t += every
        i += 1
    shutil.rmtree(tmp, ignore_errors=True)
    grid(tiles, cols).save(out, quality=85)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("takes")
    a1.add_argument("root", type=Path)
    a1.add_argument("moments", nargs="*")
    a2 = sub.add_parser("strip")
    a2.add_argument("out", type=Path)
    a2.add_argument("frames", nargs="+")
    a3 = sub.add_parser("dense")
    a3.add_argument("out", type=Path)
    a3.add_argument("video", type=Path)
    a3.add_argument("--every", type=float, default=0.5)
    a3.add_argument("--labels", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "takes":
        takes(a.root.resolve(), a.moments)
    elif a.cmd == "strip":
        strip(a.out, a.frames)
    else:
        dense(a.out, a.video, a.every, json.loads(a.labels.read_text()) if a.labels else [])


if __name__ == "__main__":
    main()
