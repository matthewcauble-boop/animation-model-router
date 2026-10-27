# Tools

```
tools/
  common/vision.py            shared yes/no vision backends (Jev, Gemini, fal OpenRouter, Ollama)
  common/launch_detached.ps1  start a long job hidden and detached (Windows)
  continuity/continuity.py    story-continuity checker; --stills = keyframe gate
  continuity/examples/        continuity.example.json (a three-character bible)
  frameqa/frameqa.py          broken-frame QA
  frameqa/questions.default.json, examples/questions.character-swap.json, examples/holds.example.json
  storyboard/sheet.py         annotated storyboard sheet (arrows, end frames, timing, IN/CAM/action); --thirds overlay sheet
  storyboard/thirds.py        rule-of-thirds check (fal / OpenAI-compatible / manual) + grid overlays
  storyboard/example/         storyboard.json, placeholder frames (make_frames.py) and the rendered sheets
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
  explainer-critic/eclib.py   explainer-critic core: caption/script parsing, metrics, judges (heuristic, Jev, OpenAI-compatible, fal), cut metrics
  explainer-critic/build_bible.py  reference captions (+ low-res video) -> bible.json of pacing/structure targets
  explainer-critic/score.py   score a script or cut against a bible; copy guard
  explainer-critic/example/   bible.example.json, sample_script.txt, sample_script.weak.txt
  fal_run.py                  one fal queue call with a daily cap, a ledger and a dry run
  hf_run.py                   call a Hugging Face Space
  edit/mix.py                 voice + music + SFX -> two-pass loudnorm, 48 kHz AAC, muxed onto the video
  edit/glow.py                pulsing glow / X-ray ghost on a masked region (mask PNG, matte folder, colour key)
  edit/reps.py                N reps from one top-to-bottom clip (forward, hold, reversed, hold)
  voice/lines.py              line-by-line TTS on fal with a locked voice; cached by text; trims silence
  voice/examples/             lines.example.json, voice.example.json, timeline.example.json
```

