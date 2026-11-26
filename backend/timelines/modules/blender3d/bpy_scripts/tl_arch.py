"""v2 detailed architecture (runs inside Blender): modelled orders, temple, street
facades, houses and small props. Imported at the end of tl_buildings, which re-exports
column / temple / insula / domus / facade / amphora, so every caller (city and asset
library) uses these versions.

Proportions follow Vitruvius where noted; mouldings, facade rhythms and all prop
dimensions are estimates.
"""
from __future__ import annotations

import math
import random

from tl_buildings import (arcade_wall, beam, lean_to_roof, rect_walls, stairs, window_row, _inner_ring)
from tl_mesh import MeshBuilder

TAU = math.tau


# =========================================================================== orders
def attic_base(mb, x, y, z0, D, mat, segs=24):
    """Attic base: square plinth, torus - scotia - torus (base height ~D/2, Vitruvius III.5)."""
    pw = 0.74 * D
    b = z0 + 0.17 * D
    mb.box(x - pw, y - pw, z0, x + pw, y + pw, b, mat)
    k = D
    mb.lathe([(0.70 * k, b), (0.735 * k, b + 0.045 * k), (0.71 * k, b + 0.10 * k), (0.63 * k, b + 0.125 * k),
              (0.585 * k, b + 0.18 * k), (0.615 * k, b + 0.235 * k), (0.60 * k, b + 0.255 * k),
              (0.635 * k, b + 0.285 * k), (0.60 * k, b + 0.325 * k), (0.51 * k, b + 0.335 * k)],
             segs, mat, x, y, cap_top=False)
    return b + 0.335 * D


def fluted_shaft(mb, x, y, z0, z1, r0, r1, mat, flutes=24, rings=6, entasis=0.018, depth=0.075):
    """Column shaft with entasis and `flutes` concave flutes separated by fillets."""
    pitch = TAU / flutes
    pat = [(-0.5, 1.0), (-0.4, 1.0), (-0.22, 1 - depth * 0.72), (0.0, 1 - depth), (0.22, 1 - depth * 0.72),
           (0.4, 1.0)]
    angs = [(pitch * (k + f), rf) for k in range(flutes) for f, rf in pat]
    rows = []
    for j in range(rings + 1):
        t = j / rings
        taper = 0.0 if t < 0.33 else (t - 0.33) / 0.67     # straight lower third, then taper
        r = r0 + (r1 - r0) * taper + r0 * entasis * math.sin(math.pi * t)
        z = z0 + (z1 - z0) * t
        rows.append([(x + r * rf * math.cos(a), y + r * rf * math.sin(a), z) for a, rf in angs])
    n = len(angs)
    du = TAU * r0 / n
    for j in range(rings):
        va, vb = (z1 - z0) * j / rings, (z1 - z0) * (j + 1) / rings
        for k in range(n):
            k2 = (k + 1) % n
            mb.poly([rows[j][k], rows[j][k2], rows[j + 1][k2], rows[j + 1][k]], mat, smooth=True,
                    uvs=[(k * du, va), ((k + 1) * du, va), ((k + 1) * du, vb), (k * du, vb)])


def _leaf(mb, cx, cy, ang, r0, z0, h, w, mat):
    """One acanthus leaf: curved, mid-ribbed patch leaning out, tip curling over."""
    ca, sa = math.cos(ang), math.sin(ang)
    nj, ni = 4, 4
    rows = []
    for j in range(nj + 1):
        t = j / nj
        wid = w * (0.55 + 0.55 * math.sin(math.pi * min(t * 0.95, 1.0))) * (1.0 - 0.8 * t ** 4)
        out = r0 + h * (0.04 + 0.30 * t * t)
        z = z0 + h * (t if t <= 0.75 else 0.75 + (t - 0.75) * 0.35)
        if j == nj:
            out += h * 0.16
            z -= h * 0.06
        row = []
        for i in range(ni + 1):
            s = (i / ni - 0.5) * wid
            lobe = 0.5 + 0.5 * math.cos(i * math.pi)
            rr = out + h * 0.05 * (1 - abs(2 * i / ni - 1)) - abs(s) * 0.28 + h * 0.025 * lobe * t
            row.append((cx + rr * ca - s * sa, cy + rr * sa + s * ca, z))
        rows.append(row)
    for j in range(nj):
        for i in range(ni):
            mb.poly([rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]], mat, smooth=True)


def _volute(mb, cx, cy, a, rt, z0, z1, D, mat):
    """Cauliculus rising from the bell and rolling into a corner volute under the abacus."""
    ca, sa = math.cos(a), math.sin(a)

    def P(r, z):
        return (cx + r * ca, cy + r * sa, z)
    rc, R, zc = 0.80 * D, 0.11 * D, z1 - 0.13 * D
    pts = [P(rt * 1.02, z0), P(rt * 1.20, z0 + (z1 - z0) * 0.40), P(rt * 1.45, z0 + (z1 - z0) * 0.72),
           P(rc - R * 0.3, zc + R * 1.05)]
    for k in range(10):
        th = math.pi / 2 - k * 0.72
        rr = R * (1 - 0.075 * k)
        pts.append(P(rc + rr * math.cos(th), zc + rr * math.sin(th)))
    for p0, p1 in zip(pts, pts[1:]):
        beam(mb, p0, p1, 0.075 * D, mat, 0.06 * D)


