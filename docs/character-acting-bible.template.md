# Character acting bible (template)

Copy this file next to your episode, fill in one section per character, and give it to the blind critic
(`agents/animation-director.md`) with every clip, pose sheet or animatic. It is the **acting** side of the cast:
design locks, proportions and palettes live in your character sheets ([KEYFRAMES.md](../KEYFRAMES.md),
[CONSISTENCY.md](../CONSISTENCY.md)). If those change, they win; update this file the same day.

Anything under **Hard rules** is a P0 for the critic. Keep that list short and absolute, so it is never argued with.
The worked rows below show the kind of thing to write; replace them.

---

## <Character name>

**Who they are when they move:** one or two sentences: role in the group, temperament, what they want most.
*Example: a strongman leader; warm, proud and simple-hearted; leads from the front and solves things with muscle.*

**Design the acting must respect:** body shape, what they have and don't have (limbs, fingers, a neck), the loose parts
that carry overlap (a leaf and stem, a mane, a tail, a cape), and anything that must never change size.

**Hard rules (each one is a P0):**
- Emotional range: the expressions this character never shows (*e.g. never angry, scared or worried; never the butt of
  the joke*).
- Body: what must never appear (*e.g. no fingers, gloves only; no limbs, ever; no chest*).
- Physics: *e.g. always on the ground, never floating; or floats by design.*
- Status: *e.g. nothing happens TO this character; they make the jokes.*

**Acting palette:**
| Situation | How they do it |
|---|---|
| Rest / listening | *a planted stance, weight on one leg, a slow breathing moving hold; never a dead freeze over 1.5 s* |
| Thinking | *eyes to the object, a beat, a small head tilt; one clear thought at a time* |
| Deciding | *a blink, then a nod or a squared-shoulders accent* |
| Effort (lift, push, climb) | *look, set, sink, slow start, overshoot, settle; the face stays in pleasant, determined effort* |
| Pride / success | *a different gesture each time; a gesture repeats at most once per film* |
| Joke | *a deadpan beat, the line, a hold for the laugh* |
| Talking to camera | *head and shoulders carry the accents of the line; hands gesture on the key words only* |

**Gesture rules** (for characters without hands, fingers or limbs): how they point, count, show size or direction.
*Example for gloves only: raise or extend the whole glove toward the target; tap a glove on a graphic while the number
appears in a code layer. Example for ball characters: lean toward what they want, squash down to gather, stretch up to
hope; the eyes move first, then the body tilts, then the loose part on top follows.*

**Timing personality (numbers):**
| Parameter | Value |
|---|---|
| Weight class | light / medium / heavy |
| Anticipation for a big move | *e.g. 3-6 f (light) or 8-16 f (heavy)* |
| Squash at landing (0-1) | *e.g. 0.20 light and precise, 0.27 springy, 0.34 heavy and soft* |
| Settle spring (Hz / damping) | *e.g. 5.6 / 0.30 light, 4.6 / 0.21 springy, 3.5 / 0.16 heavy (three slow jiggles)* |
| Hop or step tempo vs the group | *e.g. 0.86x, 1.0x, 1.15x* |
| Sound pitch | low / mid / high |

Every character in a group needs numbers that differ from the others, or they move in lockstep.

**Typical failures to look for:** the things AI or code keeps getting wrong for this character.
*Example: worried brows on a glance; long thin legs from a motion-copy model; a prop that floats or slides in the
hands; fingers appearing; a loose part frozen rigid.*

---

## Group rules (everyone on screen)

- Never lockstep: offsets of 0.1-0.6 s, with a leader, a follower and a straggler.
- Never overlapping each other on screen, at any depth, unless the beat is marked as a deliberate pass-in-front
  (and whitelisted in the scene's `overlap_ok`, see [QA.md](../QA.md#staging-rules-overlap-spacing-stairs)).
- Stairs are taken one tread at a time, landing on each tread.
- Characters enter from a frame edge, from behind something or out of a dark interior; they never appear.
- Every landing is on a real surface, with a contact shadow.
- Any house rules for tone: *e.g. nobody hits anyone; nobody is hurt, mocked or scared; calm faces, fewer and clearer
  gestures.*
