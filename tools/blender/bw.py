"""bw: small shared helpers for the painted-world Blender scripts in this folder (import inside Blender only).

    import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import bw
    a = bw.args(parser)              # parses the arguments after "--" on the blender command line
    view = bw.View(cam, W, H)        # rays through output pixels (lens shift and sensor fit included)
    view.hit_depth(x, y, skip)       # depth along the camera axis of the first real surface under a pixel

Blender 4.2+ (tested on 5.1). Material nodes are found by type, never by name, so localised Blender works too.
"""
import os
import sys

try:
    import bpy
    from mathutils import Vector
except ImportError:                                  # imported outside Blender (e.g. by --help tooling): fine
    bpy = None


def args(parser):
    """argparse on the arguments after '--' (blender -b file.blend -P script.py -- --flag value)."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(argv)


def scene():
    return bpy.context.scene


def set_output(W, H, samples=16, fmt="PNG"):
    s = scene()
    s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = W, H, 100
    try:
        s.eevee.taa_render_samples = samples
    except AttributeError:
        pass
    s.render.image_settings.file_format = fmt


def render_to(path):
    s = scene(); s.render.filepath = os.path.abspath(path); bpy.ops.render.render(write_still=True)


class View:
    """A camera's view at the current frame, for rays through output pixels (px, py) of a W x H frame."""

    def __init__(self, cam, W, H):
        self.cam, self.W, self.H = cam, W, H
        M = cam.matrix_world.copy(); self.q = M.to_quaternion(); self.org = M.translation.copy()
        self.fwd = (self.q @ Vector((0, 0, -1))).normalized()
        c = cam.data; self.f = c.lens
        fit = c.sensor_fit
        if fit == "AUTO": fit = "HORIZONTAL" if W >= H else "VERTICAL"
        if fit == "VERTICAL":
            self.SH = c.sensor_height if c.sensor_fit == "VERTICAL" else c.sensor_width
            self.SW = self.SH * W / H; big = self.SH
        else:
            self.SW = c.sensor_width; self.SH = self.SW * H / W; big = self.SW
        self.shx, self.shy = c.shift_x * big, c.shift_y * big

    def ray(self, px, py):
        u = px / self.W - 0.5; v = 0.5 - py / self.H
        return (self.q @ Vector(((u * self.SW + self.shx) / self.f, (v * self.SH + self.shy) / self.f, -1.0))).normalized()

    def frustum_quad(self):
        """Corners of the full frame on the plane 1 unit in front of the camera, in camera space (for depth cards)."""
        x0, x1 = (-0.5 * self.SW + self.shx) / self.f, (0.5 * self.SW + self.shx) / self.f
        y0, y1 = (-0.5 * self.SH + self.shy) / self.f, (0.5 * self.SH + self.shy) / self.f
        return [(x0, y0, -1), (x1, y0, -1), (x1, y1, -1), (x0, y1, -1)]

    def plane_depth(self, name, px, py):
        """Depth (along the camera axis) where the pixel's ray meets the plane of object `name`'s first face."""
        ob = bpy.data.objects[name]; mw = ob.matrix_world; me = ob.data
        p0 = mw @ me.vertices[0].co; n = (mw.to_3x3() @ me.polygons[0].normal).normalized(); d = self.ray(px, py)
        t = (p0 - self.org).dot(n) / d.dot(n)
        return (d * t).dot(self.fwd)

    def hit(self, px, py, skip=(), skip_prefix=(), depsgraph=None, max_steps=10):
        """(object name, world location, depth) of the first visible surface under the pixel, skipping names in `skip`,
        names starting with `skip_prefix` and objects hidden in render. None if the ray hits nothing."""
        s = scene(); dg = depsgraph or bpy.context.evaluated_depsgraph_get()
        d = self.ray(px, py); o = self.org.copy()
        for _ in range(max_steps):
            ok, loc, nrm, idx, ob, mw = s.ray_cast(dg, o, d)
            if not ok: return None
            if ob.name in skip or ob.hide_render or (skip_prefix and ob.name.startswith(tuple(skip_prefix))):
                o = loc + d * 1e-3; continue
            return ob.name, loc, (loc - self.org).dot(self.fwd)
        return None

    def hit_depth(self, px, py, skip=(), skip_prefix=(), depsgraph=None):
        h = self.hit(px, py, skip, skip_prefix, depsgraph)
        return h[2] if h else None


def emission_node(mat):
    """The material's emission node that carries the paint (the first one with a linked Color input, else any)."""
    nt = mat.node_tree
    return next((n for n in nt.nodes if n.type == "EMISSION" and n.inputs["Color"].links), None) or \
        next(n for n in nt.nodes if n.type == "EMISSION")


def flat_colour(matname, rgb, drop_gloss=True):
    """Turn a painted material into a flat emission colour (for mask passes). Optionally bypass glossy mixes."""
    mat = bpy.data.materials[matname]; nt = mat.node_tree; em = emission_node(mat)
    for l in list(em.inputs["Color"].links): nt.links.remove(l)
    em.inputs["Color"].default_value = (*rgb, 1); em.inputs["Strength"].default_value = 1.0
    if drop_gloss:
        out = next(x for x in nt.nodes if x.type == "OUTPUT_MATERIAL")
        for n in nt.nodes:
            if n.type == "MIX_SHADER" and any(l.from_node.type == "BSDF_GLOSSY" for i in (1, 2) for l in n.inputs[i].links):
                nt.links.new(em.outputs[0], out.inputs["Surface"])


def standard_view():
    """Exact colours for mask passes: no filmic/AgX tone mapping, no look."""
    s = scene()
    s.view_settings.view_transform = "Standard"
    try:
        s.view_settings.look = "None"
    except TypeError:
        pass