def _abacus(mb, x, y, z0, h, D, mat):
    a, sag, cut = 0.74 * D, 0.11 * D, 0.07 * D
    corners = [(-a, -a), (a, -a), (a, a), (-a, a)]
    ring = []
    for i in range(4):
        (x0, y0), (x1, y1) = corners[i], corners[(i + 1) % 4]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        ux, uy = dx / L, dy / L
        nx, ny = -uy, ux
        for k in range(7):
            t = k / 6
            s = cut + (L - 2 * cut) * t
            sg = sag * math.sin(math.pi * t)
            ring.append((x + x0 + ux * s + nx * sg, y + y0 + uy * s + ny * sg))
    mb.prism(ring, z0, z0 + h, mat)
    for fx, fy in ((0, -1), (1, 0), (0, 1), (-1, 0)):        # fleurons
        px, py = x + fx * (a - sag - 0.03 * D), y + fy * (a - sag - 0.03 * D)
        mb.box(px - 0.06 * D, py - 0.06 * D, z0 + 0.1 * h, px + 0.06 * D, py + 0.06 * D, z0 + h * 0.95, mat)


def corinthian_capital(mb, x, y, zc, D, mat, segs=16, leaves=True):
    """Approximate Corinthian capital: astragal, bell, 2 x 8 acanthus leaves, 4 corner
    volutes, concave abacus with fleurons. Height = D (Vitruvius IV.1.11)."""
    rt = D * 5 / 12
    ab = D / 7
    hb = D - ab
    mb.lathe([(rt * 1.0, zc - 0.07 * D), (rt * 1.09, zc - 0.045 * D), (rt * 1.09, zc - 0.02 * D),
              (rt * 1.0, zc)], segs, mat, x, y, cap_top=False)
    mb.lathe([(rt, zc), (rt * 1.02, zc + 0.4 * hb), (rt * 1.10, zc + 0.85 * hb), (rt * 1.25, zc + hb)], segs, mat,
             x, y, cap_top=True)
    if leaves:
        for row, (h0, hh, off) in enumerate(((0.0, 0.40, 0.0), (0.24, 0.42, 0.5))):
            for k in range(8):
                ang = TAU * (k + off) / 8 + math.pi / 8
                _leaf(mb, x, y, ang, rt * (1.0 + 0.04 * row), zc + h0 * hb, hh * hb, TAU * rt / 8 * 1.05, mat)
        for k in range(4):
            _volute(mb, x, y, math.pi / 4 + k * math.pi / 2, rt, zc + 0.55 * hb, zc + hb, D, mat)
    _abacus(mb, x, y, zc + hb, ab, D, mat)


def column(mb, x, y, z0, H, D, mat, order="corinthian", segs=12, fluted=None):
    """Roman column, total height H (base + shaft + capital), lower diameter D.
    corinthian: attic base, fluted shaft (24 flutes, Vitruvius IV.4) with entasis tapering
    to 5/6 D, capital height D. tuscan: torus base, plain shaft, D/2 capital."""
    r = D / 2
    if order == "corinthian":
        fluted = D >= 0.7 if fluted is None else fluted
        zs0 = attic_base(mb, x, y, z0, D, mat, segs=max(segs, 16))
        zs1 = z0 + H - D
        if fluted:
            fluted_shaft(mb, x, y, zs0, zs1 - 0.07 * D, r, r * 5 / 6, mat)
        else:
            prof = [(r * (1 - (max(0.0, k / 4 - 0.33) / 0.67) / 6) + r * 0.02 * math.sin(math.pi * k / 4),
                     zs0 + (zs1 - zs0) * k / 4) for k in range(5)]
            mb.lathe(prof, segs, mat, x, y, cap_top=False)
        corinthian_capital(mb, x, y, zs1, D, mat, segs=max(segs, 12), leaves=fluted or D >= 0.5)
        return
    cap_h = 0.5 * D
    zs0, zs1 = z0 + 0.5 * D, z0 + H - cap_h
    pw = 0.68 * D
    mb.box(x - pw, y - pw, z0, x + pw, y + pw, z0 + 0.16 * D, mat)
    mb.lathe([(0.66 * D, z0 + 0.16 * D), (0.66 * D, z0 + 0.28 * D), (0.58 * D, z0 + 0.36 * D),
              (0.60 * D, z0 + 0.44 * D), (r * 1.04, zs0)], segs, mat, x, y, cap_top=False)
    prof = [(r * (1 - k / 24) + r * 0.02 * math.sin(math.pi * k / 4), zs0 + (zs1 - zs0) * k / 4) for k in range(5)]
    mb.lathe(prof, segs, mat, x, y, cap_top=False)
    rt = r * 5 / 6
    mb.lathe([(rt * 1.05, zs1), (rt * 1.1, zs1 + 0.2 * cap_h), (rt * 1.35, zs1 + 0.6 * cap_h)],
             segs, mat, x, y, cap_top=True)
    a = 0.62 * D
    mb.box(x - a, y - a, zs1 + 0.6 * cap_h, x + a, y + a, z0 + H, mat)


def _rect_sides(x0, y0, x1, y1):
    """(origin, rot, length) frames for the 4 sides of a rectangle, local -y = outward."""
    return [((x0, y0, 0), 0.0, x1 - x0), ((x1, y0, 0), math.pi / 2, y1 - y0),
            ((x1, y1, 0), math.pi, x1 - x0), ((x0, y1, 0), 1.5 * math.pi, y1 - y0)]


