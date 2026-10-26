# Lessons from production (2026-10)

Rules learned the hard way on short cartoon videos: workouts, stretches, explainers and talking characters. Each
one cost a re-render or a reviewer's "this doesn't match". Where a lesson has a tool or a longer write-up, the last
column links it.

| # | Lesson | One-line rule | Tool / detail |
|---|---|---|---|
| 1 | [On screen must match what's said](#1-on-screen-must-match-whats-said) | Each line lands on the picture it describes; never speed up the voice to fit | `tools/vosync/`, [QA.md](QA.md#voice-over-sync-vosync) |
| 2 | [Poses must match too](#2-poses-must-match-not-just-timing) | Check the named position in frames; fix with a keyframe per position | `vosync --judge pose`, [KEYFRAMES.md](KEYFRAMES.md) |
| 3 | [Motion-copy swaps stretch cartoon proportions](#3-motion-copy-swaps-stretch-cartoon-proportions) | Measure leg/body ratio against the sheet; anchor the swap on an on-model first frame | `tools/judge/` proportion pack, [ROUTING.md](ROUTING.md#10-replace-a-real-person-in-footage-with-a-cartoon-character-cartoon-in-live-action) |
| 4 | [No frozen characters](#4-no-frozen-characters-living-holds) | A held or talking character breathes, blinks, emotes and lip-syncs its own lines | [TIMING.md](TIMING.md#living-holds) |
| 5 | [Stretches must hold](#5-stretches-must-hold) | Ease in once, hold with visible breathing, switch; never ping-pong or reverse | [TIMING.md](TIMING.md#living-holds) |
| 6 | [Breath pacer overlay](#6-breath-pacer-overlay) | A circle on 5.5 s in / 5.5 s out that never stops moving and never covers a character | `tools/breathpacer/` |
| 7 | [A fast judge model for QA](#7-a-fast-judge-model-for-qa) | Atomic yes/no questions per frame, maths in code, fitted to your own approve/reject notes | `tools/judge/`, [QA.md](QA.md#a-fast-judge-model) |
| 8 | [Paid APIs lock; budgets](#8-paid-apis-lock-when-the-balance-runs-out) | Stop and report on a 403; cap spend per day; log every paid call | `tools/fal_run.py`, [SETUP.md](SETUP.md) |
| 9 | [Storyboard the motion before animating](#9-storyboard-the-motion-before-animating) | An annotated sheet (arrows, end frames, eyelines, beats) and a thirds check, approved before any video spend | `tools/storyboard/`, [STORYBOARD.md](STORYBOARD.md) |
| 10 | [Composition: rule of thirds](#10-composition-rule-of-thirds) | Horizon on a third, eyes on an intersection, lead room, no dead foreground | `tools/storyboard/thirds.py` |
| 11 | [Screen direction and the 180-degree line](#11-screen-direction-and-the-180-degree-line) | Keep the journey's direction; mirror a plate, never flip a character | [STORYBOARD.md](STORYBOARD.md#direction-and-continuity) |
| 12 | [Cuts, camera moves and rhythm](#12-cuts-camera-moves-and-rhythm) | Cut on action, match on action, motivated moves ending on a planned end frame, cuts on beats | [STORYBOARD.md](STORYBOARD.md#cuts) |
| 13 | [Score explainer scripts before recording voices](#13-score-explainer-scripts-before-recording-voices) | Measure a channel you admire into a bible; score and blind-critique every script before VO and every rough cut; learn structure, never copy words | `tools/explainer-critic/`, [EXPLAINER-CRITIC.md](EXPLAINER-CRITIC.md) |

---

## 1. On screen must match what's said

A global rule for every video with a narrator or a talking character.

- **Each line lands on the picture it describes.** An instruction starts as its move starts (at most 0.3 s early)
  and finishes before the next shot.
- **"Switch sides" comes just before the switch:** start the cue 0.3-0.8 s before the mirrored shot's cut, and end
  it within 0.9 s after.
- **No line runs past its shot.** If a line is longer than its shot, **hold the shot** (extend the held end pose).
  Never speed up the voice, and never let the words land on the next move.
- **On-screen text matches the voice at that moment.** A caption that says "left leg" while the voice says "right
  leg" is a P1, even if the picture is right.
- **If a word is wrong,** cut it from the existing take using word timestamps, or re-record the line. Never leave a
  line that describes a move the character doesn't make.

What went wrong first: the lines were scheduled one after another with no regard to the cuts, so "and over" landed
on the next move and "now switch sides" played after the switch had happened.

**Tool:** `tools/vosync/vosync.py` builds one strip per line (4-6 frames across the line, stamped with time and shot,
a red divider where a cut falls inside it) and runs the timing checks for free. `--backend fal|openai` adds a vision
yes/no per line ("does the move match this line, now?"), about $0.001 a line. **Somebody still opens `sheet.jpg`:**
timing checks pass a line whose picture is wrong.

## 2. Poses must match, not just timing

The timing can be perfect and the pose still wrong. A **motion-copy swap** (a model that copies a performer's motion
onto your character) redraws the character's limbs on its own build, and in doing so it **wipes out pose
differences**: five different pull-up grips (wide, close, normal and so on) all came back at the same hand width,
so five lines described five grips over one grip.

- **Check the named position in frames,** not just the move. The judge's pose pack asks one Choice question ("how
  far apart are the hands: together / shoulder width / wide?") and code maps the line ("Wide grip...") to the
  expected option. That caught the defect that the timing-only sheet had passed with 0 P0.
- **Fix:** make **one keyframe per position** (an image-edit still with explicit hand and foot placement: "both
  gloves on the bar, far apart, out past the shoulders, arms in a wide V"), gate the stills, then animate each with
  image-to-video with the limbs locked in the prompt ("hands stay exactly where they are on the bar").
- Back views can't show palms, so a reverse grip from behind only reaches "unsure". Stage grip shots from the front.

## 3. Motion-copy swaps stretch cartoon proportions

A motion-copy swap pulls a cartoon's proportions toward the human performer: **long legs, slim arms, a taller,
thinner body.** It is the most common way a round or stocky mascot goes off-model in "cartoon in live action" work.

**Measure it, don't eyeball it.** Box the body and the legs separately (two Box questions to the judge), and compute
the legs-to-body height ratio **in code**. Compare it with the same ratio on the character sheet.

| Take | Leg/body ratio | Verdict |
|---|---|---|
| Character sheet (target) | 0.80 | |
| Plain motion-copy swap | 1.41 | off-model (legs 75% too long) |
| Swap anchored on an on-model first frame | 0.86 | on-model |

**Fixes, in order:**
1. **Anchor the swap on an on-model first frame.** Make the first frame as a still (image edit from the sheet, in the
   performer's starting pose), gate it, and give it to the swap model as the start or reference frame. It worked:
   0.86 against the sheet's 0.80.
2. **Keyframes + image-to-video** per position. On-model, but you lose the performer's exact motion.
3. **Skeleton retarget** (rescale the performer's bones to the character's proportions, then drive the character from
   the rescaled pose) is right in theory, but it needs a model that accepts a pose video, such as Wan VACE's pose
   mode (`fal-ai/wan-vace-14b/pose`). Feeding a stick-figure video into a generic motion-control model failed: it
   copied the stick figure.

## 4. No frozen characters (living holds)

A held pose or a talking character must **breathe, blink, emote and lip-sync its own lines.** Freezing a frame and
bobbing it in code reads as a sticker, and viewers notice in under a second.

**Method:**
1. Take the held still (the approved keyframe or the last frame of the move).
2. Run a **lip-sync / reference-to-video model started from that still** (for example a hosted audio-driven
   image-to-video model such as `minimax/h3-max/lip-sync/image-to-video`, or H3 Max reference-to-video with the line's
   audio; see [ROUTING.md](ROUTING.md#4-talking-two-shot-lip-synced-to-your-own-voice-track)).
3. Prompt for life, on a fixed rhythm: "breathes slowly in for 5.5 seconds and out for 5.5 seconds, chest and
   shoulders rising and falling; soft natural blinks; eyes close gently on each exhale; a small relaxed smile; stays
   in the same pose; locked-off camera."
4. If only one character speaks, the others still breathe and blink; "only the speaking character moves their mouth".
5. **Relight if the model darkens the background:** match the held clip's background brightness to the plate (a
   simple levels match in the edit) or composite the character back over the original plate.

The judge's `alive` pack checks it: "has the body moved between the previous sample and this one?" A hold that fails
for 3 samples in a row is frozen.

## 5. Stretches must hold

- **Ease in once, hold with visible breathing, then switch.** A stretch is a hold, not a loop.
- **Never ping-pong a clip or play footage backwards** to fill time. It reads as the character bouncing in and out
  of the stretch, which is wrong for the exercise and obviously fake.
- If the hold is longer than the generated take, make the hold a **living hold** (lesson 4) from the held pose, then
  cut to the switch.
- Mirror every stretch: left and right (and front and back where it applies) get the same hold time.

## 6. Breath pacer overlay

`tools/breathpacer/pacer.py` burns a small breathing circle onto a video; `hero.py` makes the big guided-breathing
panel (disc, ring, countdown, "Breathe in / Breathe out").

| Setting | Default | Why |
|---|---|---|
| Colour | record-button red `#E8171C` | reads on any background; one colour across the series |
| Style | ring: soft disc + thin guide ring + progress arc with a dot at its head | the arc shows where you are in the breath |
| Timing | 5.5 s in, 5.5 s out | a calm, common paced-breathing rate |
| Motion | smoothed triangle wave | a sine dwells at the ends and looks like it stopped; this keeps moving with a soft turn |
| Placement | top-left; `--pos top-right`, `--pos bottom` (just under the subtitles), or `--x/--y` | |
| Rule | **never over a character**, a label chip or the subtitles | check frames across the clip, or use the judge's layout pack |

## 7. A fast judge model for QA

A cheap vision model answering atomic yes/no questions, **with the decisions in code**, does the first pass of QA on
every frame for fractions of a cent, and the expensive reviewer only looks at what it flags.

**The pattern:**

| Part | What it is |
|---|---|
| Question bank | Atomic, observable questions in JSON, the only place wording lives. Groups: pose, proportion (against a reference sheet), alive, continuity, text, layout (bounding boxes), style, design |
| Code | Turns answers into verdicts: truth tables, box ratios and overlaps, and a gate per verdict ("is the character there at all?") |
| Eval set | Labelled frames from **your own approve/reject notes**, ideally bad-versus-fixed pairs of the same shot; 30% held out by a stable hash |
| Learned layer | A small logistic regression per verdict over the judge's probabilities, fitted on the train split only, once a verdict has 20+ labels |
| Bands | pass >= 0.7, fail <= 0.3; the band between is "unsure" and escalates to a bigger vision model |

**What worked:**
- **Putting separate boxes round the body and the legs and comparing them in code** beats asking "are the legs too long?". On-model frames
  measured 0.1-0.84 and stretched ones 0.87-1.56: a clean gap. The direct question sat at 0.3-0.5 on stretched frames.
  Adding the ratio to the learned layer took the on-model verdict from 81% to 95% on train.
- **A Choice for named positions** (hand spacing: together / shoulder width / wide) with code mapping the line to the
  expected option. It caught the five-grips-one-width defect.
- **Continuity as a truth table over samples:** clearly present before (>= 0.7), clearly gone now (<= 0.3), same shot.
  More reliable than asking "is the thing from the previous frame still here?", which says no when it was never there.
- **Fingers on a gloved character:** 100% on 54 labels as a single high-resolution question.
- **Presence, text cut by the edge, text over a face, background type:** 97-100%, and most answers land below 0.1 or
  above 0.9.
- **Cheap and fast:** about 2k input tokens for a 1024-px frame (well under $0.001), p50 latency under 0.3 s. Bundle
  every question that uses the same images into one request; keep a frame-only Box out of requests that carry a
  reference sheet (extra images pulled boxes onto the wrong image).

**What failed, and the jaggedness to expect:**
- **Ask the question the positive way round.** Wording is not symmetric:

  | Asked this way | Accuracy | Asked the other way | Accuracy |
  |---|---|---|---|
  | "Is the graphic pushed to one side?" | 5% | "Is the graphic centred?" | 95% |
  | "Does he have short stubby legs like the sheet?" | 31% | "Are his legs longer than his body?" | 76% |
  | "Are both hands mitts?" | 30% | "Can you see separate fingers?" | 100% |

  Ask plainly about what is there to see (centred, fingers visible, legs longer than the body), and try both
  wordings on your eval set before trusting either: a negated twin does not behave like the original.
- **"Maybe" answers are usually yes** on cartoons. Calibration from one eval set:

  | Judge p | Share actually true |
  |---|---|
  | below 0.1 | 0% |
  | 0.3-0.5 | 67-70% |
  | 0.5-0.7 | 88-92% |
  | above 0.9 | 99-100% |

  Keep the 0.3/0.7 band anyway and escalate the middle; don't refit thresholds to a handful of cases.
- **A reference sheet in the request didn't help** a direct proportion question (76% with the sheet, 82% without).
  The box ratio did.
- **"Flat 2D" on soft-shaded cartoon characters** reads at 0.2-0.5. Treat style questions as "drawn vs 3D or photo".
- **Weak spots:** eyes on an upside-down face, palms in a back view, a leg "lying along the mat" vs "straight but
  vertical". Mark them unsure and escalate.
- **An overlay gets mistaken for a logo** (a red pacer circle read as a corner logo at 0.6-0.75). Say in the criteria
  what the overlay is.
- **Answers are stable:** the same request repeated moves by about ±0.02, and other questions in the bundle don't move
  an answer. Cache by request hash and re-runs are free.

**Rules to keep it honest:** every question atomic and observable; the null case gets its own companion question,
gated in code before a Box or Choice is read; option names say what they mean; criteria describe the general case,
never a test item; verdicts with fewer than 20 labels keep a hand rule.

**Which model:** any vision model that returns probabilities (or confident JSON) can fill the role. One option is
**TypeSafe Jev**, a "System One" model that answers typed questions (Noul yes/no, Choice, Score, Box) with calibrated
probabilities: images need the header `TypeSafe-Danger-Zone-Images: true`, and Box questions need jev-1.14 or later.
A small flash-lite class model through fal or any OpenAI-compatible endpoint works too (JSON answers, slower and
pricier per frame), and a local Ollama vision model is free but takes 15-60 s a call; that makes it a fine escalation
target and a poor first pass.

**Tool:** `tools/judge/judge.py` with an example bank for a generic round mascot (`tools/judge/questions/`) and
`packs.example.json`. Bring your own frames and labels; none ship with the repo.

## 8. Paid APIs lock when the balance runs out

- **Hosted model and voice providers can lock the account** when the prepaid balance runs out, and the API then
  answers 403 (or 402, or a "locked / top up" message) on every call, including cheap ones.
- **Make jobs stop and report on a 401/402/403.** Never silently fall back to another provider or model: a fallback
  run produces different takes, and nobody notices until review. Never read an error as a "no" in QA.
- **Turn on auto top-up** for providers you rely on, with a monthly ceiling, or check the balance before a batch.
- **Budget caps per day,** checked before each submit (`tools/fal_run.py --daily-cap`, `bake.py --hard-cap`).
- **Log every paid call** to one CSV ledger: date, tool, provider, model, units, USD, note. The tools here append to
  `spend-ledger.csv` (or `$AMR_LEDGER`).

## 9. Storyboard the motion before animating

- A sheet of approved stills with **motion arrows, camera moves with their end frames, eyelines, and timing on
  beats** answers the questions a video model would otherwise answer at random: which way things move, where the
  camera stops, who looks at what, how each shot hands over to the next.
- **Get a yes on the sheet before any video spend.** Moving an arrow is free; re-rendering a shot is not.
- **Explore cheap, finish expensive:** rough the frames and blocking on a cheap image model, then render the approved
  keyframes on the expensive one with the same composition.
- Write an **edit-plan table** (shot, motion in, motion out, cut type, camera move, duration) and check the cut
  against it.

**Tool:** `tools/storyboard/sheet.py` (the sheet), `tools/storyboard/thirds.py` (the composition check). Guide:
[STORYBOARD.md](STORYBOARD.md).

## 10. Composition: rule of thirds

- Horizon or ground line on a third, never across the middle.
- The main subject's eyes on a third intersection; lead room in the direction it looks or moves.
- No big band of empty ground at the bottom of the frame.
- A push-in may start wide and off the thirds, as long as its **end frame** lands the subject on an intersection.
- A vision model can place the horizon and face; the flags are code (thresholds you can change), and a free manual
  mode takes the numbers by eye.

## 11. Screen direction and the 180-degree line

- The journey has a direction (rain, a fall, a walk out and back); keep it across every cut.
- When a new set would flip the direction (outside to inside), **mirror the plate**, not the character: a flipped
  character swaps sides of its own design.
- An eyeline in one shot points where the looked-at subject sits in the next.

## 12. Cuts, camera moves and rhythm

- **Cut on action** and **match on action:** out of the bottom at the right third, in at the top at the right third,
  same speed.
- **Transitions that tell the story:** a flash that is the cut, cold-to-warm at a door, a match cut from a fire's glow
  to a lit window seen from outside.
- **Motivated camera moves** (push in = this matters, tilt up = where is it coming from?) that end on a planned end
  frame the next shot picks up from. Lock the camera when the action carries the shot.
- **Rhythm:** cut on beats; hold 5-6 beats for mood, 2-3 for action, about 4 for acting.

## 13. Score explainer scripts before recording voices

- **Pacing and structure are measurable.** Seconds to the first stake or number, where the first "but" lands, comparisons
  per minute, the longest run of plain facts, words per second, how long the picture sits still. Measure a reference
  channel you admire into a bible (numbers only) and score every script against it.
- **Gate the script before any voice spend.** A rewrite is free; a re-recorded voice track and re-synced shots are not.
  Fix every P0 (no stakes, a hook slower than the reference, no turn, copied wording) before recording.
- **Use a blind critic, not the writer.** Give it only the script and the bible; it runs the scorer, reads the whole
  script and returns timestamped issues and up to 3 rewrites. If its call and the score disagree, the critic wins.
- **Gate the rough cut too:** the same scorer on the cut plus its captions adds picture pacing (no long still
  stretches, no frozen frames).
- **Learn structure and rhythm, never words or art.** A copy guard fails any 8-word run shared with the reference
  captions; keep downloaded captions private and out of git.

**Tool:** `tools/explainer-critic/` (`build_bible.py`, `score.py`, an example bible and sample scripts) and the agent
`agents/explainer-critic.md`. Guide: [EXPLAINER-CRITIC.md](EXPLAINER-CRITIC.md).
