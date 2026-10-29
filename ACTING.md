# Acting for animation: the short version

A clip can be on-model, in continuity and lit well and still feel dead, because nobody in it *thinks*. AI video
models average motion: everything evenly spaced, everyone moving at once, no pause before a decision, no weight in a
lift. [ANIMATION.md](ANIMATION.md) covers the mechanics (squash and stretch, arcs, settles, contact). This page is the
layer on top: the performance. It is a distillation in our own words, with sources so you can go to the books.

**The core rule:** a character moves because it thinks something and feels something about it. Every significant move
needs a visible thought before it, a want behind it, a pose that reads in silhouette, timing that shows its weight and a
hold that lets it land.

## Read these

| Book | What it gives you |
|---|---|
| Frank Thomas & Ollie Johnston, *The Illusion of Life: Disney Animation* (1981) | The 12 principles (ch. 3), appeal (ch. 6), character development (ch. 15), expressions and dialogue (ch. 16), acting and emotions (ch. 17) |
| Richard Williams, *The Animator's Survival Kit* (2001; expanded 2009) | Timing vs spacing, breakdowns, walks, flexibility (overlap), weight, anticipation, takes and accents, dialogue, acting |
| Ed Hooks, *Acting for Animators* (2000; 5th ed. 2023) | Seven acting concepts: thinking leads to conclusions and emotion to action, empathy, theatrical reality, acting is reacting, play an action until something changes it, start in the middle, a scene is a negotiation |
| Eric Goldberg, *Character Animation Crash Course!* (2008) | Attitude poses, layout and staging, breakdowns, squash and stretch, weight and balance, properties of matter, animating shapes (characters without limbs) |
| Hayao Miyazaki, *Starting Point 1979-1996* (2009) + *Studio Ghibli Layout Designs* (exhibition catalogue, 2008) | Ghibli's approach: the layout as each cut's blueprint, everyday effort, the deliberate pause (*ma*, from his 2002 Roger Ebert interview) |
| Optional: Keith Johnstone, *Impro* (1979); Nancy Beiman, *Prepare to Board!* (2007); Marcos Mateu-Mestre, *Framed Ink* (2010) | Status between characters; acting poses on the board; framing a gesture |

There is no single book that Disney and Ghibli animators both use. Disney's canon is Thomas & Johnston and Williams.
Ghibli trains in-house and publishes no manual, so a lot of the "Ghibli rules" you'll find online are commentary or
folklore. (Ghibli isn't "all on ones", and it isn't "computer-free".) Cite only what Miyazaki or the studio said.

## The per-beat check

For every beat (one thought) and every character on screen, write this down before any keyframe or code:

1. **Thinks / wants / feels.** A playable verb for the want ("to lift", "to show off", "to coax") and a feeling you can name. (Hooks)
2. **The obstacle.** What's in the way? The acting is the effort against it. (Hooks)
3. **The thought change.** The visible signal (the eyes move to a new target, a blink, a pause) and the action that follows it 4-12 frames later. (Hooks; Thomas & Johnston ch. 16)
4. **The key pose.** One clear line of action (a C or an S curve), weight on one side, no twinned limbs, the gesture off the body so it reads in silhouette. (Goldberg; Thomas & Johnston ch. 3)
5. **Timing.** Anticipation scaled to the action and opposite in direction, the accent frame, the hold. Ease in and out on acting moves, never into an impact. (Williams)
6. **Weight.** What's heavy, and how does the body show it: preparation, a slow start, contact on ones, a settle? (Williams, "Weight")
7. **Loose parts and life.** What drags and settles (hair, leaves, tails, cloth); what keeps a hold alive (breath, blinks, wind). (Thomas & Johnston ch. 3; Williams, "Flexibility")
8. **The others.** Listeners react, offset in time, never in lockstep, never upstaging the main action. (Hooks: acting is reacting)

## Rules that catch most problems