def entablature(mb, x0, y0, x1, y1, z, D, mat, sides=(True, True, True, True)):
    """Corinthian entablature over the rectangle of the upper column faces: architrave in
    three fasciae, frieze, dentils, modillions, corona and sima (profile = estimate).
    Returns the top z (= z + 2.45 D)."""
    prof = [(0.0, z), (0.0, z + 0.24 * D), (0.03 * D, z + 0.26 * D), (0.03 * D, z + 0.48 * D),
            (0.06 * D, z + 0.50 * D), (0.06 * D, z + 0.68 * D), (0.14 * D, z + 0.76 * D), (0.14 * D, z + 0.79 * D),
            (0.0, z + 0.80 * D), (0.0, z + 1.52 * D), (0.06 * D, z + 1.56 * D), (0.06 * D, z + 1.60 * D),
            (0.11 * D, z + 1.64 * D), (0.11 * D, z + 1.81 * D), (0.20 * D, z + 1.84 * D), (0.20 * D, z + 2.04 * D),
            (0.80 * D, z + 2.04 * D), (0.80 * D, z + 2.26 * D), (0.88 * D, z + 2.33 * D), (0.86 * D, z + 2.45 * D)]
    mb.moulding(x0, y0, x1, y1, prof, mat, closed=True, sides=sides)
    zd0, zd1 = z + 1.64 * D, z + 1.81 * D
    zm0, zm1 = z + 1.86 * D, z + 2.04 * D
    for (ox, oy, _), rot, L in [f for f, s in zip(_rect_sides(x0, y0, x1, y1), sides) if s]:
        with mb.push((ox, oy, 0.0), rot):
            for i in range(int((L + 0.4 * D) / (0.21 * D))):
                xx = -0.15 * D + i * 0.21 * D
                mb.box(xx, -0.25 * D, zd0, xx + 0.13 * D, -0.11 * D, zd1, mat, top=False, bottom=True)
            for i in range(int((L + 1.2 * D) / (0.8 * D))):
                xx = -0.55 * D + i * 0.8 * D
                mb.box(xx, -0.74 * D, zm0, xx + 0.2 * D, -0.20 * D, zm1, mat, top=False, bottom=True)
                mb.box(xx + 0.02 * D, -0.78 * D, zm0 + 0.03 * D, xx + 0.18 * D, -0.70 * D, zm1, mat, top=False,
                       bottom=True)
    return z + 2.45 * D


