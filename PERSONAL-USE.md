# Personal use: animate from any reference image (2026-10)

This route is for **private, non-commercial** projects: a bedtime cartoon starring your kid, a family pet as a
character, a birthday video in a style your kid loves. The hosted "brand-safe" models often refuse a reference image
they recognise, or swap in a generic character. These routes take whatever reference you give them.

> **Read this first.** A model that doesn't refuse doesn't change the law.
> - **Other people's characters and art:** keep anything based on them private. Don't post it, sell it or monetise it.
> - **Real people:** use only your own family or people who've agreed.
> - **Voices:** never clone a real person's voice without their consent (an actor's included).
> - **Content:** no sexual or harmful content of real people, and nothing involving minors beyond innocent family
>   scenes.
> - **Terms:** check each model's licence and terms; several open-weight models are **non-commercial only**, which is
>   fine for this route.

## The route

| Step | Use | Why |
|---|---|---|
| Style and character lock | 3-6 reference images of the look you want, plus **one character sheet** made first (front, 3/4, 2 expressions) | Every later frame copies the sheet, so the characters stay consistent |
| Keyframes from any reference, hosted | **FLUX.1 Kontext [pro / max]** (image edit with a reference) or **Seedream 4.x edit**, on fal or similar | They follow a reference closely and refuse far less than GPT Image or Gemini models |
| Keyframes from any reference, no filter | **Open-weight edit models on a rented GPU:** FLUX.1 Kontext [dev], Qwen-Image-Edit (Hugging Face Jobs or Inference Endpoints, or ComfyUI on RunPod, Vast or Modal; setup in [SETUP.md](SETUP.md#hugging-face)) | No built-in refusals. Kontext dev is a **non-commercial** licence, which suits private use. About a 24 GB GPU, roughly $0.30-0.80/hr |
| Scene consistency | The master-plate method in [KEYFRAMES.md](KEYFRAMES.md): one master scene, then every shot edited from it with the sheet as a reference | Same room, same light, same characters |
| Motion | **Hailuo 2.3** for simple cartoon acting; **Kling** or **Wan** when hands hold props (see [ROUTING.md](ROUTING.md)) | Image-to-video from your approved keyframe |
| Open-weight motion, no filter | **Wan 2.x image-to-video** self-hosted (Apache-2.0), e.g. as an HF Job ([SETUP.md](SETUP.md#self-hosting-open-weights-inference-endpoints-and-jobs)) | Runs on a rented 24-80 GB GPU; slower, but nothing is refused. Read each model card's licence first ([SETUP.md](SETUP.md#licences-when-you-self-host)) |
| Cartoon timing | Finish on twos with `tools/timing/onestwos.py` | Reads as hand-drawn animation, not smooth AI motion |

## Voices (no cloning of real people)

| Need | Use |
|---|---|
| A character voice that fits a vibe ("cheerful young Australian girl", "gruff friendly dad") | **Stock voices** in ElevenLabs' voice library, filtered by age, accent and style, or ElevenLabs **Voice Design** (describe the voice in words) |
| Free and fully local | **Kokoro TTS** (Apache-2.0, 82M parameters, runs on a CPU) |
| Your own family's voices | Clone **only with that person's consent**, e.g. a parent narrating; ElevenLabs Instant Voice Clone |
| Lip-sync | Generate the audio first, then a lip-sync model or MiniMax H3 hosted ref-to-video with the audio (see [ROUTING.md](ROUTING.md)) |

## A good default for a kid's personal cartoon
1. **The kid's own characters:** turn your kid (or the dog) into a character in the style they love, rather than
   copying an existing show's characters. Kids love seeing themselves, and it keeps the project clearly your own.
2. **The sheet:** one character sheet first. Approve it, then generate every keyframe from it.
3. **Gate the stills:** run `tools/continuity/continuity.py --stills` on all the keyframes before spending on video.
4. **Animate:** animate, finish on twos, and add stock or Kokoro voices plus music.
