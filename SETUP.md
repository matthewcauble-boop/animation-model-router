# Setup: fal and Hugging Face routes (2026-10)

Two ways to run the models in [ROUTING.md](ROUTING.md): **hosted on fal** (pay per call, fast, no GPU) and **Hugging
Face** (free or cheap Spaces, or your own rented GPU for open weights). Model ids below were checked against fal's
public model list on 2026-10-25; prices are fal's list prices on that date. Check both before you spend.

## Which route when

| Route | Good for | Cost | Speed | Watch out for |
|---|---|---|---|---|
| **Hosted fal** | Production: every model in the routing table, one key, one API shape | pay per call (table below) | seconds to a few minutes; no queue for GPUs | the account locks when the balance runs out; prices differ by host |
| **HF Spaces** (Gradio) | Trying an open model before paying; one-off private jobs | free, or a PRO account ($9/mo) for more ZeroGPU time | queues; a ZeroGPU task is time-limited | the API changes without notice; the Space's and the model's licences both apply |
| **HF Inference Providers** | One HF token for several hosted providers | pay per call through HF (PRO includes monthly credit) | like the provider | not every model is on every provider |
| **HF Inference Endpoints / Jobs** (self-host) | Open weights you control: no refusals, your own LoRA, batch jobs | GPU-hour rates (roughly $0.80-6/hr by GPU) | cold start minutes; then fast | **you** must check the weights' licence and territory |

## fal

### Account and key

1. Make an account at fal.ai, add a payment method, then **Dashboard -> Keys -> Add key**. Give it a name you will
   recognise in the dashboard.
2. Put it in the environment as `FAL_KEY`, or in a git-ignored `.env` file in your working directory (`FAL_KEY=...`).
   The tools here read either. **Never commit it, never paste it into a prompt, never print it.**
