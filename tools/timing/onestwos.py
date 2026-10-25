"""onestwos: re-time smooth AI video to classic animation timing (ones, twos, threes), per shot and per action.

    python tools/timing/onestwos.py IN.mp4 --spec timing.json -o OUT.mp4 [--pick sharpest|first]
           [--report timing-report.json] [--crf 14]

AI video models interpolate everything at 24 fps, so it reads like a motion-smoothed TV, not animation. Real animators
time each action: characters on TWOS (12 drawings a second), fast actions/snaps/impacts on ONES, crowds on THREES,
holds as holds, camera moves and effects on ones (see TIMING.md). This tool does that to a flattened video, in the
edit, after generation:

  * every output frame index is preserved (same frame count, same fps) and the audio stream is copied untouched,
    so dialogue, music and SFX stay in sync to the frame;
  * inside each segment the output holds one source drawing for N frames (N = 1/2/3); hold blocks restart at every
    segment start, so a cut or a ones-window never starts mid-hold;
  * --pick sharpest (default) holds the sharpest frame of each block (anti-smear: interpolated in-betweens are blurry),
    --pick first is classic exposure sheet behaviour;
  * frames that are already a hold (no change) stay a hold whatever the rate.

Camera (the trade-off, per segment "camera"):
  "step"        (default) the whole frame is stepped. Right for a LOCKED-OFF camera: nothing is lost.
  "compensate"  for a camera move baked into the AI clip (a push-in, a pan) where the layers are NOT separated: the
                held drawing is warped by the camera's own motion (similarity transform from ORB features + RANSAC,
                fitted on the background) to where the camera is on THIS frame. The camera glides on ones while the
                drawing holds on twos, which is what a layered cel camera does. Limits: the character rides the
                background warp (fine for slow moves, wrong for parallax), and it needs texture in the background.
  "ones"        keep the segment on ones (a code camera move on a static plate, an FX shot).
If your own pipeline applies the camera move (a code crop/zoom in the edit), the clean fix is to run onestwos on the source
take BEFORE the move and apply the move afterwards on ones; that is true layer separation and beats "compensate".

Spec (timing.json):
{
  "fps": 24, "default": "twos", "pick": "sharpest",
  "segments": [
    {"shot": "S1", "start": 0.0, "end": 3.8, "rate": "twos", "camera": "compensate", "why": "acting; slow push-in"},
    {"start": 1.0, "end": 1.25, "rate": "ones", "why": "sidekick bounce contact + rebound"},     <- later rows win
    {"shot": "S6", "start": 25.6, "end": 28.7, "rate": "ones", "why": "code push-in on a still plate"}
  ]
}
rate: "ones" | "twos" | "threes" | "fours" (a pose hold) | an integer. Later segments override earlier ones, so list the
shot-wide rate first and the ones-windows after it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RATES = {"ones": 1, "twos": 2, "threes": 3, "fours": 4}


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,nb_frames"
                        ":format=duration", "-of", "json", str(p)], capture_output=True, text=True, creationflags=NOWIN)
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    n, dd = v["r_frame_rate"].split("/")
    return {"w": v["width"], "h": v["height"], "fps": float(n) / float(dd), "duration": float(d["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in d["streams"])}


def build_plan(spec, nframes, fps):
    """Per output frame: (rate, block_start, camera). Later segments override earlier ones."""
    rate = np.full(nframes, RATES.get(spec.get("default", "twos"), 2), int)
    cam = np.array([spec.get("camera", "step")] * nframes, object)
    seg_id = np.zeros(nframes, int)  # block alignment restarts where the segment id changes
    for k, s in enumerate(spec.get("segments", []), start=1):
        a = max(0, int(round(s["start"] * fps)))
        b = min(nframes, int(round(s["end"] * fps)))
        r = s.get("rate", spec.get("default", "twos"))
        rate[a:b] = RATES[r] if isinstance(r, str) else int(r)
        if "camera" in s:
            cam[a:b] = s["camera"]
        seg_id[a:b] = k
    src = np.arange(nframes)
    block_start = np.zeros(nframes, int)
    i = 0
    while i < nframes:
        r = rate[i]
        j = i
        while j < nframes and j < i + r and seg_id[j] == seg_id[i] and rate[j] == r:
            j += 1
        block_start[i:j] = i
        i = j
    return rate, block_start, cam, seg_id


def sharpness(fr):
    import cv2
    g = cv2.cvtColor(fr[::4, ::4], cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_32F).var())


def camera_warp(src_fr, ref_fr, dst_fr):
    """Warp src (the held drawing) by the camera motion ref->dst (ref = the frame the drawing came from)."""
    import cv2
    s = 0.5
    a = cv2.cvtColor(cv2.resize(ref_fr, None, fx=s, fy=s), cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(cv2.resize(dst_fr, None, fx=s, fy=s), cv2.COLOR_RGB2GRAY)
    orb = cv2.ORB_create(1500)
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 30 or len(kb) < 30:
        return src_fr, None
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    if len(m) < 30:
        return src_fr, None
    pa = np.float32([ka[x.queryIdx].pt for x in m]) / s
    pb = np.float32([kb[x.trainIdx].pt for x in m]) / s
    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None or inl is None or inl.sum() < 25:
        return src_fr, None
    if np.abs(M - np.array([[1, 0, 0], [0, 1, 0]])).max() < 0.002:
        return src_fr, M
    h, w = src_fr.shape[:2]
    return cv2.warpAffine(src_fr, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE), M


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--pick", choices=["sharpest", "first"])
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    spec = json.loads(a.spec.read_text(encoding="utf-8"))
    info = probe(a.input)
    fps = info["fps"]
    if abs(fps - spec.get("fps", fps)) > 0.01:
        sys.exit(f"input is {fps} fps but the spec says {spec['fps']}; conform first")
    W, H = info["w"], info["h"]
    n_est = int(round(info["duration"] * fps))
    pick = a.pick or spec.get("pick", "sharpest")
    rate, block_start, cam, seg_id = build_plan(spec, n_est + 48, fps)

    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(a.input), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE, creationflags=NOWIN)
    tmp = a.output.with_suffix(".video.mp4")
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r",
                            f"{fps}", "-i", "-", "-c:v", "libx264", "-crf", str(a.crf), "-preset", "slow", "-pix_fmt",
                            "yuv420p", str(tmp)], stdin=subprocess.PIPE, creationflags=NOWIN)
    nbytes = W * H * 3
    block, i, stats = [], 0, {"frames": 0, "held": 0, "warped": 0, "warp_fail": 0}

    def flush(block):
        """block = list of (idx, frame). Emit len(block) frames holding one drawing."""
        if not block:
            return
        idxs = [x[0] for x in block]
        frs = [x[1] for x in block]
        k = int(np.argmax([sharpness(f) for f in frs])) if (pick == "sharpest" and len(frs) > 1) else 0
        held = frs[k]
        for j, (idx, fr) in enumerate(block):
            out = held
            if len(block) > 1 and cam[idx] == "compensate" and j != k:
                out, M = camera_warp(held, frs[k], fr)
                stats["warped" if M is not None else "warp_fail"] += 1
            if j != k:
                stats["held"] += 1
            enc.stdin.write(np.ascontiguousarray(out).tobytes())
            stats["frames"] += 1

    while True:
        buf = dec.stdout.read(nbytes)
        if len(buf) < nbytes:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        if i >= len(rate):
            rate = np.append(rate, rate[-1]); block_start = np.append(block_start, i)
            cam = np.append(cam, cam[-1]); seg_id = np.append(seg_id, seg_id[-1])
        if cam[i] == "ones" or rate[i] == 1:
            flush(block); block = []
            enc.stdin.write(buf)
            stats["frames"] += 1
        else:
            if block and block_start[i] != block_start[block[0][0]]:
                flush(block); block = []
            block.append((i, fr))
        i += 1
    flush(block)
    dec.wait()
    enc.stdin.close()
    enc.wait()
    if stats["frames"] != i:
        sys.exit(f"frame count mismatch {stats['frames']} != {i}")
    if info["audio"]:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-i", str(a.input), "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "copy", "-movflags", "+faststart", str(a.output)], check=True, creationflags=NOWIN)
        tmp.unlink()
    else:
        tmp.replace(a.output)
    # summary per segment
    segs = []
    for k, s in enumerate(spec.get("segments", []), start=1):
        segs.append({"shot": s.get("shot", ""), "start": s["start"], "end": s["end"], "rate": s.get("rate"),
                     "camera": s.get("camera", spec.get("camera", "step")), "why": s.get("why", "")})
    o = info.copy()
    rep = {"input": str(a.input), "output": str(a.output), "fps": fps, "frames": i, "pick": pick, **stats,
           "share_on": {r: round(float((rate[:i] == v).mean()), 3) for r, v in RATES.items()}, "segments": segs,
           "audio": "copied untouched" if o["audio"] else "none"}
    if a.report:
        a.report.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("frames", "held", "warped", "warp_fail", "share_on", "audio")}))


if __name__ == "__main__":
    main()