| Rule | Failure on AI or code takes | Source |
|---|---|---|
| Thought before action | the character just starts moving | Hooks |
| Eyes lead, then the head, then the body; head turns dip on the breakdown | a block turn; a straight-line head turn | Williams, Goldberg |
| Blinks on thought changes, 4-8 frames, never on a metronome | a dead stare, or regular blinks | practice |
| The expression holds for the beat and changes at the thought change | faces that morph several times a second | Thomas & Johnston ch. 16 |
| Asymmetry; never twins; never lockstep | mirrored arms; group landings on the same frame | Thomas & Johnston |
| Contrast in timing: fast against slow, still against moving | every move the same length and speed | Williams, "Acting" |
| Holds: 6-12 frames on a gesture, 12-24 on a reaction; living, not frozen | no hold, or a frozen frame | Thomas & Johnston ch. 3 (moving holds) |
| Weight in lifts: get set, sink, slow start, overshoot, settle; the object never floats or slides in the hands | the object rises at hand speed | Williams, "Weight"; Goldberg |
| Actions play through: pick up, carry, lower, contact, let go, settle | cut away and back with it done | everyday-effort practice (Ghibli) |
| Comedy: set-up, beat before, turn, hold on the result | the reaction before the gag; no hold | Williams, "Takes and accents" |
| A pause with life (*ma*) at the turn of the feeling | wall-to-wall motion | Miyazaki (Ebert, 2002) |

Characters with no limbs (balls, fruit, stars) act through their whole shape: squash and stretch, lean and tilt, the
eyes, the rhythm of their bounces, and the loose parts on top (Goldberg, "Animating shapes"; the flour-sack exercise in
Thomas & Johnston). A hero who must never look scared or be the butt of the joke shows effort through the body and the
timing, and keeps a pleasant, determined face.

## The acting pass (AI, code or 3D)

1. Write the beat sheet (above).
2. Make the **key poses** as stills (image edits on the master plate, or posed rig frames). Number them and give each a frame number.
3. Put them on a **pose sheet** with a timing chart per pair (frames, rate, where it eases and where it hits) and a silhouette strip. Review and approve it **before any in-betweens**.
4. Decide the **breakdowns**: the arc, which part leads, what overlaps.
5. In-betweens: start and end frame video models per key pair, one action per generation, timing in the prompt, then
   the ones-and-twos pass ([TIMING.md](TIMING.md)); or ease curves, per-character numbers and overlap springs in code.
6. Cut a **pose-only animatic** first (the keys held on their frames) and review the timing there; it's the cheapest place to fix it.
7. Review the full take, then run the cut gates ([QA.md](QA.md)).

Timing chart, frames at 24 fps (the ticks show spacing; tight ticks near a key = ease):
```
K2 (f12 crouch) -> K3 (f20 take-off)   6 f  ones   |  |  | | ||      ease out of the crouch
K3 -> K4 (f34 apex)                    14 f twos   |   |   |  | | || slow into the apex (hang)
K4 -> K5 (f44 contact)                 10 f        || |  |   |    |   fast into contact, no ease
K5 -> K6 (f56 settled)                 12 f        squash, rebound, 2 jiggles, then a living hold
```
Give the chart a matching `timing.json` for `onestwos.py` too ([TIMING.md](TIMING.md)), so the in-betweens are stepped
the way the chart says.

## Pre-flight checklist (pose sheet, animatic or cut)

A NO on a starred item is a P0: no spend on the next stage, and nothing goes to the director.

1. \* Every beat of every on-screen character has thinks / wants / feels and an obstacle written down.
2. \* **Thought before action:** every deliberate action is preceded by a visible thought signal (eyes, blink, pause) 4-12 frames earlier.
3. \* **Character locks hold in the acting:** every hard rule in the character bible (forbidden expressions, forbidden
   body parts, grounded or floating, status). Template: [docs/character-acting-bible.template.md](docs/character-acting-bible.template.md).
