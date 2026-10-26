# QA: gates, cheap screens and blind critics

Five tools, each answering a different question:

| Tool | Question | Cost |
|---|---|---|
| `tools/continuity/continuity.py` | Is this frame still **the same story** as the last one? | about $0.0001-0.0002 a sample |
| `tools/frameqa/frameqa.py` | Is this frame **broken**? (glitches, cut-off text, flicker, loudness) | about $0.03-0.04 per minute of video |
| `tools/vosync/vosync.py` | Does the picture **match what is being said**, at that moment? | free (timing); about $0.001 a line with a vision pass |
| `tools/judge/judge.py` | Atomic yes/no checks tuned to **your own** approve/reject calls (pose, proportion, alive, layout) | well under $0.001 a frame |
| Blind critics | Which take is **better**? | 3 fresh LLM agents per round |

The expensive reviewer (a person, or an LLM that reads frames) comes last and opens **only the frames the cheap
passes flag**. A frame-by-frame LLM review of one episode took about 2,000 tool calls; the cheap screens do the same
first pass for a few cents.

## The gate rules

1. **Keyframe gate** before any video spend: `continuity.py --stills` on all of a scene's start frames. Animate nothing
   until it passes. ([KEYFRAMES.md](KEYFRAMES.md))
2. **Cut gate** on the rendered cut: `continuity.py`, then `frameqa.py`, then `vosync.py` on anything with a narrator.
3. **Any confirmed P0 fails the gate.** Both tools exit with code 1, so they can block a build script.
4. **Fix every P0 that code can fix** (safe area, black frames, loudness, a missing character in a start frame) and
   re-run. Re-runs are nearly free: answers are cached by frame hash.
5. **Timing pass, then the cut gate again** on the timed cut.
6. **Then the human / LLM review,** given only `report.md` + `flagged.jpg` from each tool, told to open only the listed
   frames and to spend the rest of its attention on what code can't see: story beats, staging, who holds what, the
   brief.
7. **A human picks the takes.** The gates remove broken candidates; blind critics rank candidates; neither replaces the
   director's pick.

## Severity

- **P0:** the shot can't ship (a character missing where the story needs them, fingers on a gloved character, a
  duplicate character, text cut off by the frame edge, a hard rendering seam).
- **P1:** visible and should be fixed (off-model proportions, a prop in the wrong state, flicker, loudness off target).
- **P2:** worth a look (disputed findings, small safe-area overshoot, a frozen stretch that may be an intended hold).

---

## Continuity checker

`continuity.py` reads a **bible** (`continuity.json`, one per scene or episode; see
`tools/continuity/examples/continuity.example.json`):

- **characters:** name, a one-line visual description, reference sheets, default facing, optional HSV colour range for
  a free tracker, and **traits**: yes/no questions written for the house rules ("Does she show bare fingers instead of
  gloves?" P0; "Does it have any arms or legs?" P0 for a limbless sidekick).
- **props:** a yes/no question each.
- **set:** the master plate and set checks ("Is this the SAME kitchen as the reference?").
- **screen_direction:** "A stays screen-left of B".
- **shots:** id, start, end, keyframe, who must be `present` (optionally `where` = their mark, `enters` / `exits`,
  `required_when: "prop:pillow"` = only while that prop is in frame), who must be `absent`, held `gestures` with a
  time window, prop states (`true`, `false`, or a change at a time), and per-shot screen `side`.

**How it decides:**

1. **Sample** every shot at 4-6 fps (one decode pass), skipping 0.1 s at each cut. An optional HSV colour tracker
   follows characters on every frame for position jumps and screen direction.
2. **Screen:** one call per sample to a cheap probability-returning vision model (TypeSafe Jev by default; `--screen
   fal|gemini|ollama` for others) with every question the bible implies for that shot.
3. **Temporal analysis**, which is where continuity lives: a character missing for a whole shot, popping in late,
   disappearing mid-shot (and whether they come back), appearing where the bible has none; trait, facing, mark,
   gesture and prop runs; position jumps between consecutive frames; screen-direction flips inside a shot and across
   cuts. A grey-band hit must persist for 2 samples; a hard hit counts on one frame.
4. **Confirm:** every candidate event is re-asked on its key frames at full resolution, with the character's reference
   sheet and a zoomed crop, by a stronger model (Gemini via fal by default, local qwen3-vl via Ollama as a free, slow
   fallback). Verdicts: **confirmed**, **disputed** (screen sure, confirmer not: kept at P2), **dismissed** (a grey-band
   hit the confirmer rejects; listed, not counted).
5. **Report:** `report.md`, `flagged.jpg` (contact sheet of every finding), `presence.png` (one lane per character:
   green visible, red missing where required, orange visible where forbidden), `report.json`, `STATUS.json`.

**Lessons built in:**
- Back-turns are confirmed with the positive question "can you see their face?". "Is he turned away?" gets a false "no"
  from both screen and confirmer models.
- Small characters in wide shots are misjudged at full frame; the confirmer gets a crop around the tracked character.
- Colour tracking is only trusted for position and screen direction: a night-sky window matched a dark-coloured character and
  dim light lost a bright-coloured one. A `shape: round` filter helps.

**Measured:** a 39 s cut, 194 samples, 16 s, $0.022. On its first real cut it caught every problem the director had
reported by eye (a sidekick missing for two whole shots while his spot was in frame, a back-turn, a character leaving
his mark, eyelashes appearing on a character who has none, a held gesture breaking), and the stills gate found the
root cause: two start frames had the sidekick's spot in shot and no sidekick.

**Dry run:** `--dry-run` prints every question per shot and the sample count without calling any model. Use it to
proof-read a bible.

## frameqa

`frameqa.py` is the "is it broken?" pass, SageCut-style: code measures what is measurable, a cheap model answers yes/no
per frame, a stronger model confirms only the grey band.

**Stage 1, code (free):** one decode pass over every frame finds cuts, black and flat frames, frozen stretches (outside
`--holds`) and A-B-A flicker on coarse tiles. ffmpeg measures integrated loudness (default target -16 LUFS +/- 1.5),
true peak (max -1 dBTP) and mid-video dropouts. Local OCR (RapidOCR, optional) boxes every word on the sampled frames
and checks it against the format's **safe area**: 9x16 keeps text inside x 6-85%, y 6-75% (the right ~15% and bottom
~25% carry Shorts/Reels/TikTok UI); 16x9 is 90% title-safe. Optional brand-palette presence.

