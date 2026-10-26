# Explainer critic: measure a channel you admire, then score your scripts against it (2026-10)

Explainer videos live or die on pacing and structure: how fast the hook pays off, when the first "but" lands, how
often a big number gets an everyday picture, how long the picture sits still. Those things are measurable. This
guide and `tools/explainer-critic/` turn a reference channel you admire into numbers (a **bible**), score your scripts
and cuts against them, and put a **blind critic** on top that can't be talked into a pass.

**Learn structure and rhythm. Never copy words or art.** The bible holds numbers only; a copy guard fails any script
that shares 8 or more words in a row with the reference.

## The method

1. **Pick a reference you admire** and have legal access to (a channel you watch, your own past hits). 20-60 videos
   is plenty; include its Shorts if you make Shorts. Captions are the only text needed; low-res copies (240-360p)
   are optional, for cut timing.
2. **Measure it into a bible:**
   ```bash
   python tools/explainer-critic/build_bible.py --urls urls.txt --corpus refs/mychannel --out bible.json
   python tools/explainer-critic/build_bible.py --urls urls.txt --corpus refs/mychannel --download-video --out bible.json
   python tools/explainer-critic/build_bible.py --captions my/caption/folder --out bible.json   # VTT/SRT you have
   ```
   It uses yt-dlp for captions (and `--download-video` for low-res copies), splits Shorts (<= 180 s, `--short-max`)
   from long videos, holds out ~20% for calibration, and writes medians, IQRs and p10/p90 per metric. Everything is
   cached; `--dry-run` shows what it would fetch.
3. **Score a script or a cut against it** (free with the default heuristic judge):
   ```bash
   python tools/explainer-critic/score.py script.txt --bible bible.json --refs refs/mychannel/subs
   python tools/explainer-critic/score.py cut.mp4 --captions cut.srt --bible bible.json --refs refs/mychannel/subs
   ```
   You get `report.md` + `score.json`: a 0-100 score, a verdict, P0/P1/P2 issues with timestamps, the metrics table,
   the pacing curve and per-sentence flags. Exit code 1 on any P0.
4. **Ask the blind critic** ([agents/explainer-critic.md](agents/explainer-critic.md)): give it only the artifact path
   and the bible. It runs the scorer, reads the whole script, checks what numbers can't (one question answered? does
   the ending land? does the picture match the words?), and returns a verdict, timestamped issues and up to 3
   rewrites in your voice. It never sees the builder's reasoning.
5. **Write, score, rewrite** (the loop below) until the critic and the score agree.

Try it now with the example: `python tools/explainer-critic/score.py tools/explainer-critic/example/sample_script.txt
--bible tools/explainer-critic/example/bible.example.json` (ON BAR, about 95) and the same with
`sample_script.weak.txt` (FAIL: no stakes, no turn, a fact pile-up, a recap ending).

## What it measures

| Metric | What it is | How |
|---|---|---|
| Speech rate and pacing curve | words per second overall, per tenth of runtime, and the slowest tenth vs the median | caption timings (scripts: estimated at `--wps`, default 2.7) |
| Hook, first number, first stakes | seconds until the viewer gets a number or a reason to care | regex for numbers; the judge for stakes |
| Turns and twist positions | when the first complication and the later twist start, turns per minute | the judge's act labels |
| Resolution start | where the answer / reframe begins, % of runtime | act labels |
| Comparisons per minute | metaphors and everyday-scale comparisons | the judge |
| Longest plain-fact run | sentences in a row with no comparison, turn or question | per-sentence flags |
| Sentence lengths | median, p90, share over 25 words; punch lines (a short line after a long one) | counting |
| Question and "you" rates | questions per minute, "you" per 100 words | regex |
| Picture-change rate | cuts, pans, zooms and big moves per minute; longest stretch with no change; frozen frames; shot lengths | ffmpeg on the (low-res) video, free |
| Ending type | takeaway, reframe, optimistic, question, joke, summary, abrupt | the judge's act labels |
| Structural checks | 11 yes/no questions: specific opener, central question, early stakes, a turn, a plain mechanism, numbers made real, ending lands, fact pile-up, unexplained jargon, lecture tone, moralising | the judge |

