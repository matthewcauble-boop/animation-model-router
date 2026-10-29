# For AI agents: start here

Someone gave you this repo's link and wants to make short animated stories for their own family. This file tells you
how to get them going. Read it first, then follow the steps in order.

## What the person wants

Short animated episodes (10-60 s) made from **a picture they give you**: their kid's drawing, a pet, a family photo
turned into a cartoon, or a character their kid loves. The episodes are for **private family viewing**. Read
[PERSONAL-USE.md](PERSONAL-USE.md) before anything else and follow its rules:
- **Keep it private:** anything made from other people's characters is for home viewing, not for posting or selling.
- **Voices:** clone only a voice whose owner agrees, such as the parent's own (see [VOICES.md](VOICES.md)).
- **Content:** nothing sexual or harmful, ever.

## Steps

1. **Ask three things:** what picture or character to start from; who the story is for (the kid's age); and the
   person's budget per episode. A short episode usually costs a few dollars of model calls.
2. **Set up the accounts and keys** with them, using [SETUP.md](SETUP.md):
   - a fal.ai key (`FAL_KEY`), which covers most images, video and voices;
   - optionally a Hugging Face token (`HF_TOKEN`) for open-weight models;
   - keys go in environment variables or a git-ignored `.env`, never in files you commit;
   - install the tools' Python needs with `pip install -r requirements.txt`, plus ffmpeg.
3. **Lock the character first:** make one character sheet from their picture (front, 3/4, two expressions) and get
   their OK. Every later frame copies this sheet. See [KEYFRAMES.md](KEYFRAMES.md).
4. **Write a tiny script with them:** 3-8 shots, one action per shot, and the lines each character says.
5. **Make every shot as a still** from one master scene plus the sheet. Show the stills, fix anything off-model,
   then make a storyboard sheet from them (`tools/storyboard/sheet.py`: arrows for motion, camera moves with their
   end frames, eyelines, timing) and run the thirds check (`tools/storyboard/thirds.py --backend manual` is free).
   Show the sheet and get a yes before animating; see [STORYBOARD.md](STORYBOARD.md). Then animate: see
   [ROUTING.md](ROUTING.md) for which model to use per moment. Start with
   `python tools/fal_run.py --dry-run` to show costs before spending.
6. **Score the script before recording voices** (explainers especially): run
   `python tools/explainer-critic/score.py script.txt --bible bible.json` and the blind critic in
   [agents/explainer-critic.md](agents/explainer-critic.md), then fix every P0 (no stakes, slow hook, no turn, copied
   wording). If the person admires an explainer channel, build their own bible from its captions first (captions stay
   private); otherwise use the example bible. See [EXPLAINER-CRITIC.md](EXPLAINER-CRITIC.md).
7. **Voices:** a stock or designed voice, or the parent's own voice trained per [VOICES.md](VOICES.md). Record the
   audio first, then lip-sync to it.
8. **Finish:** cartoon timing on twos ([TIMING.md](TIMING.md)), music, then run the checks in [QA.md](QA.md) and
   [LESSONS.md](LESSONS.md). Make sure what's on screen matches what's said, the characters stay on-model and nobody
   freezes. For character acting, run the blind critic in [agents/animation-director.md](agents/animation-director.md)
   with a character bible filled in from [docs/character-acting-bible.template.md](docs/character-acting-bible.template.md)
   ([ACTING.md](ACTING.md)). Show the person the result and ask what to change.
9. **Optional, for a set that recurs across many shots:** build it once in Blender and paint it
   ([BLENDER-WORLD.md](BLENDER-WORLD.md)); it needs Blender installed and is slower to set up, but every shot agrees.

## Rules of thumb

- **Before spending:** show stills before animating, and a cost estimate before any paid call. Keep a running total
  against their budget.
- **Keep it small:** one shot at a time, with the person picking takes. Don't batch-generate a whole episode.
- **When a paid API refuses** (402/403, a locked account), stop and tell the person instead of quietly switching
  services.
- **Their own photos:** treat photos of their kids as private. Don't upload them anywhere the person hasn't agreed to.
