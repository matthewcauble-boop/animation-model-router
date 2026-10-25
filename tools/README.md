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

## Windows: no console popups

Every subprocess in these tools passes `CREATE_NO_WINDOW` (a no-op elsewhere). The real cause of popup storms is a
console-less parent (`pythonw`, a detached job) launching ffmpeg: Windows gives each child a new console. If you write
your own wrappers, pass `creationflags=subprocess.CREATE_NO_WINDOW` on every `subprocess` call, `windowsHide: true` in
Node, and run browsers headless.