# =========================================================================== temple
def temple(mb: MeshBuilder, rng: random.Random, D=0.9, ncols=6, flank=11, podium_h=3.2,
           marble="TL_Marble", podium_mat="TL_Ashlar", roof="TL_Tile"):
    """Italic Corinthian hexastyle pseudoperipteral temple on a high podium with
    frontal stairs (type of the Maison Carree at Nimes). Front at y=0, centred on x=0.
    Column height 10 D; eustyle intercolumniation (2.25 D clear, 3 D at the centre,
    Vitruvius III.3); pediment rise 1/9 of the front (Vitruvius III.5.12).
    Returns the footprint (w, d)."""
    H = 10 * D
    sp = [3.25 * D] * (ncols - 1)
    sp[(ncols - 1) // 2] = 4.0 * D
    axis_w = sum(sp)
    xs = [-axis_w / 2]
    for s in sp:
        xs.append(xs[-1] + s)
    a = 3.25 * D
    stair_d = round(podium_h / 0.3) * 0.38 + 0.2
    ys = [stair_d + 1.2 * D + a * i for i in range(flank)]
    half = axis_w / 2 + 0.9 * D
    pod_x0, pod_x1 = -half - 0.5, half + 0.5
    pod_y0, pod_y1 = stair_d, ys[-1] + 0.9 * D + 0.5
    zp = podium_h
    mb.box(pod_x0, pod_y0, 0, pod_x1, pod_y1, zp - 0.45, podium_mat, top=False)
    mb.moulding(pod_x0, pod_y0, pod_x1, pod_y1,
                [(0.45, -0.3), (0.45, 0.30), (0.38, 0.36), (0.30, 0.42), (0.22, 0.55), (0.12, 0.60), (0.0, 0.66)],
                podium_mat, closed=False, sides=(False, True, True, True))
    mb.moulding(pod_x0, pod_y0, pod_x1, pod_y1,
                [(0.0, zp - 0.45), (0.06, zp - 0.42), (0.10, zp - 0.30), (0.22, zp - 0.22), (0.32, zp - 0.12),
                 (0.32, zp)], podium_mat, closed=True)
    stairs(mb, pod_x0 + 1.4, pod_x1 - 1.4, 0, 0, zp, 0.38, "TL_Travertine")
    for cx0, cx1 in ((pod_x0, pod_x0 + 1.4), (pod_x1 - 1.4, pod_x1)):
        mb.box(cx0, 0, 0, cx1, pod_y0, zp - 0.45, podium_mat, top=False)
        mb.moulding(cx0, 0.0, cx1, pod_y0 + 0.3, [(0.0, zp - 0.45), (0.10, zp - 0.30), (0.25, zp - 0.15),
                                                  (0.25, zp)], podium_mat, closed=True)
        mb.box(cx0 + 0.2, 0.3, zp, cx1 - 0.2, 1.6, zp + 1.1, podium_mat)        # statue bases on the cheeks
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            if j == 0 or (j <= 2 and i in (0, ncols - 1)):
                column(mb, x, y, zp, H, D, marble, segs=16)
    cx0, cx1 = xs[0] + 0.25 * D, xs[-1] - 0.25 * D
    cy0, cy1 = ys[2] + 0.5 * D, ys[-1]
    door = [dict(xc=(cx1 - cx0) / 2, w=3.4, zb=0.0, zs=6.8, arch=False, depth=0.9, rmat="TL_Bronze")]
    with mb.push((cx0, cy0, zp)):
        rect_walls(mb, cx1 - cx0, cy1 - cy0, 0, H, 0.8, marble, openings={"s": door}, through=False)
        dx = (cx1 - cx0) / 2
        mb.box(dx - 2.2, -0.25, 6.8, dx + 2.2, 0.0, 7.6, marble)
        mb.box(dx - 2.5, -0.45, 7.6, dx + 2.5, 0.0, 7.85, marble)
        for sx in (-1, 1):
            mb.box(dx + sx * 1.95 - 0.25, -0.2, 0, dx + sx * 1.95 + 0.25, 0.0, 6.8, marble)
    for j in range(3, flank):
        for x in (xs[0], xs[-1]):
            column(mb, x, ys[j], zp, H, D * 0.98, marble, segs=12)
    for x in xs[1:-1]:
        column(mb, x, ys[-1], zp, H, D * 0.98, marble, segs=12)
    rt = D * 5 / 12
    ex0, ex1 = xs[0] - rt, xs[-1] + rt
    ey0, ey1 = ys[0] - rt, ys[-1] + rt
    zt = entablature(mb, ex0, ey0, ex1, ey1, zp + H, D, marble)
    ov = 0.86 * D
    rx0, rx1, ry0, ry1 = ex0 - ov, ex1 + ov, ey0 - ov, ey1 + ov
    pitch = math.degrees(math.atan2((rx1 - rx0) / 9, (rx1 - rx0) / 2))
    t = math.tan(math.radians(pitch))
    mb.gable_roof(rx0 + 0.05, ry0 + 0.05, rx1 - 0.05, ry1 - 0.05, zt, pitch, roof, overhang=0.25, ridge_axis="y",
                  gable_mat=marble, thickness=0.3, verge_mat=marble)
    apex = zt + (rx1 - rx0) / 2 * t
    for yy, s in ((ry0, -1), (ry1, 1)):
        y_t = yy - s * 0.35                       # tympanum set back behind the cornice line
        tri = [(rx0 + 0.6, y_t, zt), (rx1 - 0.6, y_t, zt), (0.0, y_t, apex - 0.55)]
        mb.poly(tri if s < 0 else tri[::-1], marble)
        for xa in (rx0 - 0.1, rx1 + 0.1):         # raking cornice in two steps
            beam(mb, (xa, yy + s * 0.25, zt + 0.12), (0.0, yy + s * 0.25, apex + 0.12), 0.95 * D, marble, 0.30 * D)
            beam(mb, (xa * 0.995, yy + s * 0.1, zt + 0.40), (0.0, yy + s * 0.1, apex + 0.40), 1.05 * D, marble,
                 0.20 * D)
        mb.box(-0.5, yy - 0.4, apex + 0.3, 0.5, yy + 0.4, apex + 1.4, marble)          # acroteria plinths
        for xa in (rx0 + 0.2, rx1 - 1.0):
            mb.box(xa, yy - 0.4, zt + 0.3, xa + 0.8, yy + 0.4, zt + 1.0, marble)
    return (pod_x1 - pod_x0, pod_y1)


# =========================================================================== houses
def facade_style(rng):
    """Coherent facade parameters for one building (estimates after Ostia/Pompeii types)."""
    return dict(fl0=rng.uniform(3.7, 4.3), fln=rng.uniform(2.9, 3.3), shop_w=rng.uniform(2.3, 3.0),
                pier=rng.uniform(1.1, 1.9), shop_h=rng.uniform(2.8, 3.2), shop_arch=rng.random() < 0.45,
                win_w=rng.uniform(0.8, 1.1), win_h=rng.uniform(1.2, 1.6), spacing=rng.uniform(2.5, 3.4),
                win_arch=rng.random() < 0.22, closed=rng.uniform(0.12, 0.40), open=rng.uniform(0.10, 0.35),
                course=rng.random() < 0.75, pent=rng.random() < 0.3, balcony=rng.random() < 0.5,
                cmat=rng.choice(["TL_Travertine", "TL_Travertine", "TL_Brick"]))


def balcony(mb, a0, a1, z, depth=1.15):
    """Timber maenianum: projecting joists, plank floor, posts and rails (facade frame)."""
    x = a0 + 0.2
    while x < a1 - 0.1:
        mb.box(x - 0.08, -depth - 0.05, z - 0.22, x + 0.08, 0.0, z, "TL_TimberDark", bottom=True)
        x += 0.85
    mb.box(a0, -depth, z, a1, 0.0, z + 0.07, "TL_Timber", bottom=True)
    x = a0 + 0.05
    while x <= a1:
        mb.box(x - 0.05, -depth, z + 0.07, x + 0.05, -depth + 0.1, z + 1.0, "TL_TimberDark")
        x += 0.95
    mb.box(a0, -depth - 0.02, z + 0.95, a1, -depth + 0.1, z + 1.05, "TL_TimberDark")
    mb.box(a0, -depth, z + 0.48, a1, -depth + 0.05, z + 0.54, "TL_TimberDark")
    for xx in (a0, a1 - 0.08):
        mb.box(xx, -depth, z + 0.95, xx + 0.08, 0.0, z + 1.05, "TL_TimberDark")


def facade(mb, rng, L, floors, mat, st, H, shop=True, door_mid=False, t=0.6):
    """Street facade along local x in [0, L], outer face y=0 (outward -y), height H.
    Ground floor: tabernae (deep openings, counters, shutter boards, goods) and stair
    doors; upper floors: recessed windows with sills and shutters; string course,
    two-step eave cornice, optional pent roof on brackets or a timber balcony."""
    fl0, fln = st["fl0"], st["fln"]
    gh = min(fl0, H)
    ops = []
    if shop:
        sw = st["shop_w"]
        sp = sw + st["pier"]
        n = max(1, int((L - 1.0) // sp))
        x0 = (L - (n - 1) * sp) / 2
        for i in range(n):
            xc = x0 + i * sp
            if door_mid and i == n // 2:
                ops.append(dict(xc=xc, w=2.0, zb=0.0, zs=min(3.0, gh - 0.6), arch=False, depth=1.4,
                                rmat="TL_TimberDark"))
            elif rng.random() < 0.16:
                ops.append(dict(xc=xc, w=1.2, zb=0.0, zs=2.5 - (0.6 if st["shop_arch"] else 0), arch=st["shop_arch"],
                                depth=0.7, rmat="TL_TimberDark"))
            else:
                ops.append(dict(xc=xc, w=sw, zb=0.0, zs=min(st["shop_h"], gh - 0.5) - (sw / 2 if st["shop_arch"] else 0),
                                arch=st["shop_arch"], depth=1.7, rmat="TL_ShopDark", shop=True))
    else:
        for o in window_row(L, 3.4, 0.55, 2.1, 2.7, arch=False, margin=1.0):
            o.update(depth=0.35)
            ops.append(o)
    arcade_wall(mb, L, 0.0, gh, t, ops, mat, through=False, cap=False)
    for o in ops:
        xl, xr = o["xc"] - o["w"] / 2, o["xc"] + o["w"] / 2
        if o.get("shop"):
            r = rng.random()
            if r < 0.45:
                mb.box(xl + 0.15, 0.15, 0.0, xl + o["w"] * rng.uniform(0.45, 0.7), 0.75, 0.95, "TL_TravertineSlabs")
            elif r < 0.7:
                mb.box(xl, 0.12, 0.0, xl + o["w"] * rng.uniform(0.3, 0.6), 0.2, o["zs"], "TL_Shutter")
            if not o["arch"]:
                mb.box(xl - 0.18, -0.05, o["zs"], xr + 0.18, 0.0, o["zs"] + 0.24, "TL_TimberDark", bottom=True)
            if r > 0.8:
                for k in range(rng.randint(1, 3)):
                    amphora(mb, xl + 0.4 + 0.45 * k, 0.45, 0.0)
    if H <= fl0 + 0.1:
        if st["course"]:
            mb.box(0, -0.22, H - 0.3, L, 0.0, H - 0.05, st["cmat"], bottom=True)
        return
    z = fl0
    for f in range(1, floors):
        top = f == floors - 1
        z1 = H if top else z + fln
        ww, wh = st["win_w"], st["win_h"]
        if top:
            ww, wh = ww * 0.85, wh * 0.72
        zb = z + (0.95 if top else 0.85)
        arch = st["win_arch"]
        ops = []
        n = max(1, int((L - 1.2) // st["spacing"]))
        x0 = (L - (n - 1) * st["spacing"]) / 2
        for i in range(n):
            o = dict(xc=x0 + i * st["spacing"], w=ww, zb=zb, zs=zb + wh - (ww / 2 if arch else 0.0), arch=arch,
                     depth=0.3)
            if rng.random() < st["closed"]:
                o["rmat"] = "TL_Shutter"
            ops.append(o)
        arcade_wall(mb, L, z, z1, t, ops, mat, through=False, cap=False)
        for o in ops:
            xl, xr = o["xc"] - ww / 2, o["xc"] + ww / 2
            mb.box(xl - 0.08, -0.08, zb - 0.09, xr + 0.08, 0.0, zb, "TL_Travertine", bottom=True)
            if "rmat" not in o and rng.random() < st["open"]:
                mb.box(xl - ww / 2, -0.06, zb, xl - 0.02, -0.01, zb + wh, "TL_Shutter")
                mb.box(xr + 0.02, -0.06, zb, xr + ww / 2, -0.01, zb + wh, "TL_Shutter")
        z = z1
    if st["course"]:
        mb.box(0, -0.13, fl0 - 0.06, L, 0.0, fl0 + 0.14, st["cmat"], bottom=True)
    mb.box(0, -0.18, H - 0.42, L, 0.0, H - 0.22, st["cmat"], bottom=True)
    mb.box(0, -0.32, H - 0.22, L, 0.0, H - 0.02, st["cmat"], bottom=True)
    if shop and st["pent"]:
        lean_to_roof(mb, 0.3, L - 0.3, -1.05, 0.0, fl0 - 0.5, fl0 - 0.05, "TL_Tile", overhang=0.15)
        x = 0.6
        while x < L - 0.3:
            beam(mb, (x, 0.0, fl0 - 0.75), (x, -1.0, fl0 - 0.48), 0.12, "TL_TimberDark")
            x += 2.4
    elif floors >= 3 and st["balcony"] and L > 7:
        a0 = rng.uniform(0.1, 0.35) * L
        a1 = min(L - 0.6, a0 + rng.uniform(5.0, 13.0))
        balcony(mb, a0, a1, fl0 + 0.02)


def _side_frame(side, w, d):
    """push() args giving a frame whose x runs along facade `side`, outward = -y."""
    return [((0, 0, 0), 0.0), ((w, 0, 0), math.pi / 2), ((w, d, 0), math.pi), ((0, d, 0), 1.5 * math.pi)][side]


def _walls(mb, rng, w, d, H, floors, street, mat, st, blank_mat, door_mid=False, shop=True):
    """Outer walls of [0,w]x[0,d]: modelled facades on street sides, plain (shader-windowed)
    party walls elsewhere."""
    for side in range(4):
        L = w if side % 2 == 0 else d
        with mb.push(*_side_frame(side, w, d)):
            if street[side] and L >= 4.0:
                facade(mb, rng, L, floors, mat, st, H, shop=shop, door_mid=door_mid and side == 0)
            else:
                mb.poly([(0, 0, 0), (L, 0, 0), (L, 0, H), (0, 0, H)], blank_mat, uvs=[(0, 0), (L, 0), (L, H), (0, H)],
                        fac=2 if blank_mat in ("TL_Plaster", "TL_BrickWin") else 0, wlen=L)


def _roof(mb, rng, w, d, H, roof, court=None, pitch=None):
    pitch = pitch or rng.uniform(18.0, 24.0)
    if court:
        ix0, iy0, ix1, iy1 = court
        mb.courtyard_roof(0, 0, w, d, ix0, iy0, ix1, iy1, H, pitch, roof)
    elif rng.random() < 0.5:
        mb.hip_roof(0, 0, w, d, H, pitch, roof)
    else:
        mb.gable_roof(0, 0, w, d, H, pitch, roof, ridge_axis="x" if w >= d else "y", gable_mat="TL_PlasterPlain")


def insula(mb, rng, w, d, floors, street=(True, False, False, False), material=None, roof="TL_Tile",
           balconies=True, style=None, split=True):
    """Multi-storey apartment block (Ostia type) with modelled street facades, an optional
    light court, and (when long) two masses of different height. Footprint [0,w]x[0,d];
    street = facades with shops for (s, e, n, w). Returns the highest wall top."""
    st = dict(style or facade_style(rng))
    if not balconies:
        st["balcony"] = False
    mat = material or rng.choice(["TL_PlasterWall", "TL_PlasterWall", "TL_PlasterWall", "TL_Brick"])
    if mat == "TL_Plaster":
        mat = "TL_PlasterWall"
    blank = {"TL_PlasterWall": "TL_Plaster", "TL_Brick": "TL_BrickWin"}.get(mat, mat)
    if split and w >= 18 and d < 20 and floors >= 2 and rng.random() < 0.45:
        wa = w * rng.uniform(0.4, 0.6)
        fb = max(1, floors + rng.choice([-1, -1, 1]))
        ha = insula(mb, rng, wa, d, floors, street=(street[0], False, street[2], street[3]), material=mat, roof=roof,
                    balconies=balconies, style=st, split=False)
        old = mb.var
        mb.var = (mb.var + rng.uniform(0.15, 0.4)) % 1.0
        with mb.push((wa, 0, 0)):
            hb = insula(mb, rng, w - wa, d, fb, street=(street[0], street[1], street[2], False), material=mat,
                        roof=roof, balconies=balconies, style=st, split=False)
        mb.var = old
        return max(ha, hb)
    H = st["fl0"] + st["fln"] * (floors - 1) + 0.5
    court = None
    if w >= 20 and d >= 20:
        cw, cd = max(6.0, w * 0.32), max(6.0, d * 0.32)
        ix0, iy0 = (w - cw) / 2, (d - cd) / 2
        court = (ix0, iy0, ix0 + cw, iy0 + cd)
    _walls(mb, rng, w, d, H, floors, street, mat, st, blank)
    if court:
        ix0, iy0, ix1, iy1 = court
        ring = [(ix0, iy1), (ix1, iy1), (ix1, iy0), (ix0, iy0)]
        for i in range(4):
            a, b = ring[i], ring[(i + 1) % 4]
            ln = math.dist(a, b)
            mb.poly([(a[0], a[1], 0), (b[0], b[1], 0), (b[0], b[1], H), (a[0], a[1], H)], blank,
                    uvs=[(0, 0), (ln, 0), (ln, H), (0, H)], fac=2, wlen=ln)
        mb.poly([(ix0, iy0, 0.05), (ix1, iy0, 0.05), (ix1, iy1, 0.05), (ix0, iy1, 0.05)], "TL_TravertineSlabs")
    _roof(mb, rng, w, d, H, roof, court)
    return H


def domus(mb, rng, w, d, street=(True, False, False, False), floors=1):
    """Atrium-peristyle house with shops either side of the entrance (Pompeii type).
    Footprint [0,w]x[0,d]."""
    H = 5.4 if floors == 1 else 8.4
    st = facade_style(rng)
    st.update(fl0=5.0 if floors == 1 else 4.2, pent=False, balcony=False, win_w=0.7, win_h=0.9, spacing=4.0,
              closed=0.5)
    split = d * rng.uniform(0.42, 0.55)
    _walls(mb, rng, w, split, H, floors, (street[0], street[1], False, street[3]), "TL_PlasterWall", st,
           "TL_PlasterWall", door_mid=True)
    with mb.push((0, split, 0)):
        _walls(mb, rng, w, d - split, H - 1.2, 1, (False, street[1], street[2], street[3]), "TL_PlasterWall",
               dict(st, fl0=H - 1.2), "TL_PlasterWall", shop=False)
    aw, ad = min(6.0, w * 0.3), min(5.0, split * 0.3)
    ax0, ay0 = (w - aw) / 2, (split - ad) / 2
    mb.courtyard_roof(0, 0, w, split, ax0, ay0, ax0 + aw, ay0 + ad, H, 22.0, "TL_Tile")
    _inner_ring(mb, ax0, ay0, ax0 + aw, ay0 + ad, H, "TL_PlasterPlain")
    mb.poly([(ax0, ay0, 0.05), (ax0 + aw, ay0, 0.05), (ax0 + aw, ay0 + ad, 0.05), (ax0, ay0 + ad, 0.05)],
            "TL_TravertineSlabs")
    mb.box(ax0 + aw * 0.25, ay0 + ad * 0.25, 0.05, ax0 + aw * 0.75, ay0 + ad * 0.75, 0.3, "TL_Marble")  # impluvium
    if d - split > 12 and w > 14:
        pw, pd = w * 0.55, (d - split) * 0.5
        px0, py0 = (w - pw) / 2, split + (d - split - pd) / 2
        mb.courtyard_roof(0, split, w, d, px0, py0, px0 + pw, py0 + pd, H - 1.2, 20.0, "TL_Tile")
        mb.poly([(px0, py0, 0.1), (px0 + pw, py0, 0.1), (px0 + pw, py0 + pd, 0.1), (px0, py0 + pd, 0.1)],
                "TL_Garden")
        _inner_ring(mb, px0, py0, px0 + pw, py0 + pd, 0.9, "TL_PlasterPlain")
        nx, ny = max(2, int(pw / 2.6)), max(2, int(pd / 2.6))
        ch = H - 1.25
        for i in range(nx + 1):
            for yy in (py0 + 0.1, py0 + pd - 0.1):
                column(mb, px0 + 0.1 + (pw - 0.2) * i / nx, yy, 0, ch, 0.3, "TL_PlasterPlain", "tuscan", 6)
        for j in range(1, ny):
            for xx in (px0 + 0.1, px0 + pw - 0.1):
                column(mb, xx, py0 + 0.1 + (pd - 0.2) * j / ny, 0, ch, 0.3, "TL_PlasterPlain", "tuscan", 6)
        mb.cylinder(px0 + pw / 2, py0 + pd / 2, 0.1, 0.7, 0.9, 12, "TL_Marble")
    else:
        mb.hip_roof(0, split, w, d, H - 1.2, 21.0, "TL_Tile")
    return H


# =========================================================================== props
def amphora(mb, x, y, z, mat="TL_Terracotta", h=1.05):
    """Transport amphora (Dressel-like profile, estimate), standing on its toe."""
    r = h * 0.2
    prof = [(0.02, z), (0.05 * h, z + 0.06 * h), (r * 0.7, z + 0.25 * h), (r, z + 0.52 * h), (r * 0.92, z + 0.66 * h),
            (r * 0.45, z + 0.74 * h), (r * 0.28, z + 0.80 * h), (r * 0.28, z + 0.95 * h), (r * 0.36, z + h)]
    mb.lathe(prof, 8, mat, x, y, cap_top=True)
    for s in (-1, 1):
        beam(mb, (x + s * r * 0.3, y, z + 0.93 * h), (x + s * r * 0.85, y, z + 0.86 * h), 0.035, mat)
        beam(mb, (x + s * r * 0.85, y, z + 0.86 * h), (x + s * r * 0.7, y, z + 0.70 * h), 0.035, mat)


def amphora_stack(mb, rng, x, y, z, n=8):
    for i in range(n):
        a = rng.uniform(0, TAU)
        rr = rng.uniform(0.0, 1.2)
        amphora(mb, x + rr * math.cos(a), y + rr * math.sin(a), z, h=rng.uniform(0.9, 1.15))


def fountain(mb, rng, x, y, z):
    """Street fountain (Pompeii type): basin of four stone slabs and a pillar with spout."""
    with mb.push((x, y, z), rng.choice([0.0, math.pi / 2])):
        mb.box(-0.9, -0.65, 0, 0.9, 0.65, 0.12, "TL_AshlarGrey")
        for (x0, y0, x1, y1) in ((-0.9, -0.65, 0.9, -0.45), (-0.9, 0.45, 0.9, 0.65), (-0.9, -0.45, -0.7, 0.45),
                                 (0.7, -0.45, 0.9, 0.45)):
            mb.box(x0, y0, 0.12, x1, y1, 0.85, "TL_AshlarGrey")
        mb.poly([(-0.7, -0.45, 0.7), (0.7, -0.45, 0.7), (0.7, 0.45, 0.7), (-0.7, 0.45, 0.7)], "TL_Water")
        mb.box(-0.2, 0.45, 0.85, 0.2, 0.75, 1.55, "TL_AshlarGrey")
        mb.box(-0.05, 0.3, 1.25, 0.05, 0.45, 1.32, "TL_Bronze")


def market_stall(mb, rng, x, y, z, rot=0.0, w=3.0, d=2.0):
    """Timber trestle stall with a sloping cloth awning on four poles."""
    cloth = rng.choice(["TL_Cloth", "TL_Cloth", "TL_ClothRed"])
    with mb.push((x, y, z), rot):
        mb.box(-w / 2, -d / 2, 0.75, w / 2, d / 2 - 0.4, 0.85, "TL_Timber", bottom=True)
        for sx in (-1, 1):
            mb.box(sx * w / 2 - 0.05 * sx - 0.05, -d / 2 + 0.1, 0.0, sx * w / 2 - 0.05 * sx + 0.05, d / 2 - 0.5, 0.75,
                   "TL_TimberDark")
        for sx in (-1, 1):
            mb.box(sx * (w / 2) - 0.04, -d / 2 - 0.04, 0.0, sx * (w / 2) + 0.04, -d / 2 + 0.04, 2.15, "TL_TimberDark")
            mb.box(sx * (w / 2) - 0.04, d / 2 - 0.04, 0.0, sx * (w / 2) + 0.04, d / 2 + 0.04, 2.55, "TL_TimberDark")
        sag = 0.12
        pts = []
        for k in range(5):
            t = k / 4
            pts.append((-d / 2 - 0.25 + (d + 0.3) * t, 2.1 + 0.45 * t + (-sag * math.sin(math.pi * t))))
        for (ya, za), (yb, zb) in zip(pts, pts[1:]):
            mb.poly([(-w / 2 - 0.1, ya, za), (w / 2 + 0.1, ya, za), (w / 2 + 0.1, yb, zb), (-w / 2 - 0.1, yb, zb)],
                    cloth, uvs=[(0, ya), (w, ya), (w, yb), (0, yb)])
            mb.poly([(-w / 2 - 0.1, yb, zb - 0.01), (w / 2 + 0.1, yb, zb - 0.01), (w / 2 + 0.1, ya, za - 0.01),
                     (-w / 2 - 0.1, ya, za - 0.01)], cloth, uvs=[(0, yb), (w, yb), (w, ya), (0, ya)])
        mb.poly([(-w / 2 - 0.1, -d / 2 - 0.25, 2.1), (w / 2 + 0.1, -d / 2 - 0.25, 2.1),
                 (w / 2 + 0.1, -d / 2 - 0.25, 1.75), (-w / 2 - 0.1, -d / 2 - 0.25, 1.75)], cloth)
        # goods: baskets / jars on the table
        for k in range(rng.randint(2, 5)):
            gx = rng.uniform(-w / 2 + 0.3, w / 2 - 0.3)
            gy = rng.uniform(-d / 2 + 0.25, d / 2 - 0.6)
            if rng.random() < 0.5:
                mb.cylinder(gx, gy, 0.85, 1.05, 0.22, 8, "TL_Timber", r_top=0.26)
            else:
                mb.lathe([(0.02, 0.85), (0.16, 0.92), (0.18, 1.05), (0.08, 1.17), (0.09, 1.22)], 8, "TL_Terracotta",
                         gx, gy, cap_top=True)
        amphora_stack(mb, rng, w / 2 + 0.6, 0.0, 0.0, n=rng.randint(2, 5))


def cart(mb, rng, x, y, z, rot=0.0):
    """Two-wheeled cart (carrus/plaustrum type, estimate): bed, side boards, shafts, disc wheels."""
    with mb.push((x, y, z), rot):
        mb.box(-1.1, -0.7, 0.75, 1.1, 0.7, 0.85, "TL_Timber", bottom=True)
        for sy in (-1, 1):
            mb.box(-1.1, sy * 0.7 - 0.04, 0.85, 1.1, sy * 0.7 + 0.04, 1.25, "TL_Timber")
        mb.box(-1.1, -0.7, 0.85, -1.02, 0.7, 1.2, "TL_Timber")
        for sy in (-0.35, 0.35):
            beam(mb, (1.0, sy, 0.8), (2.9, sy * 0.6, 0.35), 0.09, "TL_TimberDark")
        for sy in (-0.85, 0.85):
            pts = [(0.62 * math.cos(TAU * k / 14), sy, 0.62 + 0.62 * math.sin(TAU * k / 14)) for k in range(14)]
            if sy > 0:
                pts = pts[::-1]
            mb.poly(pts, "TL_TimberDark")
            mb.poly([(p[0], p[1] + (0.08 if sy > 0 else -0.08), p[2]) for p in pts[::-1]], "TL_TimberDark")
        mb.box(-0.06, -0.95, 0.56, 0.06, 0.95, 0.68, "TL_TimberDark")
        if rng.random() < 0.6:
            for k in range(rng.randint(2, 4)):
                mb.cylinder(-0.6 + 0.5 * k, rng.uniform(-0.2, 0.2), 0.85, 1.25, 0.24, 8, "TL_Terracotta")


def statue(mb, rng, x, y, z, rot=0.0, mat="TL_Marble", plinth=True, scale=1.0):
    """Honorific statue on an inscribed plinth: draped standing figure (abstracted, no face)."""
    with mb.push((x, y, z), rot, (scale, scale, scale)):
        h0 = 0.0
        if plinth:
            mb.box(-0.75, -0.75, 0.0, 0.75, 0.75, 0.25, "TL_Marble")
            mb.box(-0.6, -0.6, 0.25, 0.6, 0.6, 1.75, "TL_Marble")
            mb.box(-0.72, -0.72, 1.75, 0.72, 0.72, 1.95, "TL_Marble")
            h0 = 1.95
        mb.box(-0.32, -0.32, h0, 0.32, 0.32, h0 + 0.1, mat)
        # body: draped, slightly asymmetric lathe; folds via varying radius
        prof = []
        for k in range(9):
            t = k / 8
            zz = h0 + 0.1 + 1.35 * t
            rr = 0.30 - 0.05 * t + 0.02 * math.sin(t * 17.0) + (0.05 if 0.55 < t < 0.85 else 0.0)
            prof.append((rr, zz))
        prof.append((0.12, h0 + 1.5))
        mb.lathe(prof, 10, mat, 0.0, 0.0, cap_top=True)
        mb.lathe([(0.07, h0 + 1.5), (0.11, h0 + 1.58), (0.11, h0 + 1.70), (0.06, h0 + 1.78), (0.0, h0 + 1.80)], 8,
                 mat, 0.0, 0.03, cap_top=False)
        beam(mb, (0.26, 0.0, h0 + 1.38), (0.36, -0.25, h0 + 1.05), 0.12, mat)     # raised forearm
        beam(mb, (0.36, -0.25, h0 + 1.05), (0.40, -0.48, h0 + 1.12), 0.10, mat)
        beam(mb, (-0.27, 0.0, h0 + 1.36), (-0.33, 0.02, h0 + 0.85), 0.14, mat)    # arm in the toga fold