**Stage 2, screen:** default questions in `tools/frameqa/questions.default.json`: face cut by the edge, text cut or over
a face, intersecting objects, rendering glitch, garbled text, empty frame, text over busy art, off-model (with
`--refs`). Each has a grey band `lo..hi`.

**Stage 3, confirm:** frames in the grey band go to the confirmer for yes/no plus a reason. A confirmer "no" drops a
grey-band hit; on a hard hit it keeps the finding but marks it P2 "confirmer disagrees", so recall is never lost.

**Measured:** about $0.03-0.04 and 45-60 s per minute of 1080x1920 video. Validated against a human review of one
episode: it found all 3 P0s (speech bubbles outside the safe area, a texture seam down a planet), a mid-flip title on
frame 0 and an end-card line outside the safe area; it missed a flat orange stretch (captions kept the pixel variance
up); story, script and brief issues were out of scope by design. About a third of its findings in that run were wrong
or minor, which is why a human or LLM still looks at `flagged.jpg`.

**Tips:** `--refs` must be sheets rendered in the same style as the video (a 2D sheet against a 3D render flags every
frame). Tune a new question from `lo 0.6, hi 0.85` using the probabilities in `report.json`. Use `--every 1 --no-ocr`
for a cheap first sort of raw takes. `questions.character-swap.json` is a starter set for cartoon-in-live-action work.

## Voice-over sync (vosync)

