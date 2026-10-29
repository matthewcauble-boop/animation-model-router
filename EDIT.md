# Edit: the local workflow that keeps the bill small

**Only the motion is paid.** Everything a viewer reads (words, numbers, arrows, glows, check marks, subtitles) and
everything about timing (camera moves, holds, reps, ones and twos, the mix) is code on your own machine. Code is free,
exact, re-timeable and never drifts. A video model asked to draw a label gets it wrong; asked to hold a pose, it wobbles;
asked to repeat a move three times, it bills you three times.

The numbers on this page come from one real piece: a **~25 s vertical workout explainer** in which a round fruit mascot
shows three squat fixes (wrong form as an X-ray "ghost", right form solid with a green glow), then three follow-along
reps and an end card. Total spend about $3-4. The edit cost $0.

![pipeline](docs/img/pipeline.svg)

---

## 1. What runs where

| Step | Where | Cost | Why |
|---|---|---|---|
| Character and pose stills | cloud (image model) | ~$0.02-0.14 each | the drawing is the one thing code can't make |
| Motion (one move per camera angle) | cloud (image-to-video, start + end frame) | ~$0.47 per 3 s clip | the only paid motion |
| Voice | cloud (TTS) | a few cents per line | see [VOICEOVER.md](VOICEOVER.md) |
| Mattes (character cut-outs) | local (or a cheap hosted matte) | $0 | needed for glows, ghosts, tilts, layering |
| Reps, holds, re-timing | local: `tools/edit/reps.py`, `tools/timing/onestwos.py` | $0 | one clip becomes every rep |
| Camera moves (push-ins, reframes) | local crop/zoom | $0 | exact end frames, no drift |
| Glows, ghosts, arrows, X / check, pills, counters, end card | local compositor | $0 | readable and exact |
| Subtitles | local (ASS burned by ffmpeg) + `.srt` sidecar | $0 | |
| SFX and music beds | local (synthesised in code) | $0 | original, no licence to track |
| Mix, loudness, mux | local: `tools/edit/mix.py` | $0 | |
| QA | cheap screens, then a reviewer on flagged frames ([QA.md](QA.md)) | ~$0.10-0.60 | |

---

## 2. The compositor layer stack

One script draws every output frame from the bottom up. Each layer reads the shot plan (`plan.json`: shots, source
frames, camera keys, and **events in shot time**: `glow_knee: 1.44`, `check: 1.76`), so moving a cue is a number edit
and a re-render, never a new generation.

| # | Layer | Notes |
|---|---|---|
| 1 | Source drawing | a frame of a paid clip or an approved still, chosen per output frame by the plan |
| 2 | Code camera | a crop/zoom of the source into 1080x1920; zoom eased in log space so a push feels even; **stepped on twos** to match the character |
| 3 | State treatment | WRONG = X-ray ghost of the character (background shows through, outlines glow); RIGHT = the solid drawing |
| 4 | Glows | region masks (from the matte plus colour segmentation inside it: trousers, boots, body) tinted and bloomed; red pulsing on the fault, green on the fix |
| 5 | Arrows and badges | fat rounded arrows (in for the fault, out for the fix), a big red X or green check that pops on the word |
| 6 | Cue pill | one short label top-middle ("1 KNEES OUT"), the same place in every shot |
| 7 | Counters / checklists | rep dots, a checklist that ticks on the bottom of each rep |
| 8 | End card | gradient fade, card with the takeaways, the character fading in at full size |
| 9 | Subtitles | burned last by ffmpeg from an `.ass` file (section 6) |
| 10 | Overlays that sit above everything | a breath pacer, a watermark; applied to the finished cut |

**Keep the matte locked to the picture.** Stack the picture and its matte side by side (`[picture | matte]`, one
video), run the timing pass (`onestwos.py`) on the stack, then split it again in the compositor. The held drawing and
its matte are then always the same frame, so a glow never slides off a held pose.

**Resumable stages.** Build as stages (`timeline`, `timing`, `compose`, `audio`, `mux`, `deliver`), each writing
`STATUS.json`, each skippable. A subtitle fix re-runs `mux` in seconds, not the whole build.

---

## 3. Reps and holds from one clip

Generate the move **once**, top to bottom (standing to the bottom of the squat), as a ~3 s clip. Then build every rep
in code: forward, hold, the same frames reversed, hold.

```
python tools/edit/reps.py down.mp4 -o reps.mp4 --reps 3 --down 0.65 --up 0.6 \
       --bottom-hold 0.25 --top-hold 0.2 --skip 36-50 --twos --report reps.json
```

