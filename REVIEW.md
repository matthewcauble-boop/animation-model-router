# Review: blind agents, and the judge-and-fix loop

[QA.md](QA.md) covers the gates that ask "is this frame broken?" and "is it the same story as the last frame?". This
page covers two different questions, asked before money is spent and again on the rough cut:

| Reviewer | Question | When |
|---|---|---|
| **Story director** (`agents/story-director.md`) | Does the plan tell its story with pictures? Is the payoff protected, the reaction after the event, the closest shot at the peak? | on the board **before keyframes**; on the animatic / rough cut |
| **Lesson coach** (`agents/lesson-coach.md`) | After one viewing, can the viewer do the thing correctly and remember it? | on the script **before voice or video**; on the rough cut. Anything that teaches |
| **Judge-and-fix loop** (code + a cheap vision judge) | Did this still drift off-model in a way we already know about? If so, fix it automatically | after **every** generated still |

The two agents are Claude Code agent files (frontmatter + prompt). Copy them into `.claude/agents/` in your project
(or `~/.claude/agents/`) and call them by name. Both are **blind**: they get only the artifact paths, never the
builder's reasoning, for the same reason blind critics do ([QA.md](QA.md#blind-critics)): a reviewer who reads why you
did it agrees with you.

## Where they sit

```
script / board ──> story director + lesson coach ──> fix every P0 ──> voice (VOICEOVER.md)
     ──> stills, each through judge-and-fix ──> angle sheet + continuity --stills ──> motion (start/end clips)
     ──> rough cut ──> vosync + frameqa + continuity ──> story director + lesson coach on the cut ──> human picks
```

A note from the director that arrives after the voice is recorded costs a re-voice; after the stills, a re-roll; after
motion, a re-animation. The agents are cheapest at the top.

---

## The story director

Judges information control and staging, beat by beat. In brief:

1. Retell the story in three sentences from the artifact alone (can't = P0).
2. Find each payoff and decide its mode: **surprise** (hide the cause), **suspense** (the audience knows more than the
   character) or **mystery**. Not choosing is a P0.
3. Beat sheet: intended FEEL / KNOW / WONDER per beat vs what the shots deliver.
4. A 16-item checklist (story reads from pictures; no face reacts before the event; cause not visible early, including
   in the cover; reveal big enough; a still beat before it; a hold after it; every move has a meaning and an end frame;
   closest framing at the peak; contrast saved for the climax; action before reaction; screen direction; sound at
   every cut; one idea per shot; runtime earns itself).
5. Re-board: a corrected shot list with size, angle, move + end frame, duration, faces, sound. It keeps the creator's
   story and design rules and fixes order, framing and timing.

The failure it was built for came from a real cut: a twist ("the plain objects are alive") was spoiled because the
image model gave the character who discovers it a knowing smile before the reveal, and the reveal itself was staged
small. The re-board: an extreme close-up of the objects, a held still beat, then a slow pull-back as they open their
eyes, with the reaction only after.

## The lesson coach

Judges whether people learn. In brief:

1. One objective in one sentence (two competing ones = P0).
2. Every cue listed with its time: correct, consistent, **true for everyone it addresses** (a cue that splits the
   audience for no real reason is a P0).
3. Order: **see it, name it, do it, repeat it**.
4. Mistake and fix as a **minimal pair**: same framing, angle and timing, so only the taught thing differs. The mistake
   never looks rewarded.
5. Cognitive load: 3-4 cues in 30 s at most, one idea per beat, labels of 1-3 words next to what they label, the word
   landing while the thing is visible.
6. Concrete landmarks and a self-check the viewer can do; a takeaway doable today.
7. Hook = the learner's benefit; the end restates the one thing plus the action.

The failure it was built for, again from a real script: two different depth targets for two audiences in one squat
lesson, with no reason given. Every viewer has to ask "which one is me?", and the actual lesson is lost. One cue for
everyone, with a self-check, replaced it.

---

## The judge-and-fix loop

Image models drift the same few ways on a given character: eyes shrink, brows turn angry or worried, the body bulks
up. Once you know the drift, don't wait for a person to spot it on every still.

```
for each generated still:
    verdict = judge(still)                       # cheap yes/no vision model, ~$0.0001 a frame
    tries = 0
    while verdict == "fail" and tries < 2:
        still = face_only_edit(still, crop_of_approved_face)   # ~$0.02 image edit
        verdict = judge(still)
        tries += 1
    if verdict != "pass": queue for a human
```

- **The judge** asks atomic questions, each about one visible defect, compared against the character sheet: "are the
  eyes smaller than on the sheet?", "are the brows angled down in anger?", "do the brows look worried?", "is the chest
  wider than the round body?". Code combines the probabilities into pass / unsure / fail. `tools/common/vision.py` has
  the backends.
- **The fix** is an image edit with two references: image 1 = the still to keep exactly (background, framing, pose,
  body, style), image 2 = **a crop of the approved art's face**. Prompt: keep image 1 exactly; change only the face
  and head shape to match image 2. Cheap, and it can't damage the pose because it was told not to touch it.
- **Two tries, then a human.** A third automatic try rarely helps and hides a bad base still.
- A build-level failure (the body is wrong, not the face) is not fixable by a face edit: the loop reports it and the
  still is redone from the pose sheet.

---

## What judges cannot do

Written down because each one cost a wrong decision before it was learned.

- **Yes/no models can't measure size.** "Are the eyes too small?" separates a badly shrunk eye from a good one only
  roughly, and a bounding-box "eye height / body height" ratio did not separate them at all (the model's eye boxes are
  loose). Proportions that matter are better measured in code from a mask, or from two boxes whose ratio has a clean
  gap on labelled frames (body vs legs worked; eyes did not).
- **Colour segmentation needs the matte first.** A hue-based proportion check (green = trousers, so leg length =
  green height) read **grass as green trousers** on an outdoor frame. Segment by colour only inside the character's
  matte, and never trust a colour mask on a set that shares the colour.
- **Test every new check on known-good frames, not only on the failures that prompted it.** A new "too bulky" check
  failed 4 of 7 frames the director had called on-model: the design really has big shoulders, and the character frowns
  when acting. It was loosened (and a brows rule dropped, then re-added when the director said the character should
  never look angry). A check tuned only on bad frames fails good ones.
- **Wording is not symmetric.** The same judgment asked the other way round can score very differently: "is the
  graphic pushed to one side?" scored 5% where its twin scored 95%; "does he have short legs like the sheet?" 31% vs
  76%; "are both hands mitts?" 30% vs 100%. Try both directions on labelled frames and keep the one that scores; never
  assume a negated question is the mirror of the original.
- **"Unsure" on cartoons usually means yes.** On one judge, answers at p 0.5-0.7 were true 88-92% of the time and
  0.3-0.5 still 67-70%. Keep a grey band (0.3-0.7) and send it to a stronger confirmer or a person; don't fit
  thresholds to single cases.
- **A judge can't see what is hidden.** "Do the subtitles cover the ball?" scored 50%, because when the words cover the
  ball there is no ball to see. Use geometry (prop track vs subtitle box).
- **Left/right, mirrored and rotated content is weak.** Upside-down faces read as "eyes closed"; palms can't be judged
  from behind; "left leg" vs "right leg" needs the reviewer to look.
- **Story, staging and teaching are out of scope** for frame judges. That is what the two agents are for, and a
  person still picks the take.

**Every note from the director becomes a label.** When a person says "the eyes look too small" on a frame, add that
frame and verdict to the judge's eval set the same day. The judge gets better on exactly the calls that person makes.
