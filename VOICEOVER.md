# Voice-over: one locked voice per character, line by line

This is the production workflow. For choosing, designing or training a voice (with consent), see [VOICES.md](VOICES.md).

Voice is the cheapest part of a cartoon to get right and the easiest to waste money on. The workflow that keeps it at
a few cents per piece:

1. **Lock one voice per character** in a `voice.json`: endpoint, voice, seed, settings, a style tag. Never change it
   mid-series.
2. **Write the script as a `lines.json`**, one row per spoken line, each with the shot it plays in and what must be on
   screen when it starts.
3. **Generate line by line, cached by text.** Change one word and only that line is re-voiced (a few cents). Everything
   else re-renders from the cache, free and identical.
4. **Trim the silence, never the speed.** Cut lead and trail silence; tighten gaps in the edit; never time-stretch.
5. **Place each line on its picture.** The line starts as the thing it describes appears.
6. **Check the placement in code, then look at the sheet.**
7. **Mix** with the music measured under the voice ([EDIT.md](EDIT.md#8-the-audio-mix)).
8. **Pay for lip-sync only where a mouth is big on screen** and the character is the one talking.

```
python tools/voice/lines.py lines.json --voice voice.json -o vo/ --dry-run     # what would cost money
python tools/voice/lines.py lines.json --voice voice.json -o vo/               # voice the changed lines
```

---

## 1. Lock the voice

Pick each character's voice once: render the same two lines in 4-6 candidate voices, put them in front of blind critics
or the director ([QA.md](QA.md#blind-critics)), keep the winner. Then freeze every value that changes the sound.

`tools/voice/examples/voice.example.json`:

```json
{
 "characters": {
  "host": {
   "endpoint": "elevenlabs/tts/eleven-v4",
   "params": {
    "voice": "<voice name or id from the provider's library>",
    "stability": 0.5,
    "similarity_boost": 0.75,
    "seed": 7,
    "output_format": "mp3_44100_128",
    "timestamps": true
   },
   "prefix": "[warm, relaxed]",
   "text_field": "text",
   "usd_per_1k_chars": 0.08,
   "wording_style": "short plain sentences, one cue per line, says 'you', never shouts"
  }
 }
}
```

- **`seed`** is what makes a re-voice of a changed line sound like the same performance as its neighbours. A new seed,
  stability or model version is a new voice; treat it as a casting change and re-voice the whole piece.
- **`prefix`** is a delivery tag the model reads (bracketed tags such as `[warm, relaxed]`, `[excited]`) and doesn't
  speak. It is added to every line, so the delivery stays the same across sessions. Tags are dropped from the word
  timings.
- **`wording_style`** is for the writer, not the model: a character sounds like themselves mostly because of how
  their lines are written.
- **`timestamps: true`** asks for per-character alignment, which becomes word times. Word times are what let you put
  a glow on the word "knees", split a take at a word, and place subtitles.
- **Don't imitate real actors or celebrities.** Use library voices or voices you own.
- Prices move; check the endpoint page. At ~$0.08 per 1,000 characters, a 25 s script of ~400 characters is about
  $0.03 per full pass.

---

## 2. Write `lines.json`

`tools/voice/examples/lines.example.json`:

```json
{
 "lines": [
  {"id": "H0", "character": "host", "shot": "S1", "text": "Most people squat like this. Here are three fixes.",
   "cue": "the wrong squat, knees caving in, already on screen"},
  {"id": "F1", "character": "host", "shot": "S2", "text": "One: push your knees out, right over your toes.",
   "cue": "knees glow red on 'One', the fix and a green check land on 'out'"},
  {"id": "F3", "character": "host", "shot": "S4", "text": "Three: don't fold forward. Chest up!",
   "cue": "side view; the ghost tips forward on 'don't', upright on 'Chest up'"}
 ]
}
```

- **One idea per line.** A line that names two cues has to sit over two pictures, which means it crosses a cut.
- **`cue` is the contract** between the script and the picture. The reviewer, `vosync` and the compositor all read
  it. If you can't write the cue, the line has nothing to land on.
- **Say what is on screen.** "Push your knees out" over a shot of knees going out; never "remember what I said" over a
  close-up of something else.
- **Get the script reviewed before you voice it** ([REVIEW.md](REVIEW.md)): changing a line after VO is cheap; after
  the edit is built on its word times it is not.

---

## 3. Generate line by line, cached by text

`tools/voice/lines.py`:

| Step | What happens |
|---|---|
| cache key | sha256 of endpoint + params + final text (with the prefix) |
| `--dry-run` | prints each line as `cached` or `CALL`, its characters, its estimated cost and its key; sends nothing, needs no key |
| call | fal queue: `POST https://queue.fal.run/<endpoint>`, poll, download; `FAL_KEY` from the environment or `.env` |
| `--max-cost` | refuses to start if the uncached lines would cost more (default $1) |
| `--refresh F1` | a new take of one line (the old one stays in the cache under its key) |
| output | `vo/<id>.wav` (48 kHz mono, trimmed), `vo/timings.json` (duration, trim, word times), `vo/spend.csv` |

**Re-voice only what changed.** A note on one line ("say 'both knees'") is one call, about half a cent. A full re-voice
of a 10-line piece is 3-5 cents; doing that on every note is how a voice budget triples.

**Split a take instead of re-voicing it.** When one line needs to straddle a cut ("One:" over the wrong form, "push
your knees out" over the fix), cut the wav at a word boundary using the word times and place the two parts on their
own shots. Same performance, no call.

---

## 4. Trim silence, never the speed

- `lines.py` cuts anything quieter than `--floor` (-45 dBFS) at the head and tail, keeping **0.04 s** before the first
  word and **0.12 s** after the last, with 8 ms / 30 ms fades. Word times are shifted by the same amount.
- **To hit a runtime, tighten the gaps between lines and the holds between moves.** The real piece was brought under
  its ~28 s target (it landed at 25 s) this way, with no change to the voice.
- **Never use `atempo` or any time-stretch on a voice.** Sped-up speech is the first thing viewers notice as fake, and
  it shifts every word time you placed graphics on.
- If a line is still too long for its shot, extend or hold the shot, or rewrite the line shorter and re-voice it.

---

## 5. Place every line on its picture

Matching what is said to what is shown is the rule that matters most in a teaching video. Every spoken line lands on
the picture it describes:

| Rule | Example |
|---|---|
| The line starts as its subject appears | "push your knees out" starts as the knees start to move out, not 1 s before |
| Keyed words drive the graphics | the red glow comes up on "knees", the check pops on "out" (event time = line start + word time) |
| A change cue leads the change by 0.3-0.8 s | "switch sides" is heard just before the cut to the other side, so the viewer is ready |
| No line runs past its shot | extend or hold the shot; never squeeze the voice |
| Words and on-screen text agree at every moment | no label left over from the previous beat |
| The words describe exactly what is visible | the right side, the right move, the right number |

In the compositor, write events as `line start + word time` (`glow_knee = at + word("knees").start`). Re-voicing a
line then moves its graphics with it automatically.

---

## 6. Check it

**Code first, free.** `tools/vosync/vosync.py` reads your cut plus the placed lines (a `lines.json` with start/end per line, or a `timeline.json` with `vo` and
`shots`; mark change cues with `"kind": "switch"`):

- **P0** a line crosses a cut; a line placed in a different shot from the one it was written for;
- **P1** a line starts before its cue appears or well after it, a change cue not 0.3-0.8 s ahead of the change, two
  lines overlapping.

Exit code 1 on any P0, so it can block a build.

**Then look.** It writes `vosync-<stem>/sheet.jpg`: one strip of five frames across each line, labelled with its words
and times. The reviewer must open it: code can tell a line crosses a cut, not that "left leg" is said over the right
leg. A cheap per-line vision question ("does the movement match the instruction?") can screen a long cut, but treat a
"yes" as unproven for anything left/right or mirrored ([REVIEW.md](REVIEW.md#what-judges-cannot-do)).

---

## 7. Mix rules

The full recipe is in [EDIT.md](EDIT.md#8-the-audio-mix). For voice in particular:

- The voice sets the level. The music bed sits **19 dB under the voice's integrated loudness**, measured, not set by
  ear. Duck the music (about -9 dB) for the payoff line instead of pushing the voice.
- Final mix **-16 LUFS integrated, true peak <= -1 dBTP**, two-pass loudnorm, **48 kHz AAC 192k**. TTS and lip-sync
  hosts often return 32 kHz audio, which played silent on some phones.
- `tools/edit/mix.py --voice placed.json` places the per-line wavs itself (`[{"wav": "vo/H0.wav", "at": 0.05}, ...]`).

---

## 8. Lip-sync: when to pay for it

Lip-sync is the most expensive audio-related step, and most cartoon explainers don't need it.

| Situation | Lip-sync? | Do instead |
|---|---|---|
| Narrator off screen | **no** | nothing: voice over picture |
| The character demonstrates a move while the voice instructs (workouts, how-tos) | **no** | the picture is the move; the voice is narration. The mouth can stay in its drawn expression |
| A character with no mouth, or a wordless character (a limbless ball sidekick that only squeaks) | **no** | code SFX and squash-and-stretch on the sound |
| A wide shot where the mouth is a few pixels | usually no | a code mouth: 2-3 mouth drawings switched by voice loudness, on twos |
| A talking close-up or medium two-shot, the mouth clearly visible | **yes** | a reference-to-video lip-sync model fed your real VO ([ROUTING.md](ROUTING.md#4-talking-two-shot-lip-synced-to-your-own-voice-track)) |
| A host talking straight to camera for the whole piece | yes, but only the talking shots | cut away to code graphics and demonstrations for most of the runtime; sync only the to-camera shots |

- Hosted lip-sync priced per second can bill more than the clip length (one host billed about 1.6x). Price it on the
  real invoice, not the list price.
- Lip-sync models invent: backgrounds, extra text, a hand with fingers on a gloved character. Generate the talking shot
  on a plain plate and composite it (matte, not chroma key), and run the cut gates on it.
- Feed it the **final** voice. Re-voicing a line after lip-sync means paying for the sync again.
- Re-assert **48 kHz** on anything that comes back from a lip-sync host before you mux.

---

## Lesson: check what is actually said, not just the subtitles

A trim that cuts lead silence too tightly can clip the first word. In one piece the numbered lines read "Two: ..." and
"Three: ..." in the subtitles, and the sync check passed, but the voice had lost the numbers. The sync check compares
subtitle timing with the picture; it can't hear. Two fixes:

- Write short leading words as their own sentence ("Two. Feet a bit wider...") so the TTS says them fully, and keep at
  least ~80 ms of pad before the first word when trimming.
- Transcribe every voiced line (any local speech-to-text with word timestamps) and compare it with `lines.json` before
  the mix. A missing or changed word is a P0.