3. **Turn on auto top-up** with a monthly ceiling. When the prepaid balance runs out, fal locks the account and every
   call, even a cheap vision call, answers 403 until you top up. Every tool here stops and says so instead of
   falling back (see [LESSONS.md](LESSONS.md#8-paid-apis-lock-when-the-balance-runs-out)).

### The queue API

| Step | Call |
|---|---|
| Upload a local file | `POST https://rest.alpha.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3` with `{"file_name", "content_type"}` -> `{"upload_url", "file_url"}`; `PUT` the bytes to `upload_url`; pass `file_url` to the model |
| Submit | `POST https://queue.fal.run/<model id>` with header `Authorization: Key $FAL_KEY` and the model's arguments as JSON -> `{"request_id", "status_url", "response_url"}` |
| Poll | `GET status_url` (same header) until `"status": "COMPLETED"` (`IN_QUEUE`, `IN_PROGRESS` before that) |
| Fetch | `GET response_url` -> the output JSON with media URLs; download them (they expire) |
| Sync shortcut | `POST https://fal.run/<model id>` waits for the answer in one call: fine for fast models (vision, TTS), not for video |

Save the `request_id` before polling: if your script dies, poll the same request again instead of paying twice.

### Python client (optional)

```bash
pip install fal-client
```
```python
import fal_client                                  # reads FAL_KEY from the environment
url = fal_client.upload_file("frames/S1.png")
res = fal_client.subscribe("alibaba/wan-3.0/image-to-video",
                           arguments={"image_url": url, "prompt": "...", "duration": 6, "audio": False},
                           with_logs=False)
print(res["video"]["url"])
```

### The minimal script: `tools/fal_run.py`

Uploads, submits, polls, downloads, checks a **daily cap** before submitting, logs the spend, and stops on a lock.

```bash
# see exactly what would be sent, for $0
python tools/fal_run.py alibaba/wan-3.0/image-to-video --upload start=frames/S1.png --est 0.30 --dry-run \
  --args '{"image_url": "@start", "prompt": "Locked-off camera. ...", "duration": 6, "resolution": "1080p",
           "aspect_ratio": "9:16", "audio": false, "enable_prompt_expansion": false}'

# then for real (writes outputs/ and spend-ledger.csv)
python tools/fal_run.py alibaba/wan-3.0/image-to-video --upload start=frames/S1.png --est 0.30 --daily-cap 5 --args ...
```

For a set of takes with a ledger and a hard cap, use `tools/bakeoff/bake.py` ([BAKEOFF.md](BAKEOFF.md)).

### Endpoints for each job

Verified on fal's model list on 2026-10-25. "Cost" is fal's list price; the routing table's $/s figures come from the
same source.

| Job | Model id | Cost (list, 2026-10) | Notes |
|---|---|---|---|
| Exploring stills (cheap tier) | `openai/gpt-image-2/edit`, `quality: "low"` | about $0.036 billed at 720x1280 with 3 refs | looks, blocking, storyboard drafts, re-rolls ([ROUTING.md](ROUTING.md#0-image-tiers-pay-for-quality-only-on-frames-that-get-animated)) |
| Exploring stills, backup | `alibaba/qwen-image-3/edit` | about $0.049 billed | `enable_prompt_expansion: false`; at most 3 refs |
| Draft stills (mid tier) | `openai/gpt-image-2.5/flare/edit`, `quality: "medium"` | about $0.040 billed | same family as the finals |
| Keyframe edit (new framing or angle) | `openai/gpt-image-2.5/flare/edit` | about $0.14 a frame at high quality at 2K; $0.06-0.07 billed at 720x1280 | the keyframe winner ([KEYFRAMES.md](KEYFRAMES.md)) |
| Keyframe edit (runner-up, pose stills) | `openai/gpt-image-2/edit` | about $0.21 | |
| Same-camera coverage stills | `fal-ai/nano-banana-2.1/edit` | about $0.10 | most stable set; fakes new angles |
| Packaging with exact text | `fal-ai/nano-banana-pro/edit` | $0.15 at 2K | list every word verbatim |
| Reference edit that refuses less | `fal-ai/flux-pro/kontext` (`/max` for the bigger model) | $0.04 an image ($0.08 max) | 4 references at most |
| Reference edit that refuses less (alternative) | `fal-ai/bytedance/seedream/v4/edit` | $0.03 an image | if a model refuses the reference ([ROUTING.md](ROUTING.md#if-a-model-refuses-the-reference)) |
| Cheap open-weight edit, hosted | `fal-ai/qwen-image-edit` | $0.03 per megapixel | |
| Image-to-video, prop-light acting | `fal-ai/minimax/hailuo-2.3/standard/image-to-video` (`/pro/` for 1080p) | $0.28 / $0.49 per 6 s | first frame only |
| Image-to-video, held gesture (first + last frame) | `fal-ai/minimax/hailuo-02/pro/image-to-video` | | end frame = start frame |
| Image-to-video, close-ups and plates | `kling/v4/image-to-video` | $0.157/s | |
| Image-to-video, glove on food, thick liquids | `alibaba/wan-3.0/image-to-video` | $0.05/s | `audio: false`, `enable_prompt_expansion: false` |
| Cartoon replacing a person in footage | `alibaba/wan-3.0/reference-to-video` | about $0.05/s of output | proportion-lock prompt ([ROUTING.md](ROUTING.md#10-replace-a-real-person-in-footage-with-a-cartoon-character-cartoon-in-live-action)) |
| Full-body action with a prop | `bytedance/seedance-2.5/us/image-to-video` | about $0.46/s | the most expensive per second |
| Pose-video driven motion (skeleton retarget) | `fal-ai/wan-vace-14b/pose` | $0.08/s | takes a pose video; see lesson 3 |
| Two-shot lip-sync to your VO | `minimax/h3-max/reference-to-video` | $0.05/s | hosted only (licence, below) |
| Living hold / lip-sync from a still | `minimax/h3-max/lip-sync/image-to-video` | $0.05/s | prompt for breathing and blinks ([LESSONS.md](LESSONS.md#4-no-frozen-characters-living-holds)) |
| Lip-sync onto an existing clip | `fal-ai/sync-lipsync/v3`; `fal-ai/kling-video/lipsync/audio-to-video` | $8 per minute; about $0.014 a unit | untested in our bake-off |
| Talking still (alternative) | `veed/fabric-1.0` | $0.08/s | untested in our bake-off |
| TTS, expressive | `elevenlabs/tts/eleven-v4`; `fal-ai/elevenlabs/tts/eleven-v3` | $0.08 / $0.10 per 1,000 characters | stock or designed voices only, never a clone without consent |
| Voice design from a description | `fal-ai/qwen-3-tts/voice-design/1.7b`; `fal-ai/minimax/voice-design` | | then lock it by cloning your own master take ([VOICES.md](VOICES.md)) |
| Clone a voice you have rights to | `fal-ai/qwen-3-tts/clone-voice/1.7b` (or `/0.6b`); `fal-ai/minimax/voice-clone` | | consent first ([VOICES.md](VOICES.md#the-consent-rule-read-this-first)) |
| TTS, cheap | `fal-ai/kokoro/american-english` | $0.02 per 1,000 characters | Kokoro also runs free on a CPU |
| Matte a character or person in video | `fal-ai/sam2/video`; `fal-ai/sam-3/video` | about $0.0011 per compute second; $0.005 per 16 frames | for compositing a swapped character back over a clean plate |
| Video upscale | `fal-ai/seedvr/upscale/video`; `topaz/upscale/video/precision` | $0.001 per megapixel; about $0.01 a unit | upscale the 480p take you liked rather than re-rolling at 720p |
| Vision yes/no (QA confirmer, vosync, judge escalation) | `openrouter/router/vision` with `model: "google/gemini-3.5-flash-lite"` | about $0.001 a call | some router models need `reasoning: true` |

### Reading the real cost

Log what fal actually billed, never a hard-coded per-image estimate (ours over-reported spend by about 4x). After a
queue job completes, the result carries an `x-fal-billable-units` header; multiply it by the endpoint's `unit_price`:

```bash
curl -s -D - -o /dev/null -H "Authorization: Key $FAL_KEY" "https://queue.fal.run/<endpoint>/requests/<request_id>" | grep -i billable
curl -s -H "Authorization: Key $FAL_KEY" "https://api.fal.ai/v1/models/pricing?endpoint_id=<endpoint>"
```

`tools/fal_run.py` does this after each call and logs a correction row, so the ledger holds the bill. **Cost levers for
image edits:** every reference image is billed as input (about $0.03 for 3 on GPT image models), so use at most 3 refs
and render at 720x1280 rather than 2K; the quality setting matters less than refs and size.

To check an id or find new ones (free, no key needed for the list):

```bash
curl -s "https://api.fal.ai/v1/models?endpoint_id=alibaba/wan-3.0/image-to-video&endpoint_id=kling/v4/image-to-video"
curl -s "https://api.fal.ai/v1/models?q=lipsync&limit=25"          # search; it rate-limits fast, so go slowly
curl -s -H "Authorization: Key $FAL_KEY" "https://api.fal.ai/v1/models/pricing?endpoint_id=alibaba/wan-3.0/image-to-video"
```

## Hugging Face

### Token and account

1. Make an account at huggingface.co, then **Settings -> Access Tokens -> Create**. A **read** token is enough to
   call Spaces and download public weights; Inference Providers and Jobs need a fine-grained token with those
   permissions. Gated models (accept the licence on the model page first) need the token too.
2. Put it in the environment as `HF_TOKEN` (or a git-ignored `.env`). `huggingface_hub` and `gradio_client` read it.
3. **PRO** ($9/month in 2026-10) raises your ZeroGPU quota on Spaces (longer and more GPU tasks per day, ahead of
   free users in the queue) and includes a monthly Inference Providers credit. Worth it if you lean on Spaces.

### Calling a Space

```bash
pip install gradio_client huggingface_hub
python tools/hf_run.py owner/space-name --view                       # list endpoints and inputs first
python tools/hf_run.py owner/space-name --api /predict --inputs '["@img", "a prompt", 42]' --file img=frames/S1.png
```
```python
from gradio_client import Client, handle_file
client = Client("owner/space-name", hf_token=os.environ["HF_TOKEN"])
client.view_api()                                               # the endpoint names and argument order
out = client.predict(handle_file("frames/S1.png"), "a prompt", api_name="/predict")
```

Spaces are other people's apps: they change their API, go to sleep, or hit their GPU limit. Duplicate a Space you
depend on to your own account (and pay for its hardware) if you need it to stay put.

### Inference Providers

One HF token routes to several hosted providers (fal among them) through `huggingface_hub.InferenceClient`:

```python
from huggingface_hub import InferenceClient
c = InferenceClient(provider="fal-ai", api_key=os.environ["HF_TOKEN"])
video = c.text_to_video("a round cartoon character waves", model="<model repo id>")
```
Billing goes through HF (PRO credit first). Useful when you want one bill; fal's own API has more models and options.

### Self-hosting open weights: Inference Endpoints and Jobs

| Option | What it is | Use it for |
|---|---|---|
| **Inference Endpoints** | a dedicated, autoscaling GPU server for one model repo (or your own container) | an always-on or scale-to-zero API for an open model or your LoRA |
| **HF Jobs** | run a script or container on a rented GPU, pay per second, then it stops | batch work: a night of image edits, an eval, a LoRA training run |

```bash
pip install -U huggingface_hub
hf jobs run --flavor a10g-small python:3.12 python -c "print('hello from a GPU')"   # check flavors with: hf jobs --help
hf jobs uv run --flavor a100-large --secrets HF_TOKEN my_batch.py                   # a uv script with inline deps
```

A 24 GB GPU (A10G / L4 class) runs most open image-edit models; open video models want 48-80 GB (A100 / H100) for
reasonable speed. Measure seconds per clip on a short test before a batch.

### Licences when you self-host

Hosted APIs bundle a licence with the price. **With open weights, the model card's licence is the contract, and it
applies to you.** Read each model card before you rely on a model.

| Weights (2026-10) | Licence | What that means |
|---|---|---|
| Wan 2.x (2.1, 2.2) | Apache-2.0 | commercial use fine; keep the notice |
| FLUX.1 Kontext [dev] | FLUX.1 [dev] Non-Commercial | private and research use only; the hosted [pro]/[max] are licensed through the host |
| Qwen-Image / Qwen-Image-Edit | Apache-2.0 | commercial use fine |
| MiniMax H3 (open weights) | MiniMax H3 Community License | **its territory excludes the USA, the EU, the UK and South Korea**, and it bars using or displaying outputs outside the territory. From those places use a hosted H3 under the host's terms, never the weights |
| Body and pose models (SMPL-X, GVHMR and similar) | mostly non-commercial; YOLOv8 is AGPL | R&D only unless licensed |

Rules of thumb: territory clauses and revenue thresholds exist, and they apply to the weights wherever you rent the
GPU; a LoRA trained on non-commercial weights inherits their terms; keep the licence file next to any output you
ship. Not legal advice.

### Where this fits

- [VOICES.md](VOICES.md): voice design on fal, and training open voice models on a home GPU or an HF Job.

- [PERSONAL-USE.md](PERSONAL-USE.md): the private, open-weight route (Kontext dev, Qwen-Image-Edit, Wan 2.x) runs on
  HF Jobs or Endpoints as above, or any GPU rental.
- [ROUTING.md](ROUTING.md): production picks, all on hosted fal.
- [BAKEOFF.md](BAKEOFF.md): to compare a self-hosted model against the hosted winner, run both on the same inputs.
