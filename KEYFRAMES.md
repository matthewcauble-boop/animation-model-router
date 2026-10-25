# Keyframes: consistent stills first

> "The animation model is fine. The key is that the frames are consistent." The director, after a cut where a
> character's arms drifted between shots and a sidekick vanished mid-scene.

Most continuity failures in AI animation are baked in before the motion model runs: the start frames don't match
each other. A sidekick missing from a start frame is missing from the clip. A set regenerated per shot is a different
room per shot. So the studio rule is:

1. **Make every shot of a scene as a still first.**
2. **Gate the stills together** (side by side, plus the continuity checker in `--stills` mode).
3. **Only then spend on video.** A keyframe re-roll costs about $0.14; a video re-roll costs $0.30-2.80 and a review pass.

---

## 1. Lock the character sheets

For each character, make (or take from the official art) a small set of sheets and reuse them in every shot:

- front, three-quarter, and the key expressions;
- a **pose card per shot**: the one or two action-sheet poses this shot needs, cut out on white, side by side;
- for video replacement work, **one clean front crop** (not a multi-view sheet: models read a turnaround as several
  characters and draw duplicates).

Never let a model freely redraw a character from a text description. Drift seen in testing: dot eyes instead of ovals,
a peel texture on a smooth character, gloves drawn as bare hands, once a horse.

## 2. One master plate per set

- Generate the room **once**: the master keyframe (characters in place, the locked two-shot or wide) and an **empty
  plate** of the same camera.
- Every other shot's background is derived from it: a reframe, crop or zoom in code, or a camera change made as an
  image edit with the master as reference and "keep everything else identical".
- **Never regenerate the room per shot.**

## 3. Place the characters: two ways

**a. Paste-up in code (zero drift, $0).** Cut the exact on-model art out of an approved frame or sheet (flood-fill the
white background), scale it to the set, set it on the plate and draw a soft contact-shadow ellipse. Use this when a
sheet pose already matches the brief. Check the sheet first: some sheet poses point with a finger.

**b. Reference-guided edit.** An image-edit model takes the plate plus the character sheets as references. This is how
you get new poses, closer framings and new camera angles. The winning recipe is below.

**Do not combine them** by pasting up and then asking a model to "harmonize" or clean the composite. In testing that
pass hallucinated photo-studio tripods and umbrellas into a kitchen (1.7/10).

## 4. The winning edit recipe

**Model:** GPT Image 2.5 high (2k, 9:16) for anything with a new framing or angle; Nano Banana 2.1 for same-camera
coverage only (it keeps the set pixel-stable but fakes close-ups by scaling the characters, and its new angles are
mild). Scores over two rounds of six-shot sets: GPT Image 2.5 high 7.1, GPT Image 2 high 6.8, Nano Banana 2.1 6.25,
Nano Banana Pro 4.3. See [ROUTING.md](ROUTING.md) for ids and prices.

**Five references, in this order, for every shot of the scene:**

1. the master keyframe (the locked shot with on-model characters);
2. the empty plate of the same camera;
3. character A's sheet;
4. character B's sheet;
5. the pose card for THIS shot.

A model limited to four references has to drop the empty plate, and scored much worse (FLUX Kontext, 3.5).

**Prompt template** (the second-round wording, which removed every finger failure):

```
Image 1 is the locked master frame of our cartoon <show>: <one sentence: set, props, who stands where>.
Image 2 is the same set, empty. Images 3 and 4 are the official character designs; image 5 shows the poses for
this shot. Keep the set, props, <light direction> light, colours and the characters' designs, proportions, line
style and size EXACTLY consistent with image 1: flat 2D cartoon characters with bold black outlines and flat cel
colours in the photoreal <set>. <Character B> always wears round boxing gloves, never fingers, thumbs or bare
hands; she gestures with the whole round glove. The <set piece> props (<list>) stay in the same places in every
shot of this scene. Vertical 9:16. No captions, no added text. THIS SHOT: <framing>. <action, one sentence per
character>.
```

**Shot-line rules:**

- **New angle:** "New camera angle (do NOT reuse the master camera): the camera moves to <where> and looks back at a
  three-quarter view, the <counter> side in perspective." Without the explicit "do NOT reuse", models quietly reuse it.
- **Close-up:** name what fills the frame: "his round body and big arms fill the frame above the counter edge".
- **Top-down insert:** "the camera looks straight down at the counter top" and list what is on it.
- **Props:** say they stay in the same places in every shot, and list them.

## 5. Prompt nouns trigger anatomy

The single most useful lesson of the keyframe tests. **A verb or noun that implies a body part draws that body part,
whatever else the prompt says.**

- The brief said a gloved character "points". **Eight of eight methods drew a finger,** even with "never fingers" in
  the same prompt.
- The fix was to describe the gesture with the anatomy the character actually has: "holds her whole closed round glove
  out toward him (she never points a finger)", or "raises a glove". The finger failure went to zero in every method.
- An open "presenting" glove still came back as a mitten with a thumb. A closed glove held out, or a glove raised high,
  is safe.

Generalise it: before sending a shot line, read every verb and ask what anatomy it implies. "Points", "grabs",
"waves her fingers", "taps" draw fingers. "Winks" can add eyelashes. "Walks" gives legs to a limbless sidekick. "Grins"
can give separate clenched teeth to a character with one open grin. Rewrite with the parts the character has, and
state the rule positively in the character's own terms ("gestures with the whole round glove").

## 6. The keyframe continuity gate

Before any video spend:

1. **Lay the frames side by side.** `python tools/bakeoff/sheet.py strip scene.jpg S1.png S2.png ... S6.png`. A strip is
   the fastest way to see a prop that moved, a counter base that changed, or a character at the wrong scale.
2. **Run the checker on the stills.** Write the scene's bible (who is in each shot, where, which props, the set's
   master plate, each character's traits) and run
   `python tools/continuity/continuity.py --stills --bible continuity.json`. It asks, per still: same room as the
   master plate? same light? every required character present and on their mark? on-model against the sheet? any
   bible trait broken (fingers, limbs, eyelashes)? It exits 1 on any confirmed P0.
3. **Reject** any frame with fingers or a thumb on a gloved character, props that moved, a changed set piece, a wrong
   character scale, or a missing character where the bible needs one. In one test, two start frames had the pillow end
   of the bed in shot and no sidekick on it, so every take animated from them was going to "lose" him. The stills gate
   caught that before a cent went to video.
4. **Re-roll a rejected frame with the same references** (about $0.14), and re-run the gate.
5. **A human picks the final frames.** The gate removes the broken ones; it does not choose the best.

## 7. Then animate

Animate each approved start frame with the motion model the moment calls for ([ROUTING.md](ROUTING.md)), then run
the cut gate, the timing pass and the cut gate again ([QA.md](QA.md), [TIMING.md](TIMING.md)).
