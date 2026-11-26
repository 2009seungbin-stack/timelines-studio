"""Terrain and vegetation generators (runs inside Blender)."""
from __future__ import annotations

import math
import random

import bpy
from mathutils import Vector, noise

from tl_mesh import MeshBuilder

TAU = math.tau


def smoothstep(a, b, x):
    if b == a:
        return 1.0 if x >= b else 0.0
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def fbm(x, y, octaves=5, seed=0):
    return noise.fractal(Vector((x + seed * 13.1, y - seed * 7.7, seed * 0.37)), 0.55, 2.0, octaves,
                         noise_basis="PERLIN_ORIGINAL")


class Terrain:
    """Height field shared by the terrain mesh and every placement on it."""

    def __init__(self, city_rect, seed=0, harbor=False, shore_y=None, ridge_dir=(0.6, 0.8),
                 ridge_start=950.0, ridge_h=42.0, valley=None, pads=None, ramps=None):
        self.x0, self.y0, self.x1, self.y1 = city_rect
        self.seed = seed
        self.harbor = harbor
        self.shore_y = shore_y if shore_y is not None else self.y0 - 40
        rd = Vector(ridge_dir).normalized()
        self.ridge_dir = (rd.x, rd.y)
        self.ridge_start = ridge_start
        self.ridge_h = ridge_h
        self.valley = valley            # (point_on_line, direction, depth, width)
        self.pads = pads or []          # (x0, y0, x1, y1, z, blend)
        self.ramps = ramps or []        # (cx, cy, angle, length, width, z_top, slope, blend)
        self.roads = []                 # polylines [(x, y), ...] that flatten the terrain slightly
        self.water_z = -0.8

    def city_dist(self, x, y):
        dx = max(self.x0 - x, 0.0, x - self.x1)
        dy = max(self.y0 - y, 0.0, y - self.y1)
        return math.hypot(dx, dy)

    def natural(self, x, y):
        d = self.city_dist(x, y)
        r = math.hypot(x, y)
        n = fbm(x * 0.0011, y * 0.0011, 5, self.seed)
        n2 = fbm(x * 0.004, y * 0.004, 3, self.seed + 5)
        h = (5.0 + 9.0 * n) * smoothstep(60.0, 700.0, d) + 2.0 * n2 * smoothstep(20.0, 200.0, d)
        proj = x * self.ridge_dir[0] + y * self.ridge_dir[1]
        lat = -x * self.ridge_dir[1] + y * self.ridge_dir[0]
        h += self.ridge_h * smoothstep(self.ridge_start, self.ridge_start + 320.0, proj) * \
            (0.75 + 0.25 * fbm(lat * 0.002, proj * 0.002, 3, self.seed + 2))
        h += 90.0 * smoothstep(self.ridge_start + 400, self.ridge_start + 1600, proj) * \
            (0.5 + 0.5 * fbm(x * 0.0015, y * 0.0015, 4, self.seed + 3))
        # distant mountains ring
        h += 420.0 * smoothstep(2300.0, 5200.0, r) * (0.55 + 0.45 * fbm(x * 0.0007, y * 0.0007, 5, self.seed + 9))
        if self.valley:
            (px, py), (vx, vy), depth, width = self.valley
            vl = math.hypot(vx, vy)
            dist = abs((x - px) * vy - (y - py) * vx) / vl
            h -= depth * math.exp(-(dist / width) ** 2) * smoothstep(30.0, 160.0, d)
        if self.harbor:
            # sea south of the city with an irregular shore (straight quay near the city)
            sy = self.shore_y + 40.0 * fbm(x * 0.003, 0.0, 3, self.seed + 4) * smoothstep(420, 700, abs(x))
            if y < sy:
                h = -1.6 - 7.0 * smoothstep(sy, sy - 140.0, y)
            else:
                h = h * smoothstep(sy, sy + 160.0, y) + 0.4 * (1 - smoothstep(sy, sy + 160.0, y))
        return h

    def h(self, x, y):
        h = self.natural(x, y)
        d = self.city_dist(x, y)
        if d <= 0.0:
            h = 0.0
        else:
            h = h * smoothstep(0.0, 70.0, d)
        for (x0, y0, x1, y1, z, blend) in self.pads:
            dx = max(x0 - x, 0.0, x - x1)
            dy = max(y0 - y, 0.0, y - y1)
            w = 1.0 - smoothstep(0.0, blend, math.hypot(dx, dy))
            h = h * (1 - w) + z * w
        for (cx, cy, ang, length, width, z_top, slope, blend) in self.ramps:
            c, s = math.cos(ang), math.sin(ang)
            lx = (x - cx) * c + (y - cy) * s
            ly = -(x - cx) * s + (y - cy) * c
            inside_x = min(max(lx, 0.0), length)
            dx = abs(lx - inside_x)
            dy = max(abs(ly) - width / 2, 0.0)
            w = 1.0 - smoothstep(0.0, blend, math.hypot(dx, dy))
            target = z_top - slope * inside_x
            h = h * (1 - w) + target * w
        return h

    # --------------------------------------------------------------- mesh
    def build(self, coll, extent=6000.0, n=300, road_fn=None):
        def axis(i):
            s = -1 + 2 * i / n
            return extent * (0.12 * s + 0.88 * s ** 3)

        xs = [axis(i) for i in range(n + 1)]
        verts, fld, urb, rock, shore = [], [], [], [], []
        hs = {}
        for j, y in enumerate(xs):
            for i, x in enumerate(xs):
                z = self.h(x, y)
                hs[(i, j)] = z
                verts.append((x, y, z))
        for j, y in enumerate(xs):
            for i, x in enumerate(xs):
                z = hs[(i, j)]
                zx = hs[(min(i + 1, n), j)] - hs[(max(i - 1, 0), j)]
                zy = hs[(i, min(j + 1, n))] - hs[(i, max(j - 1, 0))]
                dx = xs[min(i + 1, n)] - xs[max(i - 1, 0)]
                dy = xs[min(j + 1, n)] - xs[max(j - 1, 0)]
                slope = math.hypot(zx / dx, zy / dy)
                d = self.city_dist(x, y)
                r = math.hypot(x, y)
                f = smoothstep(30.0, 80.0, d) * (1 - smoothstep(1700.0, 2800.0, r)) * (1 - smoothstep(0.16, 0.3, slope))
                if self.harbor and z < 0.3:
                    f = 0.0
                fld.append(f)
                urb.append(1.0 - smoothstep(0.0, 25.0, d))
                rock.append(smoothstep(0.28, 0.55, slope) * smoothstep(400.0, 900.0, r))
                sh = 0.0
                if self.harbor and d > 2.0:
                    sh = (1.0 - smoothstep(0.6, 2.6, z)) * (1.0 - smoothstep(0.35, 0.6, slope))
                    sy = self.shore_y + 40.0 * fbm(x * 0.003, 0.0, 3, self.seed + 4) * smoothstep(420, 700, abs(x))
                    sh *= 1.0 - smoothstep(sy + 25.0, sy + 90.0, y)
                shore.append(sh)
        near, far = [], []
        for j in range(n):
            for i in range(n):
                a = j * (n + 1) + i
                f = (a, a + 1, a + n + 2, a + n + 1)
                rmax = max(math.hypot(verts[k][0], verts[k][1]) for k in f)
                (near if rmax < 2100.0 else far).append(f)
        from tl_materials import get_material
        obs = []
        for name, faces in (("Terrain", near), ("TerrainFar", far)):
            me = bpy.data.meshes.new(name)
            me.from_pydata(verts, [], faces)
            for an, data in (("fld", fld), ("urb", urb), ("rock", rock), ("shore", shore)):
                at = me.attributes.new(an, "FLOAT", "POINT")
                at.data.foreach_set("value", data)
            me.polygons.foreach_set("use_smooth", [True] * len(faces))
            me.materials.append(get_material("TL_Ground"))
            ob = bpy.data.objects.new(name, me)
            coll.objects.link(ob)
            obs.append(ob)
        # v2: hills and mountains cast shadows (sun elevations >= 5 deg keep them plausible)
        obs[0].visible_shadow = True      # near hills
        obs[1].visible_shadow = False     # far mountain ring would shade the whole plain at low sun
        return obs[0]

    def water(self, coll, extent=6000.0):
        if not self.harbor:
            return None
        z = self.water_z
        y1 = self.shore_y + 220
        # graded grid near the coast (depth attribute -> shallows/foam), coarse far out
        n = 140
        xs = [26000.0 * (s ** 3) * (1 if s >= 0 else 1) for s in [(-1 + 2 * i / n) for i in range(n + 1)]]
        xs = [x if abs(x) > 1e-6 else 0.0 for x in xs]
        ys = [y1 - 26000.0 * ((j / 90) ** 3) for j in range(91)]
        verts, depth = [], []
        for y in ys:
            for x in xs:
                verts.append((x, y, z))
                depth.append(max(0.0, z - self.h(x, y)) if abs(x) < 6000 and y > -6000 else 30.0)
        faces = []
        for j in range(len(ys) - 1):
            for i in range(n):
                a = j * (n + 1) + i
                faces.append((a, a + n + 1, a + n + 2, a + 1))
        me = bpy.data.meshes.new("Water")
        me.from_pydata(verts, [], faces)
        at = me.attributes.new("depth", "FLOAT", "POINT")
        at.data.foreach_set("value", depth)
        from tl_materials import get_material
        me.materials.append(get_material("TL_Water"))
        ob = bpy.data.objects.new("Water", me)
        coll.objects.link(ob)
        return ob


# =========================================================================== vegetation
def _blob(mb, cx, cy, cz, rx, ry, rz, mat, rng, segs=10, rings=6, rough=0.22):
    seed = rng.random() * 100
    pts = []
    for j in range(rings + 1):
        th = math.pi * j / rings
        row = []
        for k in range(segs):
            ph = TAU * k / segs
            d = Vector((math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)))
            nn = noise.noise(d * 1.7 + Vector((seed, seed, seed)))
            s = 1.0 + rough * nn
            row.append((cx + rx * d.x * s, cy + ry * d.y * s, cz + rz * d.z * s))
        pts.append(row)
    for j in range(rings):
        for k in range(segs):
            k2 = (k + 1) % segs
            a, b, c, d = pts[j][k], pts[j][k2], pts[j + 1][k2], pts[j + 1][k]
            if j == 0:
                mb.poly([a, d, c], mat, smooth=True)
            elif j == rings - 1:
                mb.poly([a, d, b], mat, smooth=True)
            else:
                mb.poly([a, d, c, b], mat, smooth=True)




# v2: card-based trees + GN instancing (tl_trees)
from tl_trees import cypress, pine, broadleaf, olive, bush, vine_row, TreeScatter  # noqa: E402,F401
