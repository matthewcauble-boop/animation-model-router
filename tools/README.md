# Tools

```
tools/
  common/vision.py            shared yes/no vision backends (Jev, Gemini, fal OpenRouter, Ollama)
  common/launch_detached.ps1  start a long job hidden and detached (Windows)
  continuity/continuity.py    story-continuity checker; --stills = keyframe gate
  continuity/examples/        continuity.example.json (a three-character bible)
  frameqa/frameqa.py          broken-frame QA
  frameqa/questions.default.json, examples/questions.character-swap.json, examples/holds.example.json
  timing/onestwos.py          ones / twos / threes re-timing in the edit
  timing/examples/timing.example.json
  bakeoff/bake.py             resumable fal bake-off runner + ledger
  bakeoff/sheet.py            contact sheets, keyframe strips, dense lip-sync sheets
  bakeoff/critic_pack.py      anonymise + shuffle takes per blind critic
  bakeoff/tally.py            decode critic votes into a table
  bakeoff/examples/           jobs, mapping and votes examples
  vosync/vosync.py            does the picture match the voice-over line, at that moment?
  vosync/examples/            lines.example.json (with two deliberate faults)
  judge/judge.py              fast judge: question bank + verdicts in code + fitted layer + escalation
  judge/questions/            example bank for a generic round mascot (edit the wording here only)
  judge/packs.example.json    packs and verdict rules
  judge/examples/             labels.example.jsonl (eval-set row format)
  breathpacer/pacer.py        breath pacer overlay (small circle)
  breathpacer/hero.py         big guided-breathing panel (disc, ring, countdown, labels)
  fal_run.py                  one fal queue call with a daily cap, a ledger and a dry run
  hf_run.py                   call a Hugging Face Space
```

