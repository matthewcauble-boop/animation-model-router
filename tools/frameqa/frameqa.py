#!/usr/bin/env python
"""frameqa: cheap first-pass QA for a rendered video, so an expensive reviewer (human or LLM) only opens flagged frames.

  python tools/frameqa/frameqa.py <video> --format 9x16|16x9 [--refs a.png b.png]
         [--questions q.json] [--every 0.5] [--holds holds.json] [--palette "#F7931E,#E8318A"]

Stage 1, code (free): one decode pass at 360 px wide measures cuts, black/flat frames, frozen
stretches and A-B-A flicker on every frame; ffmpeg ebur128/silencedetect measure loudness, true
peak and dropouts; local OCR (RapidOCR, optional) boxes every on-screen word on the sampled frames
and checks them against the format's safe area; brand-palette presence if a palette is given.
Stage 2, cheap model: every sampled frame (every --every s plus the first frames after each cut)
goes to TypeSafe Jev with yes/no questions, one call per frame, ~$0.0002 a frame.
Stage 3, confirm: frames Jev scores in a question's grey band (lo..hi) go to Gemini 3.5 Flash-Lite
on fal for a yes/no plus a reason; frames at or above hi are flagged outright (and get a reason).
Output (default <video dir>/frameqa-<stem>/): report.json, report.md, flagged.jpg, thumbs/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
import vision  # noqa: E402

CACHE = Path(os.environ.get("AMR_CACHE_DIR", HERE / "cache")) / "frameqa-vision.jsonl"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console popups on Windows

# Safe areas as fractions of width/height: (left, top, right, bottom) = the box text must stay inside.
SAFE = {
    "9x16": (0.06, 0.06, 0.85, 0.75),   # Shorts/Reels/TikTok: right ~15% buttons, bottom ~25% caption UI
    "16x9": (0.05, 0.05, 0.95, 0.95),   # TV title-safe 90%
    "1x1": (0.05, 0.05, 0.95, 0.95),
    "4x5": (0.06, 0.06, 0.94, 0.86),
}


def log(*a):
    print("[frameqa]", *a, file=sys.stderr, flush=True)


def fmt_t(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:05.2f}"


# ---------------------------------------------------------------- probing / decoding
def probe(video: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
                         capture_output=True, text=True, check=True, creationflags=NOWIN).stdout
    d = json.loads(out)
    vs = next(s for s in d["streams"] if s["codec_type"] == "video")
    num, den = (vs.get("avg_frame_rate") or vs["r_frame_rate"]).split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    if fps <= 0 or fps > 240:
        num, den = vs["r_frame_rate"].split("/")
        fps = float(num) / float(den)
    has_audio = any(s["codec_type"] == "audio" for s in d["streams"])
    return {"w": int(vs["width"]), "h": int(vs["height"]), "fps": fps,
            "duration": float(d["format"].get("duration") or vs.get("duration") or 0), "audio": has_audio}


def analyse_frames(video: Path, info: dict, aw: int = 360) -> dict:
    """One decode pass at aw px wide, gray. Per-frame luma mean, spatial std, diff to previous, flicker."""
    ah = int(round(info["h"] * aw / info["w"] / 2) * 2)
    cmd = ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={aw}:{ah},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, creationflags=NOWIN)
    n = aw * ah
    T = 40  # coarse tiles: a fast-moving small object lands in the same tile in A and C, so it doesn't score
    means, stds, diffs, flick, flick_xy, aba_g = [], [], [], [], [], []
    prev2 = prev = None
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n:
            break
        f = np.frombuffer(buf, np.uint8).reshape(ah, aw).astype(np.float32)
        means.append(float(f.mean()))
        stds.append(float(f.std()))
        diffs.append(float(np.abs(f - prev).mean()) if prev is not None else 0.0)
        if prev2 is not None:
            # A-B-A flicker (floor-flicker metric): the middle frame differs from both neighbours
            # more than the neighbours differ from each other, measured per 20 px tile.
            s = np.minimum(np.abs(prev2 - prev), np.abs(prev - f)) - np.abs(prev2 - f)
            H, W = s.shape
            st = s[: H // T * T, : W // T * T].reshape(H // T, T, W // T, T).mean((1, 3))
            k = int(st.argmax())
            flick.append(float(st.flat[k]))
            g = min(float(np.abs(prev2 - prev).mean()), float(np.abs(prev - f).mean())) - float(np.abs(prev2 - f).mean())
            aba_g.append(g)
            ty, tx = divmod(k, st.shape[1])
            flick_xy.append(((tx + 0.5) * T / aw, (ty + 0.5) * T / ah, int((st > 4).sum())))
        else:
            flick.append(0.0)
            flick_xy.append((0, 0, 0))
            aba_g.append(0.0)
        prev2, prev = prev, f
    p.wait()
    # flick[i] describes frame i-1 (middle of the triple); shift so index = middle frame
    flick = flick[1:] + [0.0]
    flick_xy = flick_xy[1:] + [(0, 0, 0)]
    aba_g = aba_g[1:] + [0.0]
    return {"mean": np.array(means), "std": np.array(stds), "diff": np.array(diffs),
            "flick": np.array(flick), "flick_xy": flick_xy, "aba_global": np.array(aba_g), "aw": aw, "ah": ah}


def detect_cuts(diff: np.ndarray, fps: float, min_abs: float = 12.0, ratio: float = 4.0) -> list[int]:
    cuts = []
    w = max(3, int(fps // 2))
    for i in range(1, len(diff)):
        d = diff[i]
        if d < min_abs:
            continue
        lo, hi = max(1, i - w), min(len(diff), i + w + 1)
        nb = np.concatenate([diff[lo:i], diff[i + 1:hi]])
        base = float(np.median(nb)) if len(nb) else 0.0
        if d > ratio * max(base, 1.0) and (not cuts or i - cuts[-1] > fps * 0.25):
            cuts.append(i)
    return cuts


def runs(mask: np.ndarray):
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            yield i, j  # [i, j)
            i = j
        else:
            i += 1


def in_holds(a: float, b: float, holds) -> bool:
    """True when [a, b] lies mostly inside an intended hold."""
    for h in holds:
        ov = min(b, h[1]) - max(a, h[0])
        if ov >= 0.6 * max(b - a, 1e-6):
            return True
    return False


# ---------------------------------------------------------------- audio
def audio_checks(video: Path, holds, duration: float, lufs_target: float, lufs_tol: float, tp_max: float,
                 sil_db: float, sil_min: float) -> tuple[dict, list]:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af",
           f"ebur128=peak=true,silencedetect=n={sil_db}dB:d={sil_min}", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", creationflags=NOWIN).stderr
    res = {}
    summ = err[err.rfind("Summary:"):] if "Summary:" in err else err
    m = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summ)
    res["integrated_lufs"] = float(m.group(1)) if m and m.group(1) != "-inf" else None
    m = re.search(r"LRA:\s+(-?[\d.]+) LU", summ)
    res["lra"] = float(m.group(1)) if m else None
    m = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf) dBFS", summ, re.S)
    res["true_peak_dbtp"] = float(m.group(1)) if m and m.group(1) != "-inf" else None
    sil = []
    for s, e in re.findall(r"silence_start: (-?[\d.]+)[\s\S]*?silence_end: (-?[\d.]+)", err):
        sil.append((max(0.0, float(s)), float(e)))
    tail = re.findall(r"silence_start: (-?[\d.]+)(?![\s\S]*silence_end)", err)
    if tail:
        sil.append((float(tail[-1]), duration))
    res["silences"] = [[round(a, 2), round(b, 2)] for a, b in sil]
    findings = []
    L = res["integrated_lufs"]
    if L is None:
        findings.append(dict(check="loudness", severity="P0", start=0, end=duration,
                             reason="no measurable audio (silent track)"))
    elif abs(L - lufs_target) > lufs_tol:
        findings.append(dict(check="loudness", severity="P1", start=0, end=duration,
                             reason=f"integrated {L:.1f} LUFS vs target {lufs_target:.0f} +/- {lufs_tol}"))
    tp = res["true_peak_dbtp"]
    if tp is not None and tp > tp_max:
        findings.append(dict(check="true_peak", severity="P1", start=0, end=duration,
                             reason=f"true peak {tp:+.1f} dBTP > {tp_max:+.1f}"))
    for a, b in sil:
        if a < 0.3 or b > duration - 0.3:   # lead-in / tail silence is normal
            continue
        if in_holds(a, b, holds):
            continue
        findings.append(dict(check="audio_dropout", severity="P1", start=round(a, 2), end=round(b, 2),
                             reason=f"silence below {sil_db} dB for {b - a:.2f} s mid-video"))
    return res, findings


# ---------------------------------------------------------------- sampling / extraction
def sample_frames(info, cuts, every: float, nframes: int) -> list[int]:
    fps = info["fps"]
    idx = set(int(round(t * fps)) for t in np.arange(0, info["duration"], every))
    for c in cuts:                       # first frames of each new shot (a few frames in, past any dissolve)
        idx.add(min(nframes - 1, c + max(2, int(fps * 0.1))))
    idx = sorted(i for i in idx if 0 <= i < nframes)
    out = []
    for i in idx:                        # drop samples closer than 0.2 s to the previous one
        if not out or (i - out[-1]) / fps >= 0.2:
            out.append(i)
    return out


def extract(video: Path, idxs: list[int], outdir: Path, fps: float, workers: int = 6) -> list[Path]:
    """Accurate-seek one ffmpeg per sampled frame, in parallel (a long select= expression overflows ffmpeg)."""
    outdir.mkdir(parents=True, exist_ok=True)

    def one(i):
        dst = outdir / f"s_{i:06d}.jpg"
        if not dst.exists():
            t = max(0.0, (i - 0.25) / fps)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.4f}", "-i", str(video), "-frames:v", "1",
                            "-q:v", "2", str(dst)], check=True, creationflags=NOWIN)
        return dst

    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, idxs))


# ---------------------------------------------------------------- OCR safe area
_ocr = None


def get_ocr():
    global _ocr
    if _ocr is None:
        try:
            from rapidocr import RapidOCR  # optional: pip install --user rapidocr
            _ocr = RapidOCR(params={"Global.log_level": "error"})
        except Exception as e:  # noqa: BLE001
            log("OCR unavailable (pip install --user rapidocr):", e)
            _ocr = False
    return _ocr


def ocr_boxes(im: Image.Image, width: int = 720) -> list[dict]:
    eng = get_ocr()
    if not eng:
        return []
    w, h = im.size
    s = width / w
    r = eng(np.asarray(im.convert("RGB").resize((width, round(h * s)))))
    if r is None or r.boxes is None:
        return []
    H = round(h * s)
    out = []
    for b, tx, sc in zip(r.boxes, r.txts, r.scores):
        tx = str(tx)
        letters = sum(c.isascii() and c.isalpha() for c in tx)
        if sc < 0.8 or (letters < 3 and " " not in tx.strip()):
            continue   # drops OCR noise like "He", "00", "C", "+"
        out.append({"text": tx, "score": round(float(sc), 2),
                    "box": [round(float(b[:, 0].min()) / width, 4), round(float(b[:, 1].min()) / H, 4),
                            round(float(b[:, 0].max()) / width, 4), round(float(b[:, 1].max()) / H, 4)]})
    return out


def safe_violations(boxes, safe):
    L, T, R, B = safe
    v = []
    for bx in boxes:
        x0, y0, x1, y1 = bx["box"]
        over = max(L - x0, x1 - R, T - y0, y1 - B, 0)
        if over > 0.005:
            edge = x0 <= 0.005 or x1 >= 0.995 or y0 <= 0.005 or y1 >= 0.995
            v.append({**bx, "over": round(over, 3), "edge": edge})
    return v


# ---------------------------------------------------------------- palette
def parse_palette(s: str | None):
    if not s:
        return None
    if os.path.exists(s):
        s = Path(s).read_text(encoding="utf-8")
        try:
            j = json.loads(s)
            s = ",".join(j if isinstance(j, list) else j.values())
        except json.JSONDecodeError:
            pass
    cols = re.findall(r"#?([0-9a-fA-F]{6})", s)
    return np.array([[int(c[i:i + 2], 16) for i in (0, 2, 4)] for c in cols], np.float32) if cols else None


def palette_presence(im: Image.Image, pal: np.ndarray, tol: float = 40.0) -> float:
    a = np.asarray(im.convert("RGB").resize((180, 320)), np.float32).reshape(-1, 1, 3)
    d = np.sqrt(((a - pal[None]) ** 2).sum(-1)).min(1)
    return float((d < tol).mean())


# ---------------------------------------------------------------- vision with cache
def load_cache() -> dict:
    c = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                c[d["k"]] = d["v"]
            except Exception:  # noqa: BLE001
                pass
    return c


def cache_put(k, v):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"k": k, "v": v}) + "\n")


def frame_hash(im: Image.Image) -> str:
    return hashlib.sha1(np.asarray(im.convert("RGB").resize((96, 170))).tobytes()).hexdigest()[:20]


def qkey(model: str, q: dict, refs_sig: str) -> str:
    return hashlib.sha1(f"{model}|{q['text']}|{refs_sig if q.get('needs_refs') else ''}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------- thumbs / sheet
def font(size):
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_thumb(src: Path, dst: Path, safe, label: str, box=None, xy=None):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    s = 480 / max(w, h)
    im = im.resize((round(w * s), round(h * s)))
    W, H = im.size
    d = ImageDraw.Draw(im)
    L, T, R, B = safe
    d.rectangle([L * W, T * H, R * W, B * H], outline=(0, 255, 255), width=1)
    if box:
        x0, y0, x1, y1 = box
        d.rectangle([x0 * W - 2, y0 * H - 2, x1 * W + 2, y1 * H + 2], outline=(255, 0, 0), width=3)
    if xy:
        d.ellipse([xy[0] * W - 18, xy[1] * H - 18, xy[0] * W + 18, xy[1] * H + 18], outline=(255, 0, 0), width=3)
    f = font(15)
    d.rectangle([0, 0, W, 22], fill=(0, 0, 0))
    d.text((4, 3), label[:60], fill=(255, 255, 0), font=f)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, quality=85)
    return dst


def contact_sheet(thumbs: list[Path], dst: Path, cols: int = 6):
    if not thumbs:
        return None
    ims = [Image.open(t) for t in thumbs[:60]]
    cw = max(i.size[0] for i in ims)
    ch = max(i.size[1] for i in ims)
    rows = math.ceil(len(ims) / cols)
    sheet = Image.new("RGB", (cw * min(cols, len(ims)), ch * rows), (24, 24, 24))
    for k, im in enumerate(ims):
        sheet.paste(im, ((k % cols) * cw, (k // cols) * ch))
    sheet.save(dst, quality=82)
    return dst


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--format", default=None, help="9x16 | 16x9 | 1x1 | 4x5 (default: from aspect)")
    ap.add_argument("--safe", help="override safe box as 'left,top,right,bottom' fractions")
    ap.add_argument("--refs", nargs="*", default=[], help="character reference images (enables off_model)")
    ap.add_argument("--questions", help="questions JSON (default questions.default.json)")
    ap.add_argument("--every", type=float, default=0.5, help="sample spacing in seconds")
    ap.add_argument("--holds", help="JSON list of [start,end] or {start,end} intended holds/silences")
    ap.add_argument("--palette", help="brand colours: '#F7931E,#E8318A' or a JSON file")
    ap.add_argument("--out", help="output folder (default <video dir>/frameqa-<stem>)")
    ap.add_argument("--backend", default="jev", help="jev | fal | gemini | ollama | none")
    ap.add_argument("--model", default=None, help="model for the backend")
    ap.add_argument("--confirm", default="google/gemini-3.5-flash-lite",
                    help="fal OpenRouter model that confirms grey-band hits and writes reasons; 'none' to skip")
    ap.add_argument("--lufs", type=float, default=-16.0, help="integrated loudness target")
    ap.add_argument("--lufs-tol", type=float, default=1.5)
    ap.add_argument("--tp-max", type=float, default=-1.0, help="max true peak dBTP")
    ap.add_argument("--freeze-min", type=float, default=1.0, help="frozen stretch to report, seconds")
    ap.add_argument("--flicker", type=float, default=6.0, help="A-B-A tile flicker threshold")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--max-cost", type=float, default=1.0, help="abort if model spend estimate exceeds this (USD)")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)

    t_start = time.time()
    video = Path(a.video).resolve()
    info = probe(video)
    fmt = a.format or ("9x16" if info["h"] > info["w"] * 1.3 else "16x9" if info["w"] > info["h"] * 1.3 else "1x1")
    safe = tuple(float(x) for x in a.safe.split(",")) if a.safe else SAFE.get(fmt, SAFE["16x9"])
    out = Path(a.out) if a.out else video.parent / f"frameqa-{video.stem}"
    out.mkdir(parents=True, exist_ok=True)
    holds = []
    if a.holds:
        for h in json.loads(Path(a.holds).read_text(encoding="utf-8")):
            holds.append((float(h["start"]), float(h["end"])) if isinstance(h, dict) else (float(h[0]), float(h[1])))
    questions = json.loads(Path(a.questions or HERE / "questions.default.json").read_text(encoding="utf-8"))
    refs = [Image.open(r).convert("RGB") for r in a.refs]
    questions = [q for q in questions if refs or not q.get("needs_refs")]
    qmap = {q["id"]: q for q in questions}
    pal = parse_palette(a.palette)
    fps = info["fps"]
    findings = []
    timing = {}

    # ---- stage 1a: every frame
    t0 = time.time()
    fr = analyse_frames(video, info)
    nfr = len(fr["diff"])
    cuts = detect_cuts(fr["diff"], fps)
    cutset = set()
    for c in cuts:
        cutset.update({c - 1, c, c + 1})
    timing["decode_s"] = round(time.time() - t0, 1)
    tt = lambda i: i / fps  # noqa: E731

    # black / flat
    black = fr["mean"] < 16
    flat = (fr["std"] < 7) & ~black
    for name, mask, sev, why in (("black", black, "P1", "black frames"),
                                 ("flat", flat, "P2", "flat frame: almost no detail (std < 7)")):
        for i, j in runs(mask):
            a_, b_ = tt(i), tt(j)
            if b_ - a_ < 0.25 or in_holds(a_, b_, holds):
                continue
            if name == "black" and (i == 0 or j >= nfr - 1) and b_ - a_ < 1.0:
                continue  # short fade-in/out
            findings.append(dict(check=name, severity=sev, start=round(a_, 2), end=round(b_, 2),
                                 reason=f"{why} for {b_ - a_:.2f} s", frame=(i + j) // 2))
    temporal = fps >= 10   # freeze/flicker need real motion sampling (skip for slideshows / 1 fps proxies)
    # frozen (identical consecutive frames)
    frozen = fr["diff"] < 0.15 if temporal else np.zeros(nfr, bool)
    frozen[0] = False
    for i, j in runs(frozen):
        a_, b_ = tt(i - 1), tt(j)
        if b_ - a_ < a.freeze_min or in_holds(a_, b_, holds):
            continue
        findings.append(dict(check="frozen", severity="P2", start=round(a_, 2), end=round(b_, 2),
                             reason=f"no pixel change for {b_ - a_:.2f} s (mark intended holds in --holds)",
                             frame=(i + j) // 2))
    # flicker
    fl = fr["flick"] > a.flicker if temporal else np.zeros(nfr, bool)
    gmed = float(np.median(fr["diff"][1:])) if nfr > 2 else 0.0
    for i in range(nfr):
        if i in cutset or (i + 1) in cutset:
            fl[i] = False
        # a jump that doesn't come back (A != C over the whole frame) is a cut or whip, not flicker
        elif 0 < i < nfr - 1 and fr["aba_global"][i] <= 0 and fr["diff"][i] > max(10.0, 6 * gmed):
            fl[i] = False
    for i, j in runs(fl):
        a_, b_ = tt(i), tt(j)
        if in_holds(a_, b_, holds):
            continue
        k = i + int(np.argmax(fr["flick"][i:j]))
        x, y, ntiles = fr["flick_xy"][k]
        peak = float(fr["flick"][k])
        if j - i == 1 and ntiles < 6 and peak < 3 * a.flicker:
            continue   # one-frame blip on a small area: easing overshoot, sparkle, particle
        big = ntiles >= 20 or ((j - i) / fps >= 0.3 and peak > 2 * a.flicker)
        findings.append(dict(check="flicker", severity="P1" if big else "P2",
                             start=round(a_, 2), end=round(max(b_, a_ + 1 / fps), 2),
                             reason=f"A-B-A flicker score {fr['flick'][k]:.1f} at x {x:.0%} y {y:.0%} "
                                    f"({ntiles} tiles)", frame=k, xy=(x, y)))

    # ---- stage 1b: audio
    t0 = time.time()
    audio = {}
    if info["audio"]:
        audio, af = audio_checks(video, holds, info["duration"], a.lufs, a.lufs_tol, a.tp_max, -50, 0.3)
        findings += af
    else:
        findings.append(dict(check="audio", severity="P2", start=0, end=info["duration"], reason="no audio stream"))
    timing["audio_s"] = round(time.time() - t0, 1)

    # ---- stage 1c: sample + OCR + palette
    t0 = time.time()
    sidx = sample_frames(info, cuts, a.every, nfr)
    frames_dir = out / "frames"
    for f in frames_dir.glob("*.jpg") if frames_dir.exists() else []:
        f.unlink()
    paths = extract(video, sidx, frames_dir, fps, a.workers)
    timing["extract_s"] = round(time.time() - t0, 1)
    samples = [{"i": i, "t": round(tt(i), 3), "file": str(p)} for i, p in zip(sidx, paths)]
    t0 = time.time()
    if not a.no_ocr:
        with ThreadPoolExecutor(2) as ex:
            boxes = list(ex.map(lambda s: ocr_boxes(Image.open(s["file"])), samples))
        for s, b in zip(samples, boxes):
            s["ocr"] = b
            s["safe_viol"] = safe_violations(b, safe)
    if pal is not None:
        for s in samples:
            s["palette"] = round(palette_presence(Image.open(s["file"]), pal), 4)
    timing["ocr_s"] = round(time.time() - t0, 1)

    # ---- stage 2: cheap model
    t0 = time.time()
    cost = {"screen": 0.0, "confirm": 0.0}
    usage = {"screen_calls": 0, "confirm_calls": 0, "cache_hits": 0}
    if a.backend != "none":
        est = len(samples) * 0.00025
        if est > a.max_cost:
            sys.exit(f"estimated model cost ${est:.2f} > --max-cost {a.max_cost}")
        be = vision.make(a.backend, a.model)
        model_id = f"{a.backend}:{getattr(be, 'model', '')}"
        refs_sig = hashlib.sha1(b"".join(r.resize((64, 64)).tobytes() for r in refs)).hexdigest()[:10]
        cache = load_cache()
        imgs = {}
        todo = []
        for s in samples:
            im = Image.open(s["file"])
            s["hash"] = frame_hash(im)
            res = {}
            for q in questions:
                k = f"{model_id}|{qkey(model_id, q, refs_sig)}|{s['hash']}"
                if k in cache:
                    res[q["id"]] = cache[k]
            s["vision"] = res
            if len(res) < len(questions):
                if s["hash"] not in imgs:
                    imgs[s["hash"]] = im
                    todo.append(s["hash"])
            else:
                usage["cache_hits"] += 1
        bs = getattr(be, "batch", 1)
        batches = [todo[k:k + bs] for k in range(0, len(todo), bs)]

        def run(batch):
            try:
                return batch, be.ask([imgs[h] for h in batch], questions, refs)
            except Exception as e:  # noqa: BLE001
                log("vision call failed:", str(e)[:200])
                return batch, ([{} for _ in batch], 0.0, {})

        got = {}
        with ThreadPoolExecutor(a.workers) as ex:
            for batch, (answers, c, u) in ex.map(run, batches):
                cost["screen"] += c
                usage["screen_calls"] += 1
                for h, ans in zip(batch, answers):
                    got[h] = ans
                    for q in questions:
                        if q["id"] in ans:
                            cache_put(f"{model_id}|{qkey(model_id, q, refs_sig)}|{h}", ans[q["id"]])
        for s in samples:
            for qid, v in got.get(s["hash"], {}).items():
                s["vision"].setdefault(qid, v)
        timing["screen_s"] = round(time.time() - t0, 1)

        # ---- stage 3: confirm grey band, explain hard hits
        t0 = time.time()
        cand = []  # (sample, qid, hard)
        for s in samples:
            for qid, v in s["vision"].items():
                q = qmap.get(qid)
                if not q:
                    continue
                p = v.get("p", 0)
                if a.backend == "jev":
                    if p >= q.get("hi", 0.85):
                        cand.append((s, qid, True))
                    elif p >= q.get("lo", 0.6):
                        cand.append((s, qid, False))
                elif v.get("answer") == "yes":
                    cand.append((s, qid, True))
        conf = None
        if a.confirm != "none" and a.backend == "jev" and cand:
            try:
                conf = vision.FalRouter(a.confirm, batch=1, max_side=1024)
            except Exception as e:  # noqa: BLE001
                log("confirm model unavailable:", e)
        by_frame = {}
        for s, qid, hard in cand:
            by_frame.setdefault(s["hash"], (s, []))[1].append((qid, hard))
        ccache_model = f"confirm:{a.confirm}"

        def confirm(item):
            s, qs = item
            qq = [qmap[qid] for qid, _ in qs]
            res, c = {}, 0.0
            need = []
            for q in qq:
                k = f"{ccache_model}|{qkey(ccache_model, q, refs_sig)}|{s['hash']}"
                if k in cache:
                    res[q["id"]] = cache[k]
                else:
                    need.append(q)
            if need:
                try:
                    ans, c, _ = conf.ask([Image.open(s["file"])], need, refs if any(q.get("needs_refs") for q in need) else None)
                    for q in need:
                        if q["id"] in ans[0]:
                            res[q["id"]] = ans[0][q["id"]]
                            cache_put(f"{ccache_model}|{qkey(ccache_model, q, refs_sig)}|{s['hash']}", ans[0][q["id"]])
                except Exception as e:  # noqa: BLE001
                    log("confirm failed:", str(e)[:200])
            return s, qs, res, c, bool(need)

        verdicts = {}
        if conf:
            with ThreadPoolExecutor(min(a.workers, 4)) as ex:
                for s, qs, res, c, called in ex.map(confirm, by_frame.values()):
                    cost["confirm"] += c
                    usage["confirm_calls"] += int(called)
                    for qid, hard in qs:
                        verdicts[(s["hash"], qid)] = res.get(qid)
        for s, qid, hard in cand:
            v = s["vision"][qid]
            cv = verdicts.get((s["hash"], qid))
            if conf and not hard and not (cv and cv["answer"] == "yes"):
                continue
            sev = qmap[qid].get("severity", "P1")
            disputed = bool(conf and hard and cv and cv["answer"] == "no")
            if disputed:
                sev = "P2"   # screen was sure, confirmer disagrees: keep it, but at the bottom of the list
            reason = (cv or {}).get("reason") or ""
            how = "screen p=%.2f" % v.get("p", 0) + (f"; confirm {cv['answer']}" if cv else "")
            if cv and cv["answer"] == "no":
                reason = "confirmer disagrees: " + reason
            findings.append(dict(check=f"vision:{qid}", severity=sev, disputed=disputed,
                                 start=s["t"], end=s["t"], question=qmap[qid]["text"],
                                 reason=reason or v.get("reason") or "(no reason: probability only)",
                                 confidence=round(v.get("p", 0), 2), how=how, frame=s["i"], sample=s["file"],
                                 confirmed=bool(cv and cv["answer"] == "yes")))
        timing["confirm_s"] = round(time.time() - t0, 1)

    # OCR safe-area findings
    for s in samples:
        for v in s.get("safe_viol", []):
            sev = "P0" if (v["edge"] or v["over"] >= 0.02) else "P2"
            findings.append(dict(check="safe_area", severity=sev, start=s["t"], end=s["t"], frame=s["i"],
                                 sample=s["file"], box=v["box"],
                                 reason=f"text '{v['text'][:48]}' at x {v['box'][0]:.0%}-{v['box'][2]:.0%} "
                                        f"y {v['box'][1]:.0%}-{v['box'][3]:.0%}"
                                        + (" cut by frame edge" if v["edge"] else f", {v['over']:.0%} outside safe")))
    # palette
    if pal is not None and samples:
        pres = np.array([s["palette"] for s in samples])
        low = pres < 0.005
        for i, j in runs(low):
            a_, b_ = samples[i]["t"], samples[j - 1]["t"]
            if b_ - a_ >= 3.0:
                findings.append(dict(check="palette", severity="P2", start=a_, end=b_, frame=samples[i]["i"],
                                     reason=f"brand palette under 0.5% of pixels for {b_ - a_:.1f} s"))

    # ---- merge consecutive same-check findings into ranges
    def sample_of(i):
        best = min(samples, key=lambda s: abs(s["i"] - i)) if samples else None
        return best
    findings.sort(key=lambda f: (f["check"], f["start"]))
    merged = []
    gap = max(a.every * 1.6, 0.8)
    for f in findings:
        m = merged[-1] if merged else None
        if m and m["check"] == f["check"] and f["start"] - m["end"] <= gap and m["check"] not in ("loudness", "true_peak"):
            m["end"] = max(m["end"], f["end"])
            m["n"] = m.get("n", 1) + 1
            sev_rank = {"P0": 0, "P1": 1, "P2": 2}
            if sev_rank[f["severity"]] < sev_rank[m["severity"]]:
                m["severity"] = f["severity"]
            if f.get("confidence", 0) > m.get("confidence", 0):
                for k in ("confidence", "frame", "sample", "box", "how", "confirmed"):
                    if k in f:
                        m[k] = f[k]
            stem = lambda r: r.split("' at x")[0].split(" (screen")[0][:60]  # noqa: E731
            if stem(f["reason"]) not in {stem(r) for r in m["reasons"]} and len(m["reasons"]) < 6:
                m["reasons"].append(f["reason"])
        else:
            f = dict(f)
            f["reasons"] = [f["reason"]]
            merged.append(f)
    sev_rank = {"P0": 0, "P1": 1, "P2": 2}
    merged.sort(key=lambda f: (f["start"], sev_rank[f["severity"]]))

    # ---- thumbs + sheet
    thumbs = []
    for k, f in enumerate(merged, 1):
        f["id"] = f"F{k:03d}"
        src = f.get("sample")
        if not src and "frame" in f and samples:
            # nearest sampled frame, else extract this frame
            s = sample_of(f["frame"])
            if s and abs(s["i"] - f["frame"]) <= fps * 0.3 and f["check"] != "flicker":
                src = s["file"]
            else:
                dst = out / "frames" / f"x_{f['frame']:06d}.jpg"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{f['frame'] / fps:.3f}", "-i", str(video),
                                "-frames:v", "1", "-q:v", "2", str(dst)], creationflags=NOWIN)
                src = str(dst) if dst.exists() else None
        if src:
            f["frame_file"] = src
            label = f"{f['id']} {fmt_t(f['start'])} {f['severity']} {f['check'].replace('vision:', '')}"
            f["thumb"] = str(make_thumb(Path(src), out / "thumbs" / f"{f['id']}.jpg", safe, label,
                                        box=f.get("box"), xy=f.get("xy")))
            if f["severity"] != "P2" or len(thumbs) < 10:
                thumbs.append(Path(f["thumb"]))
    sheet = contact_sheet(thumbs, out / "flagged.jpg")

    # ---- write report
    total = cost["screen"] + cost["confirm"]
    mins = info["duration"] / 60
    timing["total_s"] = round(time.time() - t_start, 1)
    rep = {
        "video": str(video), "format": fmt, "safe_area": safe, "info": info, "cuts_s": [round(tt(c), 2) for c in cuts],
        "settings": {"every": a.every, "backend": a.backend, "model": a.model, "confirm": a.confirm,
                     "questions": questions, "holds": holds, "refs": a.refs},
        "audio": audio,
        "cost_usd": {k: round(v, 5) for k, v in cost.items()} | {"total": round(total, 5),
                                                                   "per_minute": round(total / mins, 5) if mins else None},
        "usage": usage, "timing_s": timing,
        "n_samples": len(samples),
        "findings": [{k: v for k, v in f.items() if k not in ("reason",)} for f in merged],
        "samples": samples,
    }
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")

    md = [f"# frameqa: {video.name}", "",
          f"{info['w']}x{info['h']}, {fps:g} fps, {info['duration']:.2f} s, format {fmt}, safe box "
          f"x {safe[0]:.0%}-{safe[2]:.0%}, y {safe[1]:.0%}-{safe[3]:.0%}. {len(samples)} sampled frames "
          f"(every {a.every} s + {len(cuts)} cuts).",
          "",
          f"**Cost:** ${total:.4f} (screen ${cost['screen']:.4f} {a.backend}, confirm ${cost['confirm']:.4f}), "
          f"${total / mins if mins else 0:.4f} per minute of video; {usage['screen_calls']} screen calls, "
          f"{usage['confirm_calls']} confirm calls, {usage['cache_hits']} cached. Time {timing['total_s']} s.",
          ""]
    if audio:
        md.append(f"**Audio:** {audio.get('integrated_lufs')} LUFS integrated, LRA {audio.get('lra')}, "
                  f"true peak {audio.get('true_peak_dbtp')} dBTP, silences {audio.get('silences')}.")
        md.append("")
    n0 = sum(f["severity"] == "P0" for f in merged)
    n1 = sum(f["severity"] == "P1" for f in merged)
    md += [f"**{len(merged)} findings:** {n0} P0, {n1} P1, {len(merged) - n0 - n1} P2. Contact sheet: `flagged.jpg`.",
           "",
           "Reviewer: open only the `thumb`/`frame` files listed here; everything else passed the checks. "
           "Findings are candidates, not verdicts: confirm each before fixing.",
           "",
           "| id | time | sev | check | detail | thumb |", "|---|---|---|---|---|---|"]
    for f in merged:
        tr = fmt_t(f["start"]) + ("" if f["end"] - f["start"] < 0.05 else "-" + fmt_t(f["end"]))
        det = "; ".join(f["reasons"])
        if f.get("how"):
            det += f" ({f['how']})"
        md.append(f"| {f['id']} | {tr} | {f['severity']} | {f['check']} | {det.replace('|', '/')} | "
                  f"{('thumbs/' + Path(f['thumb']).name) if f.get('thumb') else ''} |")
    md += ["", "Full-res frames: `frames/s_<frame>.jpg`. Raw per-sample answers and OCR boxes: `report.json`."]
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"out": str(out), "findings": len(merged), "P0": n0, "P1": n1, "cost_usd": round(total, 4),
                      "per_minute": round(total / mins, 4) if mins else None, "seconds": timing["total_s"]}))


if __name__ == "__main__":
    main()
