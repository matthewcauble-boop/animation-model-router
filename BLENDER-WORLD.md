# The painted world in Blender: a set you can film in

AI video re-invents the set in every clip. The chimney moves to the other side, the barrel changes size, a step goes
missing, and a character that steps out of a door lands on a different lawn from the one in the last shot. This guide
is the other route: **build the set once in Blender as blockout geometry, paint it with an image-edit model, project
the paint back onto the real objects, and render every shot from that one world.** It comes from nineteen rounds of
one test (a cottage, a pond, a path and three ball characters hopping out of the door), judged by panels of blind
critics, with the failures kept in. Everything runs headless (`blender -b -P`) on a 12 GB consumer GPU. Render cost is $0;
the paint costs about $0.035 a painting.

The scripts are in [tools/blender/](tools/blender/README.md). Timing per layer is in [TIMING.md](TIMING.md), the
character rules in [ANIMATION.md](ANIMATION.md) and [ACTING.md](ACTING.md), and the staging gate in
[QA.md](QA.md#staging-rules-overlap-spacing-stairs).

## Contents
1. [Why painted 3D beats AI video for continuity](#1-why-painted-3d-beats-ai-video-for-continuity)
2. [Blockout first](#2-blockout-first)
3. [Paint a camera view, project it back onto real objects](#3-paint-a-camera-view-project-it-back-onto-real-objects)
4. [Bake the paint into each object so moves don't smear](#4-bake-the-paint-into-each-object-so-moves-dont-smear)
5. [Two-camera projection, safe moves and the honest plateau](#5-two-camera-projection-safe-moves-and-the-honest-plateau)
6. [Never cross-fade two paintings](#6-never-cross-fade-two-paintings)
7. [Water and the near ground are real objects](#7-water-and-the-near-ground-are-real-objects)
8. [Characters on depth cards](#8-characters-on-depth-cards)
9. [Stairs: tread lines and choreography](#9-stairs-tread-lines-and-choreography)
10. [Repaint the lawn and the path as separate edits](#10-repaint-the-lawn-and-the-path-as-separate-edits)
11. [Ambient motion: breeze and water](#11-ambient-motion-breeze-and-water)
12. [Render times and speed-ups](#12-render-times-and-speed-ups)
13. [Costs](#13-costs)
14. [What failed (so you don't repeat it)](#14-what-failed-so-you-dont-repeat-it)
15. [The recipe on one page](#15-the-recipe-on-one-page)

---

## 1. Why painted 3D beats AI video for continuity

| | AI video per shot | One painted Blender world |
|---|---|---|
| The set | redrawn every clip; props drift, mirror and vanish | the same objects in every shot, locked |
| New angles | a new generation, a new set | a new camera; it agrees with every other shot by construction |
| Camera moves | whatever the model does | eased keys you write, on ones, repeatable |
| A door that opens, a light that comes on | hoped for in the prompt | keyframes on a hinged object and a glow card |
| Characters behind things | pasted on top; they "appear" | real occlusion by the jambs, walls and tread edges |
| QA | estimated from pixels | exact tracks, depths and visibility from the renderer |
| Cost of a re-take | a paid generation | a local re-render |

The image-edit model only paints. It never decides where things are, so it can't move them. One warning: an edit
model will sometimes "fix" a layout anyway (mirror the chimney, move a barrel). Check every painting against the set's
layout with the continuity gate ([CONSISTENCY.md](CONSISTENCY.md)) before you project it.

## 2. Blockout first

Model the set as simple geometry at real scale (metres): the house front, the door as its own hinged object, the steps
as real treads, the terrain, the pond basin, the path stones, a few rocks. Put the far things (sky, distant trees, the
far face of the house) on flat cards. Name materials by what they are (`TerrainPaint`, `PathPaint`, `WaterPaint`):
the scripts address paint by material name. `tools/blender/example_world.py` builds a minimal one to try the scripts on.

Don't try to get the finished look from shading. Our first round used every trick (toon bands, brushy noise on the
light, procedural stones, line-art ink, a painterly filter, paper grain) and a blind critic scored it 2/10 as "the same
artist" as the target painting: a nice stylised 3D game, not a hand-painted world. Five more rounds of shading pushed it
to about 30-40% of the way. Shading is for the blockout and for filling gaps; the look comes from paint.

The blockout earns its keep at once: it gives you every camera, every depth map, and the layout every later painting is
checked against.

## 3. Paint a camera view, project it back onto real objects

The classic matte-painting move, done with an image-edit model:

1. **Render the blockout from the shot's camera** (2x the delivery size, e.g. 1440x2560 for a 1080x1920 shot): the
   structure image. Also render a flat-colour mask pass (lawn magenta, path cyan...) so you know exactly which pixels
   are which surface. `setup_projection.py` makes a static projector camera from the shot camera (slightly wider, see
   below) and renders both.
2. **Paint it** with an image-edit model: image 1 = the structure render, image 2 = your style plate (an approved
   finished painting of the set). Prompt shape: *"Repaint this render in the style of image 2. Keep the camera,
   framing, perspective and the exact position, size and outline of everything identical to image 1, pixel-aligned. No
   new objects, no people, no text."* GPT Image 2.5 edit at medium quality works ([ROUTING.md](ROUTING.md)).
3. **Project it back** from the projector camera onto the real objects' materials (`lawnproj.py`). Only the colour
   feeding the emission changes; transparency, a wet-sheen mix and outlines stay.

Paint the render, not the other way round. When we started from an existing painting and solved a camera to fit it
(18 matched points, OpenCV solvePnP), the fit was 15 px off on average, because the painting was never exactly our
house: paint landed on the wrong shapes wherever the two disagreed (the pond outline, the chimney, the path). Painting
our own render removes that misfit.

At frame 1 a projection equals the painting, pixel for pixel. The trouble starts when the camera moves (§4-5).

## 4. Bake the paint into each object so moves don't smear

One painting projected through one camera at render time smears as soon as the camera moves: ground seen at a grazing
angle stretches, steps grow toward the lens, and anything the projector didn't see shows the bare blockout. A single
projection held up to about a 10-15% push and 4 degrees of orbit.

The fix is to give every object **its own paint**: bake the projected views into each object's UV texture (Blender's
Bake with an Emit pass, about 50-80 s per view on the GPU). For each view, weight each texel by:
- zero where a shadow-map depth test says another object hid it from that camera, and zero outside the frame;
- otherwise a smoothstep of |normal · view direction|, so faces seen at a grazing angle count for almost nothing.

Blend the views winner-take-all (weight^10), so there are no double images, and inpaint any holes from neighbouring
paint. That let the camera go about **3x further** (a 22-degree orbit, a 30% push and a 3 m dolly kept a fully painted
house). The cost was softness and seams where views met, because each view was painted separately and drifted a little.
Paint each new view with the already-baked neighbours as references so views agree, and paint at 2x.

For flat things far away, cards are better than baking: a house face, a treeline and the sky as **complete layers**,
each painted whole behind whatever covers it, keyed to a crisp 1 px alpha and placed at its real depth (a multiplane).
Cards can't stretch, so they stay crisp through any move that doesn't orbit far.

## 5. Two-camera projection, safe moves and the honest plateau

**Two (or three) cameras.** Paint the start of the move from a projector a little wider than the shot (15% wider
covers a whole gentle push), and paint the revealed areas and the held end of the move from a second projector at the
end camera (10% wider). For a punch-in or a new angle, add a third (12% wider, so its feathered edge falls outside that
frame). Install them wide first, then end, then close (a later layer wins inside its frustum). **Paint them in the
opposite order:** the close one first, then the end one from a render that already has the close one, so stones and
clumps continue across the cut.

**Safe moves:**
- a push-in of about 20% or less toward the subject, with a slight rise (about 0.4-0.5 m) and a few degrees of tilt
  down, so the extreme near ground stays out of shot;
- slow trucks or pans where the near ground stays inside one painting's range;
- anything that animates objects (doors, lights, characters) while the camera holds or drifts;
- holds with a little parallax drift (the safest of all).

**Not safe:** orbits over about 10 degrees (flat layers show their flatness), low skims over the ground, dollies of 3 m
or more across the near ground, pushes that end close on water or a bank, and any move that relies on a reflection you
didn't paint. For a bigger move, budget one extra painting per about a second of near-ground travel, or cut to a new
angle: cuts are free, and the world keeps every shot consistent.

**The honest plateau** (strict blind panels, three fresh judges, 0-10 for "the same artist as the plate"):

| Approach | While the camera moves | Strong | Weak |
|---|---|---|---|
| Shading only | 2 | layout, light direction | it reads as a 3D render |
| One projection | 6 at a small move | frame 1 equals the painting | smears past a 10-15% push |
| Per-object baked paint | 3-4 | about 3x more travel | soft, seams, ghosting |
| Painted multiplane | 5.5-6.2 average; early frames 7-7.7 | house, sky and door stay crisp | the near ground: seams, swaps or softness |
| Real near objects + painted cards | 5.3-5.5, flat across the move | truly continuous, real reflections, any camera | the near ground reads as a render with painted textures |

Holds and near-holds on a painting score 7-8. Middle and late frames of a move sit near 6, and a fresh strict judge
almost never gives a moving frame more than that. The scores come down to resolution and repaint: any surface seen
bigger than it was painted goes soft, and anywhere two paintings meet shows a seam or a ghost. The waterline, where
water, bank and reflection meet, is the hardest part. Plan shots around that: hold or drift for the beauty frames,
move gently, and cut rather than travel.

## 6. Never cross-fade two paintings

The near ground was once four projected paintings (the start plate, a strip, a wide pond, an end-of-move pond), chosen
by camera distance, with a dissolve to the end painting late in the push. On screen, the line where one painting gave
way to the next slid across the bottom third while the camera moved, and the pond seemed to grow and change: a viewer
called it a "swipe". An earlier hand-over placed before the new painting covered the frame left a rectangular seam.

The rule: **a surface shows one painting for the whole shot.** Merge the paintings into one texture before the move
(bake them into a single texture on the near-ground mesh, with their seams baked in as fixed, irregular edges and holes
inpainted), so nothing swaps, fades or slides; the only change on screen is parallax. Check it with a strip of the
bottom third every few frames: if anything changes there except by parallax, it fails.

The trade: a merged texture has fewer pixels per metre than the best single painting near the camera (ours was about
585 px/m), so it went a little soft. Bake it at 2-3x density, split near and far into two textures baked from the same
merged sources, and paint over any ghost where two sources met. Soft is fixable; a swipe is not.

## 7. Water and the near ground are real objects

Flat cards fail near the camera. Mirror planes and mirrored cards under a water plane always read as fake (a flat house
card can't reflect like a 3D house: mid-move the reflection was too big or offset, and a giant upside-down house filled
the near pond). Plant cards in the foreground looked pasted on and out of scale. The camera once flew straight through a
near card 0.94 m in front of it.

So everything near the camera is a real object:
- **Terrain** with a carved pond basin that follows the painting's shoreline where the painting shows it, with a soft
  bank lip.
- **Water** as its own surface just below the bank: a painted water swatch, slowly scrolling ripple normals, Fresnel and
  real screen-space reflections, so the house and the door reflect correctly from every camera position. Animated rings
  where a waterfall meets the water, sparse rain rings that expand and fade.
- **Rocks and path stones** as individual objects with unique shapes, sunk into the ground (not sitting on it), with
  flat 3-band toon shading, moss on the upper faces and a thin warm ink line.
- **A painted shore band** (mud, pebbles, reeds) with a dissolving edge where grass meets water.
- Keep a flyover at least 1.5 m above the ground.

In a multiplane-only set (no real water), paint the water into the ground layer, reflection included, so it moves as
one painting and is never resampled. 3D grass blades read as CG; painted grass on real terrain reads better (§10).

## 8. Characters on depth cards

The characters are animated in 2D (here with `tools/edit/bounce.py`'s principles: squash and stretch with area kept,
anticipation, arcs, settles) in the **locked** camera's frame, rendered one character at a time to RGBA
(`rgba_from_bw.py` recovers straight alpha and the soft contact shadow from a render over black and one over white).
`depth_cards.py` then puts each RGBA sequence on a camera-facing card that covers the whole frustum at depth d, so its
pixels land exactly where they were animated, whatever d is. The depth only decides what hides the character and what
it hides:

| Where the character is | Card depth |
|---|---|
| In the room or on the sill | 0.15 m **behind** the house face, so the jambs and wall hide it for real |
| On a tread | the tread's own depth (1/depth interpolated from the sill to the foot of the steps, which matches perspective) |
| On the lawn or path | just in front of the raycast ground point |
| Always | pulled in front of the nearest surface under the body **and** its contact shadow, so nothing clips either |
| In the air | the nearer of its take-off and landing depths |

Fit the character's scale to the ground's 1/depth down the frame (raycast it with `raycast_view.py`), so the size
grows smoothly as it comes forward with no pop at the threshold. Ours grew from about 122 px tall in the doorway to
about 290 px at the end marks.

Make it sit in the light:
- **Contact shadows** are part of the RGBA, under every contact, and the card sits in front of them (above).
- **A rim and grade pass** on each RGBA: a warm rim from the key light's side, a lighter sun side and a cooler far side,
  and the shot's grade. Inside a firelit doorway add an orange back-rim and a warm wash that fades to zero by the second
  tread. Flat-lit sprites look pasted on against a painted world.
- **No dust puffs under a limbless character:** two white puffs under a ball read as feet.
- Cards must use **Blended** render mode. With Dithered, a character behind the doorway rendered solid black.
- Render the world without characters too (`depth_cards.py --no-chars`): the difference between the two passes is
  what is actually visible of each character, which is what the staging gate measures (`export_tracks.py`).

## 9. Stairs: tread lines and choreography

The first version of the hop-out passed its own checker and still failed review: the characters overlapped each other
in the doorway, and every stair landing sat about 14 px down the risers. Two lessons:

**Measure the tread lines on the clean still, zoomed in, never from the animation.** Render the shot with no
characters, zoom 1.5-2x and read, for each tread, the rows of its top face and a contact line inside it (for example
"step 1 top face 880-919, contact line 905; riser 922-994"), and its x span. Put them in the scene's `stairs` block
([QA.md](QA.md#staging-rules-overlap-spacing-stairs)). Landing rows taken from the animation's own track are wherever the
animation happened to land, so they can't catch a landing on a riser.

**Choreograph single file:**
- Threshold -> step 1 -> step 2 -> lawn: one landing per tread, a squash on each, never skipping a tread, never back up.
- The next character appears only after the previous one has left step 1 (and the doorway). At an ordinary hop tempo
  that is about 1.6-1.7 s between appearances; tighter means letting the next one appear while the previous is still on
  step 1, which crowds the doorway.
- Each character takes a lane that drifts away from the jamb the next one comes out from.
- Peek before the step-out: lean and look along the yard, then straight at the camera (the thought before the action).
- End in a row facing camera with clear gaps; one glances at a neighbour, one gives a happy hop (so they aren't in
  lockstep).
- Cut to a medium for the stairs if the wide makes them small: the same camera position and rotation with a 2x lens,
  shifted onto the door and steps (a punch-in), so the world agrees exactly across the cut. It magnifies the painted
  cards about 1.8x, so it's a touch softer; a projector layer painted for the medium fixes that (§10).

## 10. Repaint the lawn and the path as separate edits

A one-pass repaint ("repaint the lawn and the path") redraws the path's outline too, so painted stones land on grass
when the painting is projected back onto the real path stones. Split it into two edits with masks (`paint_split.py`):

1. **Lawn:** the render with the path filled flat magenta. *"Repaint only the lawn as hand-painted gouache grass like
   image 2: directional brush strokes, small clumps and tufts, a little clover and tiny flat wildflowers, light and dark
   greens and ochres, warm low light raking across it. The flat magenta shapes will be covered later: paint plain lawn
   through them. Keep everything else identical to image 1."*
2. **Path:** the render with everything but the path flat magenta. *"Repaint the path crisply in image 2's style,
   filling exactly the non-magenta area edge to edge (its outline must not move by a single pixel): individual
   flagstones with chipped rims, a lit top edge and a darker side, moss in the joints. Keep every magenta pixel pure
   flat magenta."*
3. Strip whatever magenta survives (and its pink fringe), refill those pixels from valid neighbours, and install the two
   textures on the lawn and path materials from the projector (`lawnproj.py`).

```bash
python tools/blender/paint_split.py inputs --src proj/ProjB_src.png --mask proj/ProjB_mask.png --out paint/B
python tools/fal_run.py openai/gpt-image-2.5/flare/edit --upload s=paint/B_in_ground.png --upload p=plate.png --est 0.04 \
       --args '{"prompt": "...", "image_urls": ["@s", "@p"], "quality": "medium", "image_size": {"width": 1440, "height": 2560}}' --dry-run
python tools/blender/paint_split.py textures --src proj/ProjB_src.png --mask proj/ProjB_mask.png \
       --ground-paint paint/B_paint_ground.png --path-paint paint/B_paint_path.png --out paint/B
```

Check afterwards that the medium differs from the previous version only below the lawn edge: the steps, sill and house
should be pixel-identical. Known weak spots: where the wide's start and end layers meet on the ground near the camera
there is a fixed band that is slightly soft (a place on the ground, not a fade in time), and an occasional faint stone
ghost on the grass where a layer's path ended.

## 11. Ambient motion: breeze and water

A finished still world feels dead next to animated characters. Add gentle motion outside the characters, composited in
code on top of the rendered frames (`ambient_masks.py` for the mask pass and cameras, `ambient.py` for the motion,
`frozen_check.py` for the gate):

- **Breeze:** a world-anchored wave field (waves about 1.7 m long, a period of about 4.2 s, drifting with the wind)
  moves the painted lawn sideways by about 2 cm. Because it lives on the ground in world metres, a wide and a medium of
  the same world sway together across the cut, and nothing swims with the camera.
- **Pond:** a slow ripple wobble of the painted reflection, plus warm glints that swell and fade on their own rhythms.
- **Waterfall:** streaks run down the painted stream on its card (warped to the screen with the card's homography) and
  foam churns at the base.
- **Motes:** a few warm motes drifting in the light.
- **Timing per layer, Ghibli-style:** grass on threes (8 drawings a second), water and motes on twos, the camera on
  ones; the file stays 24 fps ([TIMING.md](TIMING.md)).
- **Masking:** the warp fades to zero 2-10 px inside the lawn and samples only lawn pixels; the path, steps, house and
  characters never move. `frozen_check.py` proves it: every pixel outside the motion masks must equal the source render
  within 2 levels (ours: 0 of 365 frames changed).

Two failures on the way: the first pass weighted the warp per pixel ("stroke tips move more than roots") and every
brush stroke melted, like a liquify filter. The warp now stays rigid over about 7 px and the tips move by light (a
highlight shimmer). The second pass was too subtle to see on a phone; the amplitude was doubled. Measured on the empty
yard: about 1.2 px median and 2.8 px p95 of lawn motion over one second, twice that in the 2x medium.

## 12. Render times and speed-ups

All on one 12 GB consumer GPU (RTX 3060 class), EEVEE, headless.

| Job | Time |
|---|---|
| First render in a fresh Blender process (shader compile) | 35-90 s, once |
| A 720x1280 still, 24 samples, line art on | about 2.3 s (8-28 s with leaf cards and line art) |
| A multiplane drawing at 1440x2560 | 1-2 s |
| A 1080x1920 frame of the cottage world, 32 samples | 3.6 s warm (up to about 7 s with everything on) |
| The same at 16 samples | 2.1 s, visually identical (51.8 dB PSNR, 0.05% of pixels over 8 levels) |
| The same at 8 samples | 1.3 s; fine except grainy screen-space reflections on water |
| A medium frame with character cards on a static world | 2.3 s |
| Ambient mask pass, 1 sample | 0.4 s |
| Ambient compositing (CPU) | 1.1-1.4 s |
| Baking one view into object textures (Cycles, GPU) | 50-80 s |

The first character version took about 35 minutes for its two passes (with and without characters). Speed-ups that
worked:
1. **Render static backgrounds once.** In a locked shot the world doesn't change, so render one clean still and only
   render what changes on top: the characters on their cards, then ambient motion composited in code. The last version
   needed no new beauty renders at all: a 15 s clip plus a 5 s empty-yard clip took about 8 minutes.
2. **16 samples, not 32.**
3. **Per-layer frame rates.** Characters on twos, impacts on ones, grass on threes, water on twos, the camera on ones.
   A layer on twos needs only half its drawings rendered ([TIMING.md](TIMING.md)).
4. **Resumable, detached jobs.** Every script skips frames that exist and writes `STATUS.json`; run them detached
   ([README](README.md#running-long-jobs)).
5. **Cloud rendering** when a deadline needs it: the scripts are plain `blender -b -P` with arguments, frames are
   independent, so split frame ranges across rented GPU machines and copy the frames back. Pack the textures into the
   `.blend` first (`File > External Data > Pack Resources`) so nothing points at a local path. We didn't need it for
   these shots, so there are no measured numbers here.

Watch the disk: frame dumps at 1080x1920 add up fast. Keep them on a drive with room, not the system drive.

## 13. Costs

| Item | Cost |
|---|---|
| A painting, GPT Image 2.5 edit medium at 1440x2560 | about $0.035 |
| A painting at 720x1280 | about $0.024 |
| A camera move's paintings (6-10) | $0.20-0.35 |
| The lawn and path repaint for a two-shot 15 s clip (8 edits) | $0.28 |
| The whole 19-round test, every painting included | under $2 |
| Rendering, masks, ambient motion, QA | $0 (local) |

Compare a single AI video take at $0.30-2.80 that you can't re-light, re-time or re-frame.

## 14. What failed (so you don't repeat it)

| Tried | What happened | Do instead |
|---|---|---|
| Finished look from shading alone | scored 2/10; a stylised 3D game | paint it (§3) |
| Solving a camera to fit an existing painting | 15 px misfit; paint on the wrong shapes | paint your own render |
| One projection for a big move | smears past a 10-15% push | bake per object, or multiplane cards (§4) |
| Separately painted views without references | seams and ghosting where they meet | paint in sequence with neighbours as references |
| One painting for the whole near ground | soft: it can't hold detail from 0.5 m to 30 m | paint per camera range, at the size it's seen |
| Mirror planes and mirrored cards for reflections | fake at every angle mid-move | real water, or paint the reflection in (§7) |
| Foreground plant cards | pasted on, out of scale; the camera flew through one | real objects, or keep the near ground out of shot |
| A timed dissolve between ground paintings | a sliding "swipe" and a rectangular seam | one painting per surface per shot (§6) |
| Projecting the start painting everywhere | streaks once the camera leaves the start | limit each projector to its range, feathered |
| 3D grass blades | read as CG | painted grass on real terrain |
| Dithered character cards | a character behind the doorway rendered black | Blended |
| Dust puffs under ball characters | read as feet | no puffs |
| Overlap checked only at the same depth; supports from the character's own track | the gate passed overlaps and riser landings | screen-space overlap at any depth; tread lines from the plate (§9) |
| One-pass lawn and path repaint | the path outline moved; stones on grass | two masked edits (§10) |
| Per-pixel "tips move more" breeze | brush strokes melted | rigid warp, tips move by light (§11) |

## 15. The recipe on one page

1. Blockout at real scale: cards far, real objects near (terrain, pond basin, water, treads, stones), a hinged door.
2. Cameras for every shot of the scene: gentle push-and-rise, holds, punch-ins from the same spot.
3. For each camera range: `setup_projection.py` (projector a little wider than the shot), paint the structure render
   with your style plate, `paint_split.py` for lawn and path, `lawnproj.py` to install. Paint the closest first.
4. Check: every surface shows one painting per shot; the bottom-third strip changes only by parallax; the continuity
   gate agrees with the set's layout.
5. Characters: animate in 2D in the locked camera's frame with the acting pass ([ACTING.md](ACTING.md)), rim-light and
   grade the RGBA, `depth_cards.py` with tread lines measured on the clean still, `--no-chars` for the clean pass.
6. Gates: `export_tracks.py` -> `staging_rules.py` (overlap, spacing, stairs), the animation-director critic, then the
   cut gates ([QA.md](QA.md)).
7. Ambient: `ambient_masks.py`, `ambient.py` (grass on threes, water on twos), `frozen_check.py`.
8. Grade toward the style plate (saturation about 0.85), paper grain, sound on the contacts, then deliver.
