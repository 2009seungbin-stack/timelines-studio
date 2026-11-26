"""Roman building generators (runs inside Blender).

Every generator writes into a tl_mesh.MeshBuilder in a LOCAL frame:
front faces -Y, ground at z=0, footprint documented per function. Callers place
them with ``mb.push(loc, rot_z)``. The same functions build the city scenes and
the reusable asset library (tl_assets.py), so assets and cities never diverge.

Proportions follow Vitruvius (De architectura III-IV) where noted; everything
else is an estimate for a generic provincial city and is labelled as such in the
asset metadata.
"""
from __future__ import annotations

import math
import random

from tl_mesh import MeshBuilder

TAU = math.tau


# =========================================================================== primitives
def arcade_wall(mb: MeshBuilder, L, z0, z1, t, openings, mat, through=True, recess=0.3,
                recess_mat="TL_Dark", segs=8, cap=True, ends=False, cap_mat=None):
    """Wall along local x in [0, L], front face y=0 (facing -y), back y=t.

    openings: list of dicts {xc, w, zb, zs, arch(bool)}; arch top = zs + w/2.
    through=True cuts through the wall (arcades, gates, aqueduct), otherwise a
    dark recess of depth ``recess`` is modelled (windows, doors).
    """
    ops = sorted(openings, key=lambda o: o["xc"])
    xs = {0.0, L}
    for o in ops:
        xl, xr = o["xc"] - o["w"] / 2, o["xc"] + o["w"] / 2
        if o.get("arch", True):
            for k in range(segs + 1):
                a = math.pi - math.pi * k / segs
                xs.add(o["xc"] + o["w"] / 2 * math.cos(a))
        xs.add(xl)
        xs.add(xr)
    xs = sorted(x for x in xs if -1e-6 <= x <= L + 1e-6)

    def find(xm):
        for o in ops:
            if o["xc"] - o["w"] / 2 - 1e-6 <= xm <= o["xc"] + o["w"] / 2 + 1e-6:
                return o
        return None

    def ztop(o, x):
        if not o.get("arch", True):
            return o["zs"]
        r = o["w"] / 2
        dx = min(abs(x - o["xc"]), r)
        return o["zs"] + math.sqrt(max(0.0, r * r - dx * dx))

    def dep(o):
        return t if through else o.get("depth", recess)

    for xa, xb in zip(xs, xs[1:]):
        if xb - xa < 1e-5:
            continue
        o = find((xa + xb) / 2)
        if o is None:
            spans = [((z0, z0), (z1, z1))]
        else:
            spans = []
            if o["zb"] > z0 + 1e-4:
                spans.append(((z0, z0), (o["zb"], o["zb"])))
            ta, tb = ztop(o, xa), ztop(o, xb)
            if min(ta, tb) < z1 - 1e-4:
                spans.append(((min(ta, z1), min(tb, z1)), (z1, z1)))
        for (ba, bb), (ta_, tb_) in spans:
            mb.poly([(xa, 0, ba), (xb, 0, bb), (xb, 0, tb_), (xa, 0, ta_)], mat,
                    uvs=[(xa, ba - z0), (xb, bb - z0), (xb, tb_ - z0), (xa, ta_ - z0)])
            if through:
                mb.poly([(xb, t, bb), (xa, t, ba), (xa, t, ta_), (xb, t, tb_)], mat,
                        uvs=[(L - xb, bb - z0), (L - xa, ba - z0), (L - xa, ta_ - z0), (L - xb, tb_ - z0)])
        if o is not None:
            depth = dep(o)
            ta, tb = ztop(o, xa), ztop(o, xb)
            # soffit / lintel underside
            if max(ta, tb) < z1 - 1e-4:
                mb.poly([(xa, 0, ta), (xa, depth, ta), (xb, depth, tb), (xb, 0, tb)], mat,
                        uvs=[(xa, 0), (xa, depth), (xb, depth), (xb, 0)])
            if not through:
                zb = max(o["zb"], z0)
                mb.poly([(xa, depth, zb), (xb, depth, zb), (xb, depth, min(tb, z1)), (xa, depth, min(ta, z1))],
                        o.get("rmat", recess_mat), uvs=[(xa, zb), (xb, zb), (xb, min(tb, z1)), (xa, min(ta, z1))])
            if o["zb"] > z0 + 1e-4:  # sill
                mb.poly([(xa, 0, o["zb"]), (xb, 0, o["zb"]), (xb, depth, o["zb"]), (xa, depth, o["zb"])], mat)
    for o in ops:  # jambs
        depth = dep(o)
        xl, xr = o["xc"] - o["w"] / 2, o["xc"] + o["w"] / 2
        zb, zs = max(o["zb"], z0), min(o["zs"], z1)
        if zs > zb:
            mb.poly([(xl, 0, zb), (xl, depth, zb), (xl, depth, zs), (xl, 0, zs)], mat,
                    uvs=[(0, zb), (depth, zb), (depth, zs), (0, zs)])
            mb.poly([(xr, depth, zb), (xr, 0, zb), (xr, 0, zs), (xr, depth, zs)], mat,
                    uvs=[(depth, zb), (0, zb), (0, zs), (depth, zs)])
    if cap:
        mb.poly([(0, 0, z1), (L, 0, z1), (L, t, z1), (0, t, z1)], cap_mat or mat)
    if ends:
        mb.poly([(0, t, z0), (0, 0, z0), (0, 0, z1), (0, t, z1)], mat)
        mb.poly([(L, 0, z0), (L, t, z0), (L, t, z1), (L, 0, z1)], mat)


