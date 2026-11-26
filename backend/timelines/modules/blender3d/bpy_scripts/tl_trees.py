"""Mediterranean trees from leaf cards (runs inside Blender).

Each tree = modelled trunk/branches (TL_Bark) + a few hundred small cards with a
procedural leaf-cluster alpha (TL_Leaf* materials, dithered). Card face attribute
``var`` stores the radial depth in the crown (0 inside, 1 outside) so inner foliage
is darker. In cities, a few prototypes per species are built once and instanced
with Geometry Nodes (``TreeScatter``) - thousands of trees for the cost of a few.

Species shapes (estimates from the living species): Italian cypress (Cupressus
sempervirens, narrow spindle), stone/umbrella pine (Pinus pinea, flat crown on a bare
trunk), olive (Olea europaea, gnarled multi-stem, grey-green), broadleaf (oak/plane),
shrubs (maquis), grape vines in rows.
"""
from __future__ import annotations

import math
import random

import bpy
from mathutils import Vector

from tl_buildings import beam
from tl_mesh import MeshBuilder

TAU = math.tau
LEAF_MAT = {"cypress": "TL_LeafCypress", "pine": "TL_LeafPine", "olive": "TL_LeafOlive",
            "broadleaf": "TL_LeafBroad", "shrub": "TL_LeafShrub", "grass": "TL_LeafGrass"}


def _card(mb, c, size, rng, mat, depth, normal_bias=None, bias=0.5):
    """Random-oriented square card centred at c (local)."""
    n = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
    if normal_bias is not None:
        n = n.normalized() * (1 - bias) + Vector(normal_bias).normalized() * bias
    if n.length < 1e-4:
        n = Vector((0, 0, 1))
    n.normalize()
    ref = Vector((0, 0, 1)) if abs(n.z) < 0.9 else Vector((1, 0, 0))
    t1 = n.cross(ref).normalized()
    t2 = n.cross(t1).normalized()
    a = rng.uniform(0, TAU)
    t1, t2 = t1 * math.cos(a) + t2 * math.sin(a), -t1 * math.sin(a) + t2 * math.cos(a)
    h = size / 2
    c = Vector(c)
    pts = [c - t1 * h - t2 * h, c + t1 * h - t2 * h, c + t1 * h + t2 * h, c - t1 * h + t2 * h]
    mb.var = max(0.0, min(1.0, depth))
    mb.poly([tuple(p) for p in pts], mat, uvs=[(0, 0), (1, 0), (1, 1), (0, 1)])


def _trunk(mb, pts, r0, r1, segs=6):
    """Tapered trunk/branch through pts (local)."""
    n = len(pts) - 1
    for i in range(n):
        ra = r0 + (r1 - r0) * i / n
        rb = r0 + (r1 - r0) * (i + 1) / n
        a, b = Vector(pts[i]), Vector(pts[i + 1])
        d = (b - a)
        if d.length < 1e-4:
            continue
        u = d.normalized()
        ref = Vector((1, 0, 0)) if abs(u.z) > 0.9 else Vector((0, 0, 1))
        s1 = u.cross(ref).normalized()
        s2 = u.cross(s1).normalized()
        ra_, rb_ = [], []
        for k in range(segs):
            ang = TAU * k / segs
            off = s1 * math.cos(ang) + s2 * math.sin(ang)
            ra_.append(a + off * ra)
            rb_.append(b + off * rb)
        L = d.length
        for k in range(segs):
            k2 = (k + 1) % segs
            mb.poly([tuple(ra_[k]), tuple(ra_[k2]), tuple(rb_[k2]), tuple(rb_[k])], "TL_Bark", smooth=True,
                    uvs=[(k * 0.2, 0), ((k + 1) * 0.2, 0), ((k + 1) * 0.2, L), (k * 0.2, L)])


def _clump(mb, rng, center, rx, ry, rz, n, size, mat, crown_c, crown_r, up_bias=0.0):
    for _ in range(n):
        while True:
            v = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
            if v.length <= 1.0:
                break
        r = v.length
        v = Vector((v.x * rx, v.y * ry, v.z * rz))
        p = Vector(center) + v * (0.55 + 0.45 * r ** 0.5)
        depth = min(1.0, (p - Vector(crown_c)).length / max(crown_r, 1e-3))
        out = p - Vector(crown_c)
        _card(mb, p, size * rng.uniform(0.75, 1.25), rng, mat, depth,
              normal_bias=(out.x, out.y, out.z + up_bias * crown_r), bias=0.35)


