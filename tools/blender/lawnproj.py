"""lawnproj: project painted layers from projector cameras onto existing materials (the lawn, the path, anything).

The ground geometry is untouched: only the colour feeding the material's emission changes, so transparency, a wet
sheen mix and ink outlines stay. Layers stack in install order: a later layer wins inside its projector's frustum,
feathered at its frame edges. A new camera inside a layer's frustum gets that paint automatically; a close-up in a new
spot needs its own projector layer.

As a module (inside Blender):
    import lawnproj
    lawnproj.install("A", "ProjA", {"TerrainPaint": "lawnA_terrain.png", "PathPaint": "lawnA_path.png"}, feather=0.04)
From the command line:
    blender -b world_proj.blend -P tools/blender/lawnproj.py -- --spec layers.json --save world_painted.blend \
            [--check CamMove:1:work/bw/chk_wide.png --check CamMed:96:work/bw/chk_med.png --size 1080x1920]
layers.json (paths relative to the file):
    [{"tag": "A",  "camera": "ProjA",  "feather": 0.04,  "textures": {"TerrainPaint": "A_terrain.png", "PathPaint": "A_path.png"}},
     {"tag": "C2", "camera": "ProjC",  "feather": 0.045, "textures": {...}},
     {"tag": "B",  "camera": "ProjB",  "feather": 0.045, "textures": {...}}]
Order them wide first, then the held end of the move, then the medium (later wins). Paint them in the opposite order
(medium first) and paint each one from a render that already has the earlier layers, so stones and clumps continue
across the cut.
"""
import argparse, json, os, sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bw  # noqa: E402


def _m(nt, op, a=None, b=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
    for i, x in enumerate((a, b)):
        if x is None: continue
        if isinstance(x, (int, float)): n.inputs[i].default_value = x
        else: nt.links.new(x, n.inputs[i])
    return n.outputs[0]


def _uv_mask(nt, cam, feather):
    """Projector UV (0-1 over its frame) and a weight that is 1 inside and fades to 0 over `feather` at the edges."""
    s = bpy.context.scene; c = cam.data; f = c.lens
    W, H = s.render.resolution_x, s.render.resolution_y
    fit = c.sensor_fit if c.sensor_fit != "AUTO" else ("HORIZONTAL" if W >= H else "VERTICAL")
    if fit == "VERTICAL":
        big = c.sensor_height if c.sensor_fit == "VERTICAL" else c.sensor_width; sh = big; sw = big * W / H
    else:
        big = c.sensor_width; sw = big; sh = big * H / W
    tc = nt.nodes.new("ShaderNodeTexCoord"); tc.object = cam
    sp = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(tc.outputs["Object"], sp.inputs[0])
    nz = _m(nt, "MULTIPLY", sp.outputs[2], -1.0)                       # depth in front of the projector
    safe = _m(nt, "MAXIMUM", nz, 1e-4)
    X = _m(nt, "MULTIPLY", _m(nt, "DIVIDE", sp.outputs[0], safe), f)
    Y = _m(nt, "MULTIPLY", _m(nt, "DIVIDE", sp.outputs[1], safe), f)
    u = _m(nt, "ADD", _m(nt, "DIVIDE", _m(nt, "SUBTRACT", X, c.shift_x * big), sw), 0.5)
    v = _m(nt, "ADD", _m(nt, "DIVIDE", _m(nt, "SUBTRACT", Y, c.shift_y * big), sh), 0.5)
    cxyz = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(u, cxyz.inputs[0]); nt.links.new(v, cxyz.inputs[1])
    e = _m(nt, "MINIMUM", _m(nt, "MINIMUM", u, _m(nt, "SUBTRACT", 1.0, u)), _m(nt, "MINIMUM", v, _m(nt, "SUBTRACT", 1.0, v)))
    w = _m(nt, "DIVIDE", e, feather, clamp=True)
    w = _m(nt, "MULTIPLY", w, _m(nt, "GREATER_THAN", nz, 0.05))      # nothing behind the projector
    w = _m(nt, "MULTIPLY", w, _m(nt, "MULTIPLY", w, _m(nt, "SUBTRACT", 3.0, _m(nt, "MULTIPLY", w, 2.0))))   # smoothstep
    return cxyz.outputs[0], w


def install(tag, cam_name, textures, feather=0.04):
    """textures: {material name: painted PNG seen from cam_name}. Mixes the paint over whatever fed the emission."""
    cam = bpy.data.objects[cam_name]
    for mat, png in textures.items():
        m = bpy.data.materials[mat]; nt = m.node_tree; em = bw.emission_node(m)
        old = em.inputs["Color"].links[0].from_socket if em.inputs["Color"].links else None
        vec, w = _uv_mask(nt, cam, feather)
        tx = nt.nodes.new("ShaderNodeTexImage"); tx.name = tx.label = f"Lawn{tag}"
        tx.image = bpy.data.images.load(os.path.abspath(png), check_existing=True); tx.extension = "EXTEND"; tx.interpolation = "Cubic"
        nt.links.new(vec, tx.inputs["Vector"])
        mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.name = mx.label = f"LawnMix{tag}"
        nt.links.new(w, mx.inputs["Factor"])
        if old is not None: nt.links.new(old, mx.inputs["A"])
        else: mx.inputs["A"].default_value = tuple(em.inputs["Color"].default_value)
        nt.links.new(tx.outputs["Color"], mx.inputs["B"]); nt.links.new(mx.outputs["Result"], em.inputs["Color"])


def main():
    ap = argparse.ArgumentParser(description="Install projected paint layers onto materials and save the .blend.")
    ap.add_argument("--spec", required=True, help="layers.json (see the docstring)")
    ap.add_argument("--save", required=True)
    ap.add_argument("--check", action="append", default=[], metavar="CAMERA:FRAME:OUT.png", help="check renders after install")
    ap.add_argument("--size", default="1080x1920"); ap.add_argument("--samples", type=int, default=16)
    a = bw.args(ap)
    base = os.path.dirname(os.path.abspath(a.spec))
    W, H = map(int, a.size.lower().split("x")); bw.set_output(W, H, a.samples)   # the UV maths reads the frame aspect
    for L in json.load(open(a.spec)):
        tex = {m: os.path.join(base, p) for m, p in L["textures"].items()}
        install(L["tag"], L["camera"], tex, L.get("feather", 0.04)); print("installed", L["tag"], "from", L["camera"])
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save))
    s = bw.scene()
    for c in a.check:
        cam, fr, out = c.split(":", 2); s.camera = bpy.data.objects[cam]; s.frame_set(int(fr)); bw.render_to(out)
    print("DONE lawnproj", a.save)


if __name__ == "__main__":
    main()