Install: `pip install -r requirements.txt` (numpy, Pillow, opencv-python-headless; `rapidocr` + `onnxruntime` optional
for frameqa's safe-area OCR). ffmpeg and ffprobe must be on PATH.

## Environment

| Variable | Used by | Notes |
|---|---|---|
| `TYPESAFE_API_KEY` | screen backend `jev` (default) | TypeSafe System One; images are a preview feature (the client sends the opt-in header) |
| `FAL_KEY` | confirmer (fal OpenRouter vision), `--backend fal`, `bake.py`, `voice/lines.py` | |
| `GEMINI_API_KEY` | `--backend gemini` / `--screen gemini` | |
| `OLLAMA_HOST` | Ollama backends | default `http://127.0.0.1:11434`; free, slow |
| `AMR_ENV_FILE` | all | a `.env`-style file to read keys from (default `.env` in the working directory) |
| `AMR_CACHE_DIR` | continuity, frameqa, voice/lines.py | answer cache folder (default `cache/` beside each tool, git-ignored) |
| `CONTINUITY_SCREEN`, `CONTINUITY_FAL_MODEL`, `CONTINUITY_OLLAMA_MODEL` | continuity | defaults for `--screen`, `--fal-model`, `--ollama-model` |
| `FRAMEQA_JEV_MODEL`, `FRAMEQA_MAX_SIDE`, `FRAMEQA_BATCH` | vision backends | |
| `HF_TOKEN` | `hf_run.py` | read token; PRO for more ZeroGPU time |
| `JUDGE_JEV_MODEL`, `JUDGE_CONTEXT` | judge | default `jev-latest` (Box needs jev-1.14+); one sentence of context sent with every frame |
| `EXPLAINER_OPENAI_BASE`, `EXPLAINER_OPENAI_KEY`, `EXPLAINER_OPENAI_MODEL`, `EXPLAINER_FAL_MODEL`, `EXPLAINER_JEV_MODEL` | explainer-critic judges | `--judge openai` / `fal` / `jev` |
| `JUDGE_OPENAI_BASE`, `JUDGE_OPENAI_KEY` | judge `--backend openai` | any OpenAI-compatible vision endpoint |
| `VOSYNC_OPENAI_BASE`, `VOSYNC_OPENAI_KEY` | vosync `--backend openai` | |
| `THIRDS_OPENAI_BASE`, `THIRDS_OPENAI_KEY` | storyboard/thirds.py `--backend openai` | |
| `STORYBOARD_FONT`, `STORYBOARD_FONT_BOLD` | storyboard | font files; else the first system font found |
| `AMR_LEDGER` | judge, fal_run, thirds | spend ledger CSV (default `spend-ledger.csv` in the working directory) |
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

## storyboard/

```
python tools/storyboard/sheet.py storyboard.json [-o sheet.jpg] [--thirds [--thirds-json thirds.json]] [--panel-width 360]
python tools/storyboard/thirds.py OUTDIR [frames...] [--storyboard storyboard.json] [--backend manual|fal|openai]
       [--model ID] [--manual comp.json] [--mid 0.42,0.58] [--line-tol 0.10] [--int-tol 0.15] [--dead-max 0.25] [--max-cost 0.50]
```

- `sheet.py` output: `<stem>-sheet.jpg` (and `<stem>-thirds.jpg`) beside the JSON. Format and arrow kinds:
  [../STORYBOARD.md](../STORYBOARD.md).
- `thirds.py` output: `OUTDIR/<id>-grid.jpg` + `OUTDIR/thirds.json`. `--backend manual` reads each shot's
  `composition` block (no API); `fal` uses `FAL_KEY`; `openai` uses `THIRDS_OPENAI_BASE` + `THIRDS_OPENAI_KEY`.
- Fonts: `STORYBOARD_FONT`, `STORYBOARD_FONT_BOLD` (a `.ttf` path), else the first system font found.

## onestwos.py

```
python tools/timing/onestwos.py IN.mp4 --spec timing.json -o OUT.mp4 [--pick sharpest|first] [--report r.json]
```

Same frame count, same fps, audio stream copied untouched. Spec and camera modes: [../TIMING.md](../TIMING.md).

## edit/mix.py

```
python tools/edit/mix.py --voice voice.wav|placed.json [--music bed.wav] [--sfx sfx.wav] [--video picture.mp4]
       -o out.mp4|out.wav [--under 19] [--music-start S] [--fade-out 0.9] [--duck START,END,DB ...]
       [--lufs -16] [--tp -1.5] [--length S] [--report mix.json]
```

- The bed's gain comes from measured loudness: music lands `--under` dB below the voice's integrated LUFS.
- `placed.json` = `[{"wav": "vo/H0.wav", "at": 0.05}, ...]`; each line gets 8 ms / 30 ms fades.
- Two-pass `loudnorm` (`linear=true`), re-measured; prints voice/music LUFS, music gain, final LUFS and true peak.
- `.mp4` output copies the video stream and writes AAC 192k, 48 kHz stereo, `+faststart`. Numbers: [../EDIT.md](../EDIT.md#8-the-audio-mix).

## edit/glow.py

```
python tools/edit/glow.py IN -o OUT (--mask m.png | --mask-dir mattes/ | --key "#hex" [--tol 40]) [--color "#ff3c3c"]
       [--start S] [--end S] [--fade 0.2] [--pulse 1.6] [--strength 1] [--inside 0.38] [--ghost] [--fps 24]
```

IN = a video, a frame folder or an image; OUT = `.mp4` (audio copied) or a folder of PNGs. Drawn on ones.

## edit/reps.py

```
python tools/edit/reps.py down.mp4 -o reps.mp4 [--reps 3] [--first F] [--last F] [--skip A-B ...] [--down S] [--up S]
       [--bottom-hold 0.25] [--top-hold 0.2] [--alive 2] [--twos] [--lead S] [--report reps.json]
```

Frames are re-timed by index, never interpolated. `--alive` holds drift between neighbouring drawings instead of
freezing. `reps.json` has each rep's down / bottom / up / top time. Silent output.

## voice/lines.py

```
python tools/voice/lines.py lines.json --voice voice.json -o vo/ [--dry-run] [--only IDS] [--refresh IDS]
       [--pad 0.04] [--tail 0.12] [--floor -45] [--max-cost 1.0]
```

- `lines.py`: cache key = endpoint + params + text, so only changed lines cost money; `--dry-run` sends nothing and
  needs no key. Writes `vo/<id>.wav` (48 kHz), `vo/timings.json`, `vo/spend.csv`. Never time-stretches.
- Placement checks (a line crossing a cut, early, late, switch lead): use `vosync/vosync.py` below. Formats: [../VOICEOVER.md](../VOICEOVER.md).

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

## explainer-critic/

```
python tools/explainer-critic/build_bible.py [URL ...] [--urls urls.txt] [--captions DIR] [--videos DIR] [--download-video]
       [--corpus refs/NAME] [--out bible.json] [--judge heuristic|jev|openai|fal] [--acts heuristic|openai|fal]
       [--short-max 180] [--holdout 0.2] [--max-videos N] [--max-cost 1.0] [--rebuild] [--dry-run]
python tools/explainer-critic/score.py SCRIPT|CUT --bible bible.json [--captions cut.srt] [--refs DIR] [--ngram 8]
       [--judge ...] [--acts ...] [--format auto|short|long] [--wps 2.7] [--max-cost 0.10] [--out DIR] [--quiet]
```

- Scripts: `.txt`/`.md` (blank line = new paragraph), `.json`/`.jsonl` lines `{"text", "start"?, "end"?, "pause"?}`,
  `.csv` (`text,start,end`), `.srt`/`.vtt`; a cut is a video plus `--captions`. Untimed scripts are timed at `--wps`.
- Output `explainer-critic-<name>/` with `report.md` and `score.json`; exit 1 on any P0. The bible holds numbers only;
  `<corpus>/` (captions, video, per-video analysis) is private and git-ignored.
- Env: `TYPESAFE_API_KEY` (`--judge jev`, `EXPLAINER_JEV_MODEL`), `FAL_KEY` (`--judge fal`, `EXPLAINER_FAL_MODEL`),
  `EXPLAINER_OPENAI_BASE` / `EXPLAINER_OPENAI_KEY` / `EXPLAINER_OPENAI_MODEL` (`--judge openai`), `AMR_CACHE_DIR`.
  Method, targets and the loop: [../EXPLAINER-CRITIC.md](../EXPLAINER-CRITIC.md).

## fal_run.py and hf_run.py

See [../SETUP.md](../SETUP.md). Both have `--dry-run`; `fal_run.py` needs `--est` (your cost estimate) and refuses to
submit past `--daily-cap`.

## Windows: no console popups

Every subprocess in these tools passes `CREATE_NO_WINDOW` (a no-op elsewhere). The real cause of popup storms is a
console-less parent (`pythonw`, a detached job) launching ffmpeg: Windows gives each child a new console. If you write
your own wrappers, pass `creationflags=subprocess.CREATE_NO_WINDOW` on every `subprocess` call, `windowsHide: true` in
Node, and run browsers headless.
