"""depth_cards: put 2D character renders INTO the Blender world on camera-facing cards at the real depth of the ground
under them, so the world's own geometry does the occlusion (door jambs, walls, tread edges), then render.

    blender -b world_painted.blend -P tools/blender/depth_cards.py -- --config cards.json --out work/bw/med \
            [--no-chars] [--f0 1 --f1 120] [--dump work/bw/card_depths.json]

Each character is a sequence of full-frame RGBA images (straight alpha, the size of the output), animated in 2D in the
LOCKED camera's frame (bounce.py, your own animator, or a hand-drawn layer; see rgba_from_bw.py). A card covers the
whole camera frustum at depth d, so pixel (x, y) of the RGBA lands exactly on output pixel (x, y) whatever d is: the
depth decides only what hides the character and what it hides.

Depth rules (per frame, from the character's ground row g and the levels in cards.json):
  inside / threshold  (g <= sill_row + 3): `behind_face_m` (0.15 m) BEHIND the house-face plane, so the jambs and
                      wall hide it for real while it is in the room or on the sill
  stairs  (sill_row < g < foot_row - 3): the tread's depth, with 1/depth interpolated from the sill (on the face plane)
                      to the foot of the steps (raycast), which matches perspective, so the size never pops
  ground  (g >= foot_row - 3): `ground_pull_m` in front of the raycast ground point
Then always pulled in front of the nearest surface under the character's body AND its contact shadow, so nothing it
stands in front of clips it. While airborne, the nearest of its take-off and landing depths is used.

cards.json (output pixels; rows measured on the CLEAN still zoomed in, never taken from the animation):
  {"camera": "CamMed", "frame": 96,                    # the locked camera, and the scene frame its matrix is read at
   "scene_frame": 96,                                  # world frame for every render (static world) ...
   "scene_f0": null,                                   # ... or the world frame of character frame 1 (animated world)
   "size": [1080, 1920], "samples": 16, "rgba": "rgba",   # rgba/<character>/f_0001.png ...
   "face": "HouseFace", "behind_face_m": 0.15, "sill_row": 868, "foot_row": 1088, "ground_pull_m": 0.05,
   "see_through": ["Interior", "RoomHaze", "Spill"], "see_through_prefix": ["R_"], "collection": "World3D",
   "characters": {"red": "tracks/red.json", "blue": [...]}}
  track = one entry per frame: {"x": 540, "g": 1120, "h": 290, "vis": true, "air": false, "g0": 1120, "g1": 1120,
            "contact": true, "seg": 4}    # x, g = the contact point; h = body height px; g0/g1 = take-off/landing rows
Writes <out>/f_0001.png ...; --no-chars renders the clean pass (with a static world, ONE still: <out>/clean.png).
Cards must be BLENDED: with DITHERED a character behind a doorway rendered solid black.
"""
import argparse, json, os, sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bw  # noqa: E402


def load_cfg(path):
    cfg = json.load(open(path)); base = os.path.dirname(os.path.abspath(path))
    cfg["rgba"] = os.path.join(base, cfg.get("rgba", "rgba"))
    for k, v in list(cfg["characters"].items()):
        if isinstance(v, str): cfg["characters"][k] = json.load(open(os.path.join(base, v)))
    return cfg


def card(name, view, rgba_first, coll):
    me = bpy.data.meshes.new(name); me.from_pydata(view.frustum_quad(), [], [(0, 1, 2, 3)])
    ul = me.uv_layers.new(name="UVMap")
    for li, uv in zip(range(4), ((0, 0), (1, 0), (1, 1), (0, 1))): ul.data[li].uv = uv
    m = bpy.data.materials.new(name); m.use_nodes = True
    try:
        m.surface_render_method = "BLENDED"                   # DITHERED rendered black behind the doorway
    except (AttributeError, TypeError):
        m.blend_method = "BLEND"
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); tx = nt.nodes.new("ShaderNodeTexImage")
    im = bpy.data.images.load(rgba_first, check_existing=False); im.alpha_mode = "STRAIGHT"; tx.image = im; tx.interpolation = "Linear"
    em = nt.nodes.new("ShaderNodeEmission"); nt.links.new(tx.outputs["Color"], em.inputs["Color"])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent"); mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tx.outputs["Alpha"], mx.inputs[0]); nt.links.new(tr.outputs[0], mx.inputs[1]); nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    me.materials.append(m); ob = bpy.data.objects.new(name, me); coll.objects.link(ob)
    ob.visible_shadow = False; ob.rotation_mode = "QUATERNION"; ob.rotation_quaternion = view.q
    ob.location = view.org
    return ob, im


