"""mix: voice + music bed (+ optional SFX) -> one 48 kHz mix, loudness-normalised in two passes, muxed onto a video.

    python tools/edit/mix.py --voice voice.wav --music bed.wav [--sfx sfx.wav] [--video picture.mp4] -o out.mp4
           [--under 19] [--music-start 0] [--fade-out 0.9] [--duck START,END,DB ...] [--lufs -16] [--tp -1.5]
           [--report mix.json]

  --voice       one wav with every line already placed, OR a JSON list of {"wav": path, "at": seconds} (for example
                built from tools/voice/lines.py timings + your edit), placed here with 8 ms / 30 ms fades.
  --music       the bed. Its level is set from measured loudness: music sits --under dB (default 19) below the
                voice's integrated loudness, whatever level the file was mastered at.
  --music-start skip into the bed (start on the groove, not the intro).
  --duck        extra dips, e.g. --duck 7.6,9.0,-9 (music 9 dB down from 7.6 to 9.0 s; 0.05 s smoothing). Use it to
                clear the way for a climax line or a sting. Repeatable.
  --sfx         a wav of code-made or library SFX, already placed in time; added at unity gain.
  -o            .wav = the mix only; .mp4/.mov = mux onto --video (video stream copied, never re-encoded).

Loudness: pass 1 measures the raw mix with ffmpeg loudnorm, pass 2 applies the measured values with linear=true, so
the result is a clean gain change, not a pumping compressor. Default target -16 LUFS integrated, true peak -1.5 dBTP
(platforms want <= -1). Output is always 48 kHz stereo; the mp4 gets AAC 192k with +faststart, because 32 kHz AAC
from TTS / lip-sync hosts played silent on some phones.

Prints one JSON line: voice / music LUFS, music gain, final LUFS and true peak. Needs numpy + ffmpeg/ffprobe on PATH.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SR = 48000


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, creationflags=NOWIN, **kw)


def read_audio(p, tmpdir: Path) -> np.ndarray:
    """Any audio (or video's audio) -> mono float64 at 48 kHz."""
    raw = tmpdir / f"_{abs(hash(str(p)))}.f32"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", str(raw)])
    return np.fromfile(raw, np.float32).astype(np.float64)


def write_wav(p, x, ch=1):
    x = np.clip(x, -1, 1)
    if ch == 2 and x.ndim == 1:
        x = np.stack([x, x], 1)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def duration(p) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
            capture_output=True, text=True)
    return float(r.stdout.strip())