def cypress(mb, rng, x, y, z, h=None):
    h = h or rng.uniform(9.0, 16.0)
    r = h * rng.uniform(0.075, 0.095)
    mb.var = rng.random()
    _trunk(mb, [(x, y, z - 0.4), (x, y, z + h * 0.5)], 0.22, 0.10)
    n = int(330 * h / 12.0)
    mat = LEAF_MAT["cypress"]
    lean = Vector((rng.uniform(-0.02, 0.02), rng.uniform(-0.02, 0.02), 0)) * h
    for _ in range(n):
        t = rng.random() ** 0.85
        R = r * (math.sin(math.pi * min(t * 1.04 + 0.04, 1.0)) ** 0.55) * (1 - 0.3 * t)
        rr = R * (rng.random() ** 0.35)
        a = rng.uniform(0, TAU)
        p = Vector((x + rr * math.cos(a), y + rr * math.sin(a), z + 0.6 + (h - 0.6) * t)) + lean * t
        _card(mb, p, rng.uniform(0.7, 1.1) * (h / 12.0) ** 0.5, rng, mat, rr / max(R, 1e-3) if R > 0 else 1.0,
              normal_bias=(math.cos(a), math.sin(a), 0.25), bias=0.4)


def pine(mb, rng, x, y, z, h=None):
    """Umbrella (stone) pine, Pinus pinea: bare leaning trunk, forked limbs, flat crown."""
    h = h or rng.uniform(10.0, 15.0)
    mb.var = rng.random()
    la = rng.uniform(0, TAU)
    lean = rng.uniform(0.04, 0.14)
    top = Vector((x + math.cos(la) * lean * h, y + math.sin(la) * lean * h, z + h * 0.72))
    mid = Vector((x + math.cos(la) * lean * h * 0.35, y + math.sin(la) * lean * h * 0.35, z + h * 0.38))
    _trunk(mb, [(x, y, z - 0.5), tuple(mid), tuple(top)], 0.30 * h / 12, 0.17 * h / 12, segs=7)
    cr = h * rng.uniform(0.40, 0.50)
    cc = top + Vector((0, 0, h * 0.14))
    mat = LEAF_MAT["pine"]
    nclump = rng.randint(6, 9)
    for k in range(nclump):
        a = TAU * k / nclump + rng.uniform(-0.3, 0.3)
        d = cr * rng.uniform(0.35, 0.7)
        c = cc + Vector((d * math.cos(a), d * math.sin(a), rng.uniform(-0.5, 0.6) - 0.15 * d))
        _trunk(mb, [tuple(top), tuple(top.lerp(c, 0.5) + Vector((0, 0, 0.4))), tuple(c - Vector((0, 0, 0.6)))],
               0.13 * h / 12, 0.05, segs=5)
        _clump(mb, rng, c, cr * 0.45, cr * 0.45, cr * 0.16, int(60 * (h / 12)), 1.5 * (h / 12) ** 0.5, mat, cc, cr,
               up_bias=0.8)
    _clump(mb, rng, cc + Vector((0, 0, 0.5)), cr * 0.45, cr * 0.45, cr * 0.15, int(60 * (h / 12)),
           1.5 * (h / 12) ** 0.5, mat, cc, cr, up_bias=0.8)