def main():
    ap = argparse.ArgumentParser(description="Character RGBA sequences on depth cards in the Blender world, then render.")
    ap.add_argument("--config", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--no-chars", action="store_true", help="render the clean pass (one still if the world is static)")
    ap.add_argument("--f0", type=int, default=1); ap.add_argument("--f1", type=int)
    ap.add_argument("--dump", help="write the per-frame card depths here")
    a = bw.args(ap)
    cfg = load_cfg(a.config); s = bw.scene()
    W, H = cfg.get("size", [1080, 1920]); bw.set_output(W, H, cfg.get("samples", 16))
    cam = bpy.data.objects[cfg["camera"]]; s.camera = cam; s.frame_set(cfg.get("frame", s.frame_current))
    view = bw.View(cam, W, H); dg = bpy.context.evaluated_depsgraph_get()
    skip = set(cfg.get("see_through", [])); pre = tuple(cfg.get("see_through_prefix", [])) + ("Card_",)
    face, SILL, FOOT = cfg["face"], cfg["sill_row"], cfg["foot_row"]
    behind, pull = cfg.get("behind_face_m", 0.15), cfg.get("ground_pull_m", 0.05)
    hit = lambda x, y: view.hit_depth(x, y, skip | {face}, pre, dg)
    d_sill = view.plane_depth(face, W / 2, SILL)
    d_foot = hit(W / 2, FOOT + 2) or d_sill

    def stairs_depth(g):
        u = min(1.0, max(0.0, (g - SILL) / max(1, FOOT - SILL)))
        return 1 / (1 / d_sill + (1 / d_foot - 1 / d_sill) * u)

    def covered_min(x, g, h):
        best = 1e9
        for fx in (-0.42, -0.21, 0.0, 0.21, 0.42):
            for fy in (-0.9, -0.6, -0.3, -0.1, 0.0, 0.06):            # the body, and the contact shadow just below
                d = hit(x + fx * h, g + fy * h)
                if d: best = min(best, d)
        return best

    def depth_at(x, g, h):
        if g <= SILL + 3: return view.plane_depth(face, x, g) + behind
        d = stairs_depth(g) if g < FOOT - 3 else (hit(x, g) or stairs_depth(g)) - pull
        return min(d, covered_min(x, g, h) - pull)

    chars = cfg["characters"]; n = max(len(t) for t in chars.values())
    f1 = min(a.f1 or n, n)
    coll = bpy.data.collections.get(cfg.get("collection", "")) or s.collection
    static = cfg.get("scene_f0") is None
    os.makedirs(a.out, exist_ok=True)
    if a.no_chars and static:
        s.frame_set(cfg.get("scene_frame", cfg.get("frame", 1))); bw.render_to(os.path.join(a.out, "clean.png"))
        print("DONE depth_cards clean still", os.path.join(a.out, "clean.png")); return
    cards = {}
    if not a.no_chars:
        for key, tr in chars.items():
            ob, im = card("Card_" + key, view, os.path.join(cfg["rgba"], key, "f_0001.png"), coll)
            deps = []
            for st in tr:
                if not st.get("vis", True): deps.append(None); continue
                d = depth_at(st["x"], st["g"], st.get("h", 200))
                if st.get("air"):
                    for gg in (st.get("g0", st["g"]), st.get("g1", st["g"])): d = min(d, depth_at(st["x"], gg, st.get("h", 200)))
                deps.append(round(d, 4))
            cards[key] = dict(ob=ob, im=im, depth=deps)
        if a.dump:
            json.dump(dict(sill_depth=d_sill, foot_depth=d_foot, depth={k: v["depth"] for k, v in cards.items()}), open(a.dump, "w"))
    for fr in range(a.f0, f1 + 1):
        o = os.path.join(a.out, f"f_{fr:04d}.png")
        if os.path.exists(o): continue                             # resumable
        i = fr - 1
        s.frame_set(cfg.get("scene_frame", cfg.get("frame", 1)) if static else cfg["scene_f0"] + i)
        for key, c in cards.items():
            d = c["depth"][i] if i < len(c["depth"]) else None
            c["ob"].hide_render = d is None
            if d is not None:
                c["ob"].location = view.org; c["ob"].scale = (d, d, d)
                c["im"].filepath = os.path.join(cfg["rgba"], key, f"f_{i + 1:04d}.png"); c["im"].reload()
        bw.render_to(o); print("FRAME", fr, flush=True)
    print("DONE depth_cards", a.out)


if __name__ == "__main__":
    main()
