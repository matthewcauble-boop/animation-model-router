"""example_world: a tiny blockout of the cottage world, so every script in this folder can be tried end to end.

    blender -b --factory-startup -P tools/blender/example_world.py -- --out work/bw/world.blend [--render work/bw/start.png]

It is a blockout, not a finished set: flat painted-look emission materials with the names the other scripts expect,
real geometry wherever a character stands or the camera gets close, and cards for what stays far away.
  Terrain     20 x 24 m ground                          material TerrainPaint  (emission, colour from a noise ramp)
  PathStones  a flagstone strip from the steps to camera   material PathPaint     (emission + a glossy wet-sheen mix)
  Water       a pond surface on the left                material WaterPaint
  HouseFace   the cottage front as a card with a doorway hole (the painted plate goes here in production)
  Interior    the room card 1.6 m behind the doorway
  Step1/2     two real treads below the threshold
  CamStart    the start camera (vertical 9:16, 36 mm sensor, vertical fit)
  CamMove     an eased push from CamStart: 18% closer, 0.4 m rise, a few degrees down (frames 1-48, smootherstep)
  CamMed      a punch-in from CamMove's end: same position and rotation, 2x lens, shifted onto the door and steps
Coordinates: +y away from the camera, z up, metres. Replace every piece with your own blockout; keep the names or pass
your names to the other scripts.
"""
import argparse, math, os, sys

import bpy
from mathutils import Vector, Quaternion

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bw  # noqa: E402


def emission_mat(name, rgb, noise=0.0, gloss=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); em = nt.nodes.new("ShaderNodeEmission")
    if noise:
        tx = nt.nodes.new("ShaderNodeTexNoise"); tx.inputs["Scale"].default_value = 6.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (*[c * (1 - noise) for c in rgb], 1)
        ramp.color_ramp.elements[1].color = (*[min(1, c * (1 + noise)) for c in rgb], 1)
        nt.links.new(tx.outputs["Fac"], ramp.inputs["Fac"]); nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    else:
        em.inputs["Color"].default_value = (*rgb, 1)
    if gloss:
        gl = nt.nodes.new("ShaderNodeBsdfGlossy"); mx = nt.nodes.new("ShaderNodeMixShader")
        mx.inputs[0].default_value = gloss
        nt.links.new(em.outputs[0], mx.inputs[1]); nt.links.new(gl.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], out.inputs["Surface"])
    else:
        nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def mesh_obj(name, verts, faces, mat, coll):
    me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces); me.update()
    me.materials.append(mat); ob = bpy.data.objects.new(name, me); coll.objects.link(ob); return ob


def box(name, x0, x1, y0, y1, z0, z1, mat, coll):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    return mesh_obj(name, v, f, mat, coll)