def broadleaf(mb, rng, x, y, z, h=None, mat=None, olive_like=False):
    h = h or rng.uniform(6.0, 10.0)
    mb.var = rng.random()
    mat = mat or LEAF_MAT["broadleaf"]
    stems = rng.randint(2, 3) if olive_like else 1
    cr = h * (0.42 if olive_like else 0.38)
    cc = Vector((x, y, z + h * (0.55 if olive_like else 0.62)))
    for s in range(stems):
        a = rng.uniform(0, TAU)
        o = 0.25 if olive_like else 0.0
        b = Vector((x + o * math.cos(a), y + o * math.sin(a), z - 0.3))
        m = Vector((x + 0.5 * math.cos(a + 0.6), y + 0.5 * math.sin(a + 0.6), z + h * 0.25))
        t = Vector((x + cr * 0.4 * math.cos(a), y + cr * 0.4 * math.sin(a), cc.z - cr * 0.2))
        _trunk(mb, [tuple(b), tuple(m), tuple(t)], (0.16 if olive_like else 0.22) * h / 8, 0.07, segs=6)
    nclump = rng.randint(5, 8)
    for k in range(nclump):
        a = rng.uniform(0, TAU)
        d = cr * rng.uniform(0.2, 0.62)
        c = cc + Vector((d * math.cos(a), d * math.sin(a), rng.uniform(-0.35, 0.45) * cr))
        _trunk(mb, [tuple(cc - Vector((0, 0, cr * 0.4))), tuple(c)], 0.08 * h / 8, 0.03, segs=4)
        rc = cr * rng.uniform(0.45, 0.62)
        _clump(mb, rng, c, rc, rc, rc * 0.8, int(52 * (h / 8)), 1.15 * (h / 8) ** 0.5, mat, cc, cr * 1.3,
               up_bias=0.3)


def olive(mb, rng, x, y, z, h=None):
    broadleaf(mb, rng, x, y, z, h or rng.uniform(3.8, 5.8), LEAF_MAT["olive"], olive_like=True)


def bush(mb, rng, x, y, z, r=None):
    mb.var = rng.random()
    r = r or rng.uniform(0.7, 1.6)
    c = (x, y, z + r * 0.45)
    _clump(mb, rng, c, r, r, r * 0.6, int(26 * r), 0.75 * r ** 0.5, LEAF_MAT["shrub"], c, r, up_bias=0.5)


def grass_tuft(mb, rng, x, y, z, h=None):
    h = h or rng.uniform(0.35, 0.8)
    for _ in range(9):
        a = rng.uniform(0, TAU)
        r = rng.uniform(0.0, 0.35)
        _card(mb, (x + r * math.cos(a), y + r * math.sin(a), z + h * 0.45), h * rng.uniform(0.9, 1.3), rng,
              LEAF_MAT["grass"], rng.uniform(0.5, 1.0), normal_bias=(math.cos(a), math.sin(a), 0.2), bias=0.6)


def vine_row(mb, rng, a, b, z_of, h=1.3):
    """Row of trained vines: posts every 4 m and a continuous leafy band (cards along the row)."""
    a, b = Vector(a), Vector(b)
    d = b - a
    L = d.length
    if L < 2:
        return
    u = d.normalized()
    k = 0.0
    while k <= L:
        p = a + u * k
        z = z_of(p.x, p.y)
        mb.box(p.x - 0.05, p.y - 0.05, z, p.x + 0.05, p.y + 0.05, z + h + 0.15, "TL_TimberDark", top=True)
        k += 4.0
    k = 0.3
    while k < L - 0.3:
        p = a + u * k
        z = z_of(p.x, p.y)
        for _ in range(3):
            q = p + Vector((rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25)))
            _card(mb, (q.x, q.y, z + rng.uniform(0.5, h)), rng.uniform(0.7, 1.0), rng, "TL_LeafVine",
                  rng.uniform(0.4, 1.0), normal_bias=(-u.y, u.x, 0.3), bias=0.3)
        k += 0.8


# =========================================================================== instancing
PROTO_H = {"cypress": 12.0, "pine": 12.0, "olive": 4.8, "broadleaf": 8.0, "shrub": 1.0, "grass": 0.6}
FN = {"cypress": cypress, "pine": pine, "olive": olive, "broadleaf": broadleaf, "shrub": bush, "grass": grass_tuft}


def _outward_normals(ob, center):
    """Bend leaf-card normals away from the crown centre (soft, volumetric shading)."""
    me = ob.data
    leaf_slots = {i for i, m in enumerate(me.materials) if m and m.name.startswith("TL_Leaf")}
    loops = []
    c = Vector(center)
    for poly in me.polygons:
        leaf = poly.material_index in leaf_slots
        for li in poly.loop_indices:
            if leaf:
                v = me.vertices[me.loops[li].vertex_index].co
                n = (v - c)
                n.z *= 0.6
                n = (n.normalized() * 0.8 + poly.normal * 0.2).normalized()
                loops.append(n)
            else:
                loops.append(poly.normal.copy())
    try:
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        me.normals_split_custom_set(loops)
    except Exception as exc:  # pragma: no cover - API differences
        print("TL_WARN custom normals", exc)


