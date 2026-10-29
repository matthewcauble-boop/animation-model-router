# Sound: cartoon foley placed on the animation's real events

The UI-style effects in [EDIT.md](EDIT.md) (buzz, ding, tick, whoosh) suit explainers. A character piece needs more
than that. It needs foley: the soft landing of a small round character, a door creaking open, grass, stone, fire, a
breeze. Those sounds have to land exactly on the frames where things happen.

This page covers the method:
- a licensed library;
- automatic spotting from the animation's own event tracks;
- a gate that checks sync and the mix.

It was measured on one real piece: a ~15 s vertical clip. A painted cottage world, a slow push-in, a door that swings
open, a cut to a medium, then three small fruit characters hopping down stone steps onto a lawn: 25 landings, 22
take-offs, and the door. The old soundtrack was synthesised sine "boings" over a noise bed. The new one won a blind A/B
**3-0** with fresh-context critics, for about $0.70 of generated audio.

---

## 1. The library: every sound with its source and licence

| Source | Use it for | Licence to log |
|---|---|---|
| **Generated** (text-to-SFX on a hosted model; the one used here costs **$0.002 per second**) | the bulk: footsteps, stone handling, door parts, cloth, beds | the host's commercial terms; no attribution |
| **CC0 recordings** (Freesound with the CC0 filter) | real-world beds (breeze, fire), creaks | CC0. **Re-read the licence on each sound's own page**: don't trust the search filter. The public HQ preview is enough for most foley |
| **Public-domain archives** | only from a known PD collection, after a human looks | the item's licence. **Uploader-set "Public Domain" marks are often wrong**: a search for "sound effects" on one big archive returned a TV theme song and a 1990s game soundtrack marked PD |
| **Synthesised in code** | the character's own sounds (sized bodies, squishes, small pops, accents) | yours |

**Keep a manifest.** Give every file an entry with:
- the source (URL, prompt and request id, or recipe and seed);
- the licence and the attribution text;
- the screen stats;
- accept or reject, with a reason.

Keep the full-quality library on a big drive and a few MB of picks beside the tool.

**Make 3-5+ variants of every sound.** On top of that, vary each play: about ±45 cents of pitch and ±1.5 dB of gain.
Never play the same file at the same pitch twice within 2 s.

### Screen generated candidates by measurement, not by trust

Text-to-SFX drifts. In this build:
- "Dry close foley squish" prompts came back as clicks (spectral centroid 6-9 kHz).
- "Heavy footstep" prompts came back as sub-bass booms (95-100% of energy under 150 Hz).
- About half of the one-shots bounced 2-6 times.

What worked:

1. **Start the prompt with "Cartoon foley:"** and ask for a single event. Ask for about 1 s, even for a short hit;
   very short requests drift more.
2. **Filter per sound before you screen.** Run a high-pass at 85-220 Hz on footsteps, doors and surface contacts. The
   character's body layer carries the low end.
3. **For contact sounds, trim to the main hit, then keep only the first event.** Trim at -20 dB below the peak, then
   cut 5 ms before the next re-attack, with a 15 ms fade.
4. **Reject on numbers.** Each sound has its own spectral-centroid window, a maximum share of energy below 150 Hz, and
   a maximum length. **A contact must peak within 30 ms of its onset**, or it won't land on its frame.
5. **Look at spectrogram tiles** of every candidate. Pure horizontal lines are tones, and tones read as toys or test
   beeps. Trains of vertical lines are rattles and bounces.
6. **An audio-capable LLM can describe candidates, but it's a weak witness.** It miscounted events and agreed with
   leading questions. Ask neutral questions ("describe what you hear"), and use the answers only to reject.

---

## 2. Layering a character's landing

One sound per landing reads as stock. Three short layers read as a body landing on a surface:

| Layer | What | Shaped by |
|---|---|---|
| **Body** | a soft, short, low "thup": a sine whose pitch sags about 30% over 10 ms, plus a puff of low-passed noise | the character's **mass** (pitch × mass^-0.5; bigger is lower and a bit longer), impact |
| **Wet** | a squish: 4-8 tiny resonant noise "bubbles" whose pitch falls, plus a slurpy low tail | the character's wetness, impact |
| **Surface** | grass (a muffled pat + dry blade brushes), stone (an unpitched gritty tap + a low thock), wood (three hollow modes) | the surface the animation logged |

**Avoid ringing tones on contacts.** A stone tap built from sine modes at 1.5-3 kHz came back described as a "metallic
plink / boing". The noise-shaped version reads as a tap. Even a musical accent (a kalimba pluck) needs partials and a
short decay, or it reads as a pure 1 kHz test tone. A blind critic caught exactly that.

**Take-offs get a tiny upward "fwip"** (band-passed noise sweeping up, under 0.1 s), about 15 dB under the landing.
**Rebounds out of a mini-bounce stay silent.**

