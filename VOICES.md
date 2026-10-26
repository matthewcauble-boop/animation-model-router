# Voices: design, train and deliver character voices (2026-10)

How to get a consistent voice for each character without cloning anyone who hasn't agreed: design one from a
description, or train an open model on a voice you have the right to use, then deliver it so the picture and the
mouth follow the audio.

## The consent rule (read this first)

**Train or clone only a voice you have the right to use:**
- your own voice;
- a family member or friend who agrees (get it in writing if the result will be public);
- a hired voice actor who signs off on cloning and on where the voice will be used;
- a voice you **designed** (Route A), which belongs to no real person.

**Never clone a specific real person without their consent, actors included.** Don't prompt for "sounds like" a
named actor or a named character either: describe the voice (age, accent, energy, texture) instead. Some open
models' licences add their own rules on top (see the table in Route B), and several hosts require you to confirm
consent before they will clone. Not legal advice.

## Which route

| Need | Route | Cost | Consistency |
|---|---|---|---|
| A new character voice, fast | **A: design from a description**, then lock it by cloning your own master take | cents per line, hosted | good once locked to a master take |
| Your own, a family member's or a hired actor's voice | **B: train a local open model** on their recordings | free on a home GPU, or a few dollars of rented GPU | best: the same model every time |
| Free, offline scratch VO | Kokoro stock voices (no cloning) | $0 on a CPU | fixed stock voices |

---

## Route A: design a voice from a description

Write the voice as a casting note: **age, accent, energy, texture, pace.** For example: "a cheerful six-year-old
with an Australian accent, bright and a little breathy, fast when excited", or "a gruff but friendly dad, low and
warm, slow and amused".

