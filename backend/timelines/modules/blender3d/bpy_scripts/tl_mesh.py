"""Mesh builder used by every TIMELINES procedural generator (runs inside Blender).

Geometry is accumulated in plain Python lists and turned into one Blender mesh per
builder. Each face carries a material slot, explicit UVs in metres (so procedural
brick/tile/window patterns have real-world scale) and three face attributes read
by the shaders:

* ``var``   0..1 per-building random value (colour / weathering variation)
* ``fac``   facade kind: 0 plain, 1 street facade (shop openings + windows),
            2 windows only, 3 arcade/colonnade back wall (dark, no windows)
* ``wlen``  length of the wall the face belongs to (centres window rows)

Coordinates: 1 unit = 1 m, Z up.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Vector


TILE_MATS = {"TL_Tile"}


class MeshBuilder:
    def __init__(self, name: str):
        self.name = name
        self.verts: list[tuple[float, float, float]] = []
        self.faces: list[tuple[int, ...]] = []
        self.face_mat: list[str] = []
        self.face_uv: list[list[tuple[float, float]]] = []
        self.face_var: list[float] = []
        self.face_fac: list[int] = []
        self.face_wlen: list[float] = []
        self.smooth: list[bool] = []
        self.var = 0.5
        self._mstack = [Matrix.Identity(4)]

    # ------------------------------------------------------------ transforms
    @property
    def m(self) -> Matrix:
        return self._mstack[-1]

    def push(self, loc=(0, 0, 0), rot_z: float = 0.0, scale=(1, 1, 1)):
        mat = (Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot_z, 4, "Z")
               @ Matrix.Diagonal(Vector((*scale, 1.0))))
        self._mstack.append(self.m @ mat)
        return self

    def pop(self):
        self._mstack.pop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.pop()

    # ------------------------------------------------------------ primitives
    def _v(self, p) -> int:
        w = self.m @ Vector((p[0], p[1], p[2]))
        self.verts.append((w.x, w.y, w.z))
        return len(self.verts) - 1

    def poly(self, pts, mat, uvs=None, fac=0, wlen=0.0, smooth=False):
        """Add one polygon given local points. UVs default to box projection (m).
        Roof-tile polygons (mat in TILE_MATS, sloping up) also receive modelled
        imbrices along their UV v direction (u = along the eave, v = up the slope)."""
        if uvs is None:
            uvs = box_uv(pts)
        self._face(pts, mat, uvs, fac, wlen, smooth)
        if self.tiles and mat in TILE_MATS and len(pts) >= 3:
            self._imbrices(pts, uvs, mat)

    # roof tiling -----------------------------------------------------------
    tiles = True
    IMB_PITCH = 0.42      # tegula width (m), estimate from surviving Roman tegulae (~0.4-0.5 m)
    IMB_HALF = 0.085      # half width of an imbrex at its base
    IMB_H = 0.085         # imbrex height above the tegula plane

    def _imbrices(self, pts, uvs, mat):
        P = [Vector(p) for p in pts]
        nrm = Vector((0.0, 0.0, 0.0))
        for i in range(len(P)):          # Newell normal (winding = outward)
            a, b = P[i], P[(i + 1) % len(P)]
            nrm.x += (a.y - b.y) * (a.z + b.z)
            nrm.y += (a.z - b.z) * (a.x + b.x)
            nrm.z += (a.x - b.x) * (a.y + b.y)
        area2 = nrm.length
        if area2 < 2.0:
            return
        nrm.normalize()
        if nrm.z < 0.12 or nrm.z > 0.995:   # walls, fascias, flat caps
            return
        # affine map uv -> local point from the first non-degenerate triangle
        U = [Vector((u[0], u[1])) for u in uvs]
        best = None
        for j in range(1, len(P) - 1):
            du1, du2 = U[j] - U[0], U[j + 1] - U[0]
            det = du1.x * du2.y - du1.y * du2.x
            if abs(det) > 1e-6 and (best is None or abs(det) > abs(best[0])):
                best = (det, j)
        if best is None:
            return
        det, j = best
        du1, du2 = U[j] - U[0], U[j + 1] - U[0]
        e1, e2 = P[j] - P[0], P[j + 1] - P[0]
        Eu = (e1 * du2.y - e2 * du1.y) / det
        Ev = (e2 * du1.x - e1 * du2.x) / det
        if Eu.length < 0.5 or Ev.length < 0.5:
            return
        # wrap-around (lathe cones) - u range can be large; clip each line to the polygon
        us = [u.x for u in U]
        k0 = math.ceil(min(us) / self.IMB_PITCH - 0.5)
        k1 = math.floor(max(us) / self.IMB_PITCH - 0.5)
        n = len(U)
        hw, hh = self.IMB_HALF, self.IMB_H
        sec = [(-hw, 0.0), (-hw * 0.72, hh * 0.85), (hw * 0.72, hh * 0.85), (hw, 0.0)]
        for k in range(k0, k1 + 1):
            uc = (k + 0.5) * self.IMB_PITCH
            vs = []
            for i in range(n):
                a, b = U[i], U[(i + 1) % n]
                if (a.x - uc) * (b.x - uc) <= 0 and abs(b.x - a.x) > 1e-9:
                    t = (uc - a.x) / (b.x - a.x)
                    vs.append(a.y + (b.y - a.y) * t)
            if len(vs) < 2:
                continue
            va, vb = min(vs), max(vs)
            # keep clear of hip/valley edges: shrink by the imbrex half width
            va += 0.02
            vb -= 0.06
            if vb - va < 0.3:
                continue
            ring_a, ring_b = [], []
            for (du, dh) in sec:
                base = P[0] + Eu * (uc + du - U[0].x) + nrm * (dh + 0.01)
                ring_a.append(base + Ev * (va - U[0].y))
                ring_b.append(base + Ev * (vb - U[0].y))
            L = vb - va
            for i in range(3):
                self._face([tuple(ring_a[i]), tuple(ring_a[i + 1]), tuple(ring_b[i + 1]), tuple(ring_b[i])], mat,
                           [(i * 0.1, 0.0), ((i + 1) * 0.1, 0.0), ((i + 1) * 0.1, L), (i * 0.1, L)], 0, 0.0, False)
            # closed end at the eave (the visible round end of the cover tile)
            self._face([tuple(ring_a[3]), tuple(ring_a[2]), tuple(ring_a[1]), tuple(ring_a[0])], mat,
                       [(0.2, 0.1), (0.15, 0.17), (0.05, 0.17), (0.0, 0.1)], 0, 0.0, False)

    def _face(self, pts, mat, uvs, fac, wlen, smooth):
        idx = tuple(self._v(p) for p in pts)
        self.faces.append(idx)
        self.face_mat.append(mat)
        self.face_uv.append(list(uvs))
        self.face_var.append(self.var)
        self.face_fac.append(fac)
        self.face_wlen.append(wlen)
        self.smooth.append(smooth)

    def box(self, x0, y0, z0, x1, y1, z1, mat, top=None, bottom=False, fac=(0, 0, 0, 0),
            sides=True, top_mat=None):
        """Axis-aligned box in local space. fac = facade kind for -y,+x,+y,-x sides."""
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        h = z1 - z0
        c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if sides:
            for i in range(4):
                a, b = c[i], c[(i + 1) % 4]
                ln = math.dist(a, b)
                self.poly([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)],
                          mat, uvs=[(0, 0), (ln, 0), (ln, h), (0, h)], fac=fac[i], wlen=ln)
        if top is not False:
            self.poly([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], top_mat or mat)
        if bottom:
            self.poly([(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)], mat)

    def prism(self, ring, z0, z1, mat, cap_top=True, cap_bottom=False, fac=0, smooth=False,
              uv_scale=1.0):
        """Vertical extrusion of a closed CCW ring of (x, y) points."""
        n = len(ring)
        u = 0.0
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            ln = math.dist(a, b)
            self.poly([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], mat,
                      uvs=[(u * uv_scale, 0), ((u + ln) * uv_scale, 0), ((u + ln) * uv_scale, z1 - z0),
                           (u * uv_scale, z1 - z0)], fac=fac, wlen=ln, smooth=smooth)
            u += ln
        if cap_top:
            self.poly([(p[0], p[1], z1) for p in ring], mat)
        if cap_bottom:
            self.poly([(p[0], p[1], z0) for p in reversed(ring)], mat)

    def lathe(self, profile, segs, mat, cx=0.0, cy=0.0, smooth=True, cap_top=True, a0=0.0,
              a1=2 * math.pi, close=True):
        """Surface of revolution around a vertical axis. profile = [(r, z), ...] bottom→top."""
        rings = []
        full = close and abs(a1 - a0 - 2 * math.pi) < 1e-6
        nseg = segs if full else segs + 1
        for r, z in profile:
            ring = []
            for k in range(nseg):
                a = a0 + (a1 - a0) * k / segs
                ring.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
            rings.append(ring)
        circ = 2 * math.pi * max(r for r, _ in profile)
        vacc = 0.0
        for j in range(len(rings) - 1):
            dv = math.dist(profile[j], profile[j + 1])
            for k in range(segs):
                k2 = (k + 1) % nseg if full else k + 1
                u0, u1 = circ * k / segs, circ * (k + 1) / segs
                self.poly([rings[j][k], rings[j][k2], rings[j + 1][k2], rings[j + 1][k]], mat,
                          uvs=[(u0, vacc), (u1, vacc), (u1, vacc + dv), (u0, vacc + dv)], smooth=smooth)
            vacc += dv
        if cap_top and profile[-1][0] > 1e-4 and full:
            self.poly(rings[-1], mat)
        return rings

    def moulding(self, x0, y0, x1, y1, profile, mat, closed=True, sides=(True, True, True, True)):
        """Moulding run around the rectangle [x0,x1]x[y0,y1] (mitred corners).
        profile = [(outward offset, z), ...] bottom -> top. sides = (s, e, n, w) faces drawn."""
        rings = []
        for off, z in profile:
            rings.append([(x0 - off, y0 - off, z), (x1 + off, y0 - off, z), (x1 + off, y1 + off, z),
                          (x0 - off, y1 + off, z)])
        acc = 0.0
        for j in range(len(rings) - 1):
            dv = math.dist(profile[j], profile[j + 1])
            for i in range(4):
                if not sides[i]:
                    continue
                a, b = rings[j][i], rings[j][(i + 1) % 4]
                c, d = rings[j + 1][(i + 1) % 4], rings[j + 1][i]
                ln = math.dist(a, b)
                self.poly([a, b, c, d], mat, uvs=[(0, acc), (ln, acc), (ln, acc + dv), (0, acc + dv)])
            acc += dv
        if closed:
            self.poly(list(rings[-1]), mat)

    def cylinder(self, cx, cy, z0, z1, r, segs, mat, r_top=None, smooth=True, cap=True):
        rt = r if r_top is None else r_top
        self.lathe([(r, z0), (rt, z1)], segs, mat, cx, cy, smooth=smooth, cap_top=cap)

    def gable_roof(self, x0, y0, x1, y1, z, pitch_deg, mat, overhang=0.35, ridge_axis="x",
                   gable_mat=None, thickness=0.18, verge_mat=None):
        """Gable roof (ridge along X or Y) with closed gable triangles."""
        if ridge_axis == "y":
            self.push((0, 0, 0), math.pi / 2)
            # rotate: local x' = y, y' = -x
            self.gable_roof(y0, -x1, y1, -x0, z, pitch_deg, mat, overhang, "x", gable_mat, thickness, verge_mat)
            self.pop()
            return
        t = math.tan(math.radians(pitch_deg))
        hw = (y1 - y0) / 2
        yc = (y0 + y1) / 2
        zr = z + hw * t
        X0, X1 = x0 - overhang, x1 + overhang
        Y0, Y1 = y0 - overhang, y1 + overhang
        ze = z - overhang * t
        slope = math.hypot(hw + overhang, (hw + overhang) * t)
        L = X1 - X0
        # roof planes (UV: u along ridge, v up the slope)
        self.poly([(X0, Y0, ze), (X1, Y0, ze), (X1, yc, zr), (X0, yc, zr)], mat,
                  uvs=[(0, 0), (L, 0), (L, slope), (0, slope)])
        self.poly([(X1, Y1, ze), (X0, Y1, ze), (X0, yc, zr), (X1, yc, zr)], mat,
                  uvs=[(0, 0), (L, 0), (L, slope), (0, slope)])
        self.ridge_cap((X0, yc, zr), (X1, yc, zr), mat)
        # eave fascia (thickness)
        vm = verge_mat or mat
        self.poly([(X0, Y0, ze - thickness), (X1, Y0, ze - thickness), (X1, Y0, ze), (X0, Y0, ze)], vm)
        self.poly([(X1, Y1, ze - thickness), (X0, Y1, ze - thickness), (X0, Y1, ze), (X1, Y1, ze)], vm)
        gm = gable_mat or mat
        for xx, sgn in ((x0, -1), (x1, 1)):
            pts = [(xx, y0, z), (xx, y1, z), (xx, yc, zr)]
            if sgn < 0:
                pts = [pts[1], pts[0], pts[2]]
            self.poly(pts, gm)
        # barge boards: thin strips along the sloped verges
        tk = thickness
        for X, s in ((X0, -1), (X1, 1)):
            for ya, yb in ((Y0, yc), (yc, Y1)):
                za = ze if ya != yc else zr
                zb = ze if yb != yc else zr
                pts = [(X, ya, za - tk), (X, yb, zb - tk), (X, yb, zb), (X, ya, za)]
                if s < 0:
                    pts = [pts[1], pts[0], pts[3], pts[2]]
                self.poly(pts, vm)

    def ridge_cap(self, a, b, mat, w=0.15, h=0.12):
        """Row of ridge tiles (imbrices laid along a ridge/hip line a->b)."""
        a, b = Vector(a), Vector(b)
        d = b - a
        if d.length < 0.3:
            return
        u = d.normalized()
        side = u.cross(Vector((0, 0, 1)))
        if side.length < 1e-3:
            return
        side = side.normalized() * w
        up = side.cross(u).normalized()
        if up.z < 0:
            up = -up
        up = up * h
        tmp, self.tiles = self.tiles, False
        pa = [a - side, a + up * 0.9 - side * 0.5, a + up * 0.9 + side * 0.5, a + side]
        pb = [b - side, b + up * 0.9 - side * 0.5, b + up * 0.9 + side * 0.5, b + side]
        L = d.length
        for i in range(3):
            q = [pa[i], pa[i + 1], pb[i + 1], pb[i]]
            nz = (q[1] - q[0]).cross(q[3] - q[0]).z
            if nz < 0:
                q = q[::-1]
            self.poly([tuple(x) for x in q], mat, uvs=[(0, 0), (0.1, 0), (0.1, L), (0, L)][:4])
        self.tiles = tmp

    def hip_roof(self, x0, y0, x1, y1, z, pitch_deg, mat, overhang=0.35):
        """Hipped roof over a rectangle (ridge along the longer side)."""
        X0, X1, Y0, Y1 = x0 - overhang, x1 + overhang, y0 - overhang, y1 + overhang
        t = math.tan(math.radians(pitch_deg))
        ze = z - overhang * t
        w, d = X1 - X0, Y1 - Y0
        if w >= d:
            h = d / 2
            zr = ze + h * t
            yc = (Y0 + Y1) / 2
            a, b = X0 + h, X1 - h
            sl = math.hypot(h, h * t)
            self.poly([(X0, Y0, ze), (X1, Y0, ze), (b, yc, zr), (a, yc, zr)], mat,
                      uvs=[(0, 0), (w, 0), (w - h, sl), (h, sl)])
            self.poly([(X1, Y1, ze), (X0, Y1, ze), (a, yc, zr), (b, yc, zr)], mat,
                      uvs=[(0, 0), (w, 0), (w - h, sl), (h, sl)])
            self.poly([(X1, Y0, ze), (X1, Y1, ze), (b, yc, zr)], mat,
                      uvs=[(0, 0), (d, 0), (d / 2, sl)])
            self.poly([(X0, Y1, ze), (X0, Y0, ze), (a, yc, zr)], mat,
                      uvs=[(0, 0), (d, 0), (d / 2, sl)])
            self.ridge_cap((a, yc, zr), (b, yc, zr), mat)
            for c0, c1 in (((X0, Y0, ze), (a, yc, zr)), ((X1, Y0, ze), (b, yc, zr)), ((X1, Y1, ze), (b, yc, zr)),
                           ((X0, Y1, ze), (a, yc, zr))):
                self.ridge_cap(c0, c1, mat, w=0.13, h=0.10)
        else:
            self.push((0, 0, 0), math.pi / 2)
            self.hip_roof(y0, -x1, y1, -x0, z, pitch_deg, mat, overhang)
            self.pop()

    def courtyard_roof(self, x0, y0, x1, y1, ix0, iy0, ix1, iy1, z, pitch_deg, mat, overhang=0.3):
        """Roof ring around an open courtyard (compluvium/peristyle): outer eaves high
        side towards the street is the ridge; slopes fall both outward and inward."""
        t = math.tan(math.radians(pitch_deg))
        # ridge ring halfway between outer and inner rectangles
        rx0, ry0, rx1, ry1 = (x0 + ix0) / 2, (y0 + iy0) / 2, (x1 + ix1) / 2, (y1 + iy1) / 2
        dz = min(ix0 - x0, iy0 - y0, x1 - ix1, y1 - iy1) / 2 * t
        zr = z + dz
        O = [(x0 - overhang, y0 - overhang), (x1 + overhang, y0 - overhang), (x1 + overhang, y1 + overhang),
             (x0 - overhang, y1 + overhang)]
        R = [(rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)]
        I = [(ix0 + overhang * 0.6, iy0 + overhang * 0.6), (ix1 - overhang * 0.6, iy0 + overhang * 0.6),
             (ix1 - overhang * 0.6, iy1 - overhang * 0.6), (ix0 + overhang * 0.6, iy1 - overhang * 0.6)]
        zo = z - overhang * t
        zi = z - overhang * 0.6 * t
        for i in range(4):
            j = (i + 1) % 4
            lo = math.dist(O[i], O[j])
            lr = math.dist(R[i], R[j])
            li = math.dist(I[i], I[j])
            so = math.dist((*O[i], zo), (*R[i], zr))
            si = math.dist((*I[i], zi), (*R[i], zr))
            off_o = (lo - lr) / 2
            off_i = (lr - li) / 2
            self.poly([(*O[i], zo), (*O[j], zo), (*R[j], zr), (*R[i], zr)], mat,
                      uvs=[(0, 0), (lo, 0), (lo - off_o, so), (off_o, so)])
            self.poly([(*R[i], zr), (*R[j], zr), (*I[j], zi), (*I[i], zi)], mat,
                      uvs=[(off_i, si), (lr + off_i, si), (lr, 0), (0, 0)][::1])
            self.ridge_cap((*R[i], zr), (*R[j], zr), mat)
            self.ridge_cap((*O[i], zo), (*R[i], zr), mat, w=0.12, h=0.09)

    # ------------------------------------------------------------ output
    def to_object(self, coll=None, name=None, materials=None):
        """Create the Blender object. materials: dict name -> bpy material."""
        from tl_materials import get_material  # local import (avoid cycles)

        name = name or self.name
        me = bpy.data.meshes.new(name)
        if not self.faces:
            ob = bpy.data.objects.new(name, me)
            (coll or bpy.context.scene.collection).objects.link(ob)
            return ob
        me.from_pydata(self.verts, [], self.faces)
        mat_names = sorted(set(self.face_mat))
        slot = {}
        for i, mn in enumerate(mat_names):
            me.materials.append(materials[mn] if materials and mn in materials else get_material(mn))
            slot[mn] = i
        me.polygons.foreach_set("material_index", [slot[m] for m in self.face_mat])
        me.polygons.foreach_set("use_smooth", self.smooth)
        uvl = me.uv_layers.new(name="UVMap")
        flat = []
        for uvs in self.face_uv:
            for u in uvs:
                flat.extend(u)
        uvl.data.foreach_set("uv", flat)
        for aname, data, typ in (("var", self.face_var, "FLOAT"), ("fac", [float(f) for f in self.face_fac], "FLOAT"),
                                 ("wlen", self.face_wlen, "FLOAT")):
            at = me.attributes.new(aname, typ, "FACE")
            at.data.foreach_set("value", data)
        me.validate(clean_customdata=False)
        me.update()
        ob = bpy.data.objects.new(name, me)
        (coll or bpy.context.scene.collection).objects.link(ob)
        return ob

    def extend(self, other: "MeshBuilder"):
        off = len(self.verts)
        self.verts.extend(other.verts)
        self.faces.extend(tuple(i + off for i in f) for f in other.faces)
        for a in ("face_mat", "face_uv", "face_var", "face_fac", "face_wlen", "smooth"):
            getattr(self, a).extend(getattr(other, a))

    @property
    def face_count(self):
        return len(self.faces)


def box_uv(pts):
    """Box projection in metres based on the polygon normal (local coords)."""
    if len(pts) < 3:
        return [(0, 0)] * len(pts)
    a, b, c = Vector(pts[0]), Vector(pts[1]), Vector(pts[2])
    n = (b - a).cross(c - a)
    ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
    if az >= ax and az >= ay:
        return [(p[0], p[1]) for p in pts]
    if ax >= ay:
        return [(p[1], p[2]) for p in pts]
    return [(p[0], p[2]) for p in pts]
