"""tally: decode blind-critic votes back to takes and print the moment's table.

    python tools/bakeoff/tally.py critic-mapping.json votes.json [--group m3] [--md]

votes.json, as you transcribe each critic's reply (letters as the critic saw them):
{
  "m3": {
    "c1": {"winner": "B", "scores": {"A": 5, "B": 7, "C": 4.5}, "fails": {"C": "five-finger hand at 4.2 s"}},
    "c2": {"winner": "A", "scores": {"A": 7, "B": 6, "C": 4}},
    "c3": {"winner": "C", "scores": {"A": 7.5, "B": 5, "C": 6.5}}
  }
}
Output per take: each critic's score, the mean, wins out of N, and any automatic-fail notes. A take that won at least
2 of 3 votes is the moment's winner; otherwise call it on the means and say it was split.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mapping", type=Path)
    ap.add_argument("votes", type=Path)
    ap.add_argument("--group")
    ap.add_argument("--md", action="store_true", help="print a markdown table")
    a = ap.parse_args(argv)
    mp = json.loads(a.mapping.read_text())
    votes = json.loads(a.votes.read_text())
    out = {}
    for g, crit in votes.items():
        if a.group and g != a.group:
            continue
        rows = {}
        for c, v in crit.items():
            m = mp[g][c]
            for letter, sc in v.get("scores", {}).items():
                r = rows.setdefault(m[letter], {"scores": [], "wins": 0, "fails": []})
                r["scores"].append(sc)
            if v.get("winner"):
                rows[m[v["winner"]]]["wins"] += 1
            for letter, why in (v.get("fails") or {}).items():
                rows[m[letter]]["fails"].append(why)
        n = len(crit)
        table = sorted(((t, sum(r["scores"]) / len(r["scores"]), r) for t, r in rows.items()), key=lambda x: -x[1])
        out[g] = [{"take": t, "scores": r["scores"], "mean": round(mean, 2), "wins": f"{r['wins']}/{n}",
                   "fails": r["fails"]} for t, mean, r in table]
        if a.md:
            print(f"\n## {g}\n\n| take | scores | mean | wins | fails |\n|---|---|---|---|---|")
            for row in out[g]:
                print(f"| {row['take']} | {' / '.join(f'{s:g}' for s in row['scores'])} | {row['mean']:.2f} | "
                      f"{row['wins']} | {'; '.join(row['fails'])} |")
    if not a.md:
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