- **Pace is set by the voice,** not the model. `--down/--up` re-time by frame index (every frame is a real drawing,
  none are interpolated).
- **Write down the defect frames and never use them.** A squash that goes off-model at frames 36-50 is skipped with
  `--skip 36-50`; the ramp jumps over it. In the real piece one clip was used only as frames 0-29 plus its end frame.
- **Alive holds, not dead freezes.** A held pose that drifts between two or three neighbouring drawings, one drawing
  every 3 frames, reads as a breath. A frozen frame reads as a bug (and the frozen-frame check flags it).
- **`reps.json`** gives each rep's down / bottom / up / top time, so the checklist tick, the "ding" and the next cue
  land on the bottom of every rep.
- **Reverse is free but not always right.** Playing "down" backwards as "up" works for squats, push-ups, dips and
  presses. It doesn't work for a move with follow-through (a throw, a jump landing) or a face that changes expression on
  the way down: the reversed expression reads wrong. Check the reversed half on its own.

---

## 4. Angle coverage with start/end clips

Teaching a move needs several angles (front for knees, side for back angle, three-quarter for both). Don't generate
long multi-angle shots. Per angle:

1. Make two stills from the locked sheets: the **top pose** and the **bottom pose**, same camera ([KEYFRAMES.md](KEYFRAMES.md)).
2. Gate them together: every angle's pair on one **angle sheet**, side by side. **Show the angle sheet to the director
   before animating anything.** A wrong costume detail or a mis-drawn foot costs $0.14 to fix here and $0.47 plus a
   review per angle later.
3. One image-to-video per angle with **start frame = top, end frame = bottom**, ~3 s. About $0.47 each (Kling 4.0 at
   $0.157/s; see [ROUTING.md](ROUTING.md)). The model only invents the in-betweens of two approved drawings, so there
   is very little room to drift.
4. Everything else comes from those clips: reps (section 3), holds, the ghost version (the same clip with a code
   treatment), push-ins (section 5).

Five angle clips covered the whole 25 s piece: about **$2.35** of motion.

---

## 5. Code tricks that replace paid generations

**The fault drawn in code: a body tilt.** To show "folding forward" without generating a wrong-form clip, take the
correct bottom pose from the side and rotate only the upper body about the hips:

1. From the matte, split the character at the belt line (the top of the trousers mask).
2. Clear the old upper body with the clean empty plate, using a dilated mask (the outline sits just outside the matte).
3. Rotate the upper body about a pivot at the front of the hips, by `angle x ease(t)` (0 to 35 degrees over ~0.9 s).
4. Close the wedge that opens behind the hips by sweeping the lower band of the body through the in-between angles in
   flat body colour (stacking real outlines there looks like a smear).
5. Legs and feet stay exactly as drawn.

Shown as the ghost, next to the solid upright pose in the same framing, it is a clean minimal pair: the only difference
is the thing being taught.

**Push-ins.** A crop rectangle per key (`full`, `knees`, `feet`), interpolated with an ease, width in log space,
stepped on twos. One crop shared between the "wrong" and "right" shots makes a match cut: same framing, only the form
changes. Source resolution limits how far you can push: a 720x1280 clip pushed 1.4x into a 1080x1920 frame is about
2x upscale, the practical limit for a flat cel look.

**Glows.** `tools/edit/glow.py` (mask from a PNG, a per-frame matte folder, or a colour key; pulsing 0.75-1.0 at
~1.6 Hz; a tint inside plus an outer bloom). Colour segmentation inside the matte gives you body parts for free
(trousers, boots, the round body), but only inside the matte: see the warning in [REVIEW.md](REVIEW.md) about grass
read as green trousers.

**The X-ray ghost.** For the wrong form: inpaint the background under the character (half resolution, Telea), mix it
42/58 with a pale fill driven by the drawing's own luminance, turn the dark outlines into glowing light lines, add a rim
glow. `glow.py --ghost` does it. A ghost reads as "this is the mistake" without making the character look hurt or
punished.

**Rain, light, weather.** Particles and gradients drawn per frame (streaks with motion blur, a soft light shaft, a
vignette) on ones. Cheaper and more controllable than asking a model for weather, and they never interact with the
character's drawing.

**SFX synthesised in code.** Each is a few lines of numpy, placed at the event times from the plan:

