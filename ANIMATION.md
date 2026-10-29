# Animation principles for AI video and code animation

A clip can be on-model, in focus and well lit and still feel dead. What's missing is animation: weight, timing and
acting. The old principles (squash and stretch, anticipation, arcs, follow-through, timing, holds) still decide
whether a shot reads as alive. They apply the same way whether the motion comes from a video model, from code or
from a mix of the two.

This page lists the principles with a way to get each one from a model prompt or edit, a way to build it in code,
and a check. The best-received shot we made in 2026-10 was **pure code**: three limbless ball characters hopping out
of a doorway and across a meadow, built principle by principle. The reviewer called it "super good" and "perfect",
then asked for the same rigour on every shot. That tool is `tools/edit/bounce.py`; the shot and its review sheet are in [docs/examples/ball-characters](docs/examples/ball-characters/).

Related: timing per action and layer in [TIMING.md](TIMING.md), the local edit and code tricks in [EDIT.md](EDIT.md),
same-character-every-shot in [CONSISTENCY.md](CONSISTENCY.md), staging and shot order in [STORYBOARD.md](STORYBOARD.md).
The performance layer on top of these mechanics (thought before action, key poses first, weight, eyes lead,
blinks, comedy timing, and how to measure each one) is in [ACTING.md](ACTING.md).

---

## 1. Why AI clips look stale