4. \* **Weight is shown:** every lift, carry, landing and push has preparation, a slow start for heavy things, contact on
   ones and a settle. No object floats, slides in the hands or moves without a cause.
5. \* **Actions play through:** pick up, carry, lower, contact, let go, settle; or a clean match cut on the action.
6. \* **Readable in silhouette:** every key pose names its action as a black shape, with a clear line of action.
7. Asymmetry: no twinned limbs, no lockstep characters, no simultaneous landings unless it's a marked unison beat.
8. Anticipation before every take-off and big move, scaled to it and opposite in direction.
9. Contrast in timing: fast against slow and still against moving inside each shot; no metronome moves.
10. Holds read: 6-12 f on a gesture, 12-24 f on a reaction; living, not dead; no idle hero over about 1.5 s without a story reason.
11. Ease in and out on acting moves; no slow-in into impacts.
12. Arcs on heads, hands, bodies and loose parts.
13. Overlap and follow-through on leaves, stems, manes, braids and tails: they lag and settle.
14. Eyes lead, then the head, then the body; head turns dip on the breakdown.
15. Blinks on thought changes, not on a metronome; no dead stare.
16. Expressions hold for the beat and change only at thought changes; no flicker or drift.
17. Squash and stretch keeps volume.
18. One main action at a time; secondary actions stay secondary; no gesture repeated more than once per film.
19. Comedy: set-up, beat before, turn, hold on the result.
20. At least one living pause (*ma*) at the turn of the feeling in a short; nature keeps moving through the holds.

When it passes, run the blind critic ([agents/animation-director.md](agents/animation-director.md)) with only the clip
(or pose sheet) and the character bible.

## Writing acting into AI prompts

Models don't act; they average. Put the acting in words they can follow, one beat per generation:
- Name the **thought signal and the order**: "she looks down at the stone, pauses, then bends to lift it".
- Name the **effort with the right face**: "lifts slowly with bent knees, the stone heavy, smiling with determined
  effort, not strained".
- Name the **timing**: "a short crouch, then springs up", "holds the pose for a moment, then...".
- Name the **follow-through**: "her braided mane keeps swinging after she stops".
- Lock what they invent: no extra smiles or winks before the gag, "keeps the same proportions", "no fingers", "no arms or
  legs", camera locked off.
- Then judge the **first, middle and last frames** and the contacts, not only the end frame.

## Measuring it