| Sound | Recipe |
|---|---|
| X / wrong buzz | two short tones 330 Hz then 247 Hz (0.16 s apart), part square wave, 5 ms attack, 0.12 s decay |
| check / correct ding | 880 Hz then 1318.5 Hz (0.09 s apart) with 2nd and 3rd harmonics, 0.22 s decay |
| whoosh (cut, push-in, rep down/up) | white noise through a one-pole low-pass whose cutoff sweeps up or down, sin^2 envelope |
| thud | sine falling 135 Hz to 45 Hz over ~0.1 s, 0.07 s decay |
| tick (counters) | 1760 Hz + 2640 Hz, 25 ms decay |
| end sting | C-E-G-C arpeggio (523-1046 Hz), 70 ms apart, 0.35 s decay |

These suit explainer UI beats. For character foley (landings sized by the character, doors, surfaces, nature beds),
spotted automatically from the animation's event tracks and gated for sync and loudness, see [SOUND.md](SOUND.md).

**Music beds composed in code.** A short original loop (drums from noise and sine kicks, a bass line, a pad), rendered
once per style and reused across a series, with a known start offset for the groove. No licence, no claims, and the
same bed under every episode of a series is a brand cue.

---

## 6. Subtitles, pills and the safe area

| Element | Where (9x16, 1080x1920) | Rules |
|---|---|---|
| Subtitles | centred, **~70% of frame height** (y ~1344) | 1-3 words at a time; break on punctuation, after 3 words or past ~16 characters; pop in (70% -> 112% -> 100% over 0.17 s); the spoken word highlighted in the accent colour; scaled down to fit 68% of the width |
| Cue pill | top-middle, y ~165 | one short label, at least 50 px type (36 px was unreadable on a phone) |
| Big X / check | centre, y ~470 | pops on the word that names the fault or the fix |
| Safe area | x 6-85%, y 6-75% | the right ~15% and bottom ~25% carry the platform's buttons and caption |

- Subtitles stay in the same place on every shot. **On a clash, move the callout, never the subtitle.**
- Subtitles never cover the key prop or the body part being taught. Check that geometrically (prop track vs subtitle
  box): a yes/no vision judge can't see a prop that the words are hiding.
- When the end card already carries the same words, stop the burned-in subtitles as the card lands (a QA screen
  reads the echo as duplicate text); keep them in the `.srt`.
- Always ship a `captions.srt` sidecar for the platform's own caption track.

---

## 7. Assembly with ffmpeg

**Compositor to video:** pipe raw frames straight into the encoder (no PNG folders).

```python
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1080x1920",
                        "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "14", "-preset", "medium",
                        "-pix_fmt", "yuv420p", "picture.mp4"], stdin=subprocess.PIPE)
enc.stdin.write(frame_bgr.tobytes())   # once per frame
```

**Join clips that share codec settings** (no re-encode):

```
printf "file 'a.mp4'\nfile 'b.mp4'\n" > list.txt
ffmpeg -f concat -safe 0 -i list.txt -c copy joined.mp4
```

**Conform a model's clip** (fps, size) before the edit:

```
ffmpeg -i take.mp4 -vf "fps=24,scale=720:1280:flags=lanczos" -c:v libx264 -crf 12 -an take-24.mp4
```

**Burn subtitles** (ASS, fonts from a folder) and mux the mix in one pass:

```
ffmpeg -i picture.mp4 -i mix.wav -vf "subtitles=subs.ass:fontsdir=fonts" \
       -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -profile:v high -r 24 \
       -c:a aac -b:a 192k -ar 48000 -shortest -movflags +faststart master.mp4
```

Or keep subtitles separate and let `mix.py` do the mux (it copies the video stream):

```
python tools/edit/mix.py --video picture-subbed.mp4 --voice vo-placed.json --music bed.wav --sfx sfx.wav \
       --under 19 --duck 7.4,8.4,-9 -o master.mp4 --report mix.json
```

**Phone copy** (under ~15 MB for messaging apps) and a **cover frame**:

```
ffmpeg -i master.mp4 -vf scale=720:1280:flags=lanczos -c:v libx264 -preset medium -b:v 1100k -maxrate 1540k \
       -bufsize 2200k -pix_fmt yuv420p -c:a aac -b:a 128k -ar 48000 -movflags +faststart phone.mp4
ffmpeg -ss 3.2 -i picture.mp4 -frames:v 1 cover.png
```

Make the cover from the clean picture (no subtitles), then draw the title on it in code, in the sky or empty area, so
the subject stays clear.

---

## 8. The audio mix

