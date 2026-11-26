"""Materials for Roman architecture (runs inside Blender).

v2 (2026-11-26): photographic CC0 PBR maps from Poly Haven (data/textures, see
LICENSES.json) layered with procedural colour variation and weathering. Walls and
roofs use the explicit metre UVs written by tl_mesh.MeshBuilder; terrain and paving
use world XY. When a texture file is missing the material falls back to its
procedural pattern, so the engine still runs without data/textures.
Every material is created once per .blend and looked up by name (``TL_*``).
"""
from __future__ import annotations

import glob
import os

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
TEX_ROOT = os.environ.get("TIMELINES_TEXTURES") or os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "..", "data", "textures"))


FAST = False   # set by render_scene for quality="preview": no AO node, opaque leaf shadows


def s2l(c):
    """sRGB 0..1 -> linear."""
    def f(x):
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return (f(c[0]), f(c[1]), f(c[2]), 1.0)


def tex_path(asset, kind):
    hits = sorted(glob.glob(os.path.join(TEX_ROOT, asset, f"{asset}_{kind}_*.*")))
    return hits[0] if hits else None


def has_tex(asset):
    return tex_path(asset, "diffuse") is not None


class G:
    """Tiny node-graph helper."""

    def __init__(self, mat):
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = 0

    def n(self, typ, **props):
        node = self.nt.nodes.new(typ)
        self.x += 1
        node.location = (-200 * (self.x % 12), -180 * (self.x // 12))
        for k, v in props.items():
            if k.startswith("i_"):
                key = k[2:]
                node.inputs[int(key) if key.isdigit() else key].default_value = v
            else:
                setattr(node, k, v)
        return node

    def link(self, a, b):
        self.nt.links.new(a, b)

    def _in(self, node, idx, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.link(v, node.inputs[idx])
        else:
            node.inputs[idx].default_value = v

    def m(self, op, a, b=0.0, c=0.0, clamp=False):
        nd = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        self._in(nd, 0, a)
        self._in(nd, 1, b)
        self._in(nd, 2, c)
        return nd.outputs[0]

    def mixc(self, fac, a, b, blend="MIX"):
        nd = self.n("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        self._in(nd, 0, fac)
        self._in(nd, 6, a)
        self._in(nd, 7, b)
        return nd.outputs[2]

    def mapr(self, v, a0, a1, b0, b1, clamp=True):
        nd = self.n("ShaderNodeMapRange", clamp=clamp)
        self._in(nd, 0, v)
        nd.inputs[1].default_value = a0
        nd.inputs[2].default_value = a1
        nd.inputs[3].default_value = b0
        nd.inputs[4].default_value = b1
        return nd.outputs[0]

    def ramp(self, fac, stops, interp="LINEAR"):
        nd = self.n("ShaderNodeValToRGB")
        self._in(nd, 0, fac)
        cr = nd.color_ramp
        cr.interpolation = interp
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, col) in zip(cr.elements, stops):
            el.position = pos
            el.color = s2l(col)
        return nd.outputs[0]

    def attr(self, name, typ="GEOMETRY"):
        return self.n("ShaderNodeAttribute", attribute_name=name, attribute_type=typ).outputs["Fac"]

    def uv(self):
        return self.n("ShaderNodeUVMap", uv_map="UVMap").outputs[0]

    def sep(self, vec):
        nd = self.n("ShaderNodeSeparateXYZ")
        self.link(vec, nd.inputs[0])
        return nd.outputs[0], nd.outputs[1], nd.outputs[2]

    def comb(self, x, y, z=0.0):
        nd = self.n("ShaderNodeCombineXYZ")
        self._in(nd, 0, x)
        self._in(nd, 1, y)
        self._in(nd, 2, z)
        return nd.outputs[0]

    def noise(self, vec, scale, detail=4.0, rough=0.55, dims="3D", distortion=0.0):
        nd = self.n("ShaderNodeTexNoise", noise_dimensions=dims)
        if vec is not None:
            self.link(vec, nd.inputs["Vector"])
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        nd.inputs["Distortion"].default_value = distortion
        return nd.outputs["Fac"]

    def vscale(self, vec, s):
        nd = self.n("ShaderNodeVectorMath", operation="MULTIPLY")
        self.link(vec, nd.inputs[0])
        nd.inputs[1].default_value = s if isinstance(s, tuple) else (s, s, s)
        return nd.outputs[0]

    def vadd(self, vec, v):
        nd = self.n("ShaderNodeVectorMath", operation="ADD")
        self.link(vec, nd.inputs[0])
        self._in(nd, 1, v)
        return nd.outputs[0]

    def white(self, vec, dims="3D"):
        nd = self.n("ShaderNodeTexWhiteNoise", noise_dimensions=dims)
        self.link(vec, nd.inputs["Vector"])
        return nd.outputs["Value"]

    def pos(self):
        return self.n("ShaderNodeNewGeometry").outputs["Position"]

    def objrand(self):
        return self.n("ShaderNodeObjectInfo").outputs["Random"]

    def ao(self, dist=1.0):
        nd = self.n("ShaderNodeAmbientOcclusion", samples=8)
        nd.inputs["Distance"].default_value = dist
        return nd.outputs["AO"]

    # ------------------------------------------------------------- image textures
    def img(self, asset, kind, vec, non_color=False, box=False):
        path = tex_path(asset, kind)
        if path is None:
            return None
        im = bpy.data.images.load(path, check_existing=True)
        im.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
        nd = self.n("ShaderNodeTexImage", image=im, interpolation="Linear")
        if box:
            nd.projection = "BOX"
            nd.projection_blend = 0.3
        self.link(vec, nd.inputs["Vector"])
        return nd.outputs["Color"]

    def pbr(self, asset, vec, box=False):
        """-> dict(col, rough, nrm) sockets (None when missing)."""
        out = dict(col=self.img(asset, "diffuse", vec, box=box),
                   rough=None, nrm=None)
        r = self.img(asset, "rough", vec, non_color=True, box=box)
        if r is not None:
            out["rough"] = self.sep(r)[0]
        out["nrm"] = self.img(asset, "nor_gl", vec, non_color=True, box=box)
        return out

    def gray(self, col):
        nd = self.n("ShaderNodeRGBToBW")
        self.link(col, nd.inputs[0])
        return nd.outputs[0]

    def bsdf(self, color, rough, bump_h=None, bump_strength=0.3, bump_dist=0.02, metallic=0.0,
             spec=0.5, ao=None, ao_dist=1.5, normal_map=None, nm_strength=1.0, out=True):
        b = self.n("ShaderNodeBsdfPrincipled")
        if ao is not None and not FAST:
            aof = self.mapr(self.ao(ao_dist), 0.0, 1.0, ao, 1.0)
            color = self._mul_col(color, aof)
        self._in(b, "Base Color", color)
        if isinstance(rough, bpy.types.NodeSocket):
            self.link(rough, b.inputs["Roughness"])
        else:
            b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metallic
        b.inputs["Specular IOR Level"].default_value = spec
        nrm = None
        if normal_map is not None:
            nm = self.n("ShaderNodeNormalMap", uv_map="UVMap")
            nm.inputs["Strength"].default_value = nm_strength
            self.link(normal_map, nm.inputs["Color"])
            nrm = nm.outputs[0]
        if bump_h is not None:
            bp = self.n("ShaderNodeBump")
            bp.inputs["Strength"].default_value = bump_strength
            bp.inputs["Distance"].default_value = bump_dist
            self.link(bump_h, bp.inputs["Height"])
            if nrm is not None:
                self.link(nrm, bp.inputs["Normal"])
            nrm = bp.outputs["Normal"]
        if nrm is not None:
            self.link(nrm, b.inputs["Normal"])
        if out:
            o = self.n("ShaderNodeOutputMaterial")
            self.link(b.outputs[0], o.inputs["Surface"])
        return b

    def _mul_col(self, color, f):
        nd = self.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        nd.inputs[0].default_value = 1.0
        self._in(nd, 6, color)
        if isinstance(f, bpy.types.NodeSocket):
            self.link(self.comb(f, f, f), nd.inputs[7])
        else:
            nd.inputs[7].default_value = (f, f, f, 1.0)
        return nd.outputs[2]

    def scale_col(self, color, f):
        return self._mul_col(color, f)

    def detail(self, base, texcol, amount=1.0, mean=0.45):
        """Transfer the luminance detail of a photo texture onto a tinted base colour."""
        if texcol is None:
            return base
        lum = self.m("DIVIDE", self.gray(texcol), mean)
        f = self.m("ADD", 1.0 - amount, self.m("MULTIPLY", lum, amount))
        return self.scale_col(base, f)


def _new(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, G(mat)


def _uvs(g, size):
    """UV (metres) scaled to a texture covering `size` metres."""
    return g.vscale(g.uv(), 1.0 / size)


def _wxy(g, size, offset=(0.0, 0.0, 0.0)):
    p = g.pos()
    return g.vscale(g.vadd(p, offset), 1.0 / size)


# --------------------------------------------------------------------------- shader windows (far/party walls)
def _windows(g, u, v, fac, wlen, ground_h=3.6, floor_h=3.0, spacing=3.2):
    """Return (mask_upper, mask_shop, cell_id_vec) for window/shop openings.
    Only used on walls without modelled openings (fac 1/2)."""
    n = g.m("FLOOR", g.m("DIVIDE", g.m("SUBTRACT", wlen, 1.4), spacing))
    margin = g.m("DIVIDE", g.m("SUBTRACT", wlen, g.m("MULTIPLY", n, spacing)), 2.0)
    k = g.m("DIVIDE", g.m("SUBTRACT", u, margin), spacing)
    fx = g.m("FRACT", k)
    col_in = g.m("MULTIPLY", g.m("GREATER_THAN", k, 0.0), g.m("LESS_THAN", k, n))
    colmask = g.m("MULTIPLY", g.m("GREATER_THAN", fx, 0.38), g.m("LESS_THAN", fx, 0.62))
    r = g.m("DIVIDE", g.m("SUBTRACT", v, ground_h), floor_h)
    fy = g.m("FRACT", r)
    rowmask = g.m("MULTIPLY", g.m("GREATER_THAN", r, 0.0),
                  g.m("MULTIPLY", g.m("GREATER_THAN", fy, 0.26), g.m("LESS_THAN", fy, 0.62)))
    is_fac = g.m("MULTIPLY", g.m("GREATER_THAN", fac, 0.5), g.m("LESS_THAN", fac, 2.5))
    upper = g.m("MULTIPLY", g.m("MULTIPLY", colmask, col_in), g.m("MULTIPLY", rowmask, is_fac))
    cell = g.comb(g.m("FLOOR", k), g.m("FLOOR", r), g.m("FLOOR", g.m("MULTIPLY", wlen, 7.13)))
    sp2 = 4.2
    n2 = g.m("FLOOR", g.m("DIVIDE", g.m("SUBTRACT", wlen, 1.2), sp2))
    m2 = g.m("DIVIDE", g.m("SUBTRACT", wlen, g.m("MULTIPLY", n2, sp2)), 2.0)
    k2 = g.m("DIVIDE", g.m("SUBTRACT", u, m2), sp2)
    f2 = g.m("FRACT", k2)
    c2 = g.m("MULTIPLY", g.m("GREATER_THAN", k2, 0.0), g.m("LESS_THAN", k2, n2))
    shopx = g.m("MULTIPLY", g.m("GREATER_THAN", f2, 0.2), g.m("LESS_THAN", f2, 0.8))
    shopy = g.m("MULTIPLY", g.m("GREATER_THAN", v, 0.02), g.m("LESS_THAN", v, 2.7))
    is_shop = g.m("MULTIPLY", g.m("GREATER_THAN", fac, 0.5), g.m("LESS_THAN", fac, 1.5))
    shop = g.m("MULTIPLY", g.m("MULTIPLY", shopx, c2), g.m("MULTIPLY", shopy, is_shop))
    return upper, shop, cell


# plaster palette: ochre, cream, faded red, grey, pale pink, warm white (constant steps)
PLASTER = [(0.0, (0.80, 0.63, 0.40)), (0.17, (0.86, 0.80, 0.66)), (0.33, (0.70, 0.43, 0.33)),
           (0.47, (0.70, 0.68, 0.63)), (0.60, (0.82, 0.66, 0.56)), (0.72, (0.88, 0.84, 0.75)),
           (0.84, (0.76, 0.55, 0.36)), (0.93, (0.62, 0.38, 0.30))]


def mat_plaster(name="TL_Plaster", windows=True, plain=False):
    mat, g = _new(name)
    uvv = g.uv()
    u, v, _ = g.sep(uvv)
    var = g.attr("var")
    p = g.pos()
    if plain:
        base = g.ramp(var, [(0.0, (0.84, 0.79, 0.68)), (1.0, (0.78, 0.72, 0.60))])
    else:
        base = g.ramp(var, PLASTER, interp="CONSTANT")
    # subtle per-building hue jitter so equal palette entries never look identical
    jit = g.mapr(g.white(g.comb(var, 3.1, 0.0)), 0.0, 1.0, 0.92, 1.06)
    base = g.scale_col(base, jit)
    t = g.pbr("plastered_wall_04", _uvs(g, 3.2))
    col = g.detail(base, t["col"], 0.9, 0.52)
    # weathering: patches where the plaster has fallen off and brick shows
    patch = g.pbr("red_brick_plaster_patch_02", _uvs(g, 1.5))
    n_patch = g.noise(p, 0.18, 6, 0.65, distortion=0.4)
    low = g.mapr(v, 0.0, 2.2, 0.18, 0.0)
    pm = g.mapr(g.m("ADD", n_patch, low), 0.66, 0.74, 0.0, 1.0)
    pm = g.m("MULTIPLY", pm, g.mapr(var, 0.0, 1.0, 0.4, 1.3))
    if patch["col"] is not None:
        col = g.mixc(g.m("MINIMUM", pm, 1.0), col, patch["col"])
    # rain streaks from sills/eaves and rising damp at the foot of the wall
    streak = g.noise(g.vscale(p, (1.0, 1.0, 0.08)), 2.2, 3, 0.5)
    stain = g.noise(p, 0.35, 5, 0.6)
    dirt = g.mapr(g.m("ADD", stain, g.m("MULTIPLY", streak, 0.6)), 0.55, 1.1, 1.0, 0.70)
    damp = g.mapr(v, 0.0, 1.3, 0.62, 1.0)
    col = g.scale_col(col, g.m("MULTIPLY", dirt, damp))
    rough = 0.9
    if t["rough"] is not None:
        rough = g.mapr(t["rough"], 0.0, 1.0, 0.75, 1.0)
    nrm = t["nrm"]
    height = None
    if windows:
        fac = g.attr("fac")
        wlen = g.attr("wlen")
        upper, shop, cell = _windows(g, u, v, fac, wlen)
        rnd = g.white(cell)
        shutter = g.m("GREATER_THAN", rnd, 0.55)
        wcol = g.mixc(shutter, s2l((0.05, 0.04, 0.035)), s2l((0.30, 0.20, 0.12)))
        col = g.mixc(upper, col, wcol)
        col = g.mixc(shop, col, s2l((0.035, 0.03, 0.028)))
        height = g.m("MULTIPLY", g.m("MAXIMUM", upper, shop), -1.0)
    g.bsdf(col, rough, height, 0.35, 0.05, ao=0.45, ao_dist=2.0, normal_map=nrm, nm_strength=0.8)
    return mat


def mat_brick(name="TL_Brick", windows=False):
    """Opus latericium: photo brick (scaled to thin Roman bricks) tinted per building."""
    mat, g = _new(name)
    uvv = g.uv()
    u, v, _ = g.sep(uvv)
    var = g.attr("var")
    p = g.pos()
    # medieval_red_brick covers 2 m; squash vertically so courses read ~5.5 cm thick
    vec = g.vscale(uvv, (1.0 / 2.2, 1.0 / 1.25, 1.0))
    t = g.pbr("medieval_red_brick", vec)
    tint = g.ramp(var, [(0.0, (1.0, 0.86, 0.78)), (0.5, (0.94, 0.80, 0.70)), (1.0, (1.0, 0.92, 0.84))])
    if t["col"] is not None:
        col = g.mixc(1.0, t["col"], tint, blend="MULTIPLY")
        nrm, rough, height = t["nrm"], g.mapr(t["rough"], 0, 1, 0.7, 1.0) if t["rough"] else 0.88, None
    else:
        br = g.n("ShaderNodeTexBrick", offset=0.5, offset_frequency=2)
        g.link(uvv, br.inputs["Vector"])
        br.inputs["Scale"].default_value = 1.0
        br.inputs["Mortar Size"].default_value = 0.009
        br.inputs["Brick Width"].default_value = 0.40
        br.inputs["Row Height"].default_value = 0.058
        br.inputs["Color1"].default_value = s2l((0.60, 0.33, 0.20))
        br.inputs["Color2"].default_value = s2l((0.50, 0.28, 0.18))
        br.inputs["Mortar"].default_value = s2l((0.58, 0.54, 0.48))
        col, nrm, rough = br.outputs["Color"], None, 0.88
        height = g.m("SUBTRACT", 1.0, br.outputs["Fac"])
    stain = g.noise(p, 0.4, 5, 0.6)
    col = g.scale_col(col, g.mapr(stain, 0.35, 0.8, 1.08, 0.78))
    col = g.scale_col(col, g.mapr(v, 0.0, 1.2, 0.72, 1.0))
    if windows:
        fac = g.attr("fac")
        wlen = g.attr("wlen")
        upper, shop, cell = _windows(g, u, v, fac, wlen)
        col = g.mixc(g.m("MAXIMUM", upper, shop), col, s2l((0.04, 0.035, 0.03)))
    g.bsdf(col, rough, height, 0.4, 0.02, ao=0.45, ao_dist=2.0, normal_map=nrm, nm_strength=0.9)
    return mat


def mat_ashlar(name="TL_Ashlar", tint=(0.80, 0.74, 0.62), block=(1.2, 0.55)):
    """Squared limestone/tuff blocks: procedural coursing + photo stone surface."""
    mat, g = _new(name)
    uvv = g.uv()
    _, v, _ = g.sep(uvv)
    var = g.attr("var")
    p = g.pos()
    br = g.n("ShaderNodeTexBrick", offset=0.5, offset_frequency=2)
    g.link(uvv, br.inputs["Vector"])
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = 0.010
    br.inputs["Mortar Smooth"].default_value = 0.3
    br.inputs["Brick Width"].default_value = block[0]
    br.inputs["Row Height"].default_value = block[1]
    br.inputs["Color1"].default_value = (1, 1, 1, 1)
    br.inputs["Color2"].default_value = (0.86, 0.85, 0.83, 1)
    br.inputs["Mortar"].default_value = (0.55, 0.54, 0.52, 1)
    t = g.pbr("large_sandstone_blocks_01", _uvs(g, 3.0))
    base = g.scale_col(s2l(tint), g.mapr(var, 0, 1, 0.92, 1.06))
    col = g.detail(base, t["col"], 0.35, 0.45)
    col = g.mixc(1.0, col, br.outputs["Color"], blend="MULTIPLY")
    stain = g.noise(p, 0.25, 6, 0.62)
    streak = g.noise(g.vscale(p, (1.0, 1.0, 0.15)), 2.0, 3)
    col = g.scale_col(col, g.mapr(stain, 0.3, 0.8, 1.05, 0.84))
    col = g.scale_col(col, g.mapr(streak, 0.4, 0.75, 1.03, 0.90))
    col = g.scale_col(col, g.mapr(v, 0.0, 1.5, 0.78, 1.0))
    height = g.m("MULTIPLY", g.m("SUBTRACT", 1.0, br.outputs["Fac"]), 0.8)
    rough = g.mapr(t["rough"], 0, 1, 0.7, 1.0) if t["rough"] else 0.85
    g.bsdf(col, rough, height, 0.5, 0.03, ao=0.45, ao_dist=2.5, normal_map=t["nrm"], nm_strength=0.9)
    return mat


def mat_marble(name="TL_Marble"):
    mat, g = _new(name)
    p = g.pos()
    var = g.attr("var")
    vein = g.noise(p, 0.8, 8, 0.65, distortion=1.5)
    veinl = g.mapr(g.m("ABSOLUTE", g.m("SUBTRACT", vein, 0.5)), 0.0, 0.035, 0.86, 1.0)
    base = g.ramp(var, [(0.0, (0.80, 0.77, 0.70)), (1.0, (0.76, 0.72, 0.64))])
    t = g.pbr("plastered_wall_04", g.vscale(p, 1.0 / 2.0), box=True)
    col = g.detail(base, t["col"], 0.35, 0.52)
    dirt = g.noise(g.vscale(p, (1, 1, 0.2)), 1.2, 4)
    grime = g.mapr(g.m("ADD", dirt, g.mapr(g.sep(p)[2], 0.0, 4.0, 0.25, 0.0)), 0.45, 0.95, 1.04, 0.70)
    col = g.scale_col(col, g.m("MULTIPLY", veinl, grime))
    g.bsdf(col, 0.38, g.noise(p, 20.0, 3), 0.06, 0.01, ao=0.35, ao_dist=1.0)
    return mat


def mat_travertine(name="TL_Travertine", tint=(0.82, 0.77, 0.66), slabs=False):
    mat, g = _new(name)
    p = g.pos()
    uvv = g.uv()
    var = g.attr("var")
    if slabs:
        t = g.pbr("marble_01", g.vscale(p, 1.0 / 1.5))
    else:
        t = g.pbr("large_sandstone_blocks_01", _uvs(g, 3.0))
    band = g.noise(g.vscale(p, (0.15, 0.15, 3.0)), 1.0, 4)
    pores = g.noise(g.vscale(p, (1.0, 1.0, 3.0)), 18.0, 2)
    porem = g.mapr(pores, 0.62, 0.70, 1.0, 0.78)
    base = g.scale_col(s2l(tint), g.m("MULTIPLY", g.mapr(band, 0.3, 0.7, 0.93, 1.05), porem))
    base = g.scale_col(base, g.mapr(var, 0, 1, 0.92, 1.05))
    col = g.detail(base, t["col"], 0.75 if slabs else 0.6, 0.62 if slabs else 0.45)
    height = None
    if slabs and t["col"] is None:
        br = g.n("ShaderNodeTexBrick", offset=0.5)
        g.link(uvv, br.inputs["Vector"])
        br.inputs["Brick Width"].default_value = 1.6
        br.inputs["Row Height"].default_value = 0.9
        col = g.mixc(1.0, col, br.outputs["Color"], blend="MULTIPLY")
        height = br.outputs["Fac"]
    if slabs:
        # large paving slabs (~1.8 x 1.2 m, estimate) with per-slab tone and dark joints
        br = g.n("ShaderNodeTexBrick", offset=0.5, offset_frequency=1)
        g.link(p, br.inputs["Vector"])
        br.inputs["Scale"].default_value = 1.0
        br.inputs["Mortar Size"].default_value = 0.012
        br.inputs["Brick Width"].default_value = 1.8
        br.inputs["Row Height"].default_value = 1.2
        br.inputs["Bias"].default_value = 0.0
        br.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1)
        br.inputs["Color2"].default_value = (0.84, 0.82, 0.78, 1)
        br.inputs["Mortar"].default_value = (0.45, 0.42, 0.38, 1)
        col = g.mixc(1.0, col, br.outputs["Color"], blend="MULTIPLY")
        height = br.outputs["Fac"]
    stain = g.noise(p, 0.3, 5)
    col = g.scale_col(col, g.mapr(stain, 0.35, 0.8, 1.06, 0.78))
    rough = g.mapr(t["rough"], 0, 1, 0.65, 0.95) if t["rough"] else 0.8
    g.bsdf(col, rough, height, 0.3, 0.01, ao=0.45, ao_dist=1.5, normal_map=t["nrm"], nm_strength=0.7)
    return mat


def mat_tile(name="TL_Tile"):
    """Roman tegulae + imbrices. The ridges are real geometry (tl_mesh roof tiling);
    the photo map adds per-tile colour, chips and the course overlaps."""
    mat, g = _new(name)
    uvv = g.uv()
    u, v, _ = g.sep(uvv)
    var = g.attr("var")
    p = g.pos()
    t = g.pbr("clay_roof_tiles_02", _uvs(g, 6.3))
    cell = g.comb(g.m("FLOOR", g.m("DIVIDE", u, 0.42)), g.m("FLOOR", g.m("DIVIDE", v, 0.6)),
                  g.m("FLOOR", g.m("MULTIPLY", var, 97.0)))
    tilev = g.mapr(g.white(cell), 0, 1, 0.84, 1.12)
    base = g.ramp(var, [(0.0, (0.60, 0.36, 0.25)), (0.25, (0.66, 0.42, 0.29)), (0.45, (0.55, 0.34, 0.25)),
                        (0.65, (0.62, 0.47, 0.37)), (0.82, (0.50, 0.33, 0.26)), (1.0, (0.58, 0.40, 0.31))])
    col = g.detail(base, t["col"], 0.75, 0.42)
    col = g.scale_col(col, tilev)
    lich = g.noise(p, 0.6, 6, 0.65)
    lichm = g.mapr(lich, 0.52, 0.76, 0.0, 0.6)
    col = g.mixc(lichm, col, s2l((0.40, 0.37, 0.30)))
    soot = g.noise(p, 0.12, 3)
    col = g.scale_col(col, g.mapr(soot, 0.4, 0.75, 1.06, 0.80))
    course = g.m("MULTIPLY", g.m("FRACT", g.m("DIVIDE", v, 0.6)), 0.5)
    rough = g.mapr(t["rough"], 0, 1, 0.6, 0.95) if t["rough"] else 0.78
    g.bsdf(col, rough, course, 0.35, 0.03, ao=0.4, ao_dist=0.8, normal_map=t["nrm"], nm_strength=0.5)
    return mat


def mat_lead(name="TL_Lead"):
    mat, g = _new(name)
    uvv = g.uv()
    u, v, _ = g.sep(uvv)
    p = g.pos()
    seam = g.m("POWER", g.m("ABSOLUTE", g.m("SINE", g.m("MULTIPLY", u, 3.14159 / 0.9))), 30.0)
    patina = g.noise(p, 0.5, 5)
    col = g.scale_col(s2l((0.47, 0.49, 0.50)), g.mapr(patina, 0.3, 0.8, 1.1, 0.80))
    col = g.mixc(g.mapr(g.noise(p, 0.15, 4), 0.55, 0.7, 0.0, 0.35), col, s2l((0.58, 0.62, 0.58)))
    g.bsdf(col, 0.55, seam, 0.3, 0.05, metallic=0.25, spec=0.4, ao=0.6)
    return mat


def mat_timber(name="TL_Timber", tint=(1.0, 0.95, 0.9)):
    mat, g = _new(name)
    uvv = g.uv()
    p = g.pos()
    var = g.attr("var")
    t = g.pbr("weathered_brown_planks", _uvs(g, 1.8))
    if t["col"] is not None:
        col = g.mixc(1.0, t["col"], s2l(tint), blend="MULTIPLY")
    else:
        grain = g.noise(g.vscale(g.comb(*g.sep(uvv)[:2], 0.0), (0.4, 8.0, 1.0)), 3.0, 5, 0.6)
        col = g.scale_col(s2l((0.36, 0.26, 0.18)), g.mapr(grain, 0.3, 0.7, 0.75, 1.1))
    weather = g.mapr(var, 0, 1, 0.0, 0.35)
    col = g.mixc(weather, col, s2l((0.42, 0.39, 0.35)))
    col = g.scale_col(col, g.mapr(g.noise(p, 0.8, 3), 0.3, 0.8, 1.1, 0.8))
    rough = g.mapr(t["rough"], 0, 1, 0.7, 1.0) if t["rough"] else 0.85
    g.bsdf(col, rough, None, ao=0.45, normal_map=t["nrm"], nm_strength=0.8)
    return mat


def mat_simple(name, color, rough=0.9, bump_scale=6.0, bump=0.2, var_range=0.15, ao=0.55, tex=None,
               tex_size=2.0, tex_amt=0.7):
    mat, g = _new(name)
    p = g.pos()
    var = g.attr("var")
    n1 = g.noise(p, 0.5, 4)
    col = g.scale_col(s2l(color), g.m("MULTIPLY", g.mapr(var, 0, 1, 1 - var_range, 1 + var_range),
                                      g.mapr(n1, 0.3, 0.7, 0.9, 1.08)))
    nrm = None
    if tex:
        t = g.pbr(tex, g.vscale(p, 1.0 / tex_size), box=True)
        col = g.detail(col, t["col"], tex_amt, 0.42)
    g.bsdf(col, rough, g.noise(p, bump_scale, 4) if bump else None, bump, 0.02, ao=ao, normal_map=nrm)
    return mat


def mat_bark(name="TL_Bark"):
    mat, g = _new(name)
    p = g.pos()
    t = g.pbr("bark_brown_02", g.vscale(p, (1.0 / 0.8, 1.0 / 0.8, 1.0 / 1.6)), box=True)
    col = s2l((0.30, 0.25, 0.20))
    col = g.detail(col, t["col"], 0.9, 0.35)
    g.bsdf(col, 0.95, g.noise(p, 8.0, 4), 0.5, 0.03, ao=0.5)
    return mat


def mat_leaves(name, c0, c1, density=5.0, leaf=0.42, trans=0.25, sheen=(0.0, 0.0, 0.0)):
    """Leaf-card material: procedural leaf clusters cut out with alpha (dithered),
    per-instance and per-card colour variation, translucency."""
    mat, g = _new(name)
    try:
        mat.surface_render_method = "DITHERED"
    except Exception:
        pass
    try:
        mat.use_transparent_shadow = not FAST
    except Exception:
        pass
    uvv = g.uv()
    u, v, _ = g.sep(uvv)
    # radial card mask broken by noise -> irregular cluster outline
    du, dv = g.m("SUBTRACT", u, 0.5), g.m("SUBTRACT", v, 0.5)
    rad = g.m("SQRT", g.m("ADD", g.m("MULTIPLY", du, du), g.m("MULTIPLY", dv, dv)))
    edge = g.noise(g.vscale(uvv, 3.0), 2.5, 3, 0.6)
    rmask = g.m("LESS_THAN", g.m("ADD", rad, g.m("MULTIPLY", g.m("SUBTRACT", edge, 0.5), 0.35)), 0.47)
    vor = g.n("ShaderNodeTexVoronoi", feature="F1")
    g.link(uvv, vor.inputs["Vector"])
    vor.inputs["Scale"].default_value = density
    vor.inputs["Randomness"].default_value = 1.0
    lmask = g.m("LESS_THAN", vor.outputs["Distance"], leaf)
    alpha = g.m("MULTIPLY", rmask, lmask)
    rnd_inst = g.objrand()
    leafrnd = g.white(g.vscale(vor.outputs["Position"], 1.0), dims="3D")
    vcol = g.attr("var")
    base = g.mixc(g.m("FRACT", g.m("ADD", rnd_inst, g.m("MULTIPLY", vcol, 0.6))), s2l(c0), s2l(c1))
    col = g.scale_col(base, g.mapr(leafrnd, 0, 1, 0.72, 1.18))
    # darker towards the centre of the crown: approximated by per-card 'var' depth (0 inner, 1 outer)
    col = g.scale_col(col, g.mapr(vcol, 0.0, 1.0, 0.55, 1.08))
    b = g.bsdf(col, 0.62, None, spec=0.35, out=False)
    tr = g.n("ShaderNodeBsdfTranslucent")
    g.link(col, tr.inputs["Color"])
    mixs = g.n("ShaderNodeMixShader")
    mixs.inputs[0].default_value = trans
    g.link(b.outputs[0], mixs.inputs[1])
    g.link(tr.outputs[0], mixs.inputs[2])
    from tl_scene import haze_group
    hz = g.n("ShaderNodeGroup")
    hz.node_tree = haze_group()           # haze BEFORE the cut-out (apply_haze then skips)
    g.link(mixs.outputs[0], hz.inputs[0])
    tp = g.n("ShaderNodeBsdfTransparent")
    cut = g.n("ShaderNodeMixShader")
    g.link(alpha, cut.inputs[0])
    g.link(tp.outputs[0], cut.inputs[1])
    g.link(hz.outputs[0], cut.inputs[2])
    o = g.n("ShaderNodeOutputMaterial")
    g.link(cut.outputs[0], o.inputs["Surface"])
    return mat


def mat_foliage(name="TL_Foliage", c0=(0.17, 0.23, 0.10), c1=(0.24, 0.27, 0.13)):
    """Solid foliage (hedges, garden beds seen from afar)."""
    mat, g = _new(name)
    p = g.pos()
    var = g.attr("var")
    base = g.mixc(var, s2l(c0), s2l(c1))
    clump = g.noise(p, 2.2, 6, 0.7)
    leaf = g.noise(p, 14.0, 3, 0.6)
    col = g.scale_col(base, g.m("MULTIPLY", g.mapr(clump, 0.35, 0.7, 0.55, 1.2), g.mapr(leaf, 0.3, 0.7, 0.8, 1.1)))
    h = g.m("ADD", clump, g.m("MULTIPLY", leaf, 0.5))
    g.bsdf(col, 0.75, h, 0.9, 0.25, spec=0.35, ao=0.25, ao_dist=3.0)
    return mat


def mat_ground(name="TL_Ground"):
    """Terrain: point attributes fld (fields), urb (inside walls), rock (slope), shore (beach),
    vine (vineyard plots)."""
    mat, g = _new(name)
    p = g.pos()
    fld = g.attr("fld")
    urb = g.attr("urb")
    rock = g.attr("rock")
    shore = g.attr("shore")
    n_big = g.noise(p, 0.004, 4, 0.55)
    n_mid = g.noise(p, 0.03, 5, 0.6)
    # photographic grass/rock ground at two scales to hide tiling
    t1 = g.pbr("aerial_grass_rock", _wxy(g, 37.0))
    t2 = g.pbr("aerial_grass_rock", _wxy(g, 160.0, (311.0, 97.0, 0.0)))
    grass = g.ramp(n_big, [(0.3, (0.31, 0.34, 0.17)), (0.5, (0.38, 0.40, 0.21)), (0.7, (0.47, 0.45, 0.27))])
    scrub = g.mapr(g.noise(p, 0.025, 6, 0.65), 0.45, 0.62, 0.0, 0.55)       # patches of darker maquis
    grass = g.mixc(scrub, grass, s2l((0.17, 0.21, 0.10)))
    grass = g.detail(grass, t1["col"], 0.65, 0.40)
    grass = g.detail(grass, t2["col"], 0.45, 0.40)
    grass = g.scale_col(grass, g.mapr(n_mid, 0.3, 0.7, 0.82, 1.1))
    pxy = g.sep(p)
    ku = g.m("DIVIDE", g.m("ADD", pxy[0], 3.0), 88.75)
    kv = g.m("DIVIDE", g.m("ADD", pxy[1], 7.0), 44.4)
    cellid = g.comb(g.m("FLOOR", ku), g.m("FLOOR", kv), 0.0)
    rnd = g.white(cellid)
    crop = g.ramp(rnd, [(0.0, (0.46, 0.36, 0.24)), (0.18, (0.60, 0.50, 0.28)), (0.36, (0.33, 0.37, 0.17)),
                        (0.54, (0.50, 0.38, 0.27)), (0.72, (0.68, 0.58, 0.34)), (0.88, (0.40, 0.42, 0.22)),
                        (1.0, (0.28, 0.32, 0.16))])
    td = g.pbr("dirt", _wxy(g, 6.0))
    crop = g.detail(crop, td["col"], 0.5, 0.35)
    vrow = g.noise(g.vscale(p, (0.15, 2.5, 1.0)), 0.8, 2)
    crop = g.scale_col(crop, g.mapr(vrow, 0.3, 0.7, 0.90, 1.07))
    furrow = g.m("ABSOLUTE", g.m("SINE", g.m("MULTIPLY", pxy[1], 6.0)))
    crop = g.scale_col(crop, g.mapr(furrow, 0.0, 1.0, 0.86, 1.04))
    eu = g.m("ABSOLUTE", g.m("SUBTRACT", g.m("FRACT", ku), 0.5))
    ev = g.m("ABSOLUTE", g.m("SUBTRACT", g.m("FRACT", kv), 0.5))
    edge = g.m("MAXIMUM", g.mapr(eu, 0.475, 0.495, 0.0, 1.0), g.mapr(ev, 0.455, 0.49, 0.0, 1.0))
    crop = g.mixc(edge, crop, s2l((0.30, 0.31, 0.18)))
    lu = g.m("ABSOLUTE", g.m("SUBTRACT", g.m("FRACT", g.m("DIVIDE", g.m("ADD", pxy[0], 3.0), 710.0)), 0.5))
    lv = g.m("ABSOLUTE", g.m("SUBTRACT", g.m("FRACT", g.m("DIVIDE", g.m("ADD", pxy[1], 7.0), 710.4)), 0.5))
    lim = g.m("MAXIMUM", g.mapr(lu, 0.4955, 0.4975, 0.0, 1.0), g.mapr(lv, 0.4955, 0.4975, 0.0, 1.0))
    crop = g.mixc(lim, crop, s2l((0.60, 0.53, 0.40)))
    col = g.mixc(fld, grass, crop)
    town = g.detail(s2l((0.50, 0.44, 0.35)), td["col"], 0.7, 0.35)
    col = g.mixc(urb, col, town)
    pz = pxy[2]
    patch = g.noise(p, 0.006, 5, 0.6)
    wood = g.m("MULTIPLY", g.mapr(pz, 25.0, 70.0, 0.0, 1.0), g.mapr(patch, 0.38, 0.55, 0.0, 1.0))
    woodc = g.scale_col(s2l((0.20, 0.24, 0.13)), g.mapr(g.noise(p, 0.08, 4), 0.3, 0.7, 0.65, 1.15))
    woodc = g.detail(woodc, t1["col"], 0.5, 0.4)
    col = g.mixc(g.m("MINIMUM", wood, 0.92), col, woodc)
    tr = g.pbr("aerial_rocks_02", _wxy(g, 120.0))
    rockc = g.detail(s2l((0.56, 0.53, 0.47)), tr["col"], 0.9, 0.42)
    col = g.mixc(g.m("MULTIPLY", rock, 0.85), col, rockc)
    ts = g.pbr("coast_sand_01", _wxy(g, 25.0))
    sand = g.detail(s2l((0.72, 0.64, 0.50)), ts["col"], 0.7, 0.5)
    wet = g.mapr(pz, -0.9, 0.2, 0.55, 1.0)
    sand = g.scale_col(sand, wet)
    col = g.mixc(shore, col, sand)
    g.bsdf(col, 0.95, g.noise(p, 0.5, 6, 0.6), 0.5, 0.6, spec=0.3, ao=0.65, ao_dist=4.0,
           normal_map=t1["nrm"], nm_strength=0.5)
    return mat


def mat_paving(name="TL_Paving"):
    """Roman basalt (selce) polygonal paving for streets, with dust in the joints."""
    mat, g = _new(name)
    p = g.pos()
    vor = g.n("ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE")
    g.link(p, vor.inputs["Vector"])
    vor.inputs["Scale"].default_value = 1.5
    joint = g.mapr(vor.outputs["Distance"], 0.0, 0.07, 0.0, 1.0)
    vc = g.n("ShaderNodeTexVoronoi", feature="F1")
    g.link(p, vc.inputs["Vector"])
    vc.inputs["Scale"].default_value = 1.5
    stonev = g.mapr(g.white(vc.outputs["Position"]), 0, 1, 0.80, 1.18)
    t = g.pbr("cobblestone_large_01", _wxy(g, 9.0))
    base = g.mixc(g.noise(p, 0.05, 3), s2l((0.33, 0.32, 0.30)), s2l((0.42, 0.40, 0.37)))
    base = g.detail(base, t["col"], 0.45, 0.45)
    dust = g.mapr(g.noise(p, 0.15, 4), 0.35, 0.7, 0.0, 0.55)
    base = g.mixc(dust, base, s2l((0.52, 0.46, 0.36)))
    col = g.scale_col(base, stonev)
    col = g.mixc(g.m("SUBTRACT", 1.0, joint), col, s2l((0.40, 0.35, 0.28)))
    # cart ruts: two worn, polished bands along the street axes (world-aligned grid streets)
    g.bsdf(col, g.mapr(joint, 0, 1, 0.9, 0.62), joint, 0.6, 0.04, ao=0.55, normal_map=t["nrm"], nm_strength=0.4)
    return mat


def mat_water(name="TL_Water"):
    mat, g = _new(name)
    p = g.pos()
    w1 = g.noise(g.vscale(p, (1.0, 2.6, 1.0)), 0.35, 5, 0.55)
    w2 = g.noise(g.vscale(p, (1.0, 1.6, 1.0)), 2.2, 3, 0.5)
    w3 = g.noise(p, 9.0, 2, 0.5)
    h = g.m("ADD", g.m("ADD", w1, g.m("MULTIPLY", w2, 0.45)), g.m("MULTIPLY", w3, 0.15))
    tint = g.noise(p, 0.004, 3)
    col = g.mixc(g.mapr(tint, 0.3, 0.7, 0, 1), s2l((0.05, 0.14, 0.16)), s2l((0.09, 0.18, 0.18)))
    # shallow water near the shore is lighter (depth attribute written by the terrain)
    depth = g.attr("depth")
    col = g.mixc(g.mapr(depth, 0.0, 4.0, 0.7, 0.0), col, s2l((0.22, 0.30, 0.26)))
    foam = g.m("MULTIPLY", g.mapr(depth, 0.0, 0.6, 1.0, 0.0), g.mapr(g.noise(p, 0.6, 4), 0.45, 0.6, 0.0, 1.0))
    col = g.mixc(g.m("MULTIPLY", foam, 0.6), col, s2l((0.75, 0.76, 0.72)))
    rough = g.mapr(g.noise(p, 0.01, 3), 0.3, 0.7, 0.03, 0.12)
    b = g.bsdf(col, rough, h, 0.35, 0.5, spec=0.5)
    b.inputs["IOR"].default_value = 1.33
    return mat


def mat_cloth(name, c0, c1, stripes=False):
    mat, g = _new(name)
    uvv = g.uv()
    u, v, _ = g.sep(uvv)
    var = g.attr("var")
    p = g.pos()
    base = g.mixc(var, s2l(c0), s2l(c1))
    if stripes:
        st = g.m("GREATER_THAN", g.m("FRACT", g.m("DIVIDE", u, 0.5)), 0.5)
        base = g.mixc(g.m("MULTIPLY", st, 0.55), base, s2l((0.88, 0.84, 0.74)))
    base = g.scale_col(base, g.mapr(g.noise(p, 1.0, 4), 0.3, 0.7, 0.82, 1.05))
    b = g.bsdf(base, 0.9, g.noise(g.vscale(uvv, (6.0, 0.6, 1.0)), 2.0, 2), 0.15, 0.03, spec=0.2, out=False)
    tr = g.n("ShaderNodeBsdfTranslucent")
    g.link(base, tr.inputs["Color"])
    ms = g.n("ShaderNodeMixShader")
    ms.inputs[0].default_value = 0.3
    g.link(b.outputs[0], ms.inputs[1])
    g.link(tr.outputs[0], ms.inputs[2])
    o = g.n("ShaderNodeOutputMaterial")
    g.link(ms.outputs[0], o.inputs["Surface"])
    return mat


def mat_sail(name="TL_Sail"):
    return mat_cloth(name, (0.80, 0.74, 0.62), (0.74, 0.66, 0.52))


def mat_dark(name="TL_Dark", color=(0.06, 0.05, 0.045)):
    return mat_simple(name, color, rough=0.95, bump=0.0, var_range=0.15, ao=None)


def mat_terracotta(name="TL_Terracotta"):
    return mat_simple(name, (0.66, 0.40, 0.27), rough=0.8, bump_scale=10.0, bump=0.1, var_range=0.18,
                      tex="dirt", tex_size=1.0, tex_amt=0.4)


BUILDERS = {
    "TL_Plaster": lambda: mat_plaster("TL_Plaster", windows=True),
    "TL_PlasterWall": lambda: mat_plaster("TL_PlasterWall", windows=False),
    "TL_PlasterPlain": lambda: mat_plaster("TL_PlasterPlain", windows=False, plain=True),
    "TL_Brick": lambda: mat_brick("TL_Brick", windows=False),
    "TL_BrickWin": lambda: mat_brick("TL_BrickWin", windows=True),
    "TL_Ashlar": lambda: mat_ashlar("TL_Ashlar", tint=(0.70, 0.64, 0.54)),
    "TL_AshlarGrey": lambda: mat_ashlar("TL_AshlarGrey", tint=(0.66, 0.64, 0.60), block=(1.0, 0.5)),
    "TL_Marble": mat_marble,
    "TL_Travertine": lambda: mat_travertine("TL_Travertine"),
    "TL_TravertineSlabs": lambda: mat_travertine("TL_TravertineSlabs", tint=(0.80, 0.75, 0.64), slabs=True),
    "TL_Tile": mat_tile,
    "TL_Lead": mat_lead,
    "TL_Timber": mat_timber,
    "TL_TimberDark": lambda: mat_timber("TL_TimberDark", tint=(0.55, 0.45, 0.38)),
    "TL_Shutter": lambda: mat_timber("TL_Shutter", tint=(0.75, 0.62, 0.48)),
    "TL_Foliage": mat_foliage,
    "TL_Cypress": lambda: mat_foliage("TL_Cypress", (0.09, 0.14, 0.07), (0.13, 0.17, 0.09)),
    "TL_Olive": lambda: mat_foliage("TL_Olive", (0.30, 0.34, 0.24), (0.37, 0.40, 0.30)),
    "TL_Bark": mat_bark,
    "TL_Ground": mat_ground,
    "TL_Paving": mat_paving,
    "TL_Earth": lambda: mat_simple("TL_Earth", (0.52, 0.45, 0.35), rough=0.97, bump_scale=3.0, bump=0.3,
                                   tex="dirt", tex_size=3.0),
    "TL_Garden": lambda: mat_foliage("TL_Garden", (0.30, 0.34, 0.16), (0.42, 0.42, 0.22)),
    "TL_Water": mat_water,
    "TL_Sail": mat_sail,
    "TL_Dark": mat_dark,
    "TL_ShopDark": lambda: mat_dark("TL_ShopDark", (0.10, 0.075, 0.055)),
    "TL_Bronze": lambda: mat_simple("TL_Bronze", (0.30, 0.36, 0.30), rough=0.45, bump=0.1, var_range=0.05),
    "TL_Terracotta": mat_terracotta,
    "TL_Cloth": lambda: mat_cloth("TL_Cloth", (0.86, 0.80, 0.66), (0.80, 0.70, 0.55)),
    "TL_ClothRed": lambda: mat_cloth("TL_ClothRed", (0.62, 0.24, 0.16), (0.70, 0.45, 0.20), stripes=True),
    "TL_LeafCypress": lambda: mat_leaves("TL_LeafCypress", (0.07, 0.12, 0.05), (0.12, 0.17, 0.08), 7.0, 0.48),
    "TL_LeafPine": lambda: mat_leaves("TL_LeafPine", (0.12, 0.18, 0.07), (0.20, 0.25, 0.10), 9.0, 0.40),
    "TL_LeafOlive": lambda: mat_leaves("TL_LeafOlive", (0.30, 0.34, 0.24), (0.42, 0.45, 0.33), 8.0, 0.38, 0.2),
    "TL_LeafBroad": lambda: mat_leaves("TL_LeafBroad", (0.16, 0.24, 0.08), (0.30, 0.34, 0.13), 6.0, 0.42),
    "TL_LeafShrub": lambda: mat_leaves("TL_LeafShrub", (0.20, 0.25, 0.11), (0.38, 0.38, 0.18), 7.0, 0.44),
    "TL_LeafGrass": lambda: mat_leaves("TL_LeafGrass", (0.40, 0.40, 0.19), (0.56, 0.52, 0.30), 12.0, 0.36, 0.3),
    "TL_LeafVine": lambda: mat_leaves("TL_LeafVine", (0.24, 0.32, 0.10), (0.42, 0.42, 0.14), 6.0, 0.45),
}


def get_material(name: str):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    if name not in BUILDERS:
        raise KeyError(f"unknown material {name}")
    mat = BUILDERS[name]()
    from tl_scene import apply_haze
    apply_haze(mat)
    return mat