The rule: **what is on screen matches what is being said, at that moment**
([LESSONS.md](LESSONS.md#1-on-screen-must-match-whats-said)). `vosync.py` takes the cut and a lines file
(`[{"id", "start", "end", "text", "shot"?, "kind"?, "screen_text"?}]`, or a build timeline with `vo` and `shots`
lists; see `tools/vosync/examples/lines.example.json`).

| Check | Sev | Rule |
|---|---|---|
| overlap | P0 | two lines overlap |
| crosses_cut | P1 | a line runs past the end of the shot it starts in: hold the shot, never speed up the voice |
| early | P1 | a line starts more than 0.3 s before its own shot |
| wrong_shot | P1 | a line starts in a shot other than the one it is about |
| switch_timing | P1 | a "switch sides" cue starts 0.3-0.8 s before the cut and ends within 0.9 s after it |
| picture_mismatch | P0 / P1 | (`--backend fal` or `openai`) a vision model sees the line's frames and says the move or graphic doesn't match; a confident no is P0 |
| text_mismatch | P1 | (vision pass) the on-screen text is not the line's `screen_text` |
| judge:verdict | P0 / P2 | (`--judge pose`) on lines that name a position, the line's best frame must pass the pose verdict (grip width, leg long, fold) |

Output: `vosync-<stem>/sheet.jpg` (one strip per line, 4-6 frames, a red divider where a cut falls inside the line),
`report.md`, `report.json`. **The reviewer must open the sheet**: the timing checks alone passed a cut where five
different grips were all drawn at the same hand width.

## A fast judge model

`tools/judge/judge.py` is the pattern in [LESSONS.md](LESSONS.md#7-a-fast-judge-model-for-qa): a cheap vision model
answers atomic questions, code makes the decisions, and a small learned layer is fitted to your own labels.

```
python tools/judge/judge.py judge cut.mp4 --pack onmodel --ref mascot_sheet=sheets/mascot.png --every 1 --escalate fal
python tools/judge/judge.py label frame.png verdict:on_model false --evalset evalset/ --note "legs too long after the swap"
python tools/judge/judge.py fit  --evalset evalset/
python tools/judge/judge.py eval --evalset evalset/ --split test -v
```

- **Packs** (`tools/judge/packs.example.json`): proportion, pose, alive, continuity, text, layout, style, and
  combinations. **Verdicts** are rules over the answers: a Noul that must be yes or no, a Choice whose expected option
  comes from the spoken line, a box ratio, overlap or edge that must stay under a limit, or a truth table over
  neighbouring samples (continuity). Each verdict has a gate ("is the character there?"), so an absent character is
  n/a, not a fail.
- **Labels:** one `label` command per approve/reject note copies the frame into the eval set and splits it 70/30 by a
  stable hash. Bad-versus-fixed pairs of the same shot teach it the most.
- **Calls:** pass >= 0.7, fail <= 0.3, unsure in between; `--escalate` re-asks only the unsure inputs with a bigger
  model. A clear fail is P0; unsure is P2 (look at it).
- **Backends:** TypeSafe Jev (typed questions with calibrated probabilities, Box for layout), fal's vision router,
  any OpenAI-compatible vision endpoint, or local Ollama.

## Delivery rules the gates enforce

- **Subtitles sit centred in the bottom third, in the same place on every shot:** about 70% of frame height in 9x16
  (never below 75%, where the platform UI sits), 75-80% in 16x9. Viral style: 1-3 words at a time, popping in, the
  spoken word highlighted. **On a clash, move the callout, never the subtitle.**
- No text outside the safe area; nothing drawn over a face.
- Never publish a cut without its sound pass (music and SFX), unless the deliverable is the clean silent picture for
  a finishing team.

---

## Blind critics

**The problem:** a reviewer that shares the builder's context reads the builder's reasoning and agrees with it. Self-
review rubber-stamps.

**The fix:** critics with completely fresh context who see only the candidates, never know which one is "ours", and
answer one question.

**The loop:**

1. **Set the bar.** One to three comparison artifacts at the quality you want: a real reference you admire, a target
   still you generated and approved, or a different object at the target quality. Avoid references the model "knows"
   by name (iconic IP), which it judges by identity rather than quality.
2. **Build** a candidate.
3. **Judge blind.** Start 3 critic agents with **fresh** context (a new general-purpose agent, never a fork of the
   builder's conversation). Give each only:
   - the artifacts, labelled A, B, C... in a **different shuffled order per critic** (keep the mapping yourself);
   - one question: "Which is better overall as a <kind of thing> for <audience>? Answer with the letter, then the three
     biggest reasons, then the single most valuable change to the loser." For a bake-off: "Score every take out of 10
     and rank them." Add 3-5 criteria and the automatic fails only if they are genuinely required.
   - nothing else: no rationale, no history, no hint.
4. **Score.** A candidate wins a round only if at least 2 of 3 critics pick it. Log every round: votes, scores, the
   losers' "most valuable change".
5. **Iterate** on the notes until ours wins **two rounds in a row**. Cap at about 6 rounds, then report the trend.
6. **Keep the bar fixed.** Changing the reference mid-loop resets the count.

**Rules that matter in practice:**
- **Copy the artifacts to a folder outside every project** before critics see them
  (`tools/bakeoff/critic_pack.py --out <temp dir>`). Agent tools load a project's instruction files as soon as an agent
  reads a file inside it, which tells the critic what the project is. In one test that alone primed testers with the
  project's theme.
- For video, critics judge **contact sheets** (12 timestamped frames per take; `tools/bakeoff/sheet.py`). For lip-sync,
  add a dense sheet every 0.5 s stamped with who is really speaking in the audio.
- For multi-part work (a whole spot, a site), run a loop per part, fold the winners back, then a final whole-artifact
  round.
- Critics produce rankings; a human still picks the take.