def build_prototypes(variants=3, seed=99):
    """One hidden collection per species holding `variants` prototype trees at the origin."""
    out = {}
    for sp in ("cypress", "pine", "olive", "broadleaf", "shrub", "grass"):
        coll = bpy.data.collections.get(f"TL_Proto_{sp}") or bpy.data.collections.new(f"TL_Proto_{sp}")
        for k in range(variants):
            rng = random.Random(seed * 31 + k * 7 + len(sp))
            mb = MeshBuilder(f"{sp}_{k:02d}")
            if sp == "shrub":
                bush(mb, rng, 0.0, 0.0, 0.0, 1.0)
            elif sp == "grass":
                grass_tuft(mb, rng, 0.0, 0.0, 0.0, 0.6)
            else:
                FN[sp](mb, rng, 0.0, 0.0, 0.0, PROTO_H[sp])
            ob = mb.to_object(coll)
            cz = {"cypress": 6.5, "pine": 10.5, "olive": 2.8, "broadleaf": 5.0, "shrub": 0.45, "grass": -0.3}[sp]
            _outward_normals(ob, (0.0, 0.0, cz))
        out[sp] = coll
    return out


def _instancer_group(coll):
    name = f"TL_Inst_{coll.name}"
    ng = bpy.data.node_groups.get(name)
    if ng:
        return ng
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi = N.new("NodeGroupInput")
    go = N.new("NodeGroupOutput")
    ci = N.new("GeometryNodeCollectionInfo")
    ci.inputs["Collection"].default_value = coll
    ci.inputs["Separate Children"].default_value = True
    ci.inputs["Reset Children"].default_value = True
    iop = N.new("GeometryNodeInstanceOnPoints")
    iop.inputs["Pick Instance"].default_value = True

    def named(nm, typ):
        nd = N.new("GeometryNodeInputNamedAttribute")
        nd.data_type = typ
        nd.inputs["Name"].default_value = nm
        return nd.outputs["Attribute"]
    comb = N.new("ShaderNodeCombineXYZ")
    L.new(named("rot", "FLOAT"), comb.inputs[2])
    L.new(gi.outputs[0], iop.inputs["Points"])
    L.new(ci.outputs[0], iop.inputs["Instance"])
    L.new(named("variant", "INT"), iop.inputs["Instance Index"])
    L.new(comb.outputs[0], iop.inputs["Rotation"])
    L.new(named("scl", "FLOAT"), iop.inputs["Scale"])
    L.new(iop.outputs[0], go.inputs[0])
    return ng


class TreeScatter:
    """Collects (species, x, y, z, height) and emits one GN-instancer object per species."""

    def __init__(self, seed=0, variants=3):
        self.rng = random.Random(seed)
        self.variants = variants
        self.items = {k: [] for k in PROTO_H}

    def add(self, species, x, y, z, h=None):
        if species not in self.items:
            species = "broadleaf"
        if h is None:
            lo, hi = {"cypress": (9.0, 16.0), "pine": (9.0, 15.0), "olive": (3.6, 5.8), "broadleaf": (5.5, 10.0),
                      "shrub": (0.6, 1.7), "grass": (0.35, 0.85)}[species]
            h = self.rng.uniform(lo, hi)
        self.items[species].append((x, y, z, h))

    def count(self):
        return sum(len(v) for v in self.items.values())

    def emit(self, coll):
        protos = build_prototypes(self.variants)
        for sp, pts in self.items.items():
            if not pts:
                continue
            me = bpy.data.meshes.new(f"Scatter_{sp}")
            me.from_pydata([(x, y, z) for x, y, z, _ in pts], [], [])
            va = me.attributes.new("variant", "INT", "POINT")
            va.data.foreach_set("value", [self.rng.randrange(self.variants) for _ in pts])
            sc = me.attributes.new("scl", "FLOAT", "POINT")
            sc.data.foreach_set("value", [h / PROTO_H[sp] for *_, h in pts])
            ro = me.attributes.new("rot", "FLOAT", "POINT")
            ro.data.foreach_set("value", [self.rng.uniform(0, TAU) for _ in pts])
            ob = bpy.data.objects.new(f"Trees_{sp}", me)
            coll.objects.link(ob)
            mod = ob.modifiers.new("instances", "NODES")
            mod.node_group = _instancer_group(protos[sp])
        return self.count()