def rect_walls(mb, W, D, z0, z1, t, mat, openings=None, through=False, cap_mat=None, segs=6):
    """Four walls around [0,W]x[0,D]; openings = {'s'|'e'|'n'|'w': [...]} in wall-local x."""
    openings = openings or {}
    sides = (("s", (0, 0, 0), 0.0, W), ("e", (W, 0, 0), math.pi / 2, D),
             ("n", (W, D, 0), math.pi, W), ("w", (0, D, 0), 1.5 * math.pi, D))
    for key, loc, rot, L in sides:
        with mb.push(loc, rot):
            arcade_wall(mb, L, z0, z1, t, openings.get(key, []), mat, through=through, cap_mat=cap_mat, segs=segs)


def window_row(L, spacing, w, zb, zs, arch=True, margin=None):
    n = max(1, int((L - (margin if margin is not None else spacing * 0.6)) // spacing))
    x0 = (L - (n - 1) * spacing) / 2
    return [dict(xc=x0 + i * spacing, w=w, zb=zb, zs=zs, arch=arch) for i in range(n)]


def beam(mb, p0, p1, w, mat, h=None):
    """Square timber/stone beam between two local points (any orientation)."""
    from mathutils import Vector as V
    a, b = V(p0), V(p1)
    d = (b - a)
    if d.length < 1e-6:
        return
    u = d.normalized()
    ref = V((0, 0, 1)) if abs(u.z) < 0.9 else V((1, 0, 0))
    s1 = u.cross(ref).normalized() * (w / 2)
    s2 = u.cross(s1).normalized() * ((h or w) / 2)
    ring0 = [a + s1 + s2, a - s1 + s2, a - s1 - s2, a + s1 - s2]
    ring1 = [b + s1 + s2, b - s1 + s2, b - s1 - s2, b + s1 - s2]
    for i in range(4):
        j = (i + 1) % 4
        mb.poly([tuple(ring0[i]), tuple(ring0[j]), tuple(ring1[j]), tuple(ring1[i])], mat)
    mb.poly([tuple(v) for v in reversed(ring0)], mat)
    mb.poly([tuple(v) for v in ring1], mat)


def stairs(mb, x0, x1, y_front, z0, z1, tread, mat, direction=1):
    """Flight of steps rising from y_front (at z0) towards +y*direction up to z1."""
    n = max(1, round((z1 - z0) / 0.3))
    rise = (z1 - z0) / n
    for i in range(n):
        ya = y_front + direction * tread * i
        yb = y_front + direction * tread * (n + 0.5)
        mb.box(x0, min(ya, yb), z0 + rise * i, x1, max(ya, yb), z0 + rise * (i + 1), mat)


def lean_to_roof(mb, x0, x1, y_low, y_high, z_low, z_high, mat, overhang=0.4):
    """Mono-pitch roof; slope falls from y_high (z_high) to y_low (z_low)."""
    s = 1 if y_high > y_low else -1
    slope = (z_high - z_low) / abs(y_high - y_low)
    yl = y_low - s * overhang
    zl = z_low - overhang * slope
    L = x1 - x0 + 2 * overhang
    sl = math.hypot(abs(y_high - yl), z_high - zl)
    pts = [(x0 - overhang, yl, zl), (x1 + overhang, yl, zl), (x1 + overhang, y_high, z_high),
           (x0 - overhang, y_high, z_high)]
    uvs = [(0, 0), (L, 0), (L, sl), (0, sl)]
    if s < 0:
        pts = [pts[1], pts[0], pts[3], pts[2]]
        uvs = [(L, 0), (0, 0), (0, sl), (L, sl)]
    mb.poly(pts, mat, uvs=uvs)
    # eave edge thickness
    e = [(x0 - overhang, yl, zl - 0.15), (x1 + overhang, yl, zl - 0.15), (x1 + overhang, yl, zl),
         (x0 - overhang, yl, zl)]
    mb.poly(e if s > 0 else [e[1], e[0], e[3], e[2]], mat)


def dome(mb, cx, cy, z0, r, rise, mat, segs=32, rings=8, a0=0.0, a1=TAU, close=True):
    prof = []
    for k in range(rings + 1):
        f = k / rings
        ang = f * math.pi / 2
        prof.append((max(r * math.cos(ang), 1e-3 if k < rings else 0.0), z0 + rise * math.sin(ang)))
    prof[-1] = (0.0, z0 + rise)
    mb.lathe(prof, segs, mat, cx, cy, smooth=True, cap_top=False, a0=a0, a1=a1, close=close)


# =========================================================================== basilica
def basilica(mb: MeshBuilder, rng, L=60.0, nave=18.0, aisle=7.0, h_aisle=9.0, h_nave=17.0,
             wall="TL_Brick", roof="TL_Tile", apse=True, church=False):
    """Timber-roofed basilica: nave with clerestory, two aisles, apse at +x end.
    Local: long axis along x in [0, L], front (forum side) at y=0.
    Returns footprint (w, d)."""
    D = nave + 2 * aisle
    t = 0.9
    # aisle (outer) walls with arched windows; entrances on the front side
    win = window_row(L, 5.0, 2.0, 4.0, 6.6)
    front_ops = [dict(o) for o in win]
    for o in front_ops[len(front_ops) // 2 - 1:len(front_ops) // 2 + 2]:
        o.update(zb=0.0, zs=5.5, w=3.0)
    end_win = window_row(D, 5.0, 2.0, 4.0, 6.6)
    if church:
        # west facade (x=0) gets the doors, south side plain windows
        front_ops = win
        end_w = [dict(o) for o in end_win]
        mid = len(end_w) // 2
        end_w[mid].update(zb=0.0, zs=6.0, w=3.6)
        ops = {"s": front_ops, "n": win, "w": end_w, "e": end_win if not apse else []}
    else:
        ops = {"s": front_ops, "n": win, "w": end_win, "e": end_win if not apse else []}
    rect_walls(mb, L, D, 0, h_aisle, t, wall, openings=ops, through=False)
    # clerestory walls on the nave arcade line
    cw = window_row(L, 5.0, 2.2, h_aisle + 2.4, h_aisle + 4.8)
    for y, rot, x0 in ((aisle, 0.0, 0.0), (aisle + nave, math.pi, L)):
        with mb.push((x0, y, 0), rot):
            arcade_wall(mb, L, h_aisle - 0.5, h_nave, 0.8, cw, wall, through=False)
    # nave end gable walls (x=0 and x=L) above the aisle roofs
    with mb.push((0, aisle + nave, 0), 1.5 * math.pi):
        ow = [dict(xc=nave / 2, w=3.0, zb=h_aisle + 2.0, zs=h_aisle + 5.0, arch=True)]
        arcade_wall(mb, nave, h_aisle - 0.5, h_nave, 0.8, ow, wall, through=False)
    with mb.push((L, aisle, 0), 0.5 * math.pi):
        arcade_wall(mb, nave, h_aisle - 0.5, h_nave, 0.8, [], wall, through=False)
    # aisle lean-to roofs
    lean_to_roof(mb, 0, L, 0, aisle, h_aisle, h_aisle + 2.0, roof)
    lean_to_roof(mb, 0, L, D, aisle + nave, h_aisle, h_aisle + 2.0, roof)
    # nave gable roof
    mb.gable_roof(0, aisle, L, aisle + nave, h_nave, 22.0, roof, overhang=0.6, ridge_axis="x", gable_mat=wall,
                  thickness=0.3)
    if apse:
        r = nave / 2 - 0.5
        cy = aisle + nave / 2
        mb.lathe([(r, 0.0), (r, h_aisle + 2.5)], 20, wall, L, cy, smooth=True, cap_top=False,
                 a0=-math.pi / 2, a1=math.pi / 2)
        # half-cone tiled roof over the apse
        mb.lathe([(r + 0.5, h_aisle + 2.3), (0.01, h_aisle + 2.3 + (r + 0.5) * math.tan(math.radians(24)))],
                 20, roof, L, cy, smooth=True, cap_top=False, a0=-math.pi / 2, a1=math.pi / 2)
        # windows on the apse as recessed dark panels (3)
        for k in (-0.5, 0.0, 0.5):
            a = k * math.pi * 0.6
            with mb.push((L + r * math.cos(a), cy + r * math.sin(a), 0), a + math.pi / 2):
                arcade_wall(mb, 2.6, 4.0, 7.6, 0.2, [dict(xc=1.3, w=1.8, zb=4.3, zs=6.6)], wall,
                            through=False, cap=False)
    return (L + (nave / 2 if apse else 0), D)


# =========================================================================== houses
FLOOR0, FLOORN = 3.6, 3.0


def _side_frame(side, w, d):
    """push() args giving a frame whose x runs along facade `side`, outward = -y."""
    return [((0, 0, 0), 0.0), ((w, 0, 0), math.pi / 2), ((w, d, 0), math.pi), ((0, d, 0), 1.5 * math.pi)][side]


def _inner_ring(mb, x0, y0, x1, y1, H, mat):
    ring = [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]
    for i in range(4):
        a, b = ring[i], ring[(i + 1) % 4]
        ln = math.dist(a, b)
        mb.poly([(a[0], a[1], 0), (b[0], b[1], 0), (b[0], b[1], H), (a[0], a[1], H)], mat,
                uvs=[(0, 0), (ln, 0), (ln, H), (0, H)])


def ruin(mb, rng, w, d):
    """Partly collapsed roofless house (late-antique urban decay), garden inside."""
    t = 0.6
    for side in range(4):
        L = w if side % 2 == 0 else d
        with mb.push(*_side_frame(side, w, d)):
            x = 0.0
            while x < L - 0.1:
                seg = min(L - x, rng.uniform(2.0, 6.0))
                h = rng.choice([0.6, 1.2, 2.0, 3.2, 4.0])
                if rng.random() < 0.15:
                    h = 0.3
                mb.box(x, 0, 0, x + seg, t, h, "TL_Brick")
                x += seg
    mb.poly([(t, t, 0.08), (w - t, t, 0.08), (w - t, d - t, 0.08), (t, d - t, 0.08)], "TL_Garden")


# =========================================================================== forum portico
def portico(mb, rng, L, depth=5.5, H=5.4, D=0.6, spacing=3.0, back_wall=True, mat_col="TL_Travertine",
            wall_mat="TL_Plaster"):
    """Colonnaded portico along local x in [0, L], columns on y=0 (facing -y),
    back wall with shop doors at y=depth, lean-to roof."""
    n = max(2, int(L / spacing))
    for i in range(n + 1):
        column(mb, L * i / n, 0.0, 0.0, H, D, mat_col, "tuscan", 8)
    mb.box(-0.4, -0.4, H, L + 0.4, 0.45, H + 0.7, mat_col)  # architrave
    if back_wall:
        mb.box(0, depth, 0, L, depth + 0.7, H + 2.2, wall_mat, fac=(1, 2, 1, 2))
    lean_to_roof(mb, -0.4, L + 0.4, -0.4, depth + 0.7, H + 0.7, H + 2.2, "TL_Tile", overhang=0.5)


# =========================================================================== domed church
def domed_church(mb, rng, dome_d=22.0, wall="TL_Brick", roof="TL_Tile", lead="TL_Lead", atrium=True):
    """Centrally domed basilica (Hagia Sophia type, 537 CE, scaled down).
    Local: liturgical axis along +x (apse east at +x), entrance at x=0, centred on y=0.
    Returns footprint (length, width)."""
    R = dome_d / 2
    core = dome_d + 4.0
    nave_l = core + 2 * R  # central square + two half-dome exedrae
    W = core + 2 * 9.0     # aisles + galleries
    x0 = 18.0 if atrium else 0.0
    narthex = 6.0
    bx0 = x0 + narthex
    bx1 = bx0 + nave_l
    h_side = 16.0
    h_core = 24.0
    # outer body (aisles with galleries): two tiers of arched windows
    ops_l = window_row(nave_l, 5.0, 2.2, 3.0, 5.6) + window_row(nave_l, 5.0, 2.2, 9.5, 12.4)
    ops_e = window_row(W, 5.0, 2.2, 9.5, 12.4)
    with mb.push((bx0, -W / 2, 0)):
        rect_walls(mb, nave_l, W, 0, h_side, 1.2, wall, openings={"s": ops_l, "n": ops_l, "e": ops_e, "w": []})
        lean_to_roof(mb, 0, nave_l, 0, 9.0, h_side, h_side + 3.0, roof)
        lean_to_roof(mb, 0, nave_l, W, W - 9.0, h_side, h_side + 3.0, roof)
        mb.box(0.0, 9.0, h_side, nave_l, W - 9.0, h_side + 3.0, wall, top_mat=lead)
    # narthex
    nops = window_row(W, 4.5, 2.6, 0.0, 5.0)
    with mb.push((x0, -W / 2, 0)):
        rect_walls(mb, narthex, W, 0, 11.0, 1.0, wall, openings={"w": nops})
        mb.gable_roof(0, 0, narthex, W, 11.0, 20.0, roof, ridge_axis="y", gable_mat=wall)
    # central raised core: square tower carrying the dome on pendentives
    cx = bx0 + nave_l / 2
    with mb.push((cx - core / 2, -core / 2, 0)):
        tops = window_row(core, 4.0, 2.0, h_side + 3.6, h_core - 2.4)
        rect_walls(mb, core, core, h_side, h_core, 1.5, wall, openings={"s": tops, "n": tops})
    # big buttress piers on the north and south (HS-type)
    for sy in (-1, 1):
        for sx in (-1, 1):
            bx = cx + sx * (core / 2 - 3.0)
            by = sy * (W / 2 + 2.5)
            mb.box(bx - 3.0, by - 2.5, 0, bx + 3.0, by + 2.5, h_core - 1.0, wall)
            mb.hip_roof(bx - 3.0, by - 2.5, bx + 3.0, by + 2.5, h_core - 1.0, 25.0, roof, overhang=0.2)
    # drum with a ring of windows + ribbed lead dome
    nw = 24
    zd0 = h_core
    drum_h = 4.2
    for k in range(nw):
        a0 = TAU * k / nw
        a1 = TAU * (k + 1) / nw
        p0 = (cx + R * math.cos(a0), R * math.sin(a0))
        p1 = (cx + R * math.cos(a1), R * math.sin(a1))
        ln = math.dist(p0, p1)
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        # CCW ring: frame x along p0->p1 puts the front (-y) outward
        with mb.push((p0[0], p0[1], 0), ang):
            arcade_wall(mb, ln, zd0, zd0 + drum_h, 0.9,
                        [dict(xc=ln / 2, w=ln * 0.42, zb=zd0 + 0.9, zs=zd0 + 2.6)], wall, through=False,
                        cap=True, segs=4)
        # small buttress between windows
        bxp, byp = cx + (R + 0.35) * math.cos(a0), (R + 0.35) * math.sin(a0)
        with mb.push((bxp, byp, 0), a0):
            mb.box(-0.5, -0.45, zd0, 0.5, 0.45, zd0 + drum_h - 0.2, wall)
    dome(mb, cx, 0.0, zd0 + drum_h, R + 0.5, R * 0.62, lead, segs=48, rings=10)
    # two half domes (east and west) over the exedrae
    for sx, a0 in ((1, -math.pi / 2), (-1, math.pi / 2)):
        hx = cx + sx * core / 2
        mb.lathe([(R - 0.5, h_side), (R - 0.5, h_side + 3.5)], 24, wall, hx, 0.0, cap_top=False,
                 a0=a0, a1=a0 + math.pi)
        dome(mb, hx, 0.0, h_side + 3.5, R - 0.2, (R - 0.2) * 0.6, lead, segs=24, rings=8, a0=a0,
             a1=a0 + math.pi, close=False)
    # apse at the east end
    ra = 7.0
    mb.lathe([(ra, 0.0), (ra, 12.0)], 20, wall, bx1, 0.0, cap_top=False, a0=-math.pi / 2, a1=math.pi / 2)
    dome(mb, bx1, 0.0, 12.0, ra + 0.3, ra * 0.6, lead, segs=20, rings=6, a0=-math.pi / 2, a1=math.pi / 2,
         close=False)
    if atrium:
        # colonnaded atrium (early Christian forecourt) with a fountain basin
        aw = W - 6
        with mb.push((0, -aw / 2, 0)):
            dp = 4.0
            for lx, ly, rot, L in ((x0, dp, math.pi, x0), (0, aw - dp, 0.0, x0), (dp, 0, math.pi / 2, aw)):
                with mb.push((lx, ly, 0), rot):
                    portico(mb, rng, L, depth=dp, H=4.6, D=0.5, spacing=2.8, mat_col="TL_Marble",
                            wall_mat="TL_PlasterPlain")
            mb.box(0, 0, 0, x0, aw, 0.3, "TL_TravertineSlabs", sides=True)
            mb.cylinder(x0 / 2, aw / 2, 0.3, 1.0, 2.0, 16, "TL_Marble")
    return (bx1 + ra, W + 10)


# =========================================================================== aqueduct
def aqueduct_run(mb, L, z_top, ground, span=6.2, pier=2.3, width=2.6, mat="TL_Ashlar",
                 tier_split=17.0):
    """Arcade along local x in [0, L]. z_top = channel floor level at x (callable),
    ground = terrain height at x (callable). Piers rise from below ground; where the
    arcade is taller than `tier_split` a second, superimposed tier is used
    (Pont du Gard / Segovia principle). Specus (channel) with cover slabs on top."""
    n = max(1, int(L / span))
    sp = L / n
    ch_h = 1.9
    # walk bay by bay
    for i in range(n):
        xa = i * sp
        zt = min(z_top(xa), z_top(xa + sp))
        g = min(ground(xa), ground(xa + sp), ground(xa + sp / 2))
        hgt = zt - g
        r = (sp - pier) / 2
        if hgt < r + 2.2:
            # low: solid substructure wall; buried where the ground is above the channel
            if hgt > -1.5:
                mb.box(xa, 0, g - 1.0, xa + sp, width, zt, mat, top=False)
            continue
        with mb.push((xa, 0, 0)):
            if hgt > tier_split:
                zmid = g + hgt * 0.55
                r = (sp - pier) / 2
                with mb.push((0, -0.3, 0)):
                    arcade_wall(mb, sp, g - 1.5, zmid, width + 0.6,
                                [dict(xc=sp / 2, w=sp - pier, zb=g - 1.5, zs=zmid - r - 1.0)], mat,
                                through=True, segs=8)
                mb.box(-0.02, -0.55, zmid - 0.35, sp + 0.02, width + 0.55, zmid, mat, sides=True, top=True)
                arcade_wall(mb, sp, zmid, zt, width,
                            [dict(xc=sp / 2, w=sp - pier * 0.85, zb=zmid, zs=zt - r - 0.9)], mat,
                            through=True, segs=8)
            else:
                zs = max(g + 0.8, zt - r - 0.9)
                arcade_wall(mb, sp, g - 1.5, zt, width,
                            [dict(xc=sp / 2, w=sp - pier, zb=g - 1.5, zs=zs)], mat, through=True, segs=8)
                # impost moulding at springing
                if zs - g > 2.5:
                    mb.box(0, -0.12, zs - 0.25, pier / 2, width + 0.12, zs, mat)
                    mb.box(sp - pier / 2, -0.12, zs - 0.25, sp, width + 0.12, zs, mat)
    # specus: channel walls + cover slabs, string course below
    with mb.push((0, 0, 0)):
        for i in range(n):
            xa = i * sp
            zt = z_top(xa)
            if min(ground(xa), ground(xa + sp)) > zt + ch_h + 0.2:
                continue  # underground conduit
            mb.box(xa, -0.2, zt - 0.3, xa + sp, width + 0.2, zt, mat)  # cornice
            mb.box(xa, 0.15, zt, xa + sp, width - 0.15, zt + ch_h, mat)
            mb.box(xa - 0.01, 0.0, zt + ch_h, xa + sp + 0.01, width, zt + ch_h + 0.35, "TL_AshlarGrey")
    return n


def castellum(mb, rng):
    """Castellum divisorium: small vaulted distribution house where the aqueduct ends."""
    mb.box(0, 0, 0, 8, 8, 6.5, "TL_Ashlar")
    mb.hip_roof(0, 0, 8, 8, 6.5, 22.0, "TL_Tile")


# =========================================================================== watermill (Barbegal type)
def watermill_cascade(mb, rng, steps=8, step_drop=2.4, step_len=7.0, rows=2):
    """Stepped cascade of mill houses with overshot wheels, fed by a channel along
    the top (Barbegal, Provence, 2nd c. CE: 2 x 8 mills on a ~30 % slope).
    Local: descends along +x; top step floor at z=0. Footprint ~ steps*step_len x 26 m."""
    house_w = 9.0
    gap = 4.0  # central channel + stair
    for r in range(rows):
        side = -1 if r == 0 else 1
        y0 = side * (gap / 2) if side > 0 else -(gap / 2) - house_w
        for i in range(steps):
            x0 = i * step_len
            z = -i * step_drop
            # terrace platform (retaining wall going down into the slope)
            mb.box(x0, y0, z - step_drop - 2.5, x0 + step_len, y0 + house_w, z, "TL_Ashlar", top_mat="TL_Earth")
            # mill house
            hx0, hx1 = x0 + 0.6, x0 + step_len - 0.6
            hy0, hy1 = (y0 + 3.4, y0 + house_w - 0.6) if side > 0 else (y0 + 0.6, y0 + house_w - 3.4)
            from tl_arch import _walls, facade_style
            st = facade_style(rng)
            st.update(fl0=4.6, course=True, cmat="TL_Travertine")
            with mb.push((hx0, hy0, z)):
                _walls(mb, rng, hx1 - hx0, hy1 - hy0, 4.6, 1, (True, True, True, True), "TL_PlasterWall", st,
                       "TL_PlasterWall", shop=False)
            mb.gable_roof(hx0, hy0, hx1, hy1, z + 4.6, 22.0, "TL_Tile", ridge_axis="x", gable_mat="TL_PlasterPlain")
            # wheel pit + overshot wheel between house and central channel
            wy = (y0 + 1.7) if side > 0 else (y0 + house_w - 1.7)
            wx = x0 + step_len * 0.5
            wr = 1.1
            with mb.push((wx, wy, z - 0.9), 0.0):
                wheel(mb, wr, 0.7)
    # head-race channel at the top and central race down the slope
    mb.box(-6.0, -1.0, -0.2, 0.0, 1.0, 1.2, "TL_Ashlar")
    for i in range(steps):
        x0 = i * step_len
        z = -i * step_drop
        mb.box(x0, -gap / 2, z - step_drop - 2.5, x0 + step_len, gap / 2, z + 0.4, "TL_Ashlar")
        mb.poly([(x0, -0.6, z + 0.45), (x0 + step_len, -0.6, z + 0.45), (x0 + step_len, 0.6, z + 0.45),
                 (x0, 0.6, z + 0.45)], "TL_Water")
    return (steps * step_len, 2 * house_w + gap)


def wheel(mb, r, width, segs=16, mat="TL_TimberDark"):
    """Water wheel with its axis along y, centre at (0, 0, r) in local space."""
    for side in (-width / 2, width / 2):
        pts = []
        for k in range(segs):
            a = TAU * k / segs
            pts.append((r * math.cos(a), side, r + r * math.sin(a)))
        # rim as thin quads
        for k in range(segs):
            a, b = pts[k], pts[(k + 1) % segs]
            ia = (a[0] * 0.85, a[1], r + (a[2] - r) * 0.85)
            ib = (b[0] * 0.85, b[1], r + (b[2] - r) * 0.85)
            if side < 0:
                mb.poly([a, b, ib, ia], mat)
            else:
                mb.poly([b, a, ia, ib], mat)
    for k in range(segs):  # paddles
        a = TAU * k / segs
        c, s = math.cos(a), math.sin(a)
        p0 = (r * 0.85 * c, -width / 2, r + r * 0.85 * s)
        p1 = (r * 1.05 * c, -width / 2, r + r * 1.05 * s)
        mb.poly([p0, p1, (p1[0], width / 2, p1[2]), (p0[0], width / 2, p0[2])], mat)
    mb.push((0, 0, r), 0.0)
    mb.box(-0.12, -width, -0.12, 0.12, width, 0.12, mat)
    mb.pop()


# =========================================================================== walls
def wall_run(mb, L, H=8.5, t=3.6, mat="TL_Brick", merlon=True, base_mat="TL_Ashlar"):
    """Curtain wall along local x in [0, L], outer face at y=0 (facing -y)."""
    mb.box(0, 0, -1.0, L, t, 2.2, base_mat, fac=(0, 0, 0, 0))
    mb.box(0, 0.05, 2.2, L, t, H, mat)
    if merlon:
        n = int(L / 2.4)
        for i in range(n):
            x = i * L / n
            mb.box(x + 0.25, 0.05, H, x + L / n - 0.85, 0.75, H + 1.6, mat)
        mb.box(0, t - 0.5, H, L, t, H + 1.1, mat)


def tower(mb, rng, w=8.0, d=9.0, H=15.0, mat="TL_Brick", roofed=True):
    """Square projecting tower (late Roman); local centre x=0, projects to -y."""
    mb.box(-w / 2, -d + 3.6, -1.0, w / 2, 3.6, 2.2, "TL_Ashlar")
    win = window_row(w, 2.6, 1.0, H - 4.2, H - 2.8, arch=True)
    with mb.push((-w / 2, -d + 3.6, 0)):
        rect_walls(mb, w, d, 2.2, H, 1.0, mat, openings={"s": win, "e": win[:1], "w": win[:1]})
    if roofed:
        mb.hip_roof(-w / 2, -d + 3.6, w / 2, 3.6, H, 24.0, "TL_Tile", overhang=0.3)
    else:
        mb.box(-w / 2, -d + 3.6, H - 0.1, w / 2, 3.6, H, mat)


def round_tower(mb, r=5.0, H=16.0, mat="TL_Brick"):
    mb.lathe([(r + 0.4, -1.0), (r + 0.4, 2.2), (r, 2.2), (r, H)], 20, mat, 0, -r * 0.6, cap_top=True)
    mb.lathe([(r + 0.3, H), (0.02, H + r * math.tan(math.radians(24)))], 20, "TL_Tile", 0, -r * 0.6,
             cap_top=False)


def gate(mb, rng, wall_h=8.5, t=3.6, mat="TL_Brick", double=True):
    """City gate: twin semicircular towers flanking one or two arched passages.
    Local: centred on x=0, outer face y=0, passage along y."""
    gw = 15.0 if double else 9.0
    ops = ([dict(xc=gw / 2 - 2.7, w=4.2, zb=0.0, zs=4.2), dict(xc=gw / 2 + 2.7, w=4.2, zb=0.0, zs=4.2)]
           if double else [dict(xc=gw / 2, w=4.6, zb=0.0, zs=4.6)])
    upper = window_row(gw, 2.6, 1.2, wall_h + 1.0, wall_h + 2.6)
    with mb.push((-gw / 2, 0, 0)):
        arcade_wall(mb, gw, -0.5, wall_h + 4.5, t, ops, mat, through=True)
        mb.gable_roof(0, 0.0, gw, t, wall_h + 4.5, 22.0, "TL_Tile", ridge_axis="x", gable_mat=mat)
    for sx in (-1, 1):
        with mb.push((sx * (gw / 2 + 4.0), 0.0, 0)):
            round_tower(mb, 5.0, wall_h + 7.0, mat)
    return gw + 18.0


# =========================================================================== amphitheatre
def amphitheatre(mb, rng, a=58.0, b=46.0, H=20.0, tiers=2, mat="TL_Ashlar"):
    """Elliptical amphitheatre with arcaded facade (estimated provincial size)."""
    n = 56
    pts = [(a * math.cos(TAU * k / n), b * math.sin(TAU * k / n)) for k in range(n)]
    th = H / (tiers + 0.35)
    for k in range(n):
        p0, p1 = pts[k], pts[(k + 1) % n]
        ln = math.dist(p0, p1)
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        with mb.push((p0[0], p0[1], 0), ang):
            for tr in range(tiers):
                z0 = tr * th
                arcade_wall(mb, ln, z0 - (1.0 if tr == 0 else 0), z0 + th, 1.2,
                            [dict(xc=ln / 2, w=ln * 0.55, zb=z0 - (1.0 if tr == 0 else 0) + (0 if tr == 0 else 1.0),
                                  zs=z0 + th - ln * 0.55 / 2 - 1.2)], mat, through=False, recess=1.2, segs=6)
            arcade_wall(mb, ln, tiers * th, H, 1.0, [], mat, through=False)
    # cavea (seating slope) and arena
    ai, bi = a * 0.5, b * 0.42
    rows = 6
    for rr in range(rows):
        f0, f1 = rr / rows, (rr + 1) / rows
        z0 = 1.5 + (H - 3.0) * f0
        z1 = 1.5 + (H - 3.0) * f1
        for k in range(n):
            c0, s0 = math.cos(TAU * k / n), math.sin(TAU * k / n)
            c1, s1 = math.cos(TAU * (k + 1) / n), math.sin(TAU * (k + 1) / n)
            ra0 = (ai + (a - 1.2 - ai) * f0, bi + (b - 1.2 - bi) * f0)
            ra1 = (ai + (a - 1.2 - ai) * f1, bi + (b - 1.2 - bi) * f1)
            mb.poly([(ra0[0] * c0, ra0[1] * s0, z0), (ra0[0] * c1, ra0[1] * s1, z0),
                     (ra0[0] * c1, ra0[1] * s1, z1), (ra0[0] * c0, ra0[1] * s0, z1)][::-1], "TL_Travertine")
            mb.poly([(ra0[0] * c0, ra0[1] * s0, z1), (ra0[0] * c1, ra0[1] * s1, z1),
                     (ra1[0] * c1, ra1[1] * s1, z1), (ra1[0] * c0, ra1[1] * s0, z1)], "TL_Travertine")
    ring = [(ai * math.cos(TAU * k / n), bi * math.sin(TAU * k / n)) for k in range(n)]
    mb.poly([(x, y, 0.3) for x, y in ring], "TL_Earth")
    for k in range(n):  # podium wall around the arena
        p0, p1 = ring[k], ring[(k + 1) % n]
        mb.poly([(p1[0], p1[1], 0.3), (p0[0], p0[1], 0.3), (p0[0], p0[1], 1.5), (p1[0], p1[1], 1.5)],
                "TL_PlasterPlain")


# =========================================================================== harbour & ships
def ship(mb, rng, L=22.0, B=6.4, depth=3.2, sail_set=False, mast=True):
    """Roman merchant ship (corbita type): rounded hull, rising stern post,
    main mast with square sail (furled or set) and inclined artemon at the bow.
    Local: bow towards +x, waterline at z=0, centred."""
    nsec = 14
    nside = 7
    secs = []
    for i in range(nsec + 1):
        f = i / nsec
        x = -L / 2 + L * f
        # half-beam profile: fuller amidships, fine ends
        hb = B / 2 * (math.sin(math.pi * min(max(f, 0.0), 1.0)) ** 0.6)
        hb = max(hb, 0.08)
        sheer = 1.2 + 1.8 * (abs(f - 0.45) ** 2.2) * 4  # rising sheer at bow and stern
        keel = -depth * (0.55 + 0.45 * math.sin(math.pi * f) ** 0.5)
        ring = []
        for k in range(nside + 1):
            t = k / nside
            ang = -math.pi / 2 + math.pi / 2 * t
            y = hb * math.cos(ang)
            ring.append((x, y, keel + (sheer - keel) * (1 + math.sin(ang))))
        secs.append(ring)
    hull = "TL_TimberDark"
    for i in range(nsec):
        for k in range(nside):
            a, b = secs[i][k], secs[i + 1][k]
            c, d = secs[i + 1][k + 1], secs[i][k + 1]
            for sgn in (1, -1):
                pa, pb, pc, pd = [(p[0], sgn * p[1], p[2]) for p in (a, b, c, d)]
                if sgn > 0:
                    mb.poly([pd, pc, pb, pa], hull, smooth=True)
                else:
                    mb.poly([pa, pb, pc, pd], hull, smooth=True)
    # deck
    for i in range(nsec):
        a, b = secs[i][-1], secs[i + 1][-1]
        za, zb = a[2] - 0.3, b[2] - 0.3
        mb.poly([(a[0], -a[1], za), (b[0], -b[1], zb), (b[0], b[1], zb), (a[0], a[1], za)], "TL_Timber")
    # stern post curving up and forward (smooth swept beam)
    sx = -L / 2
    z0 = secs[0][-1][2]
    pts = [(sx - 1.1 * math.sin(f * 1.9), 0.0, z0 - 0.4 + 2.8 * math.sin(f * 1.4)) for f in
           [k / 8 for k in range(9)]]
    for p0, p1 in zip(pts, pts[1:]):
        beam(mb, p0, p1, 0.3, hull)
    # deckhouse aft and steering oars
    mb.box(-L * 0.38, -1.4, secs[2][-1][2] - 0.3, -L * 0.22, 1.4, secs[2][-1][2] + 1.5, "TL_Timber")
    mb.gable_roof(-L * 0.38, -1.4, -L * 0.22, 1.4, secs[2][-1][2] + 1.5, 20.0, "TL_Timber", overhang=0.15,
                  ridge_axis="x")
    for sgn in (-1, 1):
        mb.box(-L * 0.47, sgn * (B / 2 * 0.55) - 0.12, -1.6, -L * 0.44, sgn * (B / 2 * 0.55) + 0.12, 2.2, hull)
    if mast:
        mh = L * 0.75
        mb.cylinder(0.0, 0.0, 0.0, mh, 0.22, 8, "TL_Timber", r_top=0.14)
        yard_z = mh - 1.2
        mb.cylinder(0.0, 0.0, yard_z - 0.15, yard_z + 0.15, 0.1, 6, "TL_Timber")
        mb.box(-0.15, -B * 0.95, yard_z - 0.12, 0.15, B * 0.95, yard_z + 0.12, "TL_Timber")
        if sail_set:
            sw, sh = B * 0.9, mh * 0.55
            for k in range(6):
                z0 = yard_z - sh * k / 6
                z1 = yard_z - sh * (k + 1) / 6
                bulge0 = 0.9 * math.sin(math.pi * k / 6)
                bulge1 = 0.9 * math.sin(math.pi * (k + 1) / 6)
                mb.poly([(0.25 + bulge1, -sw, z1), (0.25 + bulge1, sw, z1), (0.25 + bulge0, sw, z0),
                         (0.25 + bulge0, -sw, z0)], "TL_Sail", smooth=True)
        else:
            mb.box(0.1, -B * 0.9, yard_z - 0.55, 0.55, B * 0.9, yard_z - 0.1, "TL_Sail")
        # artemon (bowsprit mast) with a small sail
        bx = L * 0.42
        bz = secs[-2][-1][2]
        beam(mb, (bx - 0.5, 0, bz - 0.3), (bx + 2.4, 0, bz + 3.6), 0.2, "TL_Timber")
        beam(mb, (bx + 2.2, -1.4, bz + 3.3), (bx + 2.2, 1.4, bz + 3.3), 0.12, "TL_Timber")
        if sail_set:
            mb.poly([(bx + 2.3, -1.3, bz + 1.6), (bx + 2.3, 1.3, bz + 1.6), (bx + 2.35, 1.3, bz + 3.25),
                     (bx + 2.35, -1.3, bz + 3.25)], "TL_Sail")
    return (L, B)


def boat(mb, rng, L=7.0):
    return ship(mb, rng, L=L, B=L * 0.3, depth=0.9, mast=False)


def lighthouse(mb, rng, mat="TL_Ashlar"):
    """Harbour lighthouse in stepped square stages (Ostia/Portus, Tower of Hercules type)."""
    z = 0.0
    w = 14.0
    for k, h in enumerate((12.0, 9.0, 7.0)):
        win = window_row(w, 3.5, 1.2, z + h * 0.45, z + h * 0.7)
        with mb.push((-w / 2, -w / 2, 0)):
            rect_walls(mb, w, w, z - (2.0 if k == 0 else 0.0), z + h, 1.2, mat,
                       openings={"s": win, "e": win, "n": win, "w": win})
        mb.box(-w / 2 - 0.3, -w / 2 - 0.3, z + h - 0.4, w / 2 + 0.3, w / 2 + 0.3, z + h, mat)
        mb.poly([(-w / 2, -w / 2, z + h - 0.05), (w / 2, -w / 2, z + h - 0.05), (w / 2, w / 2, z + h - 0.05),
                 (-w / 2, w / 2, z + h - 0.05)], mat)
        z += h
        w *= 0.72
    mb.cylinder(0, 0, z, z + 3.0, w * 0.35, 12, mat)
    mb.lathe([(w * 0.45, z + 3.0), (0.02, z + 5.0)], 12, "TL_Tile", 0, 0, cap_top=False)
    return z + 5.0


def horreum(mb, rng, w=60.0, d=24.0, H=8.5):
    """Warehouse (horrea) with inner court and narrow ventilation windows."""
    return insula(mb, rng, w, d, 2, street=(True, False, True, False), material="TL_BrickWin", balconies=False)


def villa_rustica(mb, rng):
    """Farmstead (villa rustica): courtyard house + barn on a levelled platform.
    Local: centred on the origin, platform 34 x 34 m (+ barn to the east)."""
    mb.box(-17, -17, -2.0, 17, 17, 0.3, "TL_AshlarGrey", top_mat="TL_Earth")
    with mb.push((-15, -15, 0.3)):
        insula(mb, rng, 30.0, 30.0, 2, street=(True, True, True, True), material="TL_Plaster", balconies=False)
    with mb.push((18, -12, 0.0)):
        mb.box(0, 0, -1.0, 9, 24, 4.2, "TL_PlasterPlain")
        mb.gable_roof(0, 0, 9, 24, 4.2, 22.0, "TL_Tile", ridge_axis="y", gable_mat="TL_PlasterPlain")


def tomb(mb, rng):
    """Roadside tomb (altar or tower type) for the necropolis along the road out."""
    k = rng.random()
    if k < 0.5:
        w = rng.uniform(3.0, 5.0)
        mb.box(-w / 2, -w / 2, -0.5, w / 2, w / 2, 1.0, "TL_Travertine")
        mb.box(-w / 2 + 0.4, -w / 2 + 0.4, 1.0, w / 2 - 0.4, w / 2 - 0.4, rng.uniform(3.0, 5.0), "TL_Travertine")
    elif k < 0.8:
        r = rng.uniform(4.0, 7.0)
        mb.cylinder(0, 0, -0.5, 3.0, r, 20, "TL_Travertine", smooth=True)
        mb.lathe([(r - 0.3, 3.0), (0.3, 3.0 + r * 0.5)], 20, "TL_Garden", 0, 0, cap_top=True)
    else:
        mb.box(-2.5, -3.0, -0.5, 2.5, 3.0, 4.2, "TL_Brick")
        mb.gable_roof(-2.5, -3.0, 2.5, 3.0, 4.2, 20.0, "TL_Tile", ridge_axis="y", gable_mat="TL_Brick")


# v2 detailed generators (modelled orders, facades, props) override the simple versions
from tl_arch import (column, temple, insula, domus, facade, facade_style, amphora, amphora_stack,  # noqa: E402,F401
                     fountain, market_stall, cart, statue, entablature, balcony)
