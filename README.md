# animation-model-router

A field guide, plus small tools, for **routing AI animation work to the right model** for each moment of a shot.
It comes from a studio making short cartoon videos: flat 2D characters, often in photoreal sets, mostly vertical
9:16, lots of food and talking. The numbers come from blind, same-input bake-offs run in **2026-10**.

Models change fast. The method lasts longer than the winners, so the repo includes the tools to re-run the tests.

![pipeline](docs/img/pipeline.svg)

## The core principle

1. **Consistent keyframes first.** Make every shot of a scene as a still, from one master plate and locked character
   sheets, and check the stills together. Most continuity failures (a sidekick who vanishes, arms that change between
   shots) are baked into the start frames before any motion model runs. A still re-roll costs about $0.14; a video
   re-roll costs $0.30-2.80.
2. **Then the right motion model per moment.** No model wins everything. The house default lost badly on props, real
   plates and glove-plus-food, and won on prop-light acting. Route by moment.
3. **Then code for diagrams and text.** Never ask a video model to draw a number, a word, a label or a chart. A code
   layer is exact, free, re-timeable and never drifts. Timing (ones, twos and threes) is applied in the edit too.
4. **Then QA gates.** Cheap per-frame screens (a continuity checker and a "broken frame" checker) gate every cut; any
   confirmed P0 fails it. The expensive reviewer opens only flagged frames, and blind fresh-context critics rank takes.
   A human picks.

## Quick routing table (2026-10)

| Moment | Use | Instead of |
|---|---|---|
| Scene keyframes | **GPT Image 2.5 high** + 5 refs (master, empty plate, 2 sheets, pose card) | Nano Banana Pro; "harmonize" passes |
| Same-camera coverage stills | Nano Banana 2.1 (most stable set; fakes new angles) | |
| New on-model pose still | **GPT Image 2 high** | |
| Packaging with exact text | **Nano Banana Pro**, every word listed verbatim | FLUX.2 / Kontext |
| Two-shot lip-sync to your VO | **MiniMax H3 Max ref-to-video, hosted** ($0.05/s); fallback Seedance 2.0 ref + audio | self-hosted H3 weights (licence) |
| Full-body action with a prop | **Seedance 2.5** or **Kling 4.0 / Wan 3.0** (by character) | Hailuo (props float), Veo 3.1 Fast |
| Expressive close-up | **Kling 4.0** | |
| Cartoon hand/glove on real food | **Wan 3.0** | Hailuo, Veo |
| Food hero | **Wan 3.0** (thick liquids), **Hailuo 2.3** (pours, peels) | |
| Character on a real plate | code composite start frame + **Kling 4.0** | |
| Cartoon replacing a person in footage | **Wan 3.0 ref-to-video** + proportion-lock prompt | whole-frame "omni edit" models |
| Prop-light cartoon acting | **Hailuo 2.3**, finished on twos | |
| Numbers, words, labels, diagrams, subtitles | **code** | any video model |

Full detail per moment (settings, prompt templates, reference recipes, cost per second, failure modes):
**[ROUTING.md](ROUTING.md)**.

## The guides

| File | What |
|---|---|
| [ROUTING.md](ROUTING.md) | A model per moment: winner, runner-up, settings, prompt, refs, cost, failure modes |
| [KEYFRAMES.md](KEYFRAMES.md) | Master-plate method, character sheets, the edit prompt, "prompt nouns trigger anatomy", the keyframe gate |
| [TIMING.md](TIMING.md) | Ones, twos and threes per action and layer, applied in the edit |
| [QA.md](QA.md) | Continuity checker, frameqa, blind critics, the gate rules, delivery rules |
| [BAKEOFF.md](BAKEOFF.md) | Run your own fair bake-off: principles, moments, critic prompt, log templates |

## The tools

All Python 3.10+, ffmpeg/ffprobe on PATH. `pip install -r requirements.txt`.

| Tool | Does | Needs |
|---|---|---|
| `tools/continuity/continuity.py` | Story continuity across frames and shots against a per-scene bible; `--stills` is the keyframe gate | a screen model key (`TYPESAFE_API_KEY`, or `--screen fal/gemini/ollama`); `FAL_KEY` or local Ollama to confirm |
| `tools/frameqa/frameqa.py` | Broken-frame QA: cuts, black, frozen, flicker, loudness, safe-area text (OCR), glitches | same keys, or `--backend none` for code checks only |
| `tools/timing/onestwos.py` | Re-time smooth AI video onto ones/twos/threes per segment, audio untouched | nothing (local) |
| `tools/bakeoff/bake.py` | Resumable, cost-capped fal bake-off runner with a ledger | `FAL_KEY` |
| `tools/bakeoff/sheet.py` | Contact sheets, keyframe strips, dense lip-sync sheets | nothing |
| `tools/bakeoff/critic_pack.py` / `tally.py` | Anonymise + shuffle takes per blind critic; decode votes into a table | nothing |
| `tools/common/vision.py` | Shared yes/no vision backends (TypeSafe Jev, Gemini, fal OpenRouter, Ollama) | the backend's key |
| `tools/common/launch_detached.ps1` | Start a long job detached with no console window (Windows) | |

```bash
# the keyframe gate, before any video spend
python tools/continuity/continuity.py --stills --bible scene/continuity.json
python tools/continuity/continuity.py --stills --bible scene/continuity.json --dry-run   # proof-read the questions

# the cut gates
python tools/continuity/continuity.py cut.mp4 --bible scene/continuity.json
python tools/frameqa/frameqa.py cut.mp4 --format 9x16 --holds holds.json --refs sheets/a.png sheets/b.png

# timing in the edit
python tools/timing/onestwos.py cut.mp4 --spec timing.json -o cut-timed.mp4

# a bake-off
python tools/bakeoff/bake.py bakeoff/jobs.json --dry-run
python tools/bakeoff/sheet.py takes bakeoff
```

More in [tools/README.md](tools/README.md).

### Keys

Keys are read from environment variables only (`TYPESAFE_API_KEY`, `FAL_KEY`, `GEMINI_API_KEY`), or from a `.env` file
in the working directory (git-ignored here). Nothing prints a key. Never commit one.

### Running long jobs

Bake-offs and long QA runs should be **detached, resumable jobs**, not work held inside an agent or a terminal tab:
interrupting an agent silently stops whatever it was holding. Each script here skips outputs that already exist and
writes `STATUS.json`; launch it detached and have the agent only launch and monitor. On Windows, start it with
`pythonw.exe` and `-WindowStyle Hidden` (`tools/common/launch_detached.ps1`), and every child process (ffmpeg and so
on) is started with `CREATE_NO_WINDOW`, so no console windows pop up on the user's screen.

## What this repo is not

- Not a benchmark. Three critics per moment on one studio's cast is a decision tool, not a leaderboard.
- Not legal advice. Model licences (notably open-weights territory restrictions) and host terms change; read them.
- Not affiliated with any model provider. Prices are list prices seen in 2026-10.

## Licence

MIT, see [LICENSE](LICENSE).