| Option | Where | Notes |
|---|---|---|
| ElevenLabs Voice Design | ElevenLabs app or API | describe the voice, get several previews, save the one you like to your library |
| Qwen3-TTS voice design | fal `fal-ai/qwen-3-tts/voice-design/1.7b`; open weights [Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign) (Apache-2.0) | the open weights also run locally or on [HF Jobs](SETUP.md#self-hosting-open-weights-inference-endpoints-and-jobs) |
| MiniMax voice design | fal `fal-ai/minimax/voice-design` | hosted only |

(fal ids checked on fal's free model list on 2026-10-25; see [SETUP.md](SETUP.md#fal) to call them.)

**Keep the voice consistent.** A designed voice drifts a little every time you regenerate it from the description.
So:
1. Generate a **master take**: 30-60 s of the voice reading varied lines (calm, excited, a question, a whisper).
2. Approve it, and keep the file with the character's sheet.
3. Make every later line by **cloning that master take** (it's your own designed voice, so you have the right):
   fal `fal-ai/qwen-3-tts/clone-voice/1.7b` (or `/0.6b`, cheaper), `fal-ai/minimax/voice-clone`, or ElevenLabs
   Instant Voice Clone. For full control, **train on it** (Route B).

**Our lesson, child voices:** for a little kid's voice, a **designed child voice plus kid-speak spelling** beat every
stock voice we tried. Write the line the way a small child says it ("Dere's a monstew undew my bed!") in the script
the voice model reads, and keep the **correct spelling in the subtitles** ("There's a monster under my bed!").
**Pitch-shifting an adult voice up sounded bad** (chipmunk formants, adult phrasing); don't.

---

## Route B: train a local open-source voice model

Use this for a voice you have the rights to: yours, a consenting family member's, a hired actor's, or your own
designed master take from Route A.

### The models (licences checked on each repo and model card, 2026-10-25)

| Model | Code licence | Weights licence | Data needed | Strengths | Watch out for |
|---|---|---|---|---|---|
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | MIT | MIT ([lj1995/GPT-SoVITS](https://huggingface.co/lj1995/GPT-SoVITS)) | zero-shot from ~5 s; few-shot fine-tune from **~1 min**; best with **10-30 min** | the easiest real fine-tune; web UI does slicing, transcripts and training; runs on 8-12 GB | the UI moves fast between versions; follow the version's own guide |
| [F5-TTS](https://github.com/SWivid/F5-TTS) | MIT | **CC-BY-NC-4.0** for the released checkpoints ([SWivid/F5-TTS](https://huggingface.co/SWivid/F5-TTS)) | zero-shot from a short clip; fine-tune on hours | very natural prosody | **non-commercial weights**: private use only unless you train your own base |
| [Chatterbox](https://github.com/resemble-ai/chatterbox) | MIT | MIT ([ResembleAI/chatterbox](https://huggingface.co/ResembleAI/chatterbox)) | zero-shot from a ~10 s clip | an **emotion/exaggeration control**; commercial-friendly | outputs carry an inaudible watermark (by design); zero-shot, so pick the reference clip carefully |
| [XTTS-v2](https://huggingface.co/coqui/XTTS-v2) | MPL-2.0 ([coqui-ai/TTS](https://github.com/coqui-ai/TTS)) | **Coqui Public Model License: non-commercial** | zero-shot from ~6 s; fine-tune on 10+ min | many languages | non-commercial, and the company that sold commercial licences has closed |
| [StyleTTS2](https://github.com/yl4579/StyleTTS2) | MIT | pre-trained models carry a rule: tell listeners the speech is synthesised unless you have the speaker's permission | fine-tune on 1+ hour | expressive, high quality | heavier to train (plan on a 24 GB+ GPU); the best phonemizer is GPL |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | Apache-2.0 | Apache-2.0 | none | tiny, fast, runs on a CPU, commercial-friendly | **cannot clone**: stock voices only |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | Apache-2.0 | Apache-2.0 | zero-shot clone from a short clip; voice design from text | design and clone in one family | newer; check the card for fine-tuning support |

**Rules of thumb:** a non-commercial weights licence covers everything you make with it, LoRAs and fine-tunes
included; for anything public or paid, pick MIT or Apache weights (GPT-SoVITS, Chatterbox, Kokoro, Qwen3-TTS).
Keep the licence file next to the trained model.

### 1. Record

- **Room:** quiet and soft (a closet of clothes beats a bare room). No fridge hum, no fan, no echo.
- **Format:** 44.1 or 48 kHz, 24-bit WAV, mono. No noise suppression or auto-gain on the recorder.
- **Mic:** the same mic at the same distance (a hand-span, about 15-20 cm) for every session, a pop filter, slightly
  off-axis.
- **Script list:** 100-300 varied lines: statements, questions, exclamations, whispers, laughs, the character's
  catch-phrases, numbers and the words the scripts will use most. Read them **in the character's emotions** (happy,
  scared, sleepy, excited), not one flat read. Keep the script file: it is the first draft of your transcripts.
- **Amount:** 1 minute for a few-shot GPT-SoVITS model; 10-30 minutes for a solid fine-tune; more is better only if
  it is clean.

### 2. Clean

| Step | How |
|---|---|
| Denoise | a light pass only (e.g. a denoiser such as DeepFilterNet or RNNoise, or your editor's noise reduction); heavy denoising makes the model sound underwater |
| Trim silences | cut long pauses to about 0.3 s; keep breaths that are natural |
| Normalise loudness | the same level for every clip (e.g. `ffmpeg -af loudnorm=I=-20:TP=-2`) |
| Split | 3-15 s clips, cut at pauses, one sentence or phrase each (GPT-SoVITS's slicer does this) |
| Transcribe | Whisper or faster-whisper, then **check every transcript by hand** against the script; a wrong transcript teaches wrong sounds |
| Reject | clips with clipping, background noise, mouth clicks or a misread |

Write the dataset as `wavs/0001.wav ...` plus a `metadata.csv` / `.list` file in the format your model's trainer
asks for (`path|speaker|language|text` for GPT-SoVITS).

### 3. Train

| Where | Rough needs and times (2026-10, measure on a short test) |
|---|---|
| Home GPU, GPT-SoVITS | 8-12 GB VRAM; a 10-30 min dataset fine-tunes in roughly 10-40 min on an RTX 3060-4090 class card |
| Home GPU, XTTS-v2 fine-tune | 12-16 GB VRAM; about an hour for 10-30 min of data |
| Home GPU, F5-TTS / StyleTTS2 fine-tune | 24 GB+ VRAM recommended; several hours |
| Zero-shot (Chatterbox, Qwen3-TTS clone) | no training; 4-8 GB VRAM to run, or a CPU (slowly) |
| No GPU | rent one by the hour, or run the trainer as a Hugging Face Job: see [SETUP.md](SETUP.md#self-hosting-open-weights-inference-endpoints-and-jobs) |

Stop early: save checkpoints every few epochs and listen. Over-trained voice models get metallic or start to mumble.
Keep the best checkpoint, not the last one.

### 4. Inference settings

- **Reference clip** (for zero-shot and for GPT-SoVITS's prompt audio): 3-10 s, clean, in the **emotion of the line**
  you are generating. Keep a small set of reference clips per emotion.
- **Temperature / top-p:** lower (about 0.6-0.8) for consistency; higher for livelier reads, then pick the best take.
- **Speed:** leave at 1.0. Change the pace with punctuation and wording, not a speed slider.
- **Seeds:** fix the seed while tuning settings; then make 3 takes per line and pick.
- **Text:** spell numbers and abbreviations out as spoken; use kid-speak spelling for child voices (subtitles keep the
  correct spelling).

### 5. Evaluate

- **Blind A/B against the target:** mix the trained voice's takes with real clips of the target voice (or the
  approved master take), shuffle, and have people who don't know which is which pick the real one, or pick the
  better one. Same method as the blind critics in [QA.md](QA.md#blind-critics). If listeners can't tell, ship it.
- **Word error rate:** transcribe every generated line with Whisper or faster-whisper and compare with the script.
  A WER above a few percent means mumbling or skipped words; regenerate those lines.
- **Consistency:** play 10 lines from different sessions back to back. The voice should sound like one person.

---

## Delivery: getting voices onto the picture

| Rule | Why |
|---|---|
| **Write scripts with natural connective words** ("okay, so", "and then", "wait, look") | lines with no glue sound read, not spoken |
| **Use emotion tags where the model supports them** (bracketed tags such as `[laughs]`, `[whispers]`, `[excited]` in models that document them; Chatterbox's exaggeration control) | the read carries the acting, and the animation follows it |
| **Never speed a take up to fit a cut** | it sounds rushed and chipmunky; hold the shot longer instead ([LESSONS.md](LESSONS.md#1-on-screen-must-match-whats-said)) |
| **Generate the audio first, then lip-sync to it** | the voice sets the timing; the picture follows |
| **Keep each lip-synced take locked to its audio** | never re-time, trim or swap the audio under a lip-synced take; if a line changes, re-sync it |
| **Mouths on ones** inside lip-synced shots | stepping a synced mouth on twos makes it lag the consonants; time the body on twos if you want, but leave the mouth layer on ones |
| Check sync and meaning with `tools/vosync/` | each line must land on the picture it describes |

See also: [PERSONAL-USE.md](PERSONAL-USE.md) (voices for private projects), [ROUTING.md](ROUTING.md) (lip-sync
models), [SETUP.md](SETUP.md) (calling fal and Hugging Face).
