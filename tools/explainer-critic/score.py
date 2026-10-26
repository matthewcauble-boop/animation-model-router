"""explainer-critic scorer: measure one explainer script or cut against a bible.json.

    python tools/explainer-critic/score.py SCRIPT --bible bible.json [--refs refs/mychannel/subs]
    python tools/explainer-critic/score.py cut.mp4 --captions cut.srt --bible bible.json [--refs DIR]

SCRIPT can be:
  .txt / .md       plain narration (blank line = new paragraph; "# headings" and "NAME: " speaker tags are dropped)
  .json / .jsonl   lines: [{"text", "speaker"?, "start"?, "end"?, "pause"?}] or {"lines": [...]}
  .csv             columns text[,start,end,speaker]
  .srt / .vtt      captions of a recorded VO or a finished cut (real timings)
  .mp4/.mov/.webm  a cut: needs --captions (or a same-name .srt/.vtt beside it); adds picture-pacing metrics
Untimed scripts are timed at --wps (default 2.7 words/s); say so when you report.

Options: --judge heuristic|jev|openai|fal (default: the judge the bible was built with), --acts heuristic|openai|fal,
         --format auto|short|long, --refs DIR (repeatable; reference captions/transcripts for the COPY GUARD),
         --ngram 8, --max-cost 0.10, --out DIR, --quiet
Writes <out>/report.md and <out>/score.json (default out: explainer-critic-<name>/ beside the input).
Exit code 1 if any P0.

Verdict: FAIL (P0) if any P0; ON BAR if score >= 85 with at most one P1; CLOSE if >= 72; else BELOW BAR.
Score = 70% metrics (1.0 inside the reference IQR, 0.75 inside p10-p90, then decaying) + 30% structural checks.
COPY GUARD: any run of --ngram (8) or more words shared with the reference captions is a P0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import eclib

# metric -> (weight, side, label, unit). side: both | upper (only too high is bad) | lower (only too low is bad)
SPEC = {
    "wps": (2.0, "both", "words per second", "w/s"),
    "pacing_sag": (1.0, "lower", "pacing sag (slowest tenth / median tenth)", ""),
    "hook_s": (2.0, "upper", "hook: seconds to first stakes or number", "s"),
    "first_stakes_s": (1.5, "upper", "seconds to first stakes", "s"),
    "first_number_s": (1.0, "upper", "seconds to first concrete number", "s"),
    "turns_per_min": (1.0, "lower", "turns (reversals) per minute", "/min"),
    "first_turn_pct": (1.0, "both", "first complication/twist position", "% of runtime"),
    "questions_per_min": (0.5, "lower", "questions per minute", "/min"),
    "longest_plain_run": (1.0, "upper", "longest run of plain sentences (no comparison, turn or question)", "sentences"),
    "punch_per_min": (0.5, "lower", "punch lines per minute (short line after a long one)", "/min"),
    "you_per_100w": (1.0, "lower", "'you' per 100 words", ""),
    "analogies_per_min": (1.5, "lower", "comparisons per minute", "/min"),
    "numbers_per_min": (1.0, "upper", "numbers per minute", "/min"),
    "jargon_per_min": (1.0, "upper", "unexplained-jargon sentences per minute", "/min"),
    "sent_len_median": (1.0, "both", "median sentence length", "words"),
    "sent_len_p90": (0.75, "upper", "90th-percentile sentence length", "words"),
    "long_sentence_share": (0.75, "upper", "share of sentences over 25 words", ""),
    "resolution_first_pct": (0.75, "both", "resolution starts at", "% of runtime"),
}
CUT_SPEC = {
    "picture_changes_per_min": (2.0, "lower", "picture changes per minute (cuts, pans, zooms, big moves)", "/min"),
    "picture_gap_median": (1.0, "upper", "median time between picture changes", "s"),
    "longest_no_change": (1.5, "upper", "longest stretch with no picture change", "s"),
    "longest_static": (1.0, "upper", "longest frozen stretch", "s"),
    "shot_median": (0.5, "upper", "median hard-cut shot length", "s"),
}
PCT_METRICS = {"first_turn_pct", "resolution_first_pct"}
P1_STRUCT = ("has_turn", "ending_lands", "stakes_early", "open_specific", "central_question")


def fmt_t(s):
    if s is None:
        return "-"
    s = float(s)
    return f"{int(s // 60)}:{s % 60:04.1f}"


def metric_score(v, d, side):
    """1.0 inside the IQR, 0.75 inside p10-p90, then decays. One-sided metrics ignore the harmless side."""
    if v is None or not d:
        return None, "n/a"
    p10, p25, p75, p90 = d["p10"], d["p25"], d["p75"], d["p90"]
    iqr = max(p75 - p25, 1e-6, 0.15 * abs(d["p50"] or 1))
    lo_ok, hi_ok = side == "upper", side == "lower"
    if p25 <= v <= p75 or (lo_ok and v < p25) or (hi_ok and v > p75):
        return 1.0, "in range"
    if p10 <= v <= p90 or (lo_ok and v < p10) or (hi_ok and v > p90):
        return 0.75, "edge"
    dist = (p10 - v) if v < p10 else (v - p90)
    return max(0.0, 0.75 - 0.5 * dist / iqr), ("low" if v < p10 else "high")


def find_input(p: Path, captions: Path | None):
    if p.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv"):
        if captions:
            return captions, p
        for c in (p.with_suffix(".srt"), p.with_suffix(".vtt")):
            if c.exists():
                return c, p
        raise SystemExit("a cut needs its captions: pass --captions cut.srt")
    return p, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--bible", type=Path, required=True)
    ap.add_argument("--captions", type=Path)
    ap.add_argument("--video", type=Path)
    ap.add_argument("--refs", type=Path, action="append", default=[], help="reference captions for the copy guard")
    ap.add_argument("--ngram", type=int, default=8)
    ap.add_argument("--judge", choices=["heuristic", "jev", "openai", "fal"])
    ap.add_argument("--acts", choices=["heuristic", "openai", "fal"])
    ap.add_argument("--format", default="auto", choices=["auto", "short", "long"])
    ap.add_argument("--title", default="")
    ap.add_argument("--wps", type=float, default=2.7, help="speech rate for untimed scripts")
    ap.add_argument("--max-cost", type=float, default=0.10)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    eclib.MAX_COST[0] = a.max_cost

    bible = json.loads(a.bible.read_text(encoding="utf-8"))
    judge_kind = a.judge or bible.get("judge", "heuristic")
    acts_kind = a.acts or (bible.get("acts_judge") if not a.judge else None)
    judge = eclib.make_judge(judge_kind, acts_kind)
    notes = []
    if judge.name != bible.get("judge", "heuristic") or judge.acts_name != bible.get("acts_judge", judge.acts_name):
        notes.append(f"Judge mismatch: bible built with {bible.get('judge')}+{bible.get('acts_judge')}, scored with "
                     f"{judge.name}+{judge.acts_name}. Judgment metrics are not strictly comparable.")
    src, video = find_input(a.input, a.captions)
    video = a.video or video
    words, timing = eclib.load_words(src, a.wps)
    if not words:
        raise SystemExit("no words found")
    res = eclib.analyse(words, judge, a.title or a.input.stem)
    rt = res["runtime_s"]
    fmt = a.format if a.format != "auto" else ("short" if rt <= bible.get("short_max_s", 180) else "long")
    if fmt not in bible:
        fmt = "short" if "short" in bible else "long"
        notes.append(f"Bible has no targets for this length; using {fmt} targets.")
    T = bible[fmt]
    house = (bible.get("house") or {}).get(fmt) or {}
    sents = res.pop("_sentences")

    rows, tot, tot_w = [], 0.0, 0.0
    for k, (w, side, label, unit) in SPEC.items():
        v, d = res.get(k), T.get(k)
        sc, state = metric_score(v, d, side)
        if k in ("first_stakes_s", "first_number_s") and v is None and d:
            sc, state = 0.0, "missing"
        rows.append((label, v, d, state, sc, unit, k))
        if sc is not None:
            tot += w * sc
            tot_w += w
    cut, CT = None, None
    if video:
        cb = bible.get("cut") or {}
        CT = cb.get(fmt) if ((cb.get(fmt) or {}).get("longest_no_change") or {}).get("n", 0) >= 3 else cb.get("all")
        cut = eclib.cut_metrics(video)
        if not CT:
            notes.append("Bible has no cut targets (build it with low-res videos); cut metrics are reported, not scored.")
        for k, (w, side, label, unit) in CUT_SPEC.items():
            v, d = cut.get(k), (CT or {}).get(k)
            sc, state = metric_score(v, d, side)
            rows.append((label, v, d, state, sc, unit, "cut." + k))
            if sc is not None:
                tot += w * sc
                tot_w += w
    metric_part = tot / tot_w if tot_w else 0

    struct_rows, s_pass, s_n = [], 0, 0
    for k, p in (res.get("structural") or {}).items():
        d = (T.get("structural") or {}).get(k)
        if not d:
            continue
        good_if_yes = eclib.STRUCT_Q[k][1]
        if good_if_yes:
            ok, bad = p >= min(d["p25"], 0.5), p < min(d["p10"], 0.35)
        else:
            ok, bad = p <= max(d["p75"], 0.5), p > max(d["p90"], 0.65)
        s_n += 1
        s_pass += ok
        struct_rows.append((k, p, d, ok, bad))
    struct_part = s_pass / s_n if s_n else 0
    overall = round(100 * (0.7 * metric_part + 0.3 * struct_part), 1) if s_n else round(100 * metric_part, 1)

    issues = []  # (sev, t, text)

    def tgt(k, q="p75"):
        return (T.get(k) or {}).get(q)
    if res["first_stakes_s"] is None:
        issues.append(("P0", 0, "No stakes anywhere: the viewer is never told why this matters to them."))
    elif tgt("first_stakes_s", "p90") and res["first_stakes_s"] > tgt("first_stakes_s", "p90"):
        issues.append(("P0", res["first_stakes_s"], f"Stakes arrive late ({res['first_stakes_s']:.1f} s; reference p90 "
                       f"{tgt('first_stakes_s', 'p90'):.1f} s). Say why it matters inside the first beat."))
    if tgt("hook_s", "p90") and res["hook_s"] > tgt("hook_s", "p90"):
        issues.append(("P0", 0, f"Hook too slow: {res['hook_s']:.1f} s before the first stake or number (reference "
                       f"median {tgt('hook_s', 'p50'):.1f} s, p90 {tgt('hook_s', 'p90'):.1f} s)."))
    elif tgt("hook_s") and res["hook_s"] > tgt("hook_s"):
        issues.append(("P1", 0, f"Hook slower than most reference videos ({res['hook_s']:.1f} s vs p75 {tgt('hook_s'):.1f} s)."))
    fn = res["first_number_s"]
    if house.get("first_number_max_s") is not None and (fn is None or fn > house["first_number_max_s"]):
        issues.append(("P1", fn, f"House rule: first concrete number at {'never' if fn is None else f'{fn:.1f} s'}; "
                       f"your rule puts it by {house['first_number_max_s']} s."))
    if house.get("stakes_max_s") is not None and res["first_stakes_s"] and res["first_stakes_s"] > house["stakes_max_s"]:
        issues.append(("P1", res["first_stakes_s"], f"House rule: stakes by {house['stakes_max_s']} s "
                       f"(here {res['first_stakes_s']:.1f} s)."))
    if not res["turn_positions_pct"] and res["turns_per_min"] < (tgt("turns_per_min", "p10") or 0):
        issues.append(("P0", None, "Missing turn: nothing complicates or overturns the first explanation."))
    elif not res["turn_positions_pct"]:
        issues.append(("P1", None, "No complication or twist section: the story never says 'but here is the catch'."))
    elif res["first_turn_pct"] is not None and tgt("first_turn_pct", "p90") and res["first_turn_pct"] > tgt("first_turn_pct", "p90"):
        issues.append(("P1", res["first_turn_pct"] * rt, f"First turn comes late ({res['first_turn_pct']:.0%} of runtime; "
                       f"reference median {tgt('first_turn_pct', 'p50'):.0%})."))
    curve = res["pacing_curve_wps"]
    med = sorted(curve[1:9])[4] if len(curve) >= 9 else None
    if med:
        for i in range(1, 9):
            if curve[i] < 0.7 * med:
                issues.append(("P1", rt * i / 10, f"Pacing sag {fmt_t(rt * i / 10)}-{fmt_t(rt * (i + 1) / 10)}: {curve[i]:.2f} "
                               f"w/s vs {med:.2f} median. Tighten it, or put picture or music to work there."))
    wd = T.get("wps")
    if wd and res["wps"] > wd["p90"] * 1.05:
        issues.append(("P1", None, f"Talking too fast overall ({res['wps']} w/s vs reference {wd['p25']}-{wd['p75']})."))
    if wd and res["wps"] < wd["p10"] * 0.95:
        issues.append(("P1", None, f"Talking too slowly overall ({res['wps']} w/s vs reference {wd['p25']}-{wd['p75']}). "
                       f"Cut words and gaps; don't speed the voice up."))
    if res["ending"] in ("summary", "abrupt"):
        issues.append(("P1", rt * 0.9, f"Flat ending ({res['ending']}): end on a reframe or a takeaway, not a recap."))
    if tgt("longest_plain_run", "p90") and res["longest_plain_run"] > tgt("longest_plain_run", "p90"):
        issues.append(("P1", res["longest_plain_run_at"], f"Fact pile-up: {res['longest_plain_run']} sentences in a row with no "
                       f"comparison, turn or question (reference p90 {tgt('longest_plain_run', 'p90'):.0f}). Break it up."))
    if tgt("numbers_per_min", "p90") and res["numbers_per_min"] > tgt("numbers_per_min", "p90"):
        issues.append(("P1", None, f"Too many numbers: {res['numbers_per_min']}/min (reference p90 "
                       f"{tgt('numbers_per_min', 'p90')}). Keep one number per idea."))
    if tgt("analogies_per_min", "p10") is not None and res["analogies_per_min"] < tgt("analogies_per_min", "p10"):
        issues.append(("P1", None, f"Too few comparisons: {res['analogies_per_min']}/min (reference median "
                       f"{tgt('analogies_per_min', 'p50')}). Give each big number an everyday picture."))
    for s in sents:
        j = s.get("judge", {})
        if j.get("jargon", 0) >= 0.8:
            issues.append(("P2", s["t0"], f"Jargon without a plain-words gloss: \"{s['text'][:90]}\""))
        if s["n"] > max(30, (tgt("sent_len_p90", "p90") or 30) + 5):
            issues.append(("P2", s["t0"], f"Long sentence ({s['n']} words): \"{s['text'][:90]}...\""))
    for k, p, d, ok, bad in struct_rows:
        if bad:
            issues.append(("P1" if k in P1_STRUCT else "P2", None, f"Structure check '{k}' fails (p={p:.2f}; reference "
                           f"p10-p90 {d['p10']:.2f}-{d['p90']:.2f})."))
    if cut and CT:
        lim = CT["longest_no_change"]["p90"]
        pcs = [0.0]
        for g in cut["picture_gaps"]:
            pcs.append(pcs[-1] + g)
        for a0, b0 in zip(pcs, pcs[1:]):
            if b0 - a0 > lim:
                issues.append(("P0" if b0 - a0 > 2 * lim else "P1", a0, f"No picture change for {b0 - a0:.1f} s "
                               f"({fmt_t(a0)}-{fmt_t(b0)}); reference p90 {lim:.1f} s. Cut in, move the camera, or bring "
                               f"an element on."))
        if cut["picture_changes_per_min"] < (CT["picture_changes_per_min"]["p10"] or 0) * 0.8:
            issues.append(("P1", None, f"Picture changes too rarely ({cut['picture_changes_per_min']}/min vs reference "
                           f"{CT['picture_changes_per_min']['p25']}-{CT['picture_changes_per_min']['p75']})."))
        for s0, e0 in cut["static_stretches"]:
            if e0 - s0 > (CT["longest_static"]["p90"] or 99):
                issues.append(("P1", s0, f"Frozen frame {fmt_t(s0)}-{fmt_t(e0)} ({e0 - s0:.1f} s)."))

    # COPY GUARD
    ref_dirs = a.refs or [d for d in (a.bible.parent / "refs",) if d.exists()]
    ref_texts = eclib.reference_texts(ref_dirs)
    hits = eclib.copy_check(sents, ref_texts, a.ngram)
    for h in hits:
        issues.append(("P0", h["t"], f"COPY GUARD: {a.ngram}+ words match the reference: \"{h['phrase']}\". "
                       f"Rewrite it in your own words."))
    if not ref_texts:
        issues.append(("P2", None, "Copy guard not run: pass --refs DIR (the reference captions you built the bible from)."))

    sev_rank = {"P0": 0, "P1": 1, "P2": 2}
    issues.sort(key=lambda x: (sev_rank[x[0]], x[1] if x[1] is not None else -1))
    n_p0 = sum(i[0] == "P0" for i in issues)
    n_p1 = sum(i[0] == "P1" for i in issues)
    verdict = "FAIL (P0)" if n_p0 else ("ON BAR" if overall >= 85 and n_p1 <= 1 else "CLOSE" if overall >= 72 else "BELOW BAR")

    out = a.out or a.input.parent / f"explainer-critic-{a.input.stem}"
    out.mkdir(parents=True, exist_ok=True)
    secs = " > ".join(f"{s['label']}@{fmt_t(s['start_s'])}" for s in res["sections"])
    L = [f"# explainer-critic: {a.input.name}", "",
         f"**Verdict: {verdict}** | overall {overall}/100 (metrics {metric_part * 100:.0f}, structure {s_pass}/{s_n}) | "
         f"**{fmt}** targets | runtime {fmt_t(rt)} | {res['words']} words | timing: {timing} | judge {judge.name}+{judge.acts_name}",
         f"Central question: {res.get('central_question') or '(none found)'}", f"Ending: {res.get('ending')}",
         f"Sections: {secs}", ""] + [f"Note: {n}" for n in notes] + ["", "## Issues", ""]
    for sev, t, txt in issues:
        L.append(f"- **{sev}** {('[' + fmt_t(t) + '] ') if t is not None else ''}{txt}")
    if not issues:
        L.append("- none")
    L += ["", "## Metrics vs bible", "", "| metric | this | ref p25-p75 (p10-p90) | state | score |", "|---|---|---|---|---|"]
    for label, v, d, state, sc, unit, k in rows:
        mul = 100 if k.split(".")[-1] in PCT_METRICS else 1
        vv = "-" if v is None else (f"{v * mul:.0f}%" if mul == 100 else f"{v}")
        rr = "-" if not d else f"{d['p25'] * mul:.3g}-{d['p75'] * mul:.3g} ({d['p10'] * mul:.3g}-{d['p90'] * mul:.3g})"
        L.append(f"| {label} | {vv} {unit if mul == 1 else ''} | {rr} | {state} | {'-' if sc is None else f'{sc:.2f}'} |")
    L += ["", "## Structural checks", "", "| check | p(yes) | ref p10-p90 | pass |", "|---|---|---|---|"]
    for k, p, d, ok, bad in struct_rows:
        L.append(f"| {k} ({'want yes' if eclib.STRUCT_Q[k][1] else 'want no'}) | {p:.2f} | {d['p10']:.2f}-{d['p90']:.2f} | {'yes' if ok else 'NO'} |")
    L += ["", "## Pacing curve (words/s per tenth of runtime)", "", " ".join(f"{x:.1f}" for x in curve)]
    if cut:
        L += ["", "## Cut", "", f"{cut['picture_changes_per_min']} picture changes/min (median gap {cut['picture_gap_median']} s, "
              f"longest {cut['longest_no_change']} s at {fmt_t(cut['longest_no_change_at'])}); {len(cut['cuts'])} hard cuts, "
              f"median shot {cut['shot_median']} s; longest frozen {cut['longest_static']} s."]
        cut.pop("shots", None)
    L += ["", "## Sentence flags", ""]
    for s in sents:
        j = s.get("judge", {})
        tags = [k for k in ("stakes", "turn", "analogy") if j.get(k, 0) >= 0.6] + (["JARGON"] if j.get("jargon", 0) >= 0.8 else [])
        if tags or s["n"] > 25:
            L.append(f"- [{fmt_t(s['t0'])}] ({s['n']}w) {', '.join(tags)}: {s['text'][:110]}")
    L += ["", f"Copy guard: {len(ref_texts)} reference texts, {len(hits)} hit(s) at {a.ngram}+ words.",
          f"Spend this run: ${eclib.SPEND['usd']:.4f} ({eclib.SPEND['calls']} calls, {eclib.SPEND['cached']} cached)."]
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    js = {"verdict": verdict, "overall": overall, "format": fmt, "metric_part": round(metric_part, 3),
          "structure_pass": [s_pass, s_n], "issues": [{"sev": s, "t": t, "text": x} for s, t, x in issues],
          "metrics": {k: res.get(k) for k in SPEC}, "cut": cut, "analysis": res, "copy_hits": hits,
          "spend": eclib.SPEND, "timing": timing, "judge": f"{judge.name}+{judge.acts_name}", "notes": notes}
    (out / "score.json").write_text(json.dumps(js, indent=1, ensure_ascii=False), encoding="utf-8")
    if not a.quiet:
        print("\n".join(L[: L.index("## Metrics vs bible")]))
    print(f"report: {out / 'report.md'}")
    sys.exit(1 if n_p0 else 0)


if __name__ == "__main__":
    main()