| Symptom | What's missing | Where it's fixed |
|---|---|---|
| A jump starts with no wind-up; a character just goes | **anticipation** | prompt the wind-up as its own beat, or start the clip on the crouch |
| Feet slide; the landing has no weight; the character floats a few pixels off the ground | **contact** | lock the camera, prompt "plants", composite a contact shadow, reject sliding takes |
| Every move takes the same time at the same speed | **timing and spacing** | ones/twos per action ([TIMING.md](TIMING.md)), re-time in the edit |
| The move stops dead, or drifts on forever | **settle** | a damped overshoot, then a true hold |
| Everything in the frame moves at once (hair, cloth, background, camera) | **staging**: one main action at a time | locked-off camera, a still plate, prompt one action per shot |
| Straight-line motion between poses | **arcs** | prompt the path ("an arc up and over"), check the trail |
| Hair, ears, leaves stop when the body stops | **follow-through and overlap** | prompt it, or add it in code on its own spring |
| Two characters move in lockstep | **personality in timing** | offsets and different weights per character |
| The hero stands still while something else happens | **acting** | keep the hero doing something; see [§4](#4-acting-rules) |

Models produce smooth, evenly spaced, everything-moves motion by default. Most of the fixes are a prompt beat, a
choice of where to cut, or a code layer, not a more expensive model.

---

## 2. The principle table

| Principle | What it looks like | From a video model (prompt / edit) | In code | The check |
|---|---|---|---|---|
| **Squash and stretch, volume kept** | flattens on landing, stretches along the motion in the air; never shrinks or grows | "squashes flat as it lands, stretches tall as it springs up"; stylised models do this, realistic ones resist it | scale `sx = 1/k, sy = k` about the contact point; stretch along the velocity; `sx*sy = 1` exactly | area per frame = 1.0 (bounce report `area_min/max`); silhouette area within 10% of the sheet |
| **Anticipation** | a small opposite move first: crouch before a jump, lean back before a dash | "first crouches low, then jumps"; or start the clip on the crouch keyframe | 0.08-0.20 s squash plus a lean away from travel before a hop from rest | a frame before every take-off is lower and wider than the rest pose |
| **Arcs** | heads, hands and bodies travel on curves | "in an arc up and over"; reject straight-line drifts | constant-gravity parabola; extra hang at the apex (`hang` 0.2-0.4); fast into the ground | an arcs sheet (centre per frame); the trail is a curve, spacing widest near the ground |
| **Timing and spacing** | fast in, slow out; each action has its own rate | re-time in the edit, never prompt "slow motion" | ease curves; impacts on ones, drift on twos, holds on fours or more | [TIMING.md](TIMING.md) plan per shot; `ones_frac` and `held_frac` in the report |
| **Settle** | overshoot, two or three smaller jiggles, then still | trim the clip after the settle; extend with a held drawing | damped spring: frequency 3.5-5.6 Hz, damping 0.16-0.30 | the last 0.3 s of an action has no drift; held frames at the settle |
| **Follow-through and overlap** | a leaf, ear, tuft or tail lags and swings past when the body stops | "her ponytail keeps swinging after she stops" | the top of the sprite bends on its own floppy spring driven by the body's acceleration | the appendage is still moving 2-4 frames after the body stops |
| **Secondary action** | a blink on a big landing, the face riding the squash | prompt one, not three | blink on impacts above a threshold; face is part of the sprite, so it squashes with it | it supports the main action and never competes with it |
| **Tilt into travel** | the body leans the way it's going; a small rotation kick on landing | "leaning forward as it hops along" | tilt = f(horizontal speed), 6-13 degrees; a 2-5 degree kick on landing | the lean flips when direction flips |
| **Contact and weight** | the character sits *on* the ground; a dark contact shadow; dust or dew where it lands | locked camera, "feet planted", composite a shadow if the model forgets | contact shadow that shrinks and fades with height, a dark core while touching, particles per surface | no frame where the character is above the ground without being mid-hop; no sliding |
| **Staging** | one clear main action; the eye knows where to look | one action per shot; still plate; locked camera | background on a still plate; crowd on threes | name the main action of each shot in one sentence |
| **Holds** | a held drawing reads as intent | trim to the pose; hold it in the edit | `settled()` holds the drawing (no micro-drift) | a dead freeze over ~1 s needs to become a living hold ([TIMING.md](TIMING.md#living-holds)) |
| **Sound on the event** | every landing makes a sound, pitched to the character | the model's audio is rarely usable; add your own | synthesised boops: pitch per character, a wobble at the spring's rate, pats on grass, ticks on stone | sound lands on the impact frame, not near it |

**Squash and stretch is about area.** A ball that squashes to 0.7 tall must get 1/0.7 = 1.43 wide. If the area
changes, it reads as inflating, not squashing. The bounce tool reports `area_min` and `area_max`; both should be 1.0.

---

## 3. Character personality via timing

The same hop reads as a different character when the numbers change. Never animate two characters with the same
parameters and the same start time: lockstep reads as a copy, not a group.

| Personality | Squash | Spring (Hz / damping) | Anticipation | Hop tempo / height | Hang | Tilt | Extra | Boop |
|---|---|---|---|---|---|---|---|---|
| **light** (quick, precise) | 0.20 | 5.6 / 0.30 (two clean jiggles) | 0.10 s | 0.86x / 0.95x | 0.30 | 9 deg | blinks only on the hardest landings | ~560 Hz, 0.22 s |
| **heavy** (big, soft) | 0.34 | 3.5 / 0.16 (three slow jiggles) | 0.20 s | 1.15x / 0.80x | 0.20 | 6 deg | blinks on most landings | ~250 Hz, 0.32 s |
| **springy** (playful) | 0.27 | 4.6 / 0.21 | 0.08 s | 1.0x / 1.25x | 0.40 | 13 deg | a mini-bounce after every other landing; spins | ~700 Hz, 0.22 s |

- **Offset every entrance and every hop** by 0.1-0.6 s. Stagger the order of arrival (a leader, a follower, a
  straggler), not just the start times.
- **Weight shows in the settle,** not in the hop: a heavy character squashes deeper and jiggles longer at a lower
  frequency.
- **Pitch follows size:** a bigger, heavier character gets a lower sound. Keep it per character and consistent
  across the series ([CONSISTENCY.md](CONSISTENCY.md)).
- In a video model you get personality by prompting the verbs ("bounds", "plods", "bounces twice") and by **cutting
  each character from its own take** rather than one take of a group.

---

## 4. Acting rules

| Rule | Why | Check |
|---|---|---|
| **Eyes lead.** The eyes move first, then the head, then the body | it shows thought before action | the look changes 2-6 frames before the turn |
| **The reaction comes after the event.** Never show a reaction before the audience has seen its cause | a smile before the reveal spoils it | the cause is on screen first, then the face ([STORYBOARD.md](STORYBOARD.md)) |
| **No idle hero.** A hero standing still while something else happens reads as dead time. No held still of the hero over ~1.5 s unless it's a story hold (a reaction, a beat before a reveal) | the audience watches the hero; if the hero stops, the shot stops | measure every hold of the main character; anything over 1.5 s is named in the plan or fixed |
| **Cause and effect are visible.** An object that lands was put there by a hand, matched frame to frame; never pop an object in with code alone | objects that appear on their own break the world | for each new object, find the frame where it is placed and the frame before it |
| **One idea per beat.** A simple warm payoff beats a clever twist that needs explaining | if the ending needs a line to explain it, it isn't working | describe the ending in one sentence a child would get |
| **Hold on the result.** After a gag or a reveal, hold long enough to read it (0.5-1.5 s) | cutting on the punchline loses it | the hold is in the timing plan |

The full acting checklist, the per-beat check and the key-poses-first acting pass are in [ACTING.md](ACTING.md).

Keeping the hero busy is cheap: a living hold (breathing, blinks) costs nothing in code, and for a video model a
"keeps working at X" prompt on a cut-away is one generation. A frozen still is never the fix
([TIMING.md](TIMING.md#living-holds)).

---

## 5. Contact and weight

- **No sliding feet.** When a foot or a body is in contact, its contact point stays fixed to the ground until it
  lifts. In code this is free: the squash pivots on the bottom contact point. In AI takes, reject any take where a
  planted foot drifts; trimming around the slide is better than shipping it.
- **Contact shadows, always.** A soft ellipse under the character that **shrinks and lightens with height**, plus a
  small dark core while touching. Without one, a composited character floats even when its pixels touch the ground.
- **A settle after every action,** then a true hold. No micro-drift on a held pose: code holds the exact drawing.
- **Impacts on ones.** The contact frame and the 3-4 frames after it are drawn on ones; the drift between is on
  twos ([TIMING.md](TIMING.md)).
- **Particles per surface:** dew on grass, dust on dirt or stone, a few droplets with gravity and one soft puff.
  Small and short (0.2-0.4 s). They sell the contact more than a bigger squash does.
- **Depth scale:** a character lower in the frame is closer and bigger. Scale by ground line (`depth` in the bounce
  scene) so a hop toward camera grows.

---

## 6. Openings and pans

A cozy short opens like a picture book, not like an ad. The grammar that worked:

1. **Sunrise and scenery cuts** with ambient sound only (birds, wind, water). Two to four shots, 1.5-3 s each.
2. **A slow, eased pan** across the location to where the story happens. Slow in, slow out; the layers move at
   different speeds (parallax), so a flat painting reads as a place.
3. **A hold** at the end of the pan (about 1 s) so the eye settles.
4. **Then the hero in action,** already doing something. Never open on the hero standing.

| Pan setting | Value that worked |
|---|---|
| Hold on the wide before moving | 0.8-1.0 s |
| Pan length | 3-6 s for a 9:16 plate about 2x the frame width |
| Ease | cubic in-out (or sine); never linear, which starts and stops with a jolt |
| Push-in during the pan | 1.0x to 1.1-1.15x, zoom eased in log space |
| Parallax | sky 0.1-0.2, far hills 0.5-0.6, mid 1.0, foreground 1.3-1.5 |
| Frame rate | camera on ones; characters on twos ([TIMING.md](TIMING.md)) |
| Hold at the end | 0.8-1.2 s |

`tools/edit/pan.py` renders it from layer images and keys. Video models can do the pan too, but they drift the
painting while the camera moves; a code pan over a still plate never does.

---

## 7. Mattes and the matte gate

Composited characters need a matte, and a bad matte is the cheapest way to ruin a good take.

**Never colour-key a character against a background that shares its colours.** A green character on grass, a blue
one on sky, a brown one on wood. In one cut a chroma key removed a character's green trousers on green grass and left
the belt floating above the boots. Nobody had looked at the matte; the comp looked fine at thumbnail size.

| Source of the matte | Use when |
|---|---|
| **The clip's own alpha** (a model or renderer that outputs transparency) | always first, when you have it |
| **A video segmenter** (SAM 2 or similar), seeded on frame 0 with a box or points | AI takes on any background; re-seed after cuts |
| **Difference against the clean plate** (the same plate without the character) | locked-off shots where you have the empty plate |
| A colour key | only when the character shares **no** colour with the background, and only with the gate |

**Run the matte gate on every character shot,** before the comp goes into the cut:

```
python tools/qa/matte_gate.py --masks mattes/ --frames frames/ --ref sheets/approved_mask.png \
       --ref-frame sheets/approved.png --color trousers=#2f8f3a~30 --color boots=#463223~20
```

| Check | Fails when | Catches |
|---|---|---|
| Silhouette area | outside +-10% of the approved still (or `--norm height` when the character moves in depth) | a part of the body gone, background pulled into the matte |
| Colour pixels inside the matte, per named colour | outside +-10% of the approved still | "the trousers are gone" even when the area change is small |
| Holes | interior gaps grow by more than 1% of the silhouette | a key that bit into a same-coloured patch |
| Separate parts | more pieces than the approved still | a floating belt, a detached hand |

Any fail is a P0. `failing.jpg` shows each failing frame beside the reference with holes in red and extra parts in
yellow. Then a person still looks at one full-size comp frame per shot.

---

## 8. Per-shot checklist

Before the shot is animated:
- [ ] The main action is one sentence; the hero is doing something in every second of it
- [ ] Cause and effect: every new object has a visible cause, matched frame to frame
- [ ] The reaction comes after its event; eyes lead the head
- [ ] Each character has its own personality numbers and its own offset; nothing in lockstep
- [ ] A timing plan: impacts on ones, acting on twos, holds named ([TIMING.md](TIMING.md))

After the take or the code render:
- [ ] Anticipation before every take-off or big move
- [ ] Arcs, not straight lines (arcs sheet or a scrub)
- [ ] Squash and stretch keeps area (report `area_min/max` = 1.0)
- [ ] Contact: no sliding, no floating, a contact shadow, particles where it lands
- [ ] A settle after every action, then a true hold with no drift
- [ ] Follow-through on loose parts
- [ ] No still hero over ~1.5 s that isn't a planned story hold
- [ ] Sounds land on the impact frames, pitched per character
- [ ] Matte gate passes on every composited character ([§7](#7-mattes-and-the-matte-gate))
- [ ] Then the usual cut gates ([QA.md](QA.md)) and the consistency checks ([CONSISTENCY.md](CONSISTENCY.md#one-page-checklist))

---

## Tools

```bash
# ball characters hopping over a plate (squash/stretch, anticipation, arcs, settle, follow-through, shadows, boops)
python tools/edit/bounce.py scene.json -o bounce.mp4 --report bounce.json --arcs arcs.jpg
python tools/edit/bounce.py --demo work/bounce-demo      # test sprites + gradient plate, renders and self-checks

# matte gate: area, colour, holes and parts against the approved still; exit 1 on any fail
python tools/qa/matte_gate.py --masks mattes/ --ref approved_mask.png --frames frames/ --ref-frame approved.png \
       --color trousers=#2f8f3a~30
python tools/qa/matte_gate.py --demo work/matte-demo     # one eaten frame and one holed frame must fail

# eased parallax pan with holds
python tools/edit/pan.py pan.json -o pan.mp4
python tools/edit/pan.py --demo work/pan-demo
```

Formats and options: [tools/README.md](tools/README.md).

---

## Characters must be in the scene, not on top of it

The same reviewer then caught two faults in that "perfect" shot: the characters appeared in the doorway out of
nowhere, and one ran into the door frame without touching it. Code-drawn characters are pasted over a painting, so
nothing stops them doing this unless you build the scene in layers and check it.

| Rule | How |
|---|---|
| **Enter, never appear.** A character becomes visible only from the frame edge, from behind something, or out of a dark interior. | Split the plate into layers (interior, characters, foreground: door jambs, threshold, step edges, grass tufts) and draw the foreground over the character so it is occluded, then emerges. Stagger entrances. |
| **Solids are solid.** No overlap with a wall, a jamb, a stone or another character unless it is a contact, and a contact has a response (squash, rebound, sound). | Draw a "solids" mask per plate; stop paths short of it, or add the bump on purpose. |
| **Land on something.** Every landing sits on a real surface: a step's tread, the threshold, the path; never mid-air, never inside a riser. | Draw a "supports" mask per plate (landing lines); snap each landing to it. |
| **Check it, don't trust it.** | Export each sprite's per-frame box, mask and depth from the animator and test them against the plate's masks: visible area may only grow from an edge, occluder or entrance; overlap with a solid needs a registered contact; grounded frames sit within a few pixels of a support. For AI footage, track the character's mask instead and run the same tests plus the matte gate. |

Add the masks to the scene's bible so every shot on that plate is checked the same way.