Install: `pip install -r requirements.txt` (numpy, Pillow, opencv-python-headless; `rapidocr` + `onnxruntime` optional
for frameqa's safe-area OCR). ffmpeg and ffprobe must be on PATH.

## Environment

| Variable | Used by | Notes |
|---|---|---|
| `TYPESAFE_API_KEY` | screen backend `jev` (default) | TypeSafe System One; images are a preview feature (the client sends the opt-in header) |
| `FAL_KEY` | confirmer (fal OpenRouter vision), `--backend fal`, `bake.py` | |
| `GEMINI_API_KEY` | `--backend gemini` / `--screen gemini` | |
| `OLLAMA_HOST` | Ollama backends | default `http://127.0.0.1:11434`; free, slow |
| `AMR_ENV_FILE` | all | a `.env`-style file to read keys from (default `.env` in the working directory) |
| `AMR_CACHE_DIR` | continuity, frameqa | answer cache folder (default `cache/` beside each tool, git-ignored) |
| `CONTINUITY_SCREEN`, `CONTINUITY_FAL_MODEL`, `CONTINUITY_OLLAMA_MODEL` | continuity | defaults for `--screen`, `--fal-model`, `--ollama-model` |
| `FRAMEQA_JEV_MODEL`, `FRAMEQA_MAX_SIDE`, `FRAMEQA_BATCH` | vision backends | |
| `HF_TOKEN` | `hf_run.py` | read token; PRO for more ZeroGPU time |
| `JUDGE_JEV_MODEL`, `JUDGE_CONTEXT` | judge | default `jev-latest` (Box needs jev-1.14+); one sentence of context sent with every frame |
| `JUDGE_OPENAI_BASE`, `JUDGE_OPENAI_KEY` | judge `--backend openai` | any OpenAI-compatible vision endpoint |
| `VOSYNC_OPENAI_BASE`, `VOSYNC_OPENAI_KEY` | vosync `--backend openai` | |
| `AMR_LEDGER` | judge, fal_run | spend ledger CSV (default `spend-ledger.csv` in the working directory) |
| `AMR_DAILY_CAP` | fal_run | default daily cap in USD (5.00) |
| `PACER_FONT_TITLE`, `PACER_FONT_LIGHT`, `PACER_FONT_NUM` | hero.py | font files; else the first system font found |

## continuity.py

```
python tools/continuity/continuity.py VIDEO --bible continuity.json [--timeline timeline.json] [--fps 5]
       [--screen jev|fal|gemini|ollama] [--confirm auto|fal|ollama|none] [--max-confirm 60] [--max-cost 1.0]
       [--shots S3,S4] [--out DIR] [--dry-run]
python tools/continuity/continuity.py --stills --bible continuity.json [--keyframe S3=frames/S3-v2.png]
```

- Output: `continuity-<stem>/` (or `continuity-stills-<name>/`) with `report.md`, `flagged.jpg`, `presence.png`,
  `report.json`, `STATUS.json`. Exit code 1 on any confirmed P0.
- `--timeline` takes `{"shots": [{"id", "start", "end"}]}` from your edit, so a re-cut doesn't need the bible edited.
- `--keyframe SHOT=PATH` tries an alternative start frame for one shot in stills mode.
- Bible format and decision logic: [../QA.md](../QA.md#continuity-checker).

## frameqa.py

```
python tools/frameqa/frameqa.py VIDEO --format 9x16|16x9|1x1|4x5 [--refs a.png b.png] [--questions q.json]
       [--every 0.5] [--holds holds.json] [--palette "#hex,#hex"] [--backend jev|fal|gemini|ollama|none]
       [--confirm MODEL|none] [--no-ocr] [--lufs -16] [--tp-max -1] [--safe l,t,r,b] [--max-cost 1.0]
```

- Output: `frameqa-<stem>/` with `report.md`, `report.json`, `flagged.jpg`, `thumbs/`, `frames/`.
- `--backend none` runs only the free code checks (cuts, black/flat, frozen, flicker, audio, OCR safe area).
- `--holds` marks intended freezes and silences: `[[34, 36], {"start": 78, "end": 81.7}]`.

## onestwos.py

```
python tools/timing/onestwos.py IN.mp4 --spec timing.json -o OUT.mp4 [--pick sharpest|first] [--report r.json]
```

Same frame count, same fps, audio stream copied untouched. Spec and camera modes: [../TIMING.md](../TIMING.md).

## bakeoff/

See [../BAKEOFF.md](../BAKEOFF.md). `bake.py --dry-run` lists every take with its estimated cost before you spend.
`--soft-cap` logs a warning; `--hard-cap` refuses to submit.

## vosync.py

```
python tools/vosync/vosync.py VIDEO --lines LINES.json [--timeline timeline.json] [--frames 5]
       [--backend none|fal|openai] [--model M] [--kind exercise|explainer] [--judge pose] [--max-cost 0.2]
```

- Lines: `[{"id", "start", "end", "text", "shot"?, "kind": "switch"?, "screen_text"?}]` or a timeline with `vo` and
  `shots`. Output `vosync-<stem>/` with `sheet.jpg`, `strips/`, `report.md`, `report.json`. Exit 1 on any P0.
- Checks and rules: [../QA.md](../QA.md#voice-over-sync-vosync). `--kind explainer` asks whether the graphic or the
  talking characters illustrate the line instead of whether a move matches.

## judge/

```
python tools/judge/judge.py judge IMG|VIDEO|DIR --pack P [--ref name=path] [--label "line"] [--every 1.0]
       [--backend jev|fal|openai|ollama] [--escalate fal|openai|ollama] [--max-cost 1] [--out res.json] [--dry-run]
python tools/judge/judge.py label IMG <question|verdict:name> <answer> --evalset DIR --note "why" [--prev IMG] [--label TEXT]
python tools/judge/judge.py fit  --evalset DIR [--min-rows 20]
python tools/judge/judge.py eval --evalset DIR [--split test|train|all] [--groups pose,verdict] [-v]
python tools/judge/judge.py questions [--pack P]
```

- **Question bank** (`questions/*.json`): `{"group", "about", "questions": {id: {"type": "noul"|"choice"|"score"|"box",
  "instructions", "criteria"?, "companion"?, "needs"?}}}`. Name images in backticks: `frame`, `previous_frame`, a
  reference passed as `--ref name=path`, and the text `on_screen_label`. A question is only asked when every image
  it names is available.
- **Verdict rules** (`packs.example.json`): `all_ok` terms, each giving p_ok: `{"q", "want": true|false}` (Noul),
  `{"q", "expect_from_label": {"wide": "wide", ...}}` (Choice vs the line), `{"q", "min": 0.75}` (Score),
  `{"derived": "ratio:a/b" | "overlap:a/b" | "bottom:a", "max", "soft"}` (boxes). The verdict takes the lowest term.
  `"type": "sequence"` with `presence` ids is the continuity truth table. `features` is what `fit` learns from.
- **Eval rows** (`<evalset>/labels.jsonl`, format in `examples/labels.example.jsonl`): `{"image", "q", "expect",
  "state": {"previous_frame"?, "on_screen_label"?}, "split", "note"}`. Keep the eval set and `model.json` out of
  git if the frames are your characters (both are git-ignored here).
- Answers are cached by request hash in `cache/judge/`, so re-runs and refits are free.

## breathpacer/

```
python tools/breathpacer/pacer.py IN.mp4 -o OUT.mp4 [--inhale 5.5 --exhale 5.5] [--color "#E8171C"]
       [--pos top-left|top-right|bottom] [--x 0.15 --y 0.085] [--size 0.11] [--style ring|glass] [--start 0] [--label]
python tools/breathpacer/hero.py -o panel.mp4 --w 1080 --h 960 --dur 30 [--color red|gold|#hex] [--t0 1] [--cycles 2]
python tools/breathpacer/hero.py --overlay IN.mp4 -o OUT.mp4 --x 0 --y 960 --w 1080 --h 960 [--transparent]
```

Audio is copied untouched. Never place the pacer over a character, a label or the subtitles.

## fal_run.py and hf_run.py

See [../SETUP.md](../SETUP.md). Both have `--dry-run`; `fal_run.py` needs `--est` (your cost estimate) and refuses to
submit past `--daily-cap`.

## Windows: no console popups

Every subprocess in these tools passes `CREATE_NO_WINDOW` (a no-op elsewhere). The real cause of popup storms is a
console-less parent (`pythonw`, a detached job) launching ffmpeg: Windows gives each child a new console. If you write
your own wrappers, pass `creationflags=subprocess.CREATE_NO_WINDOW` on every `subprocess` call, `windowsHide: true` in
Node, and run browsers headless.
