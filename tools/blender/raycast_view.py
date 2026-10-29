"""raycast_view: what does a camera see under every pixel? Depth, object and height, for planning character placement.

    blender -b world.blend -P tools/blender/raycast_view.py -- --camera CamMed --frame 96 --size 1080x1920 \
            --step 3 --out work/bw/med_ray.npz [--skip DoorLeaf,Spill] [--png work/bw/med_depth.png]

Writes an .npz with `dep` (depth along the camera axis, m; NaN = sky), `obj` (index into `names`, -1 = nothing),
`wz` (world height of the hit, m), `names` and `step`, one sample per `step` output pixels. The optional PNG is a
depth map (white near, black far) for looking at.
Use it to read where the ground is in a locked shot (the row where the tread tops, the sill and the lawn start), and how
1/depth runs down the frame: the character's size should follow it smoothly, with no pop at a threshold. Measure tread
lines on the CLEAN render zoomed in, not from these samples alone.
"""
import argparse, os, sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bw  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Raycast a camera view into per-pixel depth / object / height (npz).")
    ap.add_argument("--camera", required=True); ap.add_argument("--frame", type=int, default=1)
    ap.add_argument("--size", default="1080x1920", help="output frame size the pixel coordinates refer to")
    ap.add_argument("--step", type=int, default=4, help="sample every Nth output pixel")
    ap.add_argument("--skip", default="", help="comma-separated objects to see through (glows, hazes, door leaves)")
    ap.add_argument("--skip-prefix", default="", help="comma-separated name prefixes to see through")
    ap.add_argument("--out", required=True); ap.add_argument("--png")
    a = bw.args(ap)
    W, H = map(int, a.size.lower().split("x"))
    s = bw.scene(); s.frame_set(a.frame); cam = bpy.data.objects[a.camera]
    view = bw.View(cam, W, H); dg = bpy.context.evaluated_depsgraph_get()
    skip = set(filter(None, a.skip.split(","))); pre = tuple(filter(None, a.skip_prefix.split(",")))
    h, w = H // a.step, W // a.step
    dep = np.full((h, w), np.nan, np.float32); obj = np.full((h, w), -1, np.int16); wz = np.full((h, w), np.nan, np.float32)
    names = []
    for j in range(h):
        for i in range(w):
            r = view.hit(i * a.step + a.step / 2, j * a.step + a.step / 2, skip, pre, dg)
            if not r: continue
            n, loc, d = r
            if n not in names: names.append(n)
            obj[j, i] = names.index(n); dep[j, i] = d; wz[j, i] = loc.z
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    np.savez(a.out, dep=dep, obj=obj, wz=wz, names=np.array(names), step=a.step, size=np.array([W, H]))
    if a.png:
        valid = np.isfinite(dep); lo, hi = (np.nanmin(dep), np.nanmax(dep)) if valid.any() else (0, 1)
        img = np.where(valid, 1 - (dep - lo) / max(1e-6, hi - lo), 0).astype(np.float32)
        im = bpy.data.images.new("ray_depth", w, h, float_buffer=True)       # Blender's own writer: no OpenCV needed
        px = np.dstack([img, img, img, np.ones_like(img)])[::-1].ravel()      # Blender images start at the bottom row
        im.pixels.foreach_set(px)
        im.filepath_raw = os.path.abspath(a.png); im.file_format = "PNG"
        im.save()
    print("DONE raycast", a.camera, "objects:", names)


if __name__ == "__main__":
    main()