def main():
    ap = argparse.ArgumentParser(description="Build a tiny blockout cottage world for trying the painted-world scripts.")
    ap.add_argument("--out", required=True, help="where to save the .blend")
    ap.add_argument("--render", help="also render CamStart frame 1 to this PNG (270x480, 8 samples)")
    a = bw.args(ap)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene; s.frame_start, s.frame_end = 1, 96; s.render.fps = 24
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            s.render.engine = eng; break
        except TypeError:
            continue
    w = bpy.data.worlds.new("Sky"); w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.75, 0.62, 0.55, 1); s.world = w
    coll = bpy.data.collections.new("World3D"); s.collection.children.link(coll)

    grass = emission_mat("TerrainPaint", (0.32, 0.45, 0.16), noise=0.35)
    path = emission_mat("PathPaint", (0.52, 0.47, 0.42), noise=0.25, gloss=0.08)
    water = emission_mat("WaterPaint", (0.25, 0.38, 0.45), noise=0.15)
    house = emission_mat("HousePaint", (0.78, 0.66, 0.50), noise=0.1)
    room = emission_mat("RoomPaint", (0.30, 0.16, 0.08))
    stone = emission_mat("StepPaint", (0.60, 0.56, 0.52))

    mesh_obj("Terrain", [(-10, -12, 0), (10, -12, 0), (10, 12, 0), (-10, 12, 0)], [(0, 1, 2, 3)], grass, coll)
    mesh_obj("Water", [(-5.5, -2.5, 0.01), (-1.6, -2.5, 0.01), (-1.6, 2.5, 0.01), (-5.5, 2.5, 0.01)], [(0, 1, 2, 3)], water, coll)
    stones = []
    for i in range(9):                                             # flagstones from the steps toward the camera
        y0 = 3.9 - i * 0.9; x0 = -0.45 + 0.08 * math.sin(i * 1.7)
        stones.append(box(f"_stone{i}", x0, x0 + 0.9, y0 - 0.75, y0, 0.0, 0.03, path, coll))
    bpy.ops.object.select_all(action="DESELECT")
    for o in stones: o.select_set(True)
    bpy.context.view_layer.objects.active = stones[0]; bpy.ops.object.join(); stones[0].name = "PathStones"
    box("Step2", -1.0, 1.0, 4.0, 4.6, 0.0, 0.18, stone, coll)    # lower tread
    box("Step1", -0.9, 0.9, 4.6, 5.2, 0.0, 0.36, stone, coll)    # upper tread, at the door
    # house face with a doorway hole: four rectangles around the door (x -0.6..0.6, z 0.36..2.3), at y = 5.2
    Y, X0, X1, Z1, DX, DZ0, DZ1 = 5.2, -3.5, 3.5, 4.2, 0.6, 0.36, 2.3
    v = [(X0, Y, 0), (-DX, Y, 0), (-DX, Y, Z1), (X0, Y, Z1),            # left
         (DX, Y, 0), (X1, Y, 0), (X1, Y, Z1), (DX, Y, Z1),              # right
         (-DX, Y, DZ1), (DX, Y, DZ1), (DX, Y, Z1), (-DX, Y, Z1),        # above the door
         (-DX, Y, 0), (DX, Y, 0), (DX, Y, DZ0), (-DX, Y, DZ0)]          # below the sill
    f = [(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11), (12, 13, 14, 15)]
    mesh_obj("HouseFace", v, f, house, coll)
    mesh_obj("Interior", [(-1.5, Y + 1.6, 0), (1.5, Y + 1.6, 0), (1.5, Y + 1.6, 3), (-1.5, Y + 1.6, 3)], [(3, 2, 1, 0)], room, coll)
    box("RoomFloor", -1.5, 1.5, Y, Y + 1.6, 0.0, 0.36, room, coll)

    cd = bpy.data.cameras.new("CamStart"); cd.lens = 22; cd.sensor_fit = "VERTICAL"; cd.sensor_height = 36.0
    start = bpy.data.objects.new("CamStart", cd); s.collection.objects.link(start)
    start.location = (0.2, -6.5, 1.25)
    look = Vector((0, 5.0, 1.0)) - start.location
    start.rotation_mode = "QUATERNION"; start.rotation_quaternion = look.to_track_quat("-Z", "Y")
    mv = bpy.data.objects.new("CamMove", cd.copy()); s.collection.objects.link(mv); mv.rotation_mode = "QUATERNION"
    p0, q0 = start.location.copy(), start.rotation_quaternion.copy()
    p1 = p0.lerp(Vector((0, 5.0, 1.0)), 0.18) + Vector((0, 0, 0.4))
    q1 = (Vector((0, 5.0, 0.6)) - p1).to_track_quat("-Z", "Y")
    for fr in range(1, 97):
        t = min(1.0, (fr - 1) / 47); e = t * t * t * (t * (6 * t - 15) + 10)    # smootherstep: soft start, soft landing
        mv.location = p0.lerp(p1, e); mv.rotation_quaternion = q0.slerp(q1, e)
        mv.keyframe_insert("location", frame=fr); mv.keyframe_insert("rotation_quaternion", frame=fr)
    s.frame_set(96)
    med = bpy.data.objects.new("CamMed", cd.copy()); s.collection.objects.link(med)
    med.matrix_world = mv.matrix_world.copy(); med.data.lens = cd.lens * 2.0; med.data.shift_y = -0.12
    s.camera = start; s.render.resolution_x, s.render.resolution_y = 1080, 1920
    bw.standard_view()                                             # flat paint shows its own colours
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.out))
    if a.render:
        s.frame_set(1); bw.set_output(270, 480, samples=8); bw.render_to(a.render)
    print("DONE example_world", os.path.abspath(a.out))


if __name__ == "__main__":
    main()
