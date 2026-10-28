# Example: three ball characters, a doorway and a meadow

The shot the guide in [ANIMATION.md](../../../ANIMATION.md) refers to: three limbless ball characters peek out of a
cottage doorway, squish down the steps one squash per tread, and bounce across the grass, all drawn in code on
painted plates.

| File | What |
|---|---|
| `doorway-scene.mp4` | the shot, 9.8 s, 1080x1920, 24 fps, with code-synthesised sound |
| `arcs-and-squash.jpg` | the review sheet: each character's centre per frame (big dot = new drawing, small = held), the contact squash shapes in white, and a graph of squash (sy) per frame with the area line (sx·sy) sitting on 1.0, i.e. volume kept |
| `poster.jpg` | a still from the shot |

What it shows: anticipation squash before each hop, volume-preserving squash and stretch, arcs with hang time, a
damped jiggle after each landing, follow-through on the leaves and stems, per-character weight and timing (no two
move in step), contact shadows, impacts on ones and drift on twos.

What it also shows, and what we fixed next: the characters appear in the doorway without coming from anywhere, and
one touches the door frame without a contact. See "Characters must be in the scene" in
[ANIMATION.md](../../../ANIMATION.md#characters-must-be-in-the-scene-not-on-top-of-it).

**Rights.** The characters and artwork in this folder belong to their owner and are shown as an example only. They
are **not** covered by the repository's MIT licence: don't reuse them. The code that animates them is in
[`tools/edit/bounce.py`](../../../tools/edit/bounce.py) (MIT).
