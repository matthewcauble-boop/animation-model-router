"""critic_pack: anonymise and shuffle takes into one folder per blind critic.

    python tools/bakeoff/critic_pack.py GROUP --out DIR --mapping critic-mapping.json [--critics 3]
           [--refs ref1.png ref2.png] [--extra-suffix -lipsync] take1.jpg take2.jpg ...

Each critic gets DIR/GROUP-c<N>/ with take-A.jpg, take-B.jpg ... in a DIFFERENT order (seeded, reproducible), plus the
reference images as ref-1, ref-2. The letter -> take mapping is written only to --mapping, which stays with you and
never goes to a critic.

Put DIR OUTSIDE your project (a temp folder). Agent tools load project instruction files (CLAUDE.md, AGENTS.md, a
README) as soon as an agent reads a file inside the project, and those files tell the critic what the project is and
which take is "ours". That alone is enough to bias a blind vote.

--extra-suffix copies a companion file per take under the same letter (e.g. take-B-lipsync.jpg for the dense
lip-sync sheet of take B).
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("group")
    ap.add_argument("takes", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mapping", type=Path, required=True)
    ap.add_argument("--critics", type=int, default=3)
    ap.add_argument("--refs", nargs="*", type=Path, default=[])
    ap.add_argument("--extra-suffix", action="append", default=[])
    a = ap.parse_args(argv)
    mp = json.loads(a.mapping.read_text()) if a.mapping.exists() else {}
    mp[a.group] = {}
    for c in range(1, a.critics + 1):
        d = a.out / f"{a.group}-c{c}"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        for i, r in enumerate(a.refs):
            shutil.copy(r, d / f"ref-{i + 1}{r.suffix}")
        fs = list(a.takes)
        random.Random(f"{a.group}{c}").shuffle(fs)
        m = {}
        for k, f in enumerate(fs):
            letter = chr(65 + k)
            shutil.copy(f, d / f"take-{letter}{f.suffix}")
            m[letter] = f.stem
            for sx in a.extra_suffix:
                g = f.with_name(f.stem + sx + f.suffix)
                if g.exists():
                    shutil.copy(g, d / f"take-{letter}{sx}{f.suffix}")
        mp[a.group][f"c{c}"] = m
        print(d)
    a.mapping.write_text(json.dumps(mp, indent=1))


if __name__ == "__main__":
    main()
