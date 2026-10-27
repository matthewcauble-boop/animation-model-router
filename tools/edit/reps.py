"""reps: build N repetitions of a move from ONE paid clip that goes top -> bottom (one squat down, one push-up down).

    python tools/edit/reps.py rep.mp4 -o reps.mp4 [--reps 3] [--first 0] [--last LAST] [--skip 36-50 ...]
           [--down 0.65] [--up 0.6] [--bottom-hold 0.25] [--top-hold 0.2] [--alive 2] [--twos] [--lead 0]
           [--fps 24] [--report reps.json]

Each rep is: forward (top -> bottom), hold, the same frames reversed (bottom -> top), hold. One 3-5 s generation
becomes as many reps as the voice-over needs, at the pace the voice sets, for $0 more.

  --first/--last  the usable frame range of the source (drop a bad start or a model's drift at the end).
  --skip A-B      frames never to use (an off-model squash, a smeared in-between); the ramp jumps over them.
                  Repeatable. Inclusive.
  --down/--up     seconds for each half (default: the source's own pace). The frames are re-timed by index (a ramp),
                  never interpolated, so every drawing is a real one.
  --bottom-hold/--top-hold  seconds held at the bottom and the top. A held drawing reads as intent.
  --alive N       holds are "alive": the held pose drifts between it and its N nearest neighbour drawings, one drawing
                  every 3 frames, instead of a dead freeze. 0 = dead hold. Default 2.
  --twos          each drawing is shown for two frames (classic twos) inside the moves; holds are already holds.
  --lead          seconds of top hold before the first rep (room for the line that introduces it).
  --report        JSON with each rep's down / bottom / up / top times, so cue pills, ticks and SFX land on the
                  bottom of every rep.

Output is silent video (the mix is done later). Needs numpy + ffmpeg/ffprobe.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "json", str(p)], capture_output=True, text=True,
                       creationflags=NOWIN)
    v = json.loads(r.stdout)["streams"][0]
    n, d = v["r_frame_rate"].split("/")
    return v["width"], v["height"], float(n) / float(d)


def read_frames(p, W, H):
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(p), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE, creationflags=NOWIN)
    out, n = [], W * H * 3
    while True:
        b = dec.stdout.read(n)
        if len(b) < n:
            break
        out.append(b)
    dec.wait()
    return out


def ramp(usable, n):
    """n output indices walking through the usable source frames in order (by index, no interpolation)."""
    if n <= 0:
        return []
    k = len(usable)
    return [usable[int(round(j * (k - 1) / max(1, n - 1)))] for j in range(n)]


def twos(seq):
    return [seq[(i // 2) * 2] for i in range(len(seq))]


def hold(i, usable, n, alive):
    """n frames holding drawing i; alive = ping-pong over its `alive` nearest usable neighbours, one per 3 frames."""
    if n <= 0:
        return []
    if alive <= 0:
        return [i] * n
    p = usable.index(i)
    nb = usable[max(0, p - alive):p + alive + 1]
    # start on i, drift away from the end of the move and back
    side = nb[: nb.index(i) + 1][::-1] if p == len(usable) - 1 or p > len(usable) // 2 else nb[nb.index(i):]
    path = side + side[-2:0:-1] if len(side) > 1 else side
    return [path[(k // 3) % len(path)] for k in range(n)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--last", type=int)
    ap.add_argument("--skip", action="append", default=[])
    ap.add_argument("--down", type=float)
    ap.add_argument("--up", type=float)
    ap.add_argument("--bottom-hold", type=float, default=0.25)
    ap.add_argument("--top-hold", type=float, default=0.2)
    ap.add_argument("--alive", type=int, default=2)
    ap.add_argument("--twos", action="store_true")
    ap.add_argument("--lead", type=float, default=0.0)
    ap.add_argument("--fps", type=float, help="output fps (default: the source's)")
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    if not a.input.is_file():
        sys.exit(f"no such file: {a.input}")

    W, H, sfps = probe(a.input)
    fps = a.fps or sfps
    frames = read_frames(a.input, W, H)
    if not frames:
        sys.exit("no frames read")
    last = len(frames) - 1 if a.last is None else min(a.last, len(frames) - 1)
    bad = set()
    for s in a.skip:
        x, y = (int(v) for v in s.split("-"))
        bad.update(range(x, y + 1))
    usable = [i for i in range(a.first, last + 1) if i not in bad]
    if len(usable) < 2:
        sys.exit("fewer than 2 usable frames")
    F = lambda sec: max(1, int(round(sec * fps)))
    nat = len(usable) / sfps
    nd, nu = F(a.down if a.down else nat), F(a.up if a.up else nat)
    down = ramp(usable, nd)
    up = ramp(usable, nu)[::-1]
    if a.twos:
        down, up = twos(down), twos(up)
    top, bottom = usable[0], usable[-1]

    seq, reps = hold(top, usable, int(round(a.lead * fps)), a.alive), []
    for _ in range(a.reps):
        t0 = len(seq)
        seq += down
        b0 = len(seq)
        seq += hold(bottom, usable, int(round(a.bottom_hold * fps)), a.alive)
        u0 = len(seq)
        seq += up
        tp = len(seq)
        seq += hold(top, usable, int(round(a.top_hold * fps)), a.alive)
        reps.append({"down": round(t0 / fps, 3), "bottom": round(b0 / fps, 3), "up": round(u0 / fps, 3),
                     "top": round(tp / fps, 3)})

    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", f"{fps}", "-i", "-", "-c:v", "libx264", "-crf", str(a.crf), "-preset", "medium",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(a.output)],
                           stdin=subprocess.PIPE, creationflags=NOWIN)
    for i in seq:
        enc.stdin.write(frames[i])
    enc.stdin.close()
    enc.wait()
    if enc.returncode:
        sys.exit("encode failed")
    rep = {"input": str(a.input), "output": str(a.output), "fps": fps, "frames": len(seq),
           "duration": round(len(seq) / fps, 3), "usable_source_frames": len(usable), "skipped": sorted(bad),
           "reps": reps}
    if a.report:
        a.report.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("frames", "duration", "usable_source_frames", "reps")}))


if __name__ == "__main__":
    main()
