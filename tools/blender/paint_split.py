"""paint_split: repaint the lawn and the path as two separate image edits, so the path outline can't move.

A one-pass repaint ("repaint the lawn and the path") redraws the path's outline too, and its stones then land on grass
when the painting is projected back onto the real path geometry. Split it:
  edit 1 (ground): the render with the PATH filled flat magenta -> "paint plain lawn through the magenta";
  edit 2 (path):   the render with EVERYTHING BUT the path flat magenta -> "fill exactly the non-magenta area".
Then strip whatever magenta (and its pink fringe) survives and refill those pixels from valid neighbours.

    python tools/blender/paint_split.py inputs  --src P_src.png --mask P_mask.png --out work/bw/paint/P
    #   -> P_in_ground.png, P_in_path.png   (send each to the image-edit model with your style plate; see BLENDER-WORLD.md)
    python tools/blender/paint_split.py textures --src P_src.png --mask P_mask.png \
           --ground-paint P_paint_ground.png --path-paint P_paint_path.png --out work/bw/paint/P
    #   -> P_terrain.png, P_path.png (projector textures for lawnproj.py) and P_check.jpg (src | composite)

The mask is the flat-colour pass from setup_projection.py: ground (lawn) magenta, path cyan by default.
Needs numpy + opencv-python-headless.
"""
import argparse, os, sys

import cv2
import numpy as np

MAG = np.array([255, 0, 255], np.uint8)          # BGR == RGB for magenta


def hex_bgr(h):
    h = h.lstrip("#"); r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4)); return np.array([b, g, r], int)


def colour_mask(img, bgr, tol=60):
    return (np.abs(img.astype(int) - bgr).max(2) <= tol)


def magenta_like(img):
    """Magenta and its anti-aliased pink / purple fringe in a repaint."""
    x = img.astype(int); b, g, r = x[..., 0], x[..., 1], x[..., 2]
    return ((r - g) > 45) & ((b - g) > 30) & (b > 70)


def fill_from(img, keep, iters=400):
    """Grow the kept pixels outward: each new pixel = the mean of its already-valid neighbours (never samples holes)."""
    out = img.astype(np.float32); valid = keep.astype(np.float32); out[~keep] = 0
    k = np.ones((3, 3), np.float32)
    for _ in range(iters):
        if valid.min() > 0: break
        sm = cv2.filter2D(out * valid[..., None], -1, k); cnt = cv2.filter2D(valid, -1, k)
        grow = (valid == 0) & (cnt > 0)
        out[grow] = sm[grow] / cnt[grow][:, None]; valid[grow] = 1
    return np.clip(out, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description="Two-edit lawn/path repaint: make the masked inputs, then the projector textures.")
    ap.add_argument("mode", choices=["inputs", "textures"])
    ap.add_argument("--src", required=True, help="the structure render from the projector (P_src.png)")
    ap.add_argument("--mask", required=True, help="the flat-colour mask pass (P_mask.png)")
    ap.add_argument("--ground-colour", default="#ff00ff"); ap.add_argument("--path-colour", default="#00ffff")
    ap.add_argument("--ground-paint"); ap.add_argument("--path-paint")
    ap.add_argument("--out", required=True, help="output prefix, e.g. work/bw/paint/A")
    a = ap.parse_args()
    src = cv2.imread(a.src); m = cv2.imread(a.mask)
    if src is None or m is None: sys.exit("cannot read --src or --mask")
    H, W = src.shape[:2]; m = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
    G = colour_mask(m, hex_bgr(a.ground_colour)); P = colour_mask(m, hex_bgr(a.path_colour))
    P = cv2.morphologyEx(P.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)).astype(bool)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    if not P.any(): print("warning: no path pixels in the mask (check --path-colour)")
    if a.mode == "inputs":
        g = src.copy(); g[cv2.dilate(P.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)] = MAG
        p = src.copy(); p[~P] = MAG
        cv2.imwrite(a.out + "_in_ground.png", g); cv2.imwrite(a.out + "_in_path.png", p)
        print("wrote", a.out + "_in_ground.png", a.out + "_in_path.png", f"(ground {G.mean():.1%}, path {P.mean():.1%} of the frame)")
        return
    if not (a.ground_paint and a.path_paint): ap.error("textures needs --ground-paint and --path-paint")
    t = cv2.resize(cv2.imread(a.ground_paint), (W, H), interpolation=cv2.INTER_LANCZOS4)
    bad = cv2.dilate(magenta_like(t).astype(np.uint8), np.ones((9, 9), np.uint8))
    if bad.any(): t = cv2.inpaint(t, bad, 7, cv2.INPAINT_TELEA)
    p = cv2.resize(cv2.imread(a.path_paint), (W, H), interpolation=cv2.INTER_LANCZOS4)
    good = P & ~cv2.dilate(magenta_like(p).astype(np.uint8), np.ones((11, 11), np.uint8)).astype(bool)
    print(f"path pixels kept {good.sum() / max(1, P.sum()):.1%}; ground pixels refilled {int(bad.sum())}")
    p = fill_from(p, good)            # outside the path too, so the projector's bilinear edges never sample grass
    cv2.imwrite(a.out + "_terrain.png", t); cv2.imwrite(a.out + "_path.png", p)
    comp = src.copy(); comp[G] = t[G]; comp[P] = p[P]
    sc = 720 / W
    cv2.imwrite(a.out + "_check.jpg", np.hstack([cv2.resize(x, (720, int(H * sc))) for x in (src, comp)]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print("wrote", a.out + "_terrain.png", a.out + "_path.png", a.out + "_check.jpg")


if __name__ == "__main__":
    main()