**Judges** (`--judge`): `heuristic` (default; regex and word lists, free, deterministic, coarse: it undercounts
comparisons), `jev` (TypeSafe Jev, `TYPESAFE_API_KEY`; about $0.0002 per 75-second script), `openai` (any
OpenAI-compatible endpoint: `EXPLAINER_OPENAI_BASE`, `EXPLAINER_OPENAI_KEY`, `EXPLAINER_OPENAI_MODEL`; a local Ollama
works), `fal` (fal's OpenRouter router, `FAL_KEY`, `EXPLAINER_FAL_MODEL`; about $0.003 per script). Act labels come
from `--acts` (heuristic, openai or fal); Jev answers yes/no only, so with `--judge jev` the acts default to heuristic.
**Build and score with the same judge**: the judgment metrics are judge-specific, and the scorer notes a mismatch.
`--max-cost` caps spend per run; answers are cached, so re-scoring is free.

**Scoring.** Each metric scores 1.0 inside the reference IQR, 0.75 inside p10-p90, then decays; one-sided metrics
(hook time, numbers per minute) only penalise the harmful side. Overall = 70% metrics + 30% structural checks.
**Verdicts:** any P0 = FAIL; ON BAR = 85+ with at most one P1; CLOSE = 72+; else BELOW BAR. On the reference this
was built for, held-out reference videos scored a median of about 88 (Shorts lower, 71-82), so ON BAR means "as
tight as the reference's typical video".

**House rules.** Add your own to the bible's `house` block, per format: `first_number_max_s` (a number in line 1),
`stakes_max_s`. They raise P1s.

## What the targets typically look like

From a popular narrated science-explainer channel (about 50 videos, measured with an LLM judge; your reference will
differ, which is the point of measuring it):

| Target | Shorts (about 70 s) | Long (7-14 min) |
|---|---|---|
| Speech rate | about 2.9 words/s (165-175 words a minute), barely varying | about 2.8 |
| Slowest tenth vs median tenth | about 0.8 | about 0.9: no dead stretches |
| Hook (first stakes or number) | 5-20 s | 6-15 s; stakes by about 10 s |
| First turn | 20-50% of runtime | 20-50%; a second turn around 55-60% |
| Resolution starts | 80-90% | 85-95%; nothing after it but a kicker |
| Turns per minute | about 1.7 | about 1.4: a reversal every 40 s or so |
| Comparisons per minute | 2-2.5 | about 3: big numbers get an everyday picture |
| Longest plain-fact run | 3-5 sentences | 5-10 |
| Sentence length | median about 14 words, p90 about 23 | median 15, p90 about 27 |
| Picture changes | a new picture every 0.25-2 s; longest still stretch about 5 s | longest about 11 s |
| Hard cuts | rarer than you'd think: median shot about 5 s; the picture moves within shots | |
| Endings | mostly a reframe, then a practical takeaway; almost never a recap | same; promos come after the story |

The example bible (`tools/explainer-critic/example/bible.example.json`) was built from the same kind of corpus with the
free heuristic judge, so its comparison counts read low; build your own before trusting the comparison metrics.

## The write-score-rewrite loop

The scorer is the reward, script variants are the samples, and the weak metrics of the current best become the next
brief. Nothing is fine-tuned; the learning lives in the brief and the score log.

1. **Setup.** Work in `<episode>/critic-loop/`; never overwrite the real script. Keep a `facts.md` that is the only
   allowed source of numbers.
2. **Generate N variants (default 4)** as `r<round>-v<k>.txt`. Each keeps every number and claim exactly as in
   `facts.md`, keeps the characters' voices, and tries a *different structural idea*, not a synonym swap: open on the
   single most surprising number; open on a concrete scene; move the turn earlier; cut the weakest third and give the
   best fact a comparison. Use a fresh context per variant so variants don't converge.
3. **Score all variants** and the current best (`score.py --quiet --out ...`). Log each in `critic-loop/scores.jsonl`:
   `{"round", "variant", "overall", "verdict", "p0", "low_metrics": [...]}`.
4. **Select** the highest overall with zero P0; ties go to the shorter script.
5. **Feedback brief:** the best variant's 3 lowest-scoring metrics and every P0/P1, each turned into an instruction
   ("first stakes at 19 s, reference p75 is 9 s: say why it matters in line 2").
6. **Stop** when the score is >= 85 with zero P0 two rounds running, when it hasn't improved for 2 rounds, or after 4
   rounds.

**Guard rails.** Goodhart check: run the blind critic on the winner; if its call disagrees with the score, the critic
wins and the disagreement is logged. If two variants are within 3 points, hand both, shuffled and unlabelled, to blind
critics ([QA.md](QA.md)) and let them pick. The copy guard runs on every variant; any hit is a P0. A human still
picks the take.

## Ground rules

- **Structure and rhythm only.** Never copy the reference's lines, scripts, catchphrases, sign-offs, characters, art,
  palette, music or narrator voice. The copy guard (`--refs`, 8-word runs by default, `--ngram`) catches verbatim
  reuse; the critic also flags close paraphrase.
- **Keep downloaded captions private.** They are the reference's text: use them to measure, never commit or
  redistribute them. `refs/`, `corpus/`, `*.vtt` caches and the per-video `analysis/` files are git-ignored
  here. The bible itself holds distributions only (no text, titles or ids), so it is safe to commit.
- **Your own legal access.** Fetch captions for videos you can watch; respect the platform's terms and rate limits
  (`--sleep-requests` is set). Low-res video is for timing measurements only.
- **The numbers are evidence, not taste.** A script can hit every target and still be dull, or miss one on purpose.
  The critic exists to make that call, and a human makes the last one.

## Where it fits in the animation workflow

- **Script gate, before recording voices:** score the script and run the blind critic. Fix every P0 before any voice
  or lip-sync spend; a rewrite is free, a re-recorded voice track and re-synced shots are not. See [AGENTS.md](AGENTS.md)
  and [VOICES.md](VOICES.md).
- **Rough-cut gate:** score the cut with its captions. It adds picture pacing (no stretch without a picture change
  longer than the reference's, no frozen frames); pair it with the voice-over sync check
  (`tools/vosync/vosync.py --kind explainer`, [QA.md](QA.md)) so the picture changes land on the words they illustrate.
- **Before posting:** the same cut gates as everything else ([QA.md](QA.md), [LESSONS.md](LESSONS.md)).