---

## 3. Spotting from the tracks

The animation already knows every contact: use it, never place cues by hand.

- **Event time = the frame the contact is SHOWN on** (frame / fps). The animation's own sub-frame time can be up to a
  frame earlier.
- **Contacts come from per-frame tracks:** a character's contact flag turning on, or moving to a new contact segment,
  is a landing; turning off is a take-off.
- **Other data from the tracks:**
  - **surface, physical impact and mini-bounce flags:** taken from the animation's event log, matched within 2 frames;
  - **on-screen height:** from the track;
  - **screen x:** from the track;
  - **visible fraction:** from the track. A hidden character is "behind", so muffled and roomy.
- **Distance from on-screen size.** Take the reference height as near: d = ref_h / h. The sound loses 3.5 dB per
  doubling of distance and gets a low-pass of 16 kHz / d^0.9 (floor 4 kHz). Smaller on screen means quieter and duller.
- **Pan from screen x,** at about 75% width.
- **Measure what the tracks don't log from the picture.** A door's swing is the frame-to-frame difference in the
  doorway box while the camera is still. From that you get:
  - the latch, one frame before it moves;
  - the creak over the swing, time-stretched (granular, pitch kept) to the swing's length, its gain following the
    door's speed;
  - a small settle bump where the swing stops, plus a quieter one on the first rock back.

---

## 4. Beds that follow the picture

Beds run under the whole clip, each set per shot space:
- birds, breeze and water outside;
- the fire inside.

Settings interpolate across a cut with a 0.35 s crossfade, so the world never drops out. The old mix lost its bed at
the cut, and all three critics called that out. Fade the whole bed in over 0.6 s and out over 0.9 s.

- **Inside vs outside:** the interior fire is quiet and low-passed at 450 Hz while the door is shut. Along the measured
  door-open curve it opens to 7.5 kHz and comes up 12 dB.
- **Wind you can see is wind you hear:** take the gust curve from the same simulation that moves the grass. Here that
  was the mean blade-tip speed of the blades the shot shows. Swell the breeze bed by about 9 dB over the curve's range
  and open its low-pass from 1.8 to 6 kHz.
- **Perspective per shot:** closer to the door, the fire is +3 dB; when the waterfall is out of frame, it's -14 dB.

Normalise library beds to a fixed loudness (-30 LUFS here) so these gains mean the same thing for every bed.

---

## 5. The gate

Fail the cut (exit 1) on any of these:

| Check | Rule |
|---|---|
| every contact has a sound | each contact event has a cue |
| sync | the cue's real onset (measured on the rendered cue, -30 dB below its peak) within ±1 frame of the event |
| no cue without an event | every cue references an event |
| no sound without an event | every transient detected in the foley stem lies inside a cue |
| no double hits | no contact cue re-attacks within 14 dB of its peak after 80 ms |
| no identical repeats | not the same file at the same pitch within 2 s, and no two cues' waveforms more than 0.985 alike |
| loudness | -16 ±1 LUFS integrated |
| true peak | under -1 dBTP |
| clipping | no full-scale samples in the decoded file |
| ambience under the voice | beds at least 15 LU under the VO, when there is VO |
| format | AAC, 48 kHz, stereo, about 192 kbps, faststart |

Also warn when a percussive contact doesn't rise at least 2 dB (150 Hz-6 kHz) over the 60 ms before it in the final
mix. That means it's masked by a bed or by a simultaneous landing.

Draw a **sync sheet** for a reviewer: the final-mix waveform, the event ticks, the cue-onset ticks, orphan transients in
red, and the foley stem below.

**Master** with a linear gain to -16 LUFS. Use a soft look-ahead limiter only if the true peak would pass -1.5 dBTP.
Sparse foley is peaky, so expect 2-3 dB of limiting on the loudest hits.

---

## 6. Numbers from the piece

| | Old mix | New mix |
|---|---|---|
| landings | 3 sine "boing" variants, near-identical | body + wet + surface, about 99 cues, 0 identical repeats |
| beds | a noise bed that dropped about 20 dB at the cut | birds, gusting breeze, waterfall, door-driven fire, continuous across the cut |
| door | none | latch, speed-driven creak, settle |
| check | n/a | PASS: -16.1 LUFS, -1.7 dBTP, 29/29 contacts, max offset 1.5 ms |
| blind A/B (3 critics) | 0 | 3 |
| cost | $0 | about $0.71 of generated audio + listening calls |

**What the critics still wanted:**
- more warmth, because the bottom end was thin;
- a less busy second half, where three characters hop at once;
- no pure-tone accents.

**Performance trap:** smoothing a per-sample gain curve with `np.convolve` and a 0.35 s box kernel took 13 minutes for a
15 s clip. A cumulative-sum moving average takes milliseconds.
