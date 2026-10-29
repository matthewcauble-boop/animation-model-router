"""frozen_check: everything that must not move, did not move (the gate after ambient.py or any 2D motion pass).

    python tools/blender/frozen_check.py SRC OUT MOTION MASKPASS [--report frozen.md] [--fallback mask.png] [--tol 2]
      SRC       the source renders (a folder of f_####.png, one still PNG, or a JSON {frame: path})
      OUT       the frames after the motion pass (f_####.png)
      MOTION    the motion masks the pass wrote (m_####.png: where it was allowed to change pixels)
      MASKPASS  ambient_masks.py output (a folder of m_####.png, or one PNG for a locked shot)

For every frame, pixels OUTSIDE the motion masks (dilated 2 px) must equal the source within --tol levels. It also
counts the path pixels (blue in the mask pass) and everything that is not lawn, water or path (steps, buildings, props,
characters) that changed. Any changed frozen pixel is a FAIL (exit 1). Light-only changes (shimmer, glints) are
allowed only inside the motion masks. Needs numpy + opencv-python-headless.
"""
import argparse, glob, json, os, sys

import cv2
import numpy as np


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gate: pixels outside the motion masks are unchanged from the source render.")
    ap.add_argument("src"); ap.add_argument("out"); ap.add_argument("motion"); ap.add_argument("maskpass")
    ap.add_argument("--report"); ap.add_argument("--fallback", help="mask-pass PNG to use when a frame has none")
    ap.add_argument("--tol", type=int, default=2)
    a = ap.parse_args(argv)
    srcs = json.load(open(a.src)) if a.src.endswith(".json") else None
    outs = sorted(glob.glob(os.path.join(a.out, "f_*.png")))

    def src_of(o):
        if srcs: return srcs[str(int(os.path.basename(o)[2:6]))]
        return a.src if os.path.isfile(a.src) else os.path.join(a.src, os.path.basename(o))

    def mpass(f):
        p = a.maskpass if a.maskpass.endswith(".png") else os.path.join(a.maskpass, f"m_{f:04d}.png")
        if not os.path.exists(p) and a.fallback: p = a.fallback
        m = cv2.imread(p); b, g, r = (m[..., i].astype(int) for i in range(3))
        return (b > 235) & (r < 20) & (g < 20), (r > 235) & (g < 20) & (b < 20), (g > 235) & (r < 20) & (b < 20)

    rows, worst, fails = [], (0, None), 0
    for o in outs:
        f = int(os.path.basename(o)[2:6])
        A = cv2.imread(src_of(o)).astype(int); B = cv2.imread(o).astype(int)
        mm = cv2.imread(os.path.join(a.motion, f"m_{f:04d}.png"), 0)
        allow = cv2.dilate((mm > 0).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) if mm is not None else np.zeros(A.shape[:2], bool)
        d = np.abs(A - B).max(2) > a.tol
        path, lawn, water = mpass(f)
        frozen = d & ~allow
        rows.append((f, int(frozen.sum()), int((frozen & path).sum()), int((frozen & ~path & ~lawn & ~water).sum()), int((d & path).sum())))
        if frozen.any(): fails += 1
        if frozen.sum() > worst[0]: worst = (int(frozen.sum()), f)
    ok = fails == 0 and bool(outs)
    L = [f"# frozen check: {a.out}", "",
         f"- **Verdict:** {'PASS' if ok else 'FAIL'}: {fails} of {len(rows)} frames have frozen pixels that changed"
         + (f" (worst {worst[0]} px at f{worst[1]})" if worst[1] else ""),
         f"- Path pixels changed outside the motion masks: {sum(r[2] for r in rows)}; steps / buildings / props: {sum(r[3] for r in rows)}",
         f"- Path pixels changed at all (motes drifting over them included): {sum(r[4] for r in rows)} px over {len(rows)} frames", "",
         f"Tolerance: {a.tol} of 255 levels. Motion masks dilated 2 px."]
    txt = "\n".join(L); print(txt)
    if a.report: open(a.report, "w", encoding="utf-8").write(txt + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
