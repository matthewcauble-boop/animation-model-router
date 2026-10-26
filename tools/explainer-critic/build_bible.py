"""Build a bible.json (measured pacing and structure targets) from a reference channel you admire.

    # from video URLs (captions only, via yt-dlp; your own legal access)
    python tools/explainer-critic/build_bible.py --urls urls.txt --corpus refs/mychannel --out bible.json
    python tools/explainer-critic/build_bible.py URL [URL ...] --corpus refs/mychannel --out bible.json
    # also fetch low-res copies (240-360p) for cut timing
    python tools/explainer-critic/build_bible.py --urls urls.txt --corpus refs/mychannel --download-video --out bible.json
    # from caption files you already have (VTT/SRT, any folder, recursive)
    python tools/explainer-critic/build_bible.py --captions path/to/captions --videos path/to/lowres --out bible.json

Options: --judge heuristic|jev|openai|fal  (default heuristic: free, no API)
         --acts heuristic|openai|fal       (act labels + ending type; default: same as --judge, heuristic for jev)
         --short-max 180  (seconds; at or under = "short" targets, over = "long")
         --holdout 0.2    (share of videos kept out of the targets, listed for calibration)
         --max-cost 1.0   (USD cap on judge calls; everything is cached, so re-runs are free)
         --dry-run        (list what would be downloaded / analysed; no network, no judge calls)

What it writes
  <out>                        bible.json: per-format distributions (n, p10, p25, p50, p75, p90) of every metric, the
                               ending mix, section mix and structural-check distributions. NO text, titles or ids.
  <corpus>/analysis/<id>.json  per-video analysis. It holds the reference's sentences: PRIVATE, keep out of git.
  <corpus>/subs, video, meta   downloads. PRIVATE, keep out of git (refs/ and corpus/ are git-ignored here).

Captions are the only text needed. Never commit or redistribute the reference's captions, titles or scripts; the
bible keeps numbers only. Build and score with the same --judge: the judgment metrics are judge-specific.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import eclib

METRICS = ["wps", "pacing_sag", "pacing_cv", "hook_s", "hook_pct", "first_number_s", "first_stakes_s",
           "turns_per_min", "first_turn_pct", "questions_per_min", "you_per_100w", "we_per_100w",
           "analogies_per_min", "numbers_per_min", "jargon_per_min", "sent_len_median", "sent_len_p90",
           "long_sentence_share", "n_mechanism_blocks", "complication_first_pct", "twist_first_pct",
           "resolution_first_pct", "runtime_s", "turn_count_story", "punch_per_min", "short_sentence_share",
           "longest_plain_run"]
CUT_METRICS = ["picture_changes_per_min", "picture_gap_median", "picture_gap_p90", "longest_no_change",
               "shot_median", "shot_p75", "shot_p90", "cuts_per_min", "longest_shot", "longest_static", "static_share"]
VIDEO_EXT = (".webm", ".mkv", ".mp4", ".mov")


def ytdlp(urls: list[str], corpus: Path, video: bool, dry: bool, max_videos: int | None):
    exe = shutil.which("yt-dlp")
    base = [exe or "yt-dlp", "--ignore-errors", "--no-overwrites", "--sleep-requests", "1"]
    if max_videos:
        base += ["--playlist-end", str(max_videos)]
    subs = base + ["--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en,en-orig",
                   "--sub-format", "vtt", "--write-info-json", "--no-write-playlist-metafiles",
                   "-o", str(corpus / "subs" / "%(id)s.%(ext)s"), "-o", "infojson:" + str(corpus / "meta" / "%(id)s")]
    cmds = [subs + urls]
    if video:
        cmds.append(base + ["-f", "worst[height>=240][height<=360]/worstvideo[height>=240]/worst", "-q",
                            "-o", str(corpus / "video" / "%(id)s.%(ext)s")] + urls)
    for c in cmds:
        print(("DRY RUN: " if dry else "") + " ".join(c[:14]) + (" ..." if len(c) > 14 else ""), file=sys.stderr)
        if not dry:
            if not exe:
                raise SystemExit("yt-dlp not found on PATH (pip install yt-dlp), or pass --captions DIR instead")
            subprocess.run(c, **eclib.NOWIN)


def collect(caption_dirs: list[Path], video_dirs: list[Path], meta_dirs: list[Path]) -> dict:
    """-> {id: {"subs": path, "video": path|None, "meta": {...}}}. id = file name up to the first dot."""
    items = {}
    for d in caption_dirs:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() not in (".vtt", ".srt"):
                continue
            vid = p.name.split(".")[0]
            cur = items.setdefault(vid, {"subs": None, "video": None, "meta": {}})
            # prefer human captions (<id>.en.vtt / .srt) over auto "-orig" tracks
            if cur["subs"] is None or ("orig" in cur["subs"].name and "orig" not in p.name):
                cur["subs"] = p
    for d in video_dirs:
        if d.exists():
            for p in d.rglob("*"):
                if p.suffix.lower() in VIDEO_EXT and p.name.split(".")[0] in items:
                    items[p.name.split(".")[0]]["video"] = p
    for d in meta_dirs:
        if d.exists():
            for p in d.rglob("*.info.json"):
                vid = p.name.split(".")[0]
                if vid in items:
                    try:
                        j = json.loads(p.read_text(encoding="utf-8"))
                        items[vid]["meta"] = {"duration": j.get("duration"), "title": j.get("title", ""),
                                              "upload_date": j.get("upload_date", "")}
                    except Exception:
                        pass
    return items


def is_holdout(vid: str, share: float) -> bool:
    return share > 0 and (int(hashlib.md5(vid.encode()).hexdigest(), 16) % 1000) < share * 1000


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="*", help="video, playlist or channel URLs (yt-dlp)")
    ap.add_argument("--urls", type=Path, help="text file, one URL per line")
    ap.add_argument("--corpus", type=Path, default=Path("refs/reference"), help="private download folder (git-ignored)")
    ap.add_argument("--captions", type=Path, action="append", default=[], help="folder of .vtt/.srt (recursive)")
    ap.add_argument("--videos", type=Path, action="append", default=[], help="folder of low-res videos named <id>.*")
    ap.add_argument("--download-video", action="store_true", help="also fetch 240-360p copies for cut timing")
    ap.add_argument("--max-videos", type=int, help="cap per playlist/channel URL")
    ap.add_argument("--out", type=Path, default=Path("bible.json"))
    ap.add_argument("--judge", default="heuristic", choices=["heuristic", "jev", "openai", "fal"])
    ap.add_argument("--acts", choices=["heuristic", "openai", "fal"])
    ap.add_argument("--short-max", type=float, default=180)
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--max-cost", type=float, default=1.0)
    ap.add_argument("--rebuild", action="store_true", help="ignore cached per-video analyses")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    eclib.MAX_COST[0] = a.max_cost

    urls = list(a.url) + ([l.strip() for l in a.urls.read_text(encoding="utf-8").splitlines()
                           if l.strip() and not l.startswith("#")] if a.urls else [])
    if urls:
        ytdlp(urls, a.corpus, a.download_video, a.dry_run, a.max_videos)
    caption_dirs = a.captions or [a.corpus / "subs"]
    items = collect(caption_dirs, a.videos + [a.corpus / "video"], caption_dirs + [a.corpus / "meta"])
    print(f"{len(items)} reference videos with captions; {sum(1 for v in items.values() if v['video'])} with video",
          file=sys.stderr)
    if a.dry_run or not items:
        for vid, it in list(items.items())[:20]:
            print(f"  {vid}: {it['subs'].name}{' + video' if it['video'] else ''}", file=sys.stderr)
        if not items:
            print("nothing to analyse: pass URLs or --captions DIR", file=sys.stderr)
        return
    judge = eclib.make_judge(a.judge, a.acts)
    out_dir = a.corpus / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{judge.name}+{judge.acts_name}"

    def run(vid):
        it = items[vid]
        dst = out_dir / f"{vid}.{tag}.json"
        if dst.exists() and not a.rebuild:
            res = json.loads(dst.read_text(encoding="utf-8"))
        else:
            words, _ = eclib.load_words(it["subs"])
            if len(words) < 40:
                print("too few words, skipped:", vid, file=sys.stderr)
                return None
            try:
                res = eclib.analyse(words, judge, it["meta"].get("title", ""))
            except SystemExit:
                raise
            except Exception as e:
                print("FAIL", vid, e, file=sys.stderr)
                return None
            dur = it["meta"].get("duration") or words[-1].t + 1
            res["punctuated"] = sum(1 for w in words if w.w[-1:] in ".?!") / len(words) > 0.03
            res["format"] = "short" if dur <= a.short_max else "long"
            res["holdout"] = is_holdout(vid, a.holdout)
            res["id"] = vid
        if it["video"] and "cut" not in res:
            res["cut"] = eclib.cut_metrics(it["video"])
        dst.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"ok {vid} {res['format']} {res['runtime_s']}s  spend ${eclib.SPEND['usd']:.4f}", file=sys.stderr)
        return res

    with ThreadPoolExecutor(a.jobs) as ex:
        results = [r for r in ex.map(run, list(items)) if r]

    bible = {"_note": "Measured targets from a private reference corpus (captions only). Distributions only: no text, "
                      "titles or ids. Built by tools/explainer-critic/build_bible.py.",
             "judge": judge.name, "acts_judge": judge.acts_name, "short_max_s": a.short_max,
             "_corpus": {"videos": len(results), "long": sum(r["format"] == "long" for r in results),
                         "short": sum(r["format"] == "short" for r in results),
                         "holdout": sum(r["holdout"] for r in results),
                         "with_cut_metrics": sum(1 for r in results if r.get("cut")),
                         "unpunctuated_skipped": sum(1 for r in results if not r.get("punctuated", True))}}
    for fmt in ("short", "long"):
        train = [r for r in results if r["format"] == fmt and not r["holdout"] and r.get("punctuated", True)]
        if not train:
            continue
        t = {k: eclib.dist([r.get(k) for r in train]) for k in METRICS}
        t["structural"] = {k: eclib.dist([(r.get("structural") or {}).get(k) for r in train]) for k in eclib.STRUCT_Q}
        endings = [r.get("ending") for r in train]
        t["endings"] = {e: endings.count(e) for e in sorted(set(endings), key=str)}
        t["has_cta_share"] = round(sum(r["has_cta"] for r in train) / len(train), 2)
        t["has_promo_share"] = round(sum(r["has_promo"] for r in train) / len(train), 2)
        seqs = [r["section_sequence"] or ["hook"] for r in train]
        t["label_share"] = {lab: round(statistics.mean(s.count(lab) / len(s) for s in seqs), 3) for lab in eclib.SECTIONS}
        t["pacing_curve_median"] = [eclib.pct([r["pacing_curve_wps"][i] / max(0.01, r["wps"]) for r in train], 50)
                                    for i in range(10)]
        t["n_train"] = len(train)
        bible[fmt] = t
        cuts = [r for r in results if r.get("cut") and r["format"] == fmt]
        if cuts:
            bible.setdefault("cut", {})[fmt] = {k: eclib.dist([r["cut"].get(k) for r in cuts]) for k in CUT_METRICS}
    allcuts = [r for r in results if r.get("cut")]
    if allcuts:
        bible.setdefault("cut", {})["all"] = {k: eclib.dist([r["cut"].get(k) for r in allcuts]) for k in CUT_METRICS}
    bible["house"] = {"short": {}, "long": {}}  # your own extra rules, e.g. {"first_number_max_s": 7}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(bible, indent=1), encoding="utf-8")
    print(f"wrote {a.out}  ({len(results)} videos; judge {tag}; spend ${eclib.SPEND['usd']:.4f}, "
          f"{eclib.SPEND['calls']} calls, {eclib.SPEND['cached']} cached)")


if __name__ == "__main__":
    main()
