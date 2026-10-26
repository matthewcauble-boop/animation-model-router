# Timing: ones, twos and threes

AI video models interpolate everything at 24 or 30 fps. The motion is smooth in the way a motion-smoothed TV is
smooth, and it reads as video, not animation. Hand-drawn animators never time a whole shot at one rate. They time
**each action and each layer**. Doing the same to AI footage, in the edit, is the cheapest big quality jump there is.

## The rule sheet

| Layer or action | Rate | Why |
|---|---|---|
| Characters, by default | **twos** (12 drawings a second at 24 fps) | the classic hand-drawn feel |
| Fast action, snaps, impacts, smears, contacts | **ones** | a fast move on twos strobes and loses the contact |
| Anticipation and settles | twos | |
| Pose holds | **fours or more** (a true hold) | a held drawing reads as intent, not a freeze |
| Mouths (dialogue) | **ones** inside lip-synced takes; twos for hand-timed mouth shapes | a synced mouth stepped on twos lags the consonants; keep each synced take locked to its audio ([VOICES.md](VOICES.md#delivery-getting-voices-onto-the-picture)) |
| Crowds and background cast | **threes** | keeps the eye on the hero layer |
| Camera moves | **ones** | a stepped camera judders |
| Backgrounds, effects, UI, subtitles, code graphics | **ones** | |

**One blanket rate for everything looks like a filter, not animation.** Making "a ones version, a twos version and a
threes version" of a shot misses the point; mix them per action and per layer.

## Applying it in the edit

The motion model renders smooth footage; the timing is applied afterwards, in post. That keeps it reversible, lets you
re-time without paying for a new generation, and works on any model's output.

```
python tools/timing/onestwos.py take.mp4 --spec timing.json -o take-timed.mp4 --report timing-report.json
```

`timing.json` (see `tools/timing/examples/timing.example.json`):

```json
{
 "fps": 24, "default": "twos", "pick": "sharpest",
 "segments": [
  {"shot": "S1", "start": 0.0, "end": 3.8, "rate": "twos", "camera": "compensate", "why": "acting; slow push-in"},
  {"start": 1.0, "end": 1.25, "rate": "ones", "why": "bounce contact + rebound"},
  {"shot": "S2", "start": 5.4, "end": 6.2, "rate": "fours", "why": "pose hold on the grin"},
  {"shot": "S4", "start": 9.0, "end": 12.0, "rate": "ones", "camera": "ones", "why": "code camera move on a still plate"}
 ]
}
```

- List the **shot-wide rate first and the ones-windows after it**; later rows win.
- Hold blocks restart at every segment start, so a cut or a ones-window never starts mid-hold.
- **Frame count, fps and audio are untouched,** so dialogue, music and SFX stay in sync to the frame.
- `"pick": "sharpest"` (default) holds the sharpest frame of each block. Interpolated in-betweens are blurry, so this is
  also the **anti-smear** fix for models that smear fast motion (Hailuo in particular). `"first"` is classic exposure
  sheet behaviour.

### The camera problem

Stepping the whole frame is right for a **locked-off** camera. If the AI clip has a camera move baked in (a push-in, a
pan) and the layers are not separated, stepping it makes the camera judder. Options per segment:

- `"camera": "step"` (default): step the whole frame. Locked-off shots.
- `"camera": "compensate"`: the held drawing is warped by the camera's own motion (similarity transform from ORB
  features + RANSAC, fitted on the background), so the camera glides on ones while the drawing holds on twos. Fine for
  slow moves; wrong for strong parallax; needs texture in the background.
- `"camera": "ones"`: leave the segment on ones (code camera moves, effects shots).

**The clean fix is layer separation:** if your pipeline applies the camera move (a code crop or zoom), run `onestwos`
on the source take *before* the move and apply the move afterwards on ones.

### Order of operations

1. Generate the take (smooth).
2. Run the cut gate ([QA.md](QA.md)).
3. Run the timing pass with a per-shot spec.
4. Run the cut gate again on the timed cut (stepping can expose a smeared drawing as a held frame).
5. Present the timing plan with the cut ("S2 on twos, ones for the double take, a four-frame hold on the grin"), so
   the reviewer knows the stepping is deliberate.

## Living holds

A hold is a held **drawing**, not a frozen **character**. Two different things:

- **Short holds inside an action** (a beat on the grin, four frames or more): hold the drawing in the timing pass, as
  above. Under about a second this reads as intent.
- **Long holds** (a stretch held for 10-30 s, a character listening, a character talking): the character must stay
  alive. Freezing a frame and bobbing it in code reads as a sticker.

| Situation | Do | Never |
|---|---|---|
| Held stretch or pose | Generate a living hold from the held still with a lip-sync or reference-to-video model: breathing on a fixed rhythm (5.5 s in, 5.5 s out), soft blinks, eyes closing on the exhale, a small smile, same pose, locked-off camera | freeze the frame; code bobbing; ping-pong or reverse the clip |
| A character talking | Lip-sync it to its own lines; the listener breathes and blinks with its mouth shut | a static mouth flap, or a mouth that moves on the other character's line |
| A stretch, start to end | Ease in once, hold with visible breathing, then switch; mirror it with the same hold time | bounce in and out of the stretch to fill time |
| The model darkens the background | Match levels to the plate, or composite the character back over the original plate | ship a hold whose background goes darker |

Time the living hold on twos like the rest of the character layer. Check it with the judge's `alive` pack: the body
should move between neighbouring samples. See [LESSONS.md](LESSONS.md#4-no-frozen-characters-living-holds).

## Delivering for an outside finishing team

When another team grades, mixes and subtitles, deliver **clean, silent video**: no audio from the model, no burned-in
captions, no grade or "vintage" look. Offer both the raw takes and a timing-finished version. Model-generated audio is
rarely usable, and a baked-in look is impossible to undo.
