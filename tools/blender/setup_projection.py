"""setup_projection: projector cameras for painting a camera view, plus the two renders the painter starts from.

    blender -b world.blend -P tools/blender/setup_projection.py -- \
        --proj ProjA:CamStart:1:1.15 --proj ProjB:CamMed:96:1.12 \
        --mask TerrainPaint=#ff00ff --mask PathPaint=#00ffff \
        --size 1440x2560 --frame 96 --out work/bw/proj --save work/bw/world_proj.blend

Each --proj NAME:SOURCE_CAMERA:FRAME:WIDEN copies SOURCE_CAMERA as it is at FRAME into a static camera NAME whose lens
is WIDEN times wider (shift scaled to match), so its painting covers a little more than the shot and its feathered
edge falls outside the frame. Use one projector per camera range: the start of a move (widened to cover the whole
move), the held end of a move, and each new angle or punch-in.

Writes, per projector (at --frame, so a door that opens later is already open):
  <out>/<NAME>_src.png    the current look: the structure image you send to the image-edit model
  <out>/<NAME>_mask.png   the same view with each --mask material as a flat colour (exact, no tone mapping):
                          tells the painter (and paint_split.py) which pixels are lawn, path, water...
  <out>/projectors.json   lens, shift, sensor fit, location and rotation of every projector
--save keeps the projector cameras in a new .blend (the mask pass is never saved). Then paint (see BLENDER-WORLD.md),
run paint_split.py, and install the paintings with lawnproj.py.
"""
import argparse, json, os, sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bw  # noqa: E402


def proj_cam(name, src, frame, widen):
    s = bw.scene(); s.frame_set(frame)
    c = bpy.data.objects.new(name, src.data.copy()); s.collection.objects.link(c)
    c.matrix_world = src.matrix_world.copy(); c.animation_data_clear()
    if c.data.animation_data: c.data.animation_data_clear()
    c.data.lens = src.data.lens / widen
    c.data.shift_x = src.data.shift_x / widen; c.data.shift_y = src.data.shift_y / widen
    return c


def hex_rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def main():
    ap = argparse.ArgumentParser(description="Projector cameras + structure and mask renders for painting a view.")
    ap.add_argument("--proj", action="append", required=True, metavar="NAME:CAMERA:FRAME:WIDEN")
    ap.add_argument("--mask", action="append", default=[], metavar="MATERIAL=#hex",
                    help="flat colour per painted material in the mask pass (default: none, src only)")
    ap.add_argument("--size", default="1440x2560", help="render size for the painter (2x the delivery size)")
    ap.add_argument("--frame", type=int, help="scene frame for the renders (default: each projector's own frame)")
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--out", required=True); ap.add_argument("--save")
    a = bw.args(ap)
    W, H = map(int, a.size.lower().split("x")); os.makedirs(a.out, exist_ok=True)
    s = bw.scene(); cams = []
    for spec in a.proj:
        name, src, fr, widen = spec.split(":")
        cams.append((proj_cam(name, bpy.data.objects[src], int(fr), float(widen)), int(fr)))
    info = {c.name: dict(lens=c.data.lens, shift=[c.data.shift_x, c.data.shift_y], fit=c.data.sensor_fit,
                         sensor=c.data.sensor_height if c.data.sensor_fit == "VERTICAL" else c.data.sensor_width,
                         loc=list(c.matrix_world.translation), quat=list(c.matrix_world.to_quaternion()), size=[W, H])
            for c, _ in cams}
    json.dump(info, open(os.path.join(a.out, "projectors.json"), "w"), indent=1)
    if a.save: bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save))
    bw.set_output(W, H, a.samples)
    for c, fr in cams:
        s.frame_set(a.frame or fr); s.camera = c; bw.render_to(os.path.join(a.out, f"{c.name}_src.png"))
    if a.mask:
        for m in a.mask:
            mat, col = m.split("="); bw.flat_colour(mat, hex_rgb(col))
        bw.standard_view()
        for c, fr in cams:
            s.frame_set(a.frame or fr); s.camera = c; bw.render_to(os.path.join(a.out, f"{c.name}_mask.png"))
    print("DONE setup_projection", [c.name for c, _ in cams])


if __name__ == "__main__":
    main()
