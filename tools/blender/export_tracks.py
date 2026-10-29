"""export_tracks: exact staging tracks from a Blender render with characters on depth cards, for tools/qa/staging_rules.py.

    python tools/blender/export_tracks.py --config cards.json --frames work/bw/med --clean work/bw/clean/clean.png \
           --out work/bw/check/tracks.json [--shot B --f-offset 126]
    python tools/qa/staging_rules.py --tracks work/bw/check/tracks.json --scene scene.json

For every frame and character: the silhouette (alpha of its RGBA), the part that is VISIBLE in the final render
(alpha AND "this pixel differs from the clean pass", minus the pixels of nearer characters), the contact point, contact
and hop segment from the track in cards.json. Visibility is measured from the renders, not assumed: so a jamb that hides a
character, or a card at the wrong depth, shows up in the numbers.
--clean is one still (static world) or a folder of clean frames f_0001.png ... (animated world).
--f-offset shifts frame numbers into cut-global frames (the medium starts after the wide's 126 frames, say).
Needs numpy + opencv-python-headless.
"""
import argparse, json, os, sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "qa"))
from staging_rules import rle_encode  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Per-frame character tracks (silhouette, visible part, contacts) from renders.")
    ap.add_argument("--config", required=True, help="the cards.json used by depth_cards.py")
    ap.add_argument("--frames", required=True, help="renders WITH characters (f_0001.png ...)")
    ap.add_argument("--clean", required=True, help="the clean pass: one still, or a folder of frames")
    ap.add_argument("--out", required=True); ap.add_argument("--shot", default="A")
    ap.add_argument("--f-offset", type=int, default=0); ap.add_argument("--fps", type=float, default=24)
    ap.add_argument("--thr", type=int, default=10, help="levels of difference that count as 'the character is visible here'")
    a = ap.parse_args()
    cfg = json.load(open(a.config)); base = os.path.dirname(os.path.abspath(a.config))
    rgba_dir = os.path.join(base, cfg.get("rgba", "rgba")); chars = cfg["characters"]
    for k, v in list(chars.items()):
        if isinstance(v, str): chars[k] = json.load(open(os.path.join(base, v)))
    W, H = cfg.get("size", [1080, 1920]); n = max(len(t) for t in chars.values())
    still = None if os.path.isdir(a.clean) else cv2.imread(a.clean).astype(np.int16)
    frames = []
    for i in range(n):
        fp = os.path.join(a.frames, f"f_{i + 1:04d}.png")
        if not os.path.exists(fp): continue
        img = cv2.imread(fp).astype(np.int16)
        clean = still if still is not None else cv2.imread(os.path.join(a.clean, f"f_{i + 1:04d}.png")).astype(np.int16)
        diff = np.abs(img - clean).max(2) > a.thr
        items = []
        for key, tr in chars.items():
            st = tr[i] if i < len(tr) else None
            if not st or not st.get("vis", True): continue
            rg = cv2.imread(os.path.join(rgba_dir, key, f"f_{i + 1:04d}.png"), cv2.IMREAD_UNCHANGED)
            if rg is None or rg.shape[2] < 4: continue
            items.append((st, key, rg[..., 3] > 127))
        items.sort(key=lambda r: r[0]["g"])                     # lower on screen = nearer: drawn later, in front
        out_items = []
        for j, (st, key, al) in enumerate(items):
            ys, xs = np.nonzero(al)
            if not len(ys): continue
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            A = al[y0:y1, x0:x1]; V = A & diff[y0:y1, x0:x1]
            for st2, k2, al2 in items[j + 1:]: V &= ~al2[y0:y1, x0:x1]       # hidden by a nearer character
            out_items.append(dict(char=key, depth=j, bbox=[int(x0), int(y0), int(x1 - x0), int(y1 - y0)],
                                  alpha=rle_encode(A), vis=rle_encode(V), anchor=[st["x"], st["g"]], ground=[st["x"], st["g"]],
                                  contact=bool(st.get("contact", not st.get("air", False))), seg=st.get("seg", 0),
                                  exp_area=float(A.sum())))
        frames.append(dict(f=i + a.f_offset, t=round((i + a.f_offset) / a.fps, 4), shot=a.shot, items=out_items))
    tracks = dict(version=1, tool="blender/export_tracks", fps=a.fps, size=[W, H],
                  shots=[dict(id=a.shot, f0=a.f_offset, f1=a.f_offset + n)], frames=frames)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w") as fh: json.dump(tracks, fh, separators=(",", ":"))
    print("wrote", a.out, len(frames), "frames")


if __name__ == "__main__":
    main()
