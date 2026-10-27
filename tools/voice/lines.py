"""lines: voice a script line by line with a LOCKED voice, paying only for lines whose text (or voice) changed.

    python tools/voice/lines.py lines.json --voice voice.json -o vo/ [--dry-run] [--only L1,L3] [--refresh L2]
           [--pad 0.04] [--tail 0.12] [--floor -45] [--sr 48000] [--max-cost 1.0]

lines.json  {"lines": [{"id": "L1", "character": "host", "shot": "S1", "text": "...", "cue": "what is on screen"}]}
voice.json  {"characters": {"host": {"endpoint": "<fal TTS endpoint>", "params": {...}, "prefix": "",
             "text_field": "text", "usd_per_1k_chars": 0.08}}}
            `params` is sent verbatim with the text (voice, seed, stability, timestamps ...): one locked set per
            character, so every line, this week or next month, is the same voice.

What it does, per line:
  1. Cache key = sha256(endpoint + params + final text). A hit costs nothing and returns the identical take.
     Change one word and only that line is re-voiced (a few cents). --refresh ID forces a new take of one line.
  2. Calls the fal queue (POST https://queue.fal.run/<endpoint>, polls, downloads the audio). FAL_KEY from the
     environment or a .env file (AMR_ENV_FILE). Never printed.
  3. Trims lead and trail silence (anything under --floor dBFS), keeping --pad s before the first word and --tail s
     after the last, with 8 ms / 30 ms fades. Never time-stretches: speeding up a voice is the fastest way to make it
     sound fake. Tighten the GAPS in the edit instead.
  4. Writes vo/<id>.wav (48 kHz mono) and vo/timings.json: per line the duration, the trim, and word times when the
     endpoint returns an alignment (ElevenLabs-style `timestamps`), shifted to match the trimmed file.
  5. Appends every paid call to vo/spend.csv.

--dry-run   lists each line as cached / would call, its characters and the estimated cost, and the cache key; no key
            needed, nothing is sent. Always run it first.
--max-cost  refuses to start if the uncached lines would cost more than this (USD).

Stdlib + numpy; ffmpeg/ffprobe on PATH.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def env_key(name):
    try:
        import vision  # shared .env reader; vision imports Pillow
        return vision.env_key(name)
    except ImportError:
        v = os.environ.get(name)
        return v.strip() if v else None


# ------------------------------------------------------------------ fal queue
def _http(url, key, data=None, timeout=120):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode("utf-8"),
                                 headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
                                 method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"fal HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:400]}") from None


def fal_run(endpoint, payload, key, timeout=300):
    q = _http(f"https://queue.fal.run/{endpoint}", key, payload)
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = _http(q["status_url"], key).get("status")
        if s == "COMPLETED":
            return _http(q["response_url"], key)
        if s in ("FAILED", "ERROR"):
            raise RuntimeError(f"fal job {s}")
        time.sleep(1.0)
    raise TimeoutError("fal request timed out")


def audio_url(r):
    for k in ("audio", "audio_file", "output"):
        v = r.get(k)
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
        if isinstance(v, str) and v.startswith("http"):
            return v
    if r.get("audio_url"):
        return r["audio_url"]
    raise RuntimeError(f"no audio url in the response (keys: {sorted(r)})")


def words_from_alignment(chunks):
    """ElevenLabs-style per-character alignment -> [[word, start, end]]; [bracket tags] dropped."""
    if isinstance(chunks, dict):
        chunks = [chunks]
    chars = [(c, s, e) for ch in (chunks or []) for c, s, e in
             zip(ch.get("characters", []), ch.get("character_start_times_seconds", []),
                 ch.get("character_end_times_seconds", []))]
    words, cur, depth = [], [], 0

    def flush():
        if cur and any(c.isalnum() for c, _, _ in cur):
            words.append(["".join(c for c, _, _ in cur), round(cur[0][1], 3), round(cur[-1][2], 3)])
        elif cur and words:
            words[-1][0] += "".join(c for c, _, _ in cur)
            words[-1][2] = round(cur[-1][2], 3)
        cur.clear()

    for c, s, e in chars:
        if c == "[":
            flush(); depth += 1; continue
        if c == "]":
            depth = max(0, depth - 1); continue
        if depth:
            continue
        if c.isspace():
            flush(); continue
        cur.append((c, s, e))
    flush()
    return words


# ------------------------------------------------------------------ audio
def decode(p, sr):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True, check=True, creationflags=NOWIN)
    return np.frombuffer(r.stdout, np.float32).astype(np.float64)


def write_wav(p, x, sr):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def trim(x, sr, floor_db=-45.0, pad=0.04, tail=0.12):
    """Cut lead/trail silence measured on 10 ms windows. Returns (audio, seconds cut from the head)."""
    win = max(1, int(0.01 * sr))
    n = len(x) // win
    if n == 0:
        return x, 0.0
    rms = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(1) + 1e-12)
    loud = np.nonzero(20 * np.log10(rms) > floor_db)[0]
    if not len(loud):
        return x, 0.0
    a = max(0, loud[0] * win - int(pad * sr))
    b = min(len(x), (loud[-1] + 1) * win + int(tail * sr))
    y = x[a:b].copy()
    fi, fo = min(len(y), int(0.008 * sr)), min(len(y), int(0.03 * sr))
    if fi: y[:fi] *= np.linspace(0, 1, fi)
    if fo: y[-fo:] *= np.linspace(1, 0, fo)
    return y, a / sr


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lines", type=Path)
    ap.add_argument("--voice", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="comma-separated line ids")
    ap.add_argument("--refresh", default="", help="comma-separated line ids to re-take (ignores the cache)")
    ap.add_argument("--pad", type=float, default=0.04)
    ap.add_argument("--tail", type=float, default=0.12)
    ap.add_argument("--floor", type=float, default=-45.0)
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--max-cost", type=float, default=1.0)
    ap.add_argument("--cache", type=Path, help="default: <out>/.cache (or AMR_CACHE_DIR/voice)")
    a = ap.parse_args(argv)

    lines = json.loads(a.lines.read_text(encoding="utf-8"))
    lines = lines["lines"] if isinstance(lines, dict) else lines
    chars_cfg = json.loads(a.voice.read_text(encoding="utf-8"))["characters"]
    only = set(a.only.split(",")) if a.only else None
    refresh = set(x for x in a.refresh.split(",") if x)
    cache = a.cache or (Path(os.environ["AMR_CACHE_DIR"]) / "voice" if os.environ.get("AMR_CACHE_DIR")
                        else a.out / ".cache")

    plan, est = [], 0.0
    for ln in lines:
        if only and ln["id"] not in only:
            continue
        who = ln.get("character") or next(iter(chars_cfg))
        if who not in chars_cfg:
            sys.exit(f"line {ln['id']}: character '{who}' not in {a.voice}")
        v = chars_cfg[who]
        text = ln["text"].strip()
        pre = v.get("prefix", "")
        if pre and not text.startswith(pre):
            text = f"{pre} {text}"
        payload = {**v.get("params", {}), v.get("text_field", "text"): text}
        key = hashlib.sha256(json.dumps({"endpoint": v["endpoint"], **payload}, sort_keys=True).encode()).hexdigest()[:24]
        hit = (cache / f"{key}.audio").exists() and (cache / f"{key}.json").exists() and ln["id"] not in refresh
        cost = 0.0 if hit else len(text) * v.get("usd_per_1k_chars", 0.0) / 1000
        est += cost
        plan.append((ln, who, v, payload, key, hit, cost))

    for ln, who, v, payload, key, hit, cost in plan:
        print(f"{ln['id']:<6} {who:<10} {'cached ' if hit else 'CALL   '} {len(payload[v.get('text_field', 'text')]):>4} "
              f"chars  ${cost:.4f}  key {key}  {ln['text'][:60]!r}")
    print(f"{sum(not p[5] for p in plan)} of {len(plan)} lines need a call, estimated ${est:.4f}")
    if a.dry_run:
        return
    if est > a.max_cost:
        sys.exit(f"estimated ${est:.2f} is over --max-cost ${a.max_cost:.2f}")
    fal_key = env_key("FAL_KEY") if any(not p[5] for p in plan) else None
    if any(not p[5] for p in plan) and not fal_key:
        sys.exit("FAL_KEY not set (environment or .env)")

    a.out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    tpath = a.out / "timings.json"
    timings = json.loads(tpath.read_text(encoding="utf-8")) if tpath.exists() else {}
    spend = []
    for ln, who, v, payload, key, hit, cost in plan:
        au, meta = cache / f"{key}.audio", cache / f"{key}.json"
        if not hit:
            r = fal_run(v["endpoint"], payload, fal_key)
            with urllib.request.urlopen(audio_url(r), timeout=120) as f:
                au.write_bytes(f.read())
            meta.write_text(json.dumps({"endpoint": v["endpoint"], "payload": payload,
                                        "words": words_from_alignment(r.get("timestamps"))}, indent=1),
                            encoding="utf-8")
            spend.append([time.strftime("%Y-%m-%d %H:%M"), ln["id"], who, v["endpoint"],
                          len(payload[v.get("text_field", "text")]), f"{cost:.4f}"])
        m = json.loads(meta.read_text(encoding="utf-8"))
        x, cut = trim(decode(au, a.sr), a.sr, a.floor, a.pad, a.tail)
        write_wav(a.out / f"{ln['id']}.wav", x, a.sr)
        words = [[w, round(max(0.0, s - cut), 3), round(max(0.0, e - cut), 3)] for w, s, e in m.get("words", [])]
        timings[ln["id"]] = {"wav": str(a.out / f"{ln['id']}.wav"), "character": who, "shot": ln.get("shot"),
                             "text": ln["text"], "cue": ln.get("cue"), "duration": round(len(x) / a.sr, 3),
                             "trim_lead": round(cut, 3), "words": words, "cached": hit, "cache_key": key}
        print(f"{ln['id']:<6} {timings[ln['id']]['duration']:6.2f} s  trimmed {cut:.2f} s  "
              f"{'cached' if hit else 'new take'}", flush=True)
    tpath.write_text(json.dumps(timings, indent=1), encoding="utf-8")
    if spend:
        new = not (a.out / "spend.csv").exists()
        with (a.out / "spend.csv").open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["when", "line", "character", "endpoint", "chars", "usd_est"])
            w.writerows(spend)
    print(json.dumps({"lines": len(plan), "new_takes": len(spend), "usd_est": round(sum(float(s[5]) for s in spend), 4),
                      "timings": str(tpath)}))


if __name__ == "__main__":
    main()
