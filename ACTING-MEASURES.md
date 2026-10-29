# Measuring acting: principle -> number or judge question

The companion table to [ACTING.md](ACTING.md), for anyone writing a check or tuning a judge
([tools/judge/judge.py](tools/judge/judge.py), [tools/qa/staging_rules.py](tools/qa/staging_rules.py)). Each row says
what to measure, where the data comes from, a **starting threshold**, and an atomic judge question for where code
can't see it.

The thresholds are starting values from the books in ACTING.md and from shots a director approved. **Fit them on your
own approve/reject labels** (`judge.py fit`) before anything fails a cut on its own. Until a verdict has 20 or more
labels, keep it as a P1 flag with a person looking.

## Where the data comes from

- **Layer A, code-animated or rendered (exact):** the renderer exports, per frame and per character: `cx, cy`
  (centroid), `bx, by` (contact or bottom point), the box, `sx, sy` (scale), `area` (visible pixels, and sheet pixels at
  that scale), `rot` (body tilt) and `airborne`. Where the rig has them, also `stem_angle` (or any loose part), `eye_dx,
  eye_dy` (pupil offset), `blink` (0-1), `head_rot` and `expr` (the named expression key). `tools/edit/bounce.py
  --report` gives the timing and landings; `tools/blender/export_tracks.py` gives per-frame masks, visibility and
  contacts in the staging-rules format. Add the eye, blink and loose-part channels to your renderer rather than
  estimating them from pixels.
- **Layer B, AI or composited footage (estimated):** masks from the clip's alpha, from a clean plate, or from a
  segmentation model (SAM 2 and similar) give `cx, cy`, the box, the area and the bottom point per frame. Feature
  matching on the background (ORB) removes the camera. Faces and eyes need the judge. `tools/qa/actstrip.py` gives the
  cuts, the stepping, the holds and the activity per 0.5 s.
