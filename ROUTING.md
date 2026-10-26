# Routing: which model for which moment

**Dated 2026-10.** Video and image models change every few weeks. Treat every winner here as "the winner of a
fair test on that date", not a law. When a new version lands, re-run the moment with the same inputs (see
[BAKEOFF.md](BAKEOFF.md)) and update the row.

**Where the numbers come from.** One bake-off: every model in a moment got the identical start frame, references and
prompt. Three fresh, blind critics scored each take out of 10 from anonymised contact sheets (see [QA.md](QA.md),
blind critics). Scores below are critic means; "3/3" means all three critics picked it first. Automatic fails were
fingers on a gloved character, extra or missing limbs, and design swaps. Total spend for the whole bake-off was about
$55.

**The cast used in the tests** (so the failure modes make sense):
- **Character A:** a round cartoon fruit hero with big oval eyes, a leaf, big muscular arms, a belt and trousers.
- **Character B:** a cartoon unicorn who wears round boxing gloves and never has fingers.
- Both are flat 2D cel characters with bold black outlines, usually placed in a photoreal set.

Model ids are given as fal.ai endpoints (pay per call) and, where tested, Higgsfield model names (credit plans).
Prices are list prices seen in 2026-10; check the provider before you spend.

---

## The quick table

| Moment | Winner (mean /10, wins) | Runner-up | Avoid |
|---|---|---|---|
| Scene keyframes (every shot of a scene as a still) | **GPT Image 2.5 high** (7.1 over 2 rounds) | GPT Image 2 high (6.8); Nano Banana 2.1 for same-camera shots only (6.25) | Nano Banana Pro (4.3), FLUX Kontext (3.5), "harmonize a paste-up" (1.7) |
| New on-model pose still | **GPT Image 2 high** (8.0, 3/3) | Seedream 5 Pro / FLUX Kontext Max (5.3) | Nano Banana 2.1 (put two versions in one image) |
| Package / label mockup with exact text | **Nano Banana Pro** (8.0) | Nano Banana 2.1 (7.8), Seedream 5 Pro (7.7), GPT Image 2 (7.5) | FLUX.2 Max (3.8), FLUX Kontext Max (3.3) |
| Talking two-shot, lip-synced to your own VO | **MiniMax H3 Max reference-to-video, hosted** (7.3, 3/3) | Seedance 2.0 reference + audio (6.0) | LTX-2.5 audio-to-video (cut short), Wan 3.0 / Seedance 2.5 ref + audio (4.3) |
| Full-body action holding a prop | **Seedance 2.5** for the gloved character (6.3, 3/3); **Kling 4.0 / Wan 3.0** for the round hero (5.7-5.8) | Kling 4.0 | Hailuo 2.3 (2.3-2.7: the prop floats free), Veo 3.1 Fast (design swaps) |
| Expressive reaction close-up | **Kling 4.0** (7.2, 3/3) | Seedance 2.5 (6.0) | Happy Horse 1.1 (4.0) |
| Cartoon hand/glove handling real food or props (overhead) | **Wan 3.0** (6.5, 2/3) | Happy Horse 1.1 (5.8), Kling 4.0 (5.7) | Hailuo 2.3 (3.0), Veo 3.1 Fast (the glove vanishes) |
| Food hero: thick liquid (honey, syrup) | **Wan 3.0** (7.5, 3/3) | Hailuo 2.3 Standard (6.2) | Veo (jelly blob), Happy Horse (CG rings) |
| Food hero: pours and peels | **Hailuo 2.3 Standard** (won 2/3 vs Seedance 2.5) | Seedance 2.5 (glossier, but the camera drifts) | |
| A cartoon character placed on a real (or code) plate | **Kling 4.0** (3/3 vs Hailuo, 7.2 vs 5.0) | Hailuo 2.3 | |
| Replace a person in real footage with a cartoon | **Wan 3.0 reference-to-video** + a proportion-lock prompt | a fine-tuned open model, or a specialised replace-object model for painterly styles | whole-frame "omni edit" models (they repaint the plate) |
| Prop-light cartoon acting, joy, on-model faces | **Hailuo 2.3** (house default by the director's eye) | Kling 4.0 | |
| Numbers, words, labels, diagrams, subtitles | **Code** (your motion-graphics engine) | | any video model |

---

## 1. Scene keyframes

Covered in depth in [KEYFRAMES.md](KEYFRAMES.md). The short version:

- **Winner: GPT Image 2.5, quality high, 2k, 9:16.** fal `openai/gpt-image-2.5/flare/edit` (`quality: high`) or
  Higgsfield `gpt_image_2_5 --quality high --resolution 2k --aspect_ratio 9:16`. About **$0.14 a frame** (2.75
  Higgsfield credits).
- **Runner-up: GPT Image 2 high.** fal `openai/gpt-image-2/edit`, about $0.21; Higgsfield `gpt_image_2`, 6.5 credits
  (about $0.33).
- **Nano Banana 2.1** (`thinking_level high`, 2k) keeps the set the most pixel-stable of all, but it does not really move
  the camera: its "close-ups" scale the characters up on an unchanged plate. Use it for **same-camera coverage** (pose
  changes and reactions at the master framing). Use GPT Image 2.5 for a closer framing, a new angle or a top-down insert.
- **Nano Banana Pro: not for scene keyframes.** It reused the master camera when asked for a new one, and in one take
  moved Character B's gloves onto Character A. It is still the best at printed text (section 3).
- **FLUX Kontext** takes only 4 references, so it has to drop the empty plate; it scored 3.5.
- **Never "harmonize" a paste-up** (exact art pasted on the plate, then an image model told to clean it): Nano Banana
  Pro hallucinated photo-studio tripods and umbrellas into the kitchen.
- **Reference recipe (5 images, this order, every shot):** master keyframe, empty plate of the same camera, character A
  sheet, character B sheet, a pose card for this shot.
- **Failure modes:** "points" draws a finger on a gloved character (8 of 8 methods); an open "presenting" glove still
  comes back as a mitten with a thumb; a requested new angle silently reuses the master camera.

## 2. New on-model pose still

- **Winner: GPT Image 2 high** (8.0, 3/3). fal `openai/gpt-image-2/edit`, `quality: high`, about $0.21.
- **References:** the official character sheets only.
- **Prompt template:**
  ```
  <Character A> and <Character B> stand side by side on a plain white background, both full body, feet visible:
  <pose for A>; <pose for B>. Use the exact same character designs, line style, colours and proportions as the
  reference images: flat 2D cartoon, bold black outlines, flat colours. <Character B> wears her round boxing gloves
  on both hands, no fingers. No text.
  ```
- **Failure modes:** thin arms on a muscular character (add "huge rounded biceps like the reference"); Seedream and
  Kontext drew knuckle or finger lines on gloves; FLUX.2 Max refused a harmless character prompt as a false content flag.

## 3. Package or label mockup with exact text

- **Winner: Nano Banana Pro edit.** fal `fal-ai/nano-banana-pro/edit`, `resolution: 2K`, about $0.15.
- **References:** the flat label artwork as a PNG.
- **Prompt:** describe the pack shape and **list every word on the label verbatim**: "Reproduce every word on the label
  exactly and legibly: WORD ONE, WORD TWO, NET 8 FL OZ (237 mL)."
- **Failure modes:** an invented gibberish nutrition panel on the side panel (crop it, paint it out, or ask for "plain
  white side panels"). FLUX.2 Max added a second wordmark; FLUX Kontext Max garbled the volume line. The top four all
  got the front text perfect.

## 4. Talking two-shot, lip-synced to your own voice track

- **Winner: MiniMax H3 Max reference-to-video, hosted** (7.3, 3/3). fal `minimax/h3-max/reference-to-video`:
  - `image_url` = the locked two-shot frame (start frame)
  - `reference_image_urls` = [character A sheet, character B sheet]
  - `reference_audio_urls` = [the scene's real VO, one file with every line]
  - `duration` = audio seconds, `resolution: "768P"`, `aspect_ratio: "9:16"`, `prompt_expansion_mode: "balanced"`
  - **$0.05/s, so $0.40 for 8 s.** The runner-up cost about $2.40 for the same shot.
- **Prompt:** a fixed scene head, then **timed beats** per line ("from 0.4 to 2.6 seconds Character A talks to Character
  B, ..."), then: "Only the character who is speaking moves their mouth." plus the gloves line.
- **Why it won:** turn-taking. The listener's mouth stays shut.
- **Failure modes:** the listener's mouth opens about 0.3 s early in the gap before their line (trim, or retake); a
  closing line mumbled through a narrow teeth slit (ask for "mouth wide open on every word" on that beat); the
  no-prompt H3 lip-sync endpoint drew a five-finger hand.
- **Runner-up / licence-clean fallback: Seedance 2.0 reference + audio** (6.0). The two-shot recipe:
  - `reference_images` = [the locked frame, character A sheet, character B sheet] plus `reference_audios` = the scene's
    real voice lines. **Seedance cannot take a start frame and audio together**, so the locked frame goes in as a
    reference, not a start frame.
  - Generate at 720p, then **scale and crop the result back to the locked framing** in the edit, so every two-shot in
    the episode lines up.
  - About $0.30/s on fal at 720p.
- **Licence (check this yourself, not legal advice).** The MiniMax H3 *open-weights* community licence, as read in
  2026-10, excludes the USA, EU, UK and South Korea from its territory and bars using or displaying outputs outside
  it. Hosted H3 through MiniMax's own API or a partner host is reportedly offered under the host's commercial terms.
  So: hosted only, never self-hosted weights, and get the host's terms in writing before a commercial launch.
- **Not yet tested:** silent Hailuo animation plus a separate lip-sync pass (sync-lipsync v3, Kling lip-sync).

## 5. Full-body character action with a prop (squat, lift, jump)

- **Gloved character: Seedance 2.5 image-to-video.** fal `bytedance/seedance-2.5/us/image-to-video`, `duration "6"`,
  720p, 9:16, `generate_audio false`. About **$2.77 per 6 s**, the most expensive per second.
- **Round hero: Kling 4.0 image-to-video.** fal `kling/v4/image-to-video`, `duration 6`, 1080p, $0.157/s; or Higgsfield
  `kling4_0 --mode image-to-video`, 6 credits per 6 s, **the cheapest good option**. Wan 3.0 i2v tied (`audio false`,
  `enable_prompt_expansion false`, $0.05/s).
- **Prompt:** one action described as beats ("dips, drives up, twice, holds and grins"), then the **LOCK line**:
  "Keep the character exactly on-model: same design, colours, proportions and line style as the first frame, no extra
  limbs, no morphing. Locked-off camera. No text." plus any character rule (gloves).
- **Start frame rules (every critic marked every take down for these):**
  - cut it from a clean **action/pose sheet**, not a busy promo illustration (those carry floor props and off-model
    details such as a different mane);
  - no loose props on the floor;
  - **the prop is already in the hands in frame 0**; the motion starts at rest, not mid-lift.
- **Failure modes:** the prop floats free of the hands (Hailuo, Happy Horse); a limb lets go and swells (Hailuo); design
  swaps such as white gloves or blue eyes (Veo 3.1 Fast). Every take scored 6.3 or less, so make 2 takes and pick.

## 6. Expressive reaction close-up

- **Winner: Kling 4.0 i2v** (7.2, 3/3), from a close-up keyframe made per [KEYFRAMES.md](KEYFRAMES.md).
- **Prompt:** "bursts into a huge belly laugh, mouth wide open, his whole round body squashes down and stretches up
  with each laugh, shoulders bouncing, then he opens his eyes and grins at the camera. Big, bouncy cartoon squash and
  stretch, real character acting." plus LOCK.
- **Failure mode:** the peak grin turns into a clenched row of separate teeth (off-model). Add "keep his official open
  grin, never clenched teeth".
- **Alternatives:** Seedance 2.5 for subtler acting (6.0). Hailuo 2.3 gives a big mouth but no squash and stretch, then
  snaps to a neutral smile.

## 7. Cartoon hand or glove handling real food or props (overhead)

- **Start still:** Nano Banana 2.1 edit with refs [character sheet, a real food still]. Nano Banana Pro ignored
  "top-down"; GPT Image 2 also works. **Make the start still with a near-empty pan and a full bowl** so the pour reads.
- **Video: Wan 3.0 i2v.** fal `alibaba/wan-3.0/image-to-video`, `duration 6`, 1080p, 9:16, `audio false`,
  `enable_prompt_expansion false`. **$0.30 per 6 s.**
- **Prompt:** "Locked-off top-down shot. The cartoon purple star boxing glove keeps tipping the glass bowl and the frozen
  berries pour out and tumble into the steel saucepan ... The glove stays a flat 2D cartoon with a bold black outline
  and no fingers; the pot, berries and counter stay photoreal."
- **Why it won:** the only take where the pan fills and the bowl visibly empties.
- **Failure modes:** the glove rests on the bowl instead of gripping it; the bowl stays full while food keeps arriving
  (Hailuo); the glove vanishes and the bowl flies off (Veo).

## 8. Food hero shots

- **Thick liquids (honey, syrup, caramel): Wan 3.0 i2v** (7.5, 3/3): the thickest folding ribbon and a growing pool.
- **Pours and peels: Hailuo 2.3 Standard.** fal `fal-ai/minimax/hailuo-2.3/standard/image-to-video`, `duration "6"`,
  `prompt_optimizer false`, **$0.28**. Hailuo 2.3 Pro costs $0.49 and was not better.
- **Start stills:** Nano Banana 2 / 2.1 food stills.
- **Prompt:** "Locked-off tripod macro, no camera shake." plus real-physics words: slow, viscous, folding, pooling. Add
  "Nothing holds the pan, no hands" if nothing should.
- **Failure modes:** camera drift lets the source leave the frame (Seedance; say "locked-off" twice); concentric CG
  rings (Happy Horse); jelly blobs (Veo).

## 9. A cartoon character on a real (or code-drawn) plate

- **Start frame: a code composite, not a model render.** Cut the exact character art out (flood-fill the white
  background), scale it, set it on the plate and draw a soft blurred contact-shadow ellipse under the feet. Zero drift,
  zero cost.
- **Video: Kling 4.0 i2v.** Higgsfield `kling4_0 --mode image-to-video --duration 6 --aspect_ratio 9:16 --resolution
  1080p`, 6 credits.
- **Prompt:** the action in order ("waves three friendly swings, then puts that fist on his hip"), "feet stay planted on
  the sand and his soft shadow stays under his feet", "the beach is real, he stays a flat cartoon", plus LOCK.
- **Failure modes:** angry brows or a clenched grin at the end (add "keeps his friendly open grin"); with Hailuo the
  hip arm melted into a lump and it skipped the action order.
- **Not yet tested here:** Wan 3.0 and the reference-to-video modes.

## 10. Replace a real person in footage with a cartoon character ("cartoon in live action")

From a separate series of blind tests (scores out of 25, 3 critics a shot).

- **Default: Wan 3.0 reference-to-video** (fal `alibaba/wan-3.0/reference-to-video`, about $0.05/s of output plus input;
  audio off, prompt expansion off; run at 480p, 6 s for previews). Mean 19.8/25, against 19.0 for a specialised
  replace-object model at about 2.5x the price, and 16.0 for a self-hosted open model.
- **Reference: one clean FRONT crop** of the character, padded to the performer's aspect ratio. A multi-view turnaround
  sheet made models draw 2-4 copies of the character, or grow a second body.
- **Prompt template (the "proportion lock", +1.0 over the previous wording):**
  ```
  Replace X with the cartoon character in @Image 1. Copy X's exact motion and timing frame by frame; add no gestures
  or poses they don't make. Keep the character's exact body proportions from @Image 1, never slimmer or taller.
  {BUILD line} Same size, position and facing as X, exactly one copy. {prop line} Don't change the background, sky,
  lighting or camera.
  ```
- **BUILD-line rules:** name width and mass ("barrel-chested", "belly wider than his shoulders", "gloves as big as his
  head"). Say what stays compact, never what is long ("long thin legs" made a character lanky). Never give heights or
  head counts. Never describe parts the front view hides (a "tail" line grew a dinosaur tail). Never tell it to drop a
  prop (a character lost his satchel). **No style line** (it cost 1-2 points every time).
- **Where it fails:** round or wide mascots get drawn taller and slimmer; quadrupeds and limbless blobs fail whatever
  the prompt says (route them elsewhere or don't offer them); people who are small, at the frame edge or only in part
  of the clip need a fallback model.
- **Proportion stretch (measure it):** motion-copy swaps pull a cartoon toward the performer's build: long legs,
  slim arms, taller and thinner. Box the body and the legs separately and compare the leg/body height ratio in code
  with the character sheet's (`tools/judge/`, proportion pack). In one test the sheet measured 0.80, a plain swap
  1.41, and the **same swap anchored on an on-model first frame** (an image-edit still in the performer's starting
  pose, gated first) 0.86. That anchor is the first fix; keyframes per position plus image-to-video is the second (on
  model, but you lose the exact motion). A skeleton retarget needs a model that takes a pose video (Wan VACE pose,
  `fal-ai/wan-vace-14b/pose`); a stick-figure video fed to a generic motion-control model came back as a stick
  figure. See [LESSONS.md](LESSONS.md#3-motion-copy-swaps-stretch-cartoon-proportions).
- **Poses get flattened too:** the swap redraws limbs on the character's own build and can erase pose differences
  (five grips at one hand width). Check named positions in frames; fix with one keyframe per position.
- **Fallbacks:** a specialised replace-object model (e.g. Higgsfield's) for soft or painterly styles and hero talking
  close-ups (+1-2 there); a self-hosted open animate model (Apache-2.0) when the hosted one keeps redrawing stocky
  proportions.
- **Never:** whole-frame "omni edit" models for compositing (they repaint the plate, 1.7/5); a "remove object" pass to
  make a clean plate (build the plate yourself).
- **Resolution tiers are separate generations, not sharper copies.** A 480p preview can move better than the 720p take
  of the same prompt. Judge the preview on motion first; if it is good, upscale *that* take (Real-ESRGAN anime model on
  the character only) instead of paying for a higher tier.
- **Finish in the edit:** matte the character back over the clean plate, put it on twos, add a contact shadow and
  matched light. See [TIMING.md](TIMING.md).
- **Source footage:** adults, open-licence or self-shot clips only; credit CC BY-SA sources.

## 11. Prop-light cartoon acting (the house default)

- **Hailuo 2.3** (fal Standard $0.28 / Pro $0.49 per 6 s, or Higgsfield 6 credits). The director picked it over Wan 3.0
  and Seedance 2.5 on the same shot: "real animation with character expression and joy".
- **Its weaknesses are known, so route around them:** props (they float or smear), cartoon-hand-plus-real-food, and
  characters on real plates all lost in the bake-off (sections 5, 7, 9).
- **Keep props few and simple**: no juggling, no flying clutter.
- **It takes a first frame only,** so the start frame carries all the composition; acting is prompted.
- **For a held gesture or a limb-risk shot,** use a first-and-last-frame mode (Hailuo 02 Pro) with the end frame set to
  the start frame.
- **Finish on twos in the edit** with the sharpest drawing per hold, which hides its fast-motion smear (see
  [TIMING.md](TIMING.md)).

## 12. Code, not a model: numbers, words, labels, diagrams

Use a code motion-graphics layer (HyperFrames, Remotion, Canvas, your own engine) whenever the beat's job is
**information that must be exact**. It costs $0, is deterministic, re-times to the voice track and never drifts.
**Never ask a video model to draw numbers, words, labels or diagrams.**

| Beat | Code trick |
|---|---|
| A number that must be right | a counter that ticks fast, slams to its final value, a stamp hits, the screen shakes |
| A threshold or percentage | a bar or tub that fills to exactly the legal line, with a ruler tick and the rule's year |
| Fine print | a magnifier glides in, the key word is highlighted in a pill |
| Before / after | the same product under two rules, a vertical split wipe, two date pills |
| "How it's made" | an isometric machine cutaway: the part lights up when it is named, plus a big number callout |
| A myth | myth line + archival image, a NOPE! stamp and a boing, move on in 3-5 s |
| Scale | escalating "+10x" stamps over one locked scene |
| Real products | cut-out product stickers slapped onto a sunburst on the spoken word |
| Subtitles, end card, title sting | always code |

**Hand-off rule:** characters acting go to keyframes then a motion model; facts, numbers and text go to code; real
food or real places go to sections 7-9.

**Rejected: a code puppet rig for character bodies.** A rotated-rigid-piece 2D rig reached roughly 40% of the target
quality; the director's verdict was that the arms "don't look like arms". Use code for graphics, never for the hero
characters' bodies. For character motion use a model from on-model references, key poses plus in-betweening, or a
human animator.

---

## Cost per second (list prices seen 2026-10)

The useful unit is **dollars per second of finished video**, because clip lengths differ. A Higgsfield credit is
estimated at about $0.05 (it depends on the plan).

| Model | fal | $/s (fal) | Higgsfield | $/s (Higgsfield, est.) |
|---|---|---|---|---|
| Hailuo 2.3 Standard 6 s (768p) | $0.28 | **0.047** | 6 credits | 0.05 |
| Hailuo 2.3 Pro 6 s (1080p) | $0.49 | 0.082 | | |
| Kling 4.0 | $0.157/s | 0.157 | 6 credits per 6 s | **0.05** |
| Wan 3.0 | $0.05/s | **0.05** | 21 credits per 6 s | 0.175 |
| MiniMax H3 Max reference (hosted) | $0.05/s | **0.05** | | |
| Seedance 2.0 720p reference + audio | about $0.30/s | 0.30 | | |
| Seedance 2.5 720p | about $0.46/s (token priced) | 0.46 | 42 credits per 6 s | 0.35 |
| Veo 3.1 Fast | $0.15/s | 0.15 | 24 credits per 6 s | 0.20 |
| Happy Horse 1.1 | $0.14/s | 0.14 | 27 credits per 6 s | 0.225 |

| Still | fal | Higgsfield |
|---|---|---|
| GPT Image 2.5 high 2k | about $0.14 | 2.75 credits |
| GPT Image 2 high | about $0.21 | 6.5 credits |
| Nano Banana Pro 2K | $0.15 | 2 credits |
| Nano Banana 2.1 2k | about $0.10 | 2 credits |

**Reading it:** the same model can be 3x cheaper on one host than another (Kling on a credit plan, Wan on fal). A
keyframe re-roll costs about $0.14; a video re-roll costs $0.30-2.80. That gap is the whole argument for gating the
stills before you animate.
