# Run your own fair bake-off

The routing table in [ROUTING.md](ROUTING.md) will go stale. This is how to re-run it, or run it on your own cast and
style, for roughly $30-60.

## Principles

1. **One variable: the model.** Every model in a moment gets the identical start frame, references, prompt, duration,
   aspect ratio and resolution class. Turn off prompt expansion / optimisers and model audio, or the host rewrites your
   prompt per model.
2. **Test moments, not models.** "Which model is best" has no answer; "which model is best for a cartoon glove pouring
   real berries into a real pot" does. Pick the 6-8 moments your productions actually contain.
3. **Use your real inputs.** Your characters, your set, your voice track. A model that is great on its demo reel can be
   last on a flat 2D character in a photoreal kitchen.
4. **Blind, fresh, plural judges.** Three fresh critics per moment, shuffled letters per critic, contact sheets copied
   outside the project. See [QA.md](QA.md).
5. **Automatic fails are written down first.** Decide before you look: e.g. fingers on a gloved character, extra or
   missing limbs, a design swap (eye colour, gloves), a prop that vanishes. An automatic fail caps the score.
6. **Ledger every request.** Model, endpoint, request id, estimated cost, prompt, output path. You will want to know what
   a winner cost and exactly what it was asked.
7. **Fix the inputs when every take fails the same way.** In one test every model was marked down for the same three
   things (floor props in the start frame, an off-model detail in the source art, a motion that started mid-lift). That
   is a start-frame problem, not a model problem: fix the start frame and re-run before naming a winner.
8. **Run it as a detached, resumable job** so an interrupted agent or a closed laptop doesn't lose or double-pay for takes.
9. **Date the results.** Models change monthly.

## Suggested moments

| id | Moment | Start frame | What to judge |
|---|---|---|---|
| m1 | Talking two-shot, lip-synced to your VO | the locked two-shot + character sheets + the real VO | turn-taking (listener's mouth shut), mouth shapes, on-model, gloves |
| m2 | Full-body action with a prop | a clean action-sheet pose, prop already in hand | prop stays attached, limbs intact, real squash and stretch |
| m3 | Expressive reaction close-up | a close-up keyframe | acting, squash and stretch, on-model at the peak expression |
| m4 | Cartoon hand + real food (overhead) | a top-down still, full bowl, near-empty pan | the hand grips, the volumes match, the cartoon stays flat |
| m5 | Food hero (pour, drizzle, peel) | a real food still | physics, locked camera, the source stays in frame |
| m6 | Character on a real plate | a code composite with a contact shadow | feet planted, shadow stays, plate stays real |
| m7 | Stills: new pose; packaging with exact text | character sheets; the flat label | on-model; every word exact |
| kf | Scene keyframes: 6 shots of one scene | master frame + empty plate + sheets + pose cards | same set, same props, same scale, new angles really new |

## Steps

```
bakeoff/
  inputs/            start frames, sheets, VO (yours)
  jobs.json          every take (copy tools/bakeoff/examples/jobs.example.json)
  takes/<moment>/    outputs (written by bake.py)
  sheets/            contact sheets (sheet.py)
  work/              request/result JSON, STATUS.json, log
  ledger.csv         every request and its estimated cost
  critic-mapping.json, votes.json, critic-log.md
```

1. **Write `jobs.json`.** One job per (moment, model). Copy the prompt verbatim across a moment. Give each job a
   `price` from the host's pricing page so the caps work.
2. **Dry run:** `python tools/bakeoff/bake.py bakeoff/jobs.json --dry-run` lists every take and the estimated total.
3. **Run detached** (Windows, no console window):
   `powershell -File tools/common/launch_detached.ps1 -Script tools/bakeoff/bake.py -Args "bakeoff/jobs.json --hard-cap 60" -Log bakeoff/work/launch.log`.
   On macOS/Linux: `nohup python tools/bakeoff/bake.py bakeoff/jobs.json > bakeoff/work/launch.log 2>&1 &`.
   Watch `work/STATUS.json`. A restart resumes: finished takes are skipped, submitted ones are polled, not re-paid.
4. **Contact sheets:** `python tools/bakeoff/sheet.py takes bakeoff` (12 frames per video take, plus a stacked sheet per
   moment). Keyframe sets: `sheet.py strip`. Lip-sync: `sheet.py dense ... --labels speakers.json`.
5. **Optional cheap pre-screen:** `frameqa.py take.mp4 --every 1 --no-ocr` per take, so obvious glitches are logged
   before critics spend attention.
6. **Pack for critics:** `python tools/bakeoff/critic_pack.py m3 bakeoff/sheets/m3-*.jpg --out <temp dir outside the
   project> --mapping bakeoff/critic-mapping.json --refs inputs/char-a-sheet.png inputs/char-b-sheet.png`.
7. **Run 3 fresh critics per moment** with the prompt below. Transcribe their letters and scores into `votes.json`.
8. **Tally:** `python tools/bakeoff/tally.py bakeoff/critic-mapping.json bakeoff/votes.json --md >> bakeoff/critic-log.md`.
9. **Write the routing row:** winner, runner-up, scores and wins, settings, the prompt, the reference recipe, cost per
   second, and every failure mode the critics named. Date it.

## Critic prompt (template)

Give the critic nothing but this text and the folder of anonymised files.

```
You are judging takes from an AI animation test. The folder contains take-A.jpg, take-B.jpg, ... (each is a
contact sheet: 12 frames spread evenly over a 6-second clip, timestamps in yellow) and ref-1, ref-2 (the official
character designs).

The shot brief: <one or two sentences: what happens in the shot>.

Automatic fails (cap the take at 3/10): <e.g. the gloved character shows fingers or a thumb; extra or missing
limbs; a character's design changes (eye colour, gloves, outfit); the prop vanishes or floats free>.

For every take: score it out of 10 for how well it delivers the brief while staying on-model against the reference
designs, list any automatic fail with the timestamp, and give its single biggest flaw. Then rank all takes and name
the winner. Judge only what is drawn; flat cartoon style is intended.
```

For a lip-sync moment add: "Each take also has take-X-lipsync.jpg, frames every 0.5 s stamped with who is really
speaking in the audio. Judge whether only the speaking character's mouth moves."

## Critic log (template)

```markdown
## Moment m3: expressive close-up, belly laugh (6 models)
| take | scores | mean | wins |
|---|---|---|---|
| **Model X** | 7 / 7 / 7.5 | **7.17** | **3/3** |
| Model Y | 6.5 / 5 / 6.5 | 6.00 | |

- Model X: real squash-wide / stretch-tall beats. Flaw: the peak grin becomes clenched separate teeth (off-model).
- Model Y: big mouth, then snaps to a neutral smile with no squash.
- Shared start-frame problems (fix before re-running): none.
```

## Ledger columns

`time, provider, moment, take_id, model, endpoint, request_id, cost_usd, cost_basis, seconds, output, url, prompt`
(`bake.py` writes it). Costs are estimates from list prices; reconcile against the provider's invoice.

## When a host runs dry mid-test

It happens (one test lost its fal balance two-thirds of the way through). Either top up and resume (the runner skips
finished takes), or move the remaining takes to another host that serves the same model, and **note the host change
in the log**: the same model name on two hosts can differ in defaults, resolution and price.