The order and the numbers from the real piece:

| Stem | How | Level |
|---|---|---|
| Voice | each line's wav placed at its time in the plan, 8 ms fade in, 30 ms fade out | measured -22.3 LUFS (it sets everything else) |
| Music bed | from a chosen start offset, 0.9 s fade at the end | measured -17.0 LUFS, gain -24.3 dB, so **19 dB under the voice** |
| Ducks | music -9 dB from 0.4 s before the climax cut, back over 0.8 s | clears the room for the payoff line |
| SFX | placed at event times, fixed gains 0.22-0.7 | |
| Mix | sum, then loudnorm | **-16.0 LUFS integrated, true peak -3.9 dBTP**; final master -16.1 / -3.8 |

- **Set the music by measured loudness, not by ear or by a fixed gain.** Beds are mastered at wildly different levels;
  "19 dB under the voice's integrated loudness" gives the same balance on every piece.
- **Two-pass loudnorm.** Pass 1 measures, pass 2 applies the measured values with `linear=true`, so it is a clean gain
  change. A single pass landed about 0.6 LU low and needed a trim. `mix.py` does both passes and re-measures.
- Duck the music for a line rather than pushing the voice: pushing the voice pushes the true peak.
- **Never speed up the voice to fit a shot.** Tighten the gaps, extend or hold the shot ([VOICEOVER.md](VOICEOVER.md)).
- **Never ship a silent cut,** unless the deliverable is clean picture for a finishing team ([TIMING.md](TIMING.md)).

---

## 9. Delivery specs

| | Master | Phone copy |
|---|---|---|
| Video | H.264 High, 1080x1920, 24 fps (or the source fps), yuv420p, CRF ~16 | 720x1280, ~1.1 Mbps |
| Audio | **AAC 192k, 48 kHz, stereo** | AAC 128k, 48 kHz |
| Loudness | **-16 LUFS integrated, true peak <= -1 dBTP** | same |
| Container | mp4 with `-movflags +faststart` | same |
| Sidecars | `captions.srt`, cover image, the post text | |

**The 48 kHz lesson.** TTS and lip-sync hosts often return 32 kHz (or 22.05/24 kHz) AAC or mp3. Muxed as-is, the
cut played **silent on some phones** while it played fine on a desktop. Always re-encode the final audio to 48 kHz AAC
192k, and re-assert it after any tool that copies audio through (overlays, pacers). Check with:

```
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels -of compact master.mp4
```

---

## 10. What it cost: a real ~25-30 s explainer

| Item | Count | Cost |
|---|---|---|
| Motion: start/end image-to-video per angle | 5 x ~3 s | ~$2.35 |
| Stills: poses, angle pairs, face fixes | ~20 (mostly ~$0.02 edits, a few full keyframes) | ~$0.50 |
| Voice: every line, plus re-voices of changed lines | ~10 lines | ~$0.10-0.25 |
| QA: cheap screens on stills and cuts, confirmations | a few runs | ~$0.10-0.60 |
| Editing: reps, holds, camera, glows, ghost, tilt, pills, subtitles, SFX, music, mix, mux | everything else | **$0** |
| **Total** | | **~$3-4** |

For comparison, generating the same 25 s as finished video at $0.15-0.46/s is $4-12 per take, with every label
wrong, no way to re-time a cue, and a full re-roll for every note.

---

## 11. What we'd do differently

- **Show the angle sheet before animating.** Angles were animated before the director had seen all the start/end
  pairs side by side. A detail caught on the sheet costs a $0.14 still; caught after animation it costs the still, a
  $0.47 re-animation and another review.
- **Put intermediates on a big drive and delete them after delivery.** Lossless stacks, frame dumps and per-stage
  videos run to gigabytes per piece. They filled the system drive mid-build. Point the build at a scratch folder on
  a large drive (one environment variable), mirror only the small files (plan, timeline, captions, status) back to the
  project, and delete the scratch after delivery.
- **Write clip defects into the build, with frame numbers, the moment someone sees them.** "Frames 36-50 squash
  off-model" in a comment and a `--skip` saves re-discovering it at every review.
- **Lock the cue times to word times.** Events keyed to the voice's word timestamps (`glow on "knees"`) survive a
  re-voice; events keyed to absolute seconds don't.
- **Draw the frame index from shot boundaries in frames, not seconds.** A float boundary leaked one shot's glow onto
  the next shot's first frame.
- **Test reversed halves and colour masks on their own** before trusting them in the full cut.