Most of these can be checked from per-frame tracks (from your renderer, or from masks on AI footage) or with a small
judge model answering yes/no questions per frame ([LESSONS.md](LESSONS.md#7-a-fast-judge-model-for-qa)). Starting
thresholds; fit them to your own approve/reject notes:

| Principle | Measure | Starting threshold |
|---|---|---|
| Arcs | path deviation from its chord / chord length; parabola fit while airborne | 0.05-0.30 for gestures; R^2 > 0.98 in the air |
| Ease in and out | mean step size in the first and last 20% of a move / the middle 60% | < 0.6 for acting moves; the largest step is just before a contact |
| Holds | runs with motion < 0.5% of body height per frame | 6-12 f gesture, 12-24 f reaction; a dead (frozen) hero hold > 1 s flagged |
| Volume | scale x times scale y (2D), or silhouette area against the model sheet | 1.00 ± 0.05; area ± 10% |
| Anticipation | frames moving opposite to the action just before it / the action's frames | 0.2-0.6 for hops, 0.3-1.0 for heavy lifts |
| Overlap | the lag of a loose part's angle behind the body's acceleration; the settle time after the body stops | lag 2-6 f; still moving 4-12 f after |
| Eyes lead | onset frames of eye, head and body rotation | eyes -> head 2-4 f, head -> body 2-6 f |
| Blinks | duration; the share within 3 f of a head turn or thought change; interval regularity | 4-8 f; >= 60%; interval CV > 0.3 |
| Lockstep | cross-correlation of two characters' vertical tracks, and its lag | > 0.9 at a lag < 3 f = lockstep |
| Timing contrast | fastest-to-slowest move duration within a shot | > 2 |

The full table (every principle, where its data comes from, a threshold and a judge question):
**[ACTING-MEASURES.md](ACTING-MEASURES.md)**.

## The review

Review every pose sheet, animatic and rough cut with a blind critic that sees only the clip and the character notes,
never the builder's reasoning: [agents/animation-director.md](agents/animation-director.md). Gate order on every
animatic and rough cut: story-director, then animation-director, then the cut gates ([QA.md](QA.md)).

```bash
# the strips and measurements the critic starts from (cuts, ones/twos per shot, holds, motion peaks, key triplets)
python tools/qa/actstrip.py cut.mp4 --fps 12 --overview 6 --out review/strips
```

Give it frame strips at 6-12 fps, and make it pull **24 fps bursts at every contact, anticipation and settle** before it
claims anything about them: a 12 fps strip can skip the one or two frames of a landing. It returns PASS / REVISE / FAIL,
issues with timestamps and a re-blocked key-pose plan.

### Calibrating the critic against your own calls

A critic you haven't calibrated is a guess. Do this before you let it gate anything, and again after every change to
its prompt:

1. **Collect labelled clips.** At least six, with both kinds: takes the director rejected and takes the director
   approved, with the director's one-line reason for each. More approved clips than you think: critics drift toward
   failing everything.
2. **Rename them neutrally** (`clip_a.mp4`, `clip_b.mp4`...) into a fresh folder: no version numbers, folder names, dates
   or notes. Keep the mapping in a separate file the critic never sees.
3. **Run a fresh critic per clip** with only the clip and the character bible. No history, no reasoning, no other clips.
4. **Fill the agreement table:**

   | Blind name | What it is (for you) | Director | Critic round 1 | Critic round 2 |
   |---|---|---|---|---|
   | clip_a | AI take, a character places a stone | rejected: no weight | FAIL (no weight on the stone) | FAIL |
   | clip_b | code-animated, three ball characters leave a cottage | approved | REVISE (wrong) | PASS |
   | ... | | | | |

5. **Read the disagreements, not the scores.** For each one, find the claim that caused it and check it against the
   frames. Was the claim true (the director may want to relabel) or false (the critic needs an evidence rule)?
6. **Tighten with evidence rules, never with "be nicer".** Each rule names the mistake and the proof the critic now
   needs before it can make that claim. Then re-run the whole set, not only the clip that failed.
7. **Keep a log** of each round (the table, what changed and why) and add every new verdict from the director to the set.

**Our first calibration** (six clips: four rejected, two approved, agreement 4/6 in round 1 and 5/6 in round 2). In
round 1 the critic caught every reject for the right reason (no weight on a lifted stone, a prop that morphs, a walk
through solid stones, characters overlapping each other), but it failed an approved clip on nitpicks: it demanded a
"thought" before every hop of a run, called a regular hop cycle a metronome, gave the end-of-clip hold a P1, claimed "no
contact shadow" from small frames, and claimed a skipped step from a strip that had dropped the contact frame. It also
read a same-set reframe as a background swap, because the strip tool didn't detect that kind of cut (it now does, from a
one-frame spike in changed pixels). Seven evidence rules fixed that: cuts are cuts; contact claims need a 24 fps burst;
thought before action is for decisions; cycles may be regular; end-of-clip holds are polish; absences are confirmed at
full size; weigh the whole performance. After that it agreed on five of the six, and the rejects agreed in both rounds.

The sixth was an early cut that its director had praised for the bounce, but in which the characters pass through and
stack on each other on the stairs. A later note from the same director made overlap and one-tread-at-a-time stairs hard
rules, so we left the critic failing it rather than un-learn those notes, and asked the director whether "loved" meant the
whole scene or the bounce. Six clips is a small set; the next gaps to fill are dialogue and comedy clips, and clips of
every character in the cast.
