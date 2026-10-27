# Consistency: the same characters, places, look and voices across a whole series

People want 5-10 minute episodes with characters, drawings and voices that stay the same from shot to shot,
scene to scene and episode to episode. This page covers how a small studio does that today, what works, what doesn't,
and what we measured. It links to the detailed guides and doesn't repeat them.

The honest summary: **no model keeps a character consistent on its own.** What works is the process. Lock each thing
once as an image or a file, make every shot from those locks, and check the stills against them before you pay for any
motion.

---

## The core idea

1. **Lock references as images, not prose.** A paragraph describing a character gets redrawn differently every time.
   An approved image used as a reference mostly doesn't. Words are only for what the image can't show ("never
   fingers", "no arms or legs") and for measurable proportions.
2. **Make every shot of a scene as a still first, then check the stills together.** Most drift is already baked into
   the start frames. A still re-roll costs about $0.14; a video re-roll costs $0.30-2.80 ([KEYFRAMES.md](KEYFRAMES.md)).
3. **Anything that must be exact goes in code:** text, numbers, rain, light flicker, the camera move, timing, grain.
   Code doesn't drift.
4. **Every human note becomes a check.** The fifth time a reviewer says "the eyes look small", a judge should already
   be catching it ([REVIEW.md](REVIEW.md#the-judge-and-fix-loop)).

A long episode is not one long generation. It is many short shots, each made from the same locks. Longer clips just
give drift more time to show up.

---

## The consistency stack

| Layer | The lock | The reference | The check | Usual failure | The fix |
|---|---|---|---|---|---|
| **Character identity** | one approved front image per character, plus a turnaround (front, 3/4, side, back) made from it | the front image in every keyframe prompt; the turnaround for swaps that need turns | side-by-side strip against the sheet; `continuity.py --stills` on-model question | redesign drift: dot eyes instead of ovals, a texture on a smooth character, a different animal | never let a model draw the character from text; re-roll from the sheet ([KEYFRAMES.md](KEYFRAMES.md#1-lock-the-character-sheets)) |
| **Face** | a **face crop** of the approved art, plus a face-lock line (eye size as a share of the head, outline weight, brow shape, mouth) | the face crop as an extra reference whenever the full body is small in the sheet | side by side by eye; a judge for brow anger/worry (eye size it can't judge, see below) | faces shrink in painted or "classic" looks: eyes at about 60% size, thinner outline, furrowed brows, a tiny smile | face-only edit with the face crop, about $0.02 a still, two tries then a person |
| **Proportions / build** | the approved front still + a **measurable** lock line ("legs about half the body's height", "arms as big from every side") | the approved still as image 1 for every new pose and angle | legs-to-body ratio from two boxes, computed in code, against the sheet | new angles and motion-copy swaps stretch stocky characters toward human: long thin legs, slim arms, a bodybuilder chest | anchor on an on-model still; name width and mass, never heights; angle sheet approved before motion ([LESSONS.md](LESSONS.md#3-motion-copy-swaps-stretch-cartoon-proportions)) |
| **Costume and traits** | a short list of house rules per character, written in the character's own terms ("gestures with the whole round glove", "no arms or legs, ever") | pasted into every prompt for that character | one yes/no trait question per rule in the bible (P0 for hard rules) | verbs draw anatomy: "points" draws a finger, "walks" gives legs to a limbless sidekick, "winks" adds eyelashes | rewrite verbs with the anatomy the character has ([KEYFRAMES.md](KEYFRAMES.md#5-prompt-nouns-trigger-anatomy)) |
| **Scene / geography** | one **master plate** + an **empty plate** per set; one camera geography and a 180-degree line per scene | master + empty plate as refs 1-2 for every shot | same-room question against the master; strip of all shots | the room is regenerated per shot and becomes a different room | derive every shot from the master (crop, zoom, or edit with "keep everything else identical") ([KEYFRAMES.md](KEYFRAMES.md#2-one-master-plate-per-set)) |
| **Props and state** | a prop list per scene, and a **state that only moves forward** (the basket fills, the fire burns down, the cup empties) | listed in the shot line: "the props stay in the same places in every shot" | prop yes/no per shot in the bible; prop state changes at a set time | props move, double, vanish or reset between cuts | list them every time; check the strip; one keyframe per state change |
| **Light / time of day** | one light direction and time of day per scene, written into the LOOK and the shot line | the master plate carries it | same-light question in `--stills` | light flips sides between shots; dusk becomes noon | weather and light flicker (rain, fire glow, lightning) as **code layers** over the plate, not generated per shot |
| **Style** | one **LOOK paragraph** and one palette for the series, pasted into every image prompt unchanged | one or two approved style frames | blind critic on a strip of mixed shots | each model, tier and resolution draws a slightly different look | the same finishing pass on every source in the edit: grade, grain, line boil, timing on twos ([TIMING.md](TIMING.md), [EDIT.md](EDIT.md)) |
| **Voice** | one `voice.json` per character: endpoint, voice, seed, settings, delivery tag; never changed mid-series | the file itself | listen to a changed line next to its neighbours | a new seed or model version is a different person | line-by-line cache by text; a voice change is a re-cast of the whole episode ([VOICEOVER.md](VOICEOVER.md#1-lock-the-voice)) |
| **Timing and screen direction** | a rate per action (ones, twos, threes) and a direction per journey | the edit plan | vosync sheet; screen-direction check in `continuity.py` | a blanket rate looks like a filter; a character flips sides across a cut | timing in the edit, mirror the plate not the character ([TIMING.md](TIMING.md), [LESSONS.md](LESSONS.md#11-screen-direction-and-the-180-degree-line)) |

---

## The series bible: folder layout

One folder per series and one per episode. Anything reused across episodes lives at the series level and is never
edited from inside an episode.

```
series/
  bible.md                    # who the characters are, their rules, tone, what they never do
  LOOK.md                     # the one LOOK paragraph + palette hex codes + 2 approved style frames
  characters/
    <name>/
      front.png               # THE identity reference (approved by a person)
      face.png                # crop of front.png, for face locks
      turnaround.png          # front / 3-4 / side / back, made from front.png, approved
      angles/                 # approved new-angle stills, each checked against front.png
      expressions.png         # the approved range (and the ones it never does)
      locks.txt               # FACE lock, BODY lock, trait rules, verbs to avoid
      voice.json              # locked voice (endpoint, voice, seed, settings, tag)
      judge-labels/           # every approve/reject note on this character, as labelled frames
  sets/
    <set>/
      master.png              # the locked wide with characters on their marks
      empty.png               # same camera, no characters
      reverse.png             # the other side of the 180 line, if the set needs one
      geography.png           # top-down sketch: camera positions, marks, the 180 line, exits
  props/<prop>.png
  code-layers/                # rain, fire glow, eyes, title card, subtitles style: reused as code
ep07/
  script.md  lines.json       # one row per line, with its shot and what must be on screen
  storyboard.json  board.png  # annotated sheet (STORYBOARD.md)
  continuity.json             # this episode's bible: who is present per shot, marks, facing, props state
  keyframes/<scene>/S1.png ...
  clips/  build/  qa/
  NOTES.md                    # every note from review, and which check now catches it
```

**Reuse is the cheapest consistency there is.** One small world (a cottage interior, its exterior and a meadow) has
carried several shorts for us: the plates, the code rain and the timeline were all reused, so the new episode only
paid for the new acting. For a series, budget most of the first episode's spend on the bible and the sets, and treat
every later episode as "new shots in old places".

---

## Per-episode workflow (5-10 minutes)

A 7-minute episode at 3-5 s a shot is about 90-140 shots. Do it scene by scene, never as one pass.

| Step | What | Gate before the next step |
|---|---|---|
| 1. Script | written as `lines.json`, one row per line, each with its shot | read it aloud; score explainer scripts ([EXPLAINER-CRITIC.md](EXPLAINER-CRITIC.md)) |
| 2. Board | shot list per scene, annotated sheet: size, move, end frame, eyelines, beats | blind story director: no P0 ([REVIEW.md](REVIEW.md#the-story-director), [STORYBOARD.md](STORYBOARD.md)) |
| 3. Voice | voice the lines from the locked `voice.json` (cached) | lines land on their pictures in the board timing ([VOICEOVER.md](VOICEOVER.md)) |
| 4. Keyframes per scene | every shot as a still from master + empty plate + sheets + pose card; explore cheap, finish high only for frames that get animated ([ROUTING.md](ROUTING.md#0-image-tiers-pay-for-quality-only-on-frames-that-get-animated)) | judge-and-fix on each still, then the strip and `continuity.py --stills`; a person approves the scene's stills and every new angle **together** |
| 5. Motion per moment | the model each moment calls for, from the approved still ([ROUTING.md](ROUTING.md)) | look at the take before finishing it; at most one re-roll, then re-board the shot |
| 6. Edit | timing on twos, code layers, finishing pass, subtitles, mix ([EDIT.md](EDIT.md)) | |
| 7. Cut gates | `continuity.py`, `frameqa.py`, `vosync.py`, the judge ([QA.md](QA.md)) | any confirmed P0 fails the cut |
| 8. Human pick | the director watches the cut | every note goes into the judge's labels and `NOTES.md` |

**Where the money goes wrong.** One of our shorts took 7 versions and about $30. Almost every re-spend came from a note
that could have been caught on stills: silhouettes that didn't read as the characters, a "chubby" build, rain that
stopped short of the ground, a scene whose logic was unclear, a pose the model changed mid-shot. The rule that came
out of it: **the story director on the board and a silhouette and proportion still sheet, before any video.**

---

## LoRA vs reference editing vs identity models

| Method | What it is | Worth it when | Not worth it when |
|---|---|---|---|
| **Reference-image editing** (GPT Image, Nano Banana, FLUX Kontext, Qwen-Image edit, Seedream edit) | the approved art goes in as a reference image every time | almost always for a small cast; nothing to train, works across styles, two characters in one frame stay separate | the model refuses your reference (try another edit model, see [ROUTING.md](ROUTING.md#if-a-model-refuses-the-reference)) |
| **Image-model LoRA** | a small adapter trained on 20-30 approved images per character | a cheap "explore" tier for one character, or very high volume of one character | two characters in the same frame; hard poses on characters with strict body rules |
| **Video-model LoRA** (self-hosted open video model) | trained on clips of the character | you self-host at volume | you don't have real training pairs (a sheet-only LoRA made our characters photoreal) |
| **Identity models / "elements"** (Kling elements, Veo ingredients, Seedance and Runway references, trained identity such as Soul ID) | the vendor builds and stores the identity from images (or a short clip) | a real person (with consent) or a photoreal hero across many shots on one platform | flat 2D cartoons with strict rules: identity tools are built and marketed around faces; test before you commit |

**What we measured** (one image-model LoRA per character, 21-22 curated images each, 1200 steps, about $5 per
character to train; 9 test prompts against reference editing with the approved art):

| | LoRA text-to-image | LoRA edit + art ref | Reference editing (GPT Image 2.5 medium) |
|---|---|---|---|
| Round mascot, 4 prompts on-model | 4/4 (boot colour drifted in 2) | 4/4 | 4/4 |
| Gloved character, 4 prompts passing her body and no-fingers rules | 2/4 | 0/4 | 4/4 |
| Both characters in one frame | **identity bleed:** one got the other's snout and body | partial bleed | clean |
| Cost for 9 images | $0.32 | $0.11 | $0.18 |

**Verdict: the LoRA did not beat reference editing.** It did best on the simplest character (the face filled the body
better than reference editing did) and is a fair cheap explore tier for that one character. Stacking two LoRAs merged
the characters. For a series with a small fixed cast, reference editing from approved art is the default.

**Captioning rule if you train one:** never describe the fixed design in captions (leaving it out binds it to the
trigger word); do describe the render style, so the style stays promptable and isn't baked into the character.

**Turnaround sheet or front crop?** It depends on the model, so test both. One swap model tracked turns into profile
best with one combined turnaround sheet and drew no duplicates. Other reference-to-video models read the same sheet as
several characters and drew two to four copies; they wanted one clean front crop.

---

## New angles and new poses

New angles are where good characters go off-model. A side, 3/4 or back view made from a front sheet came back with
long thin legs and, from behind, a huge ball with stub arms. We animated those before anyone checked the sheet and
threw the money away.

1. **Make every new angle from the approved front still as a reference**, plus the lock text: same body size, limb
   thickness as a share of body width, leg length as a share of body height, "arms as big from every side".
2. **Zoom each new angle side by side against the approved front.** Not a thumbnail.
3. **A person approves the angle sheet before any video.** Approved angles go into `characters/<name>/angles/` and
   become references themselves.
4. **One keyframe per named position** ([KEYFRAMES.md](KEYFRAMES.md#one-keyframe-per-named-position)).
5. **Lock lines name width and mass, never heights or head counts.** "Belly wider than his shoulders" helped; "long
   thin legs" made a character lanky. Never describe parts the reference doesn't show: a "tail" line grew a dinosaur
   tail on a character whose tail is hidden from the front.
6. **For a character for young viewers, never describe the chest or body movement.** "Chest rising" gave a child-like
   character an adult chest in 6 of 7 video takes. Write "shoulders rise and fall", turn prompt expansion off, and
   check every frame.
7. **A 3D blockout helps only if it is readable.** Capsule mannequins and blank surfaces gave image and video models
   nothing to hold, and close-ups got re-staged as wide shots. A **colour-coded** blockout (each object its real colour,
   skin-tone hands and face, one continuous take) sent as a reference video, with the character and product as image
   references, held framing, scale and motion frame for frame. Depth-controlled local models also hold layout but copy
   crude proxy shapes literally (slab hands became mitts).

---

## What automatic checks can and can't do

The full list is in [REVIEW.md](REVIEW.md#what-judges-cannot-do) and [QA.md](QA.md#a-fast-judge-model). For
consistency in particular:

| Can (measured) | Can't (yet) |
|---|---|
| Character present or missing: 97-100% | **Eye size.** Approved frames and shrunk-face frames overlapped (0.45-0.94 vs 0.63-0.79), and an eye-box ratio didn't separate them either (about 0.22 vs 0.22-0.26). Check faces by eye against the face crop |
| Fingers on a gloved character: 100% on 54 labels | "Looks off" in general: outline weight, shape, expression. Next idea is embedding similarity against the approved library; untested |
| Stretched proportions, via two boxes and a ratio in code: on-model 0.1-0.84, stretched 0.87-1.56 | A direct "are the legs too long?" question: stuck at 0.3-0.5 |
| Continuity as a truth table over samples (present before, gone now, same shot) | Colour masks on a set that shares the colour (grass read as green trousers) |
| A whole 39 s cut in 16 s for $0.022 | Story, staging, whether a reveal lands. That's the story director and a person |

Two rules that kept the checks honest: **test every new check on known-good frames** (a "too bulky" check failed 4
of 7 approved frames because the design really has big shoulders), and **write questions so "yes" names the visible
defect** (negated twins scored 5-31% where the positive wording scored 76-100%).

---

## What the field broadly agrees on, and where we differ

Sources are mostly vendor docs and practitioner guides, 2025-2026. Exact limits change often; check the live docs.

**Broadly agreed:**
- **Cast once, reuse the sheet.** Make one identity sheet per character and reuse it in every generation, scene and
  episode. Drift is mostly a workflow problem, not a model problem ([Atlabs](https://www.atlabs.ai/blog/how-to-create-consistent-characters-across-multiple-ai-generated-kids-videos),
  [Scenario on Seedance 2.0](https://help.scenario.com/articles/7140699840-seedance-2-0-the-complete-guide)).
- **A staged pipeline with gates:** lock the story, break it into shots, keep character rules separate from shot
  variables, generate, inspect continuity, repair only what failed, then edit. Longer clips give drift more room
  ([Dreamina guide](https://dreamina.capcut.com/ai-video/best-ai-animation-tools-for-creators)).
- **A series bible plus per-character and per-state sheets,** and finished episodes used as references for the next
  ([invideo FAQ](https://invideo.io/faq/how-do-you-create-an-ai-video-series-with-consistent/)).
- **Keep the cast small and visually distinct** (2-4 main characters); complex physical interaction and subtle facial
  acting are still weak spots ([Genra](https://genra.ai/blog/how-to-create-ai-animated-stories-guide)).
- **Video models now take references for characters, objects and settings:**
  - Veo 3.1 Ingredients to Video: identity, background and object consistency across scenes; Google's post doesn't
    give a reference count, a reseller's API lists 1-3 ([Google, 2026-01-13](https://blog.google/innovation-and-ai/technology/ai/veo-3-1-ingredients-to-video/),
    [Magnific docs](https://docs.magnific.com/api-reference/reference-to-video/veo-3-1/overview.md)).
  - Kling 3.0 Omni: elements from multiple images or a 3-8 s clip, with a voice bound to the element so face and voice
    stay the same across videos ([Kling element library](https://kling.ai/quickstart/klingai-element-library-3-user-guide),
    [Kling subject binding](https://kling.ai/blog/kling-3-subject-binding-character-consistency)).
  - Seedance 2.0: up to 9 reference images (plus video and audio refs) tagged in the prompt; we saw this in secondary
    sources and ComfyUI's notes, not on a ByteDance page ([ComfyUI](https://blog.comfy.org/p/seedance-20-is-now-available-in-comfyui),
    [Luma](https://lumalabs.ai/learning-center/articles/seedance-2.0-basics)).
  - Runway Gen-4 References: a character from one reference image across lighting and locations, up to three refs;
    from press and third-party help pages, not Runway's own docs ([The Decoder](https://the-decoder.com/runway-releases-gen-4-video-model-with-focus-on-consistency/),
    [Scenario help](https://help.scenario.com/articles/6803483730-runway-gen-4-references)).
- **Trained identity models** (for example Soul ID) learn a face from a set of photos and keep it across prompts and
  presets. The vendor's own pages disagree on how many photos and on whether the identity carries across models
  ([Higgsfield](https://higgsfield.ai/blog/Soul-ID-AI-Character-Consistency),
  [Higgsfield guide](https://higgsfield.ai/blog/consistent-characters-locations)).
- **3D blockouts fix layout and camera, not continuity.** A CHI '26 study of rough-3D-plus-generative previs still
  reports continuity as a challenge ([PrevizWhiz, arXiv 2602.03838](https://arxiv.org/abs/2602.03838v1)).

**Where our experience differs:**
- **Many guides rank LoRA training above reference images** for long-term reuse
  ([example](https://rangy.ai/blog/ai-character-consistency)). For a small cartoon cast with strict body rules, ours
  didn't beat reference editing, and two stacked LoRAs bled into each other. We found no independent head-to-head
  benchmark either way.
- **Identity features are built around faces.** We didn't find a published test on flat 2D characters whose rules are
  "no fingers" or "no limbs", and our own tests say text rules plus a check are still needed whatever the reference
  feature is. Treat vendor consistency claims as a starting point.
- **Multi-view sheets are not a universal win.** Several guides recommend turnarounds as references; on some of our
  models the sheet made duplicate characters.
- **Scene consistency gets less attention than character consistency.** Most guides stop at the character. In our cuts
  the bigger failures were a regenerated room, a missing sidekick in a start frame and props that moved, which is why
  the master plate and the per-episode `continuity.json` exist.

Not verified: exact reference limits per model today, whether Soul ID-style identities transfer between video models,
and the "25 minutes by one creator" kind of claims in vendor FAQs.

---

## One-page checklist

**Once per series**
- [ ] One approved front image, face crop and turnaround per character; a person signed them off
- [ ] `locks.txt` per character: face lock, body lock (measurable), trait rules, verbs to avoid
- [ ] `LOOK.md`: one paragraph and a palette, pasted into every prompt unchanged
- [ ] Master plate, empty plate and geography sketch per set
- [ ] `voice.json` per character, picked blind, seed fixed
- [ ] A judge question for every hard trait, tested on approved frames as well as bad ones
- [ ] Code layers for weather, light flicker, titles, subtitles

**Per episode**
- [ ] Script as `lines.json`; board through the story director with no P0
- [ ] `continuity.json`: who is present per shot, marks, facing, props state (forward only)
- [ ] Every shot as a still from master + empty plate + sheets + pose card
- [ ] Every new angle made from the approved front still and checked zoomed, side by side
- [ ] Strip + `continuity.py --stills`, then a person approves the stills of each scene together
- [ ] Motion only from approved stills; one re-roll, then re-board
- [ ] The same finishing pass (timing, grain, grade) on every source
- [ ] Cut gates: continuity, frameqa, vosync, judge; no confirmed P0
- [ ] Every note from the human pick becomes a label and a line in `NOTES.md`
