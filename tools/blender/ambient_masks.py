"""ambient_masks: the mask pass and the cameras that ambient.py needs to move grass and water on rendered frames.

    blender -b world_painted.blend -P tools/blender/ambient_masks.py -- --camera CamMove --f0 1 --f1 96 \
            --out work/bw/masks/wide [--lawn TerrainPaint --water WaterPaint --path PathPaint] [--card L2_mid] [--size 1080x1920]

Writes <out>/m_0001.png ... (R = lawn, G = water, B = path, flat; everything else in its own flat colour, so occlusion
is real: a pixel is pure R/G/B only where that surface is what the camera sees) and <out>/cams.json (per-frame camera
matrix, lens, shift, sensor), so ambient.py can find the world ground point under every pixel. --card stores a painted
card's matrix and vertices too (for the waterfall streaks). For a locked shot render one frame (--f0 = --f1).
1 sample is enough: about 0.4 s a frame on a 12 GB consumer GPU.
"""
import argparse, json, os, sys, time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bw  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Flat lawn/water/path mask pass + per-frame cameras for ambient.py.")
    ap.add_argument("--camera", required=True); ap.add_argument("--f0", type=int, default=1); ap.add_argument("--f1", type=int)
    ap.add_argument("--out", required=True); ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--lawn", default="TerrainPaint"); ap.add_argument("--water", default="WaterPaint")
    ap.add_argument("--path", default="PathPaint"); ap.add_argument("--card", help="painted card holding a waterfall")
    ap.add_argument("--no-ink", default="", help="comma-separated objects whose outline modifiers to switch off")
    a = bw.args(ap)
    W, H = map(int, a.size.lower().split("x")); out = os.path.abspath(a.out); os.makedirs(out, exist_ok=True)
    s = bw.scene(); cam = bpy.data.objects[a.camera]; s.camera = cam
    for mat, rgb in ((a.lawn, (1, 0, 0)), (a.water, (0, 1, 0)), (a.path, (0, 0, 1))):
        if mat and mat in bpy.data.materials: bw.flat_colour(mat, rgb)
        elif mat: print("warning: no material", mat)
    for n in filter(None, a.no_ink.split(",")):
        for md in bpy.data.objects[n].modifiers: md.show_render = False
    bw.standard_view(); bw.set_output(W, H, samples=1)
    f1 = a.f1 or a.f0
    cams = {"camera": a.camera, "size": [W, H], "frames": {}}
    if a.card:
        c = bpy.data.objects[a.card]
        cams["card"] = dict(name=a.card, mw=[list(r) for r in c.matrix_world], verts=[list(v.co) for v in c.data.vertices])
    t0 = time.time()
    for f in range(a.f0, f1 + 1):
        s.frame_set(f); c = cam.data
        cams["frames"][f] = dict(mw=[list(r) for r in cam.matrix_world], lens=c.lens, shift=[c.shift_x, c.shift_y],
                                 sensor=c.sensor_height if c.sensor_fit == "VERTICAL" else c.sensor_width, fit=c.sensor_fit)
        o = os.path.join(out, f"m_{f:04d}.png")
        if not os.path.exists(o): bw.render_to(o)
    json.dump(cams, open(os.path.join(out, "cams.json"), "w"))
    print("DONE ambient_masks", a.camera, a.f0, f1, "s/frame", round((time.time() - t0) / (f1 - a.f0 + 1), 2))


if __name__ == "__main__":
    main()