def lufs(p):
    """(integrated LUFS, true peak dBTP) from ffmpeg ebur128."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-vn", "-af", "ebur128=peak=true", "-f",
                        "null", "-"], capture_output=True, text=True, creationflags=NOWIN)
    tail = r.stderr.rsplit("Summary:", 1)[-1]
    m = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", tail)
    I = float(m.group(1)) if m and m.group(1) != "-inf" else -math.inf
    m = re.search(r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS", tail)
    tp = float(m.group(1)) if m and m.group(1) != "-inf" else -math.inf
    return I, tp


def place(buf, x, t, fade_in=0.008, fade_out=0.03):
    x = x.copy()
    fi, fo = min(len(x), int(fade_in * SR)), min(len(x), int(fade_out * SR))
    if fi: x[:fi] *= np.linspace(0, 1, fi)
    if fo: x[-fo:] *= np.linspace(1, 0, fo)
    i = int(round(t * SR))
    if i < 0:
        x, i = x[-i:], 0
    x = x[: max(0, len(buf) - i)]
    buf[i:i + len(x)] += x


def two_pass_loudnorm(src: Path, dst: Path, I: float, TP: float, LRA: float = 11.0):
    flt = f"loudnorm=I={I}:TP={TP}:LRA={LRA}"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", flt + ":print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True, creationflags=NOWIN)
    m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    if m["input_i"] in ("-inf", "inf"):
        sys.exit("the mix is silent: nothing to normalise")
    flt2 = (f"{flt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
            f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", flt2, "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le",
         str(dst)])
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice", type=Path, required=True)
    ap.add_argument("--music", type=Path)
    ap.add_argument("--sfx", type=Path)
    ap.add_argument("--video", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--under", type=float, default=19.0, help="music this many dB under the voice (default 19)")
    ap.add_argument("--music-start", type=float, default=0.0)
    ap.add_argument("--fade-out", type=float, default=0.9, help="music fade at the end, seconds")
    ap.add_argument("--duck", action="append", default=[], help="START,END,DB extra music dip; repeatable")
    ap.add_argument("--lufs", type=float, default=-16.0)
    ap.add_argument("--tp", type=float, default=-1.5)
    ap.add_argument("--length", type=float, help="mix length in seconds (default: the video, else the longest stem)")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    if a.output.suffix.lower() in (".mp4", ".mov", ".m4v") and not a.video:
        sys.exit("an .mp4 output needs --video")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # ---- voice
        if a.voice.suffix.lower() == ".json":
            items = json.loads(a.voice.read_text(encoding="utf-8"))
            items = items.get("lines", items) if isinstance(items, dict) else items
            clips = [(read_audio(Path(it["wav"]), td), float(it["at"])) for it in items]
            vlen = max(t + len(x) / SR for x, t in clips) if clips else 0.0
        else:
            clips = [(read_audio(a.voice, td), 0.0)]
            vlen = len(clips[0][0]) / SR
        total = a.length or (duration(a.video) if a.video else None)
        mus_src = read_audio(a.music, td)[int(a.music_start * SR):] if a.music else None
        sfx_src = read_audio(a.sfx, td) if a.sfx else None
        if total is None:
            total = max([vlen] + ([len(sfx_src) / SR] if sfx_src is not None else []))
        N = int(round(total * SR))
        voice = np.zeros(N)
        for x, t in clips:
            place(voice, x, t)
        write_wav(td / "voice.wav", voice)
        lv, _ = lufs(td / "voice.wav")
        if not math.isfinite(lv):
            sys.exit("the voice track is silent")

        mix = voice.copy()
        rep = {"length_s": round(total, 3), "voice_lufs": lv}
        # ---- music bed, set by measured loudness
        if mus_src is not None:
            if len(mus_src) < N:
                print(f"warning: the bed is {len(mus_src) / SR:.1f} s, shorter than the mix ({total:.1f} s); padded with "
                      "silence", file=sys.stderr)
            mus = mus_src[:N] if len(mus_src) >= N else np.pad(mus_src, (0, N - len(mus_src)))
            fo = min(N, int(a.fade_out * SR))
            if fo:
                mus[N - fo:] *= np.linspace(1, 0, fo)
            write_wav(td / "music.wav", mus)
            lm, _ = lufs(td / "music.wav")
            if math.isfinite(lm):
                gain_db = (lv - a.under) - lm
                env = np.ones(N)
                for d in a.duck:
                    s0, s1, db = (float(v) for v in d.split(","))
                    env[int(s0 * SR):int(s1 * SR)] = 10 ** (db / 20)
                k = int(0.05 * SR)
                env = np.convolve(env, np.ones(k) / k, mode="same")
                mix += mus * 10 ** (gain_db / 20) * env
                rep.update(music_lufs=lm, music_gain_db=round(gain_db, 1), music_under_voice_db=a.under,
                           ducks=a.duck)
        # ---- sfx
        if sfx_src is not None:
            s = sfx_src[:N] if len(sfx_src) >= N else np.pad(sfx_src, (0, N - len(sfx_src)))
            mix += s
        peak = float(np.abs(mix).max())
        if peak > 0.99:   # keep the raw sum from clipping before loudnorm sees it
            mix *= 0.99 / peak
        write_wav(td / "mix_raw.wav", mix)
        norm = td / "mix.wav"
        two_pass_loudnorm(td / "mix_raw.wav", norm, a.lufs, a.tp)
        I, tp = lufs(norm)
        if math.isfinite(I) and abs(a.lufs - I) > 0.2 and tp + (a.lufs - I) <= a.tp:  # linear mode can land a bit low
            g = a.lufs - I
            run(["ffmpeg", "-v", "error", "-y", "-i", str(norm), "-af", f"volume={g:.2f}dB", "-c:a", "pcm_s16le",
                 str(td / "mix2.wav")])
            norm = td / "mix2.wav"
            I, tp = lufs(norm)

        a.output.parent.mkdir(parents=True, exist_ok=True)
        if a.output.suffix.lower() == ".wav":
            shutil.copyfile(norm, a.output)
        else:
            run(["ffmpeg", "-v", "error", "-y", "-i", str(a.video), "-i", str(norm), "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2", "-t", f"{total:.3f}",
                 "-movflags", "+faststart", str(a.output)])
            I, tp = lufs(a.output)
    rep.update(final_lufs=I, final_tp=tp, output=str(a.output))
    ok = abs(I - a.lufs) <= 1.0 and tp <= -1.0
    rep["delivery_ok"] = ok
    if a.report:
        a.report.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep))
    if not ok:
        print(f"warning: final {I} LUFS / {tp} dBTP is off target ({a.lufs} LUFS, TP <= -1)", file=sys.stderr)


if __name__ == "__main__":
    main()