- **Judge:** atomic yes/no, Choice or Box questions on single frames or on 2-3 frame strips. Ask the positive way round
  ([LESSONS.md](LESSONS.md#7-a-fast-judge-model-for-qa)).

Notation: frames at 24 fps; `v` = per-frame velocity of the centroid (camera removed); `s` = step size |v|.

| Principle (rule) | Measure | Data | Starting threshold | Judge question (when code can't) |
|---|---|---|---|---|
| **Arcs** | For each move between two keys: the max distance of the path from its chord / the chord length (the sagitta ratio). For airborne spans: the R^2 of a parabola fit to `cy(t)` | A: cx, cy; B: mask centroid | head turns and gestures: sagitta ratio 0.05-0.30 (< 0.03 = straight-line drift, P1); hops: parabola R^2 > 0.98, with the apex hang (frames within 5% of the apex height) 15-40% of the airtime | "Does the character's path across these frames curve?" (on an overlay of the centroid trail) |
| **Ease in / out (spacing)** | The step sizes `s` across a move: ease index = mean(s in the first and last 20%) / mean(s in the middle 60%); linearity = CV of s | A or B | acting moves: ease index < 0.6; CV > 0.25; **contacts:** the last step before contact is the largest of the fall (no slow-in into an impact) | n/a |
| **Holds and moving holds** | Hold = a run where s < 0.5% of body height per frame. Report its length; inside it, the micro-motion of any channel (breathing, blink, loose part) | A or B (+ actstrip `holds`) | gesture hold 6-12 f; reaction hold 12-24 f; a hero hold over 36 f (1.5 s) needs a story reason (P1 otherwise); a **dead** run (exact repeats, no living channel) over 24 f = P1, over 48 f = P0 for a hero | "Is the character moving (breathing, blinking, swaying) between these two frames?" |
| **Volume in squash and stretch** | sx * sy per frame (A); visible area / sheet area at that scale (B, unoccluded frames only) | A exact; B masks | sx*sy within 1.00 ± 0.05 (ball characters); area within ± 10% of the sheet | "Is the character's body the same size as in the reference sheet?" (with the sheet) |
| **Anticipation scaled to the action** | For each take-off or big move: anticipation = the frames where v points opposite to the main action (or the body compresses, sy < rest) just before it; ratio = anticipation frames / action frames; also its depth (min sy, or the displacement against the move) | A; B with masks | present before every hop and big move; ratio 0.2-0.6 for hops, 0.3-1.0 for heavy lifts; a hop's squash depth >= 30% of its landing squash; a deliberate snap with none must be marked in the plan | "Is the character crouched lower than in its resting pose?" (frame before take-off vs rest) |
| **Weight: the lift** | Load start lag: the frames between the body starting up and the object starting up; the object's acceleration profile | A; B with object + character masks | heavy lift: the object starts 4-12 f after the body; its velocity rises over >= 6 f (not instantly) | "Are the character's knees bent?" at the set frame; "Is the object touching the character's hands?" on every carry frame |
| **Weight: landing** | Squash depth vs impact speed (v at contact); the settle: count and frequency of the rebound oscillations of sy or cy after contact | A exact | squash depth correlates with impact speed (r > 0.6 across a shot's landings); 2-3 decaying jiggles at 3.5-5.6 Hz, decaying to < 10% within 0.6 s; a heavier character has a lower frequency | n/a |
| **Contact on ones** | Are the frame of contact and the 2-3 frames after it unique drawings (not repeats)? | A; B via actstrip repeats | contact frame + 2 after it on ones | n/a |
| **Overlap and follow-through** | Lag = the frame offset maximising the cross-correlation between the body's horizontal acceleration and the loose part's angle (stem, leaf, mane, braid); settle = the frames from the body stopping to the part's angle staying within 2 degrees | A (loose-part channel); B via a Box on the part + code | lag 2-6 f; the part still moving 4-12 f after the body stops; overshoot > 0 | "Is the leaf bent to one side?" on the stop frame and 4 frames later |
| **Eyes lead, then head, then body** | The onset frames of eye movement, head rotation and body rotation for each turn; their order and lags | A (rig channels); B via the judge's eye-direction Choice per frame | order eyes -> head -> body; eye-to-head lag 2-4 f, head-to-body 2-6 f; all three starting on the same frame = P1 ("block turn") | Choice: "Which way are the character's eyes looking: left / right / up / down / at camera?" |
| **Blinks on thought changes** | Blink times (blink channel, or the judge's eyes-closed question); interval regularity (CV of intervals); blink duration; distance from each blink to the nearest head turn or expression change | A; B judge | 4-8 f (a deliberate slow blink 8-14 f); >= 60% of blinks within 3 f of a head turn or thought change; CV of intervals > 0.3 (no metronome); no blink for over about 4 s on a hero in a talking or listening beat = P2 | "Are the character's eyes closed?" |
| **Expressions change on thought changes, and hold** | The expression class per sampled frame (judge Choice, or the rig's expr key): run lengths and changes per second | A; B judge at 6-12 fps | each expression held >= 12 f; <= 1 change per beat; flicker (a class lasting < 4 f between two others) = P1; any expression the character bible forbids = P0 | Choice: "Which expression: big grin / small smile / neutral / surprised / determined / worried / angry?" |
| **Thought before action** | The gap between the eye change (or a pause, s near 0) and the start of each deliberate action | A/B | 4-12 f between the look and the move | "Is the character looking at the object it is about to touch?" on the frame before the touch |
| **No twinning, no lockstep** | Pose: the left-right symmetry of the silhouette about the body axis (IoU of the mask with its mirror). Group: the max cross-correlation of two characters' `cy(t)` and the lag at that max | A/B masks | single-character symmetry IoU < 0.9 in acting keys (front-on presenting poses fail); two characters correlated > 0.9 at a lag < 3 f = lockstep (P1); 2+ characters landing within 1 f of each other = P1 unless it's a marked unison beat | "Are both arms in the same position?" |
| **Contrast between keys** | Between consecutive held keys: the change in mask aspect ratio, area and centroid height | A/B | >= 10-15% change in at least one, unless the beat is a hold | n/a |
| **Contrast in timing** | The durations and peak speeds of the moves in a shot | A/B | fastest-to-slowest move duration ratio > 2 in any shot over 3 s; all moves within ±20% of the same duration = P1 ("metronome") | n/a |
| **Line of action** | Fit one curve through the body-axis keypoints (base contact -> centroid -> head or tip); its curvature, and whether it's a single C or S | A (rig keypoints); B judge | non-zero curvature in acting keys, bending toward the effort (the sign matches the force direction) | "Is the character's body leaning or curved, rather than standing straight up?" |
| **Silhouette reads** | The negative space between the gesturing limb and the body in the mask (the limb's area outside the body's convex hull) | B masks | in a gesture key, >= 30% of the gesturing arm or glove lies outside the body hull | "In this black silhouette, can you tell what the character is doing?" (on the mask image, with the intended action as the option) |
| **Balance** | The horizontal offset of the centre of mass from the support span | A/B masks + contact points | inside the support span unless the plan says falling or leaning on something | n/a |
| **Comedy: the hold on the result** | The hold after the turn (the gag's accent) before the next action or cut | A/B + the plan's gag times | 12-36 f | n/a |
| **Comedy: the take** | Anticipation, then the extreme on ones (2-4 f), then a settle into a hold of 12-24 f | A/B | as stated | n/a |
| **Ma (pauses with life)** | The count of planned living holds (>= 24 f with s near 0 and a living channel moving) per minute; dead ones counted separately | A/B | at least 1 per 30 s short, at the turn of the feeling; dead holds 0 | n/a |
| **No idle hero; actions play through** | (a) the hero's longest dead or near-still run without a story-hold tag; (b) for every prop that changes place: a frame where the hero touches it on both sides of the move (pick up, put down) | A/B + tracks + prop state | (a) <= 36 f; (b) both contacts visible, or a match cut on the action | "Is the character holding the object?" |
| **Accents on the beat or word** | The time between each planned accent (a word, a music beat, a sound effect) and the nearest motion peak (actstrip peaks or the track's max acceleration) | A/B + lines.json or the beat grid | within ±2 f | n/a |

## Turning these into verdicts

- **Code decides, models observe.** The thresholds above are P1 flags until fitted. A P0 needs a fitted verdict or a
  hard rule from the character bible ([docs/character-acting-bible.template.md](docs/character-acting-bible.template.md))
  or a dead hero hold over 2 s.
- Measure per **shot** and per **character**; never average across a cut.
- Every flag carries its frame range and a frame triplet (before, at, after), like actstrip's `key_*.jpg`.
- When a row needs a rig channel you don't export yet (eyes, blink, loose part), add the channel to the renderer rather
  than estimating it from pixels.
