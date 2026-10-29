"""rgba_from_bw: straight-alpha RGBA frames from two renders of the same animation, one over black and one over white.

    python tools/blender/rgba_from_bw.py --black frames_on_black/ --white frames_on_white/ --out rgba/red/

Any 2D animator that can only draw over a plate (tools/edit/bounce.py with a black and then a white plate image, a
compositor, a paint program) gives you the character AND its soft contact shadow as RGBA this way:
alpha = 1 - (white - black), colour = black / alpha. Render one character per run, so each gets its own card.
Frames pair by file name; output f_0001.png ... in the same order. Needs numpy + opencv-python-headless.
"""
import argparse, os, sys

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description="RGBA (straight alpha) from renders over black and over white.")
    ap.add_argument("--black", required=True); ap.add_argument("--white", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    names = sorted(f for f in os.listdir(a.black) if f.lower().endswith((".png", ".jpg")))
    if not names: sys.exit("no frames in --black")
    os.makedirs(a.out, exist_ok=True)
    for i, n in enumerate(names, 1):
        b = cv2.imread(os.path.join(a.black, n)).astype(np.float32) / 255
        w = cv2.imread(os.path.join(a.white, n)).astype(np.float32) / 255
        al = np.clip(1 - (w - b).mean(2), 0, 1)
        col = np.where(al[..., None] > 1e-3, b / np.maximum(al[..., None], 1e-3), 0)
        rgba = (np.dstack([np.clip(col, 0, 1), al]) * 255 + 0.5).astype(np.uint8)       # BGRA for OpenCV
        cv2.imwrite(os.path.join(a.out, f"f_{i:04d}.png"), rgba)
    print("wrote", len(names), "frames to", a.out)


if __name__ == "__main__":
    main()
