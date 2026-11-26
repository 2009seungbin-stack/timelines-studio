"""Procedural Roman city (kind="roman_city"), two eras (runs inside Blender).

era="late_antique_476"   generic Roman provincial/Italian city around 476 CE
                         (approximate reconstruction, not a specific site).
era="alt_1000"           SPECULATION: the same city in 1000 CE if the Western
                         Empire had survived - same Roman grammar, denser and
                         taller insulae, a centrally domed basilica church
                         (precedent: Hagia Sophia, 537), aqueduct-fed water mills
                         (precedent: Barbegal, 2nd c.), optional harbour.

Layout (1 unit = 1 m, +y = north): orthogonal grid of ~72 m insulae (2 actus),
cardo/decumanus maximus crossing at the forum, late-Roman curtain wall with
projecting towers and double gates, aqueduct arriving from the NE hills on arches,
roads with roadside tombs, amphitheatre outside the walls, fields and trees.
"""
from __future__ import annotations

import math
import random

import bpy
from mathutils import Vector

import tl_buildings as B
import tl_nature as N
from tl_mesh import MeshBuilder

BLOCK = 72.0
STREET = 7.0
MAIN = 11.0

ERA = {
    "late_antique_476": dict(nx=8, ny=6, ins_floors=(2, 4), mix=dict(insula=0.34, domus=0.40, ruin=0.10,
                                                                      garden=0.16), wall_tower=36.0,
                             suburbs=False, church="basilica", mills=False, plaster_var=1.0, tower_h=14.5),
    "alt_1000": dict(nx=10, ny=8, ins_floors=(3, 6), mix=dict(insula=0.74, domus=0.18, ruin=0.0, garden=0.08),
                     wall_tower=32.0, suburbs=True, church="domed", mills=True, plaster_var=0.8, tower_h=17.0),
}


def _col(name):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(c)
    return c


class City:
    def __init__(self, params: dict, seed: int):
        self.p = params
        self.era = params.get("era", "late_antique_476")
        if self.era not in ERA:
            raise ValueError(f"unknown era {self.era!r}; expected one of {list(ERA)}")
        self.E = dict(ERA[self.era])
        for k in ("nx", "ny"):
            if k in params:
                self.E[k] = int(params[k])
        self.seed = seed
        self.rng = random.Random(seed)
        self.harbor = bool(params.get("harbor", False))
        self.assets = set()
        self.poi = {}
        self.stats = {}
        self._grid()

    # ------------------------------------------------------------------ layout
    def _grid(self):
        nx, ny = self.E["nx"], self.E["ny"]
        self.cx, self.cy = nx // 2, ny // 2  # main streets run before block index cx / cy

        def edges(n, c):
            sizes = []
            for i in range(n):
                sizes.append(BLOCK)
                if i < n - 1:
                    sizes.append(MAIN if i + 1 == c else STREET)
            total = sum(sizes)
            x = -total / 2
            out = []
            for i in range(n):
                out.append((x, x + BLOCK))
                x += BLOCK + (MAIN if i + 1 == c else STREET) if i < n - 1 else BLOCK
            return out, total

        self.bx, tw = edges(nx, self.cx)
        self.by, th = edges(ny, self.cy)
        m = 14.0
        self.wall = (-tw / 2 - m, -th / 2 - m, tw / 2 + m, th / 2 + m)
        # main street centre lines
        self.cardo_x = (self.bx[self.cx - 1][1] + self.bx[self.cx][0]) / 2
        self.decu_y = (self.by[self.cy - 1][1] + self.by[self.cy][0]) / 2

    # ------------------------------------------------------------------ build
    def build(self, stage=lambda f, m: None):
        rng = self.rng
        wx0, wy0, wx1, wy1 = self.wall
        self.coll_city = _col("City")
        self.coll_land = _col("Landscape")
        self.coll_veg = _col("Vegetation")
        # aqueduct geometry decides the ridge/valley of the terrain
        ax = self.cardo_x + (wx1 - self.cardo_x) * 0.55
        self.aq_dir = Vector((math.cos(math.radians(58)), math.sin(math.radians(58))))
        self.aq_p0 = Vector((ax, wy1 - 7.0))
        self.aq_p1 = Vector((ax, wy1 + 70.0))
        self.aq_len2 = 1150.0
        bury = self.aq_p1 + self.aq_dir * 930.0
        ridge_start = bury.dot(self.aq_dir) - 120.0
        vpt = self.aq_p1 + self.aq_dir * 380.0
        perp = Vector((-self.aq_dir.y, self.aq_dir.x))
        shore = wy0 - 34.0 if self.harbor else None
        self.T = N.Terrain(self.wall, seed=self.seed, harbor=self.harbor, shore_y=shore,
                           ridge_dir=tuple(self.aq_dir), ridge_start=ridge_start, ridge_h=44.0,
                           valley=((vpt.x, vpt.y), (perp.x, perp.y), 16.0, 70.0))
        # flat pads for monuments outside the walls
        self.amph_pos = Vector((wx1 + 150.0, (wy0 + wy1) / 2 - 60.0 if self.harbor else wy0 + 90.0))
        self.T.pads.append((self.amph_pos.x - 75, self.amph_pos.y - 62, self.amph_pos.x + 75, self.amph_pos.y + 62,
                            self.T.natural(*self.amph_pos) * 0.4, 60.0))
        if self.E["mills"]:
            self._plan_mills(perp)
        stage(0.1, "terrain")
        self.T.build(self.coll_land)
        self.T.water(self.coll_land)
        stage(0.25, "city blocks")
        self._streets()
        self._blocks()
        stage(0.5, "forum and monuments")
        self._forum()
        self._church()
        self._walls()
        self._aqueduct(perp)
        self._amphitheatre()
        self._roads_and_tombs()
        if self.harbor:
            self._harbor()
        if self.E["mills"]:
            self._mills()
        if self.E["suburbs"]:
            self._suburbs()
        stage(0.75, "landscape")
        self._farms()
        self._vegetation()
        self._poi()
        return self

    # ------------------------------------------------------------------ helpers
    def _mb(self, name):
        mb = MeshBuilder(name)
        return mb

    def _emit(self, mb, coll=None):
        if mb.face_count:
            mb.to_object(coll or self.coll_city)
            self.stats["faces"] = self.stats.get("faces", 0) + mb.face_count

    def _streets(self):
        wx0, wy0, wx1, wy1 = self.wall
        mb = self._mb("Streets")
        mb.var = 0.5
        mb.poly([(wx0 + 3, wy0 + 3, 0.04), (wx1 - 3, wy0 + 3, 0.04), (wx1 - 3, wy1 - 3, 0.04),
                 (wx0 + 3, wy1 - 3, 0.04)], "TL_Paving")
        self._emit(mb)

    def _reserved(self):
        """Blocks taken by the forum / church precinct."""
        res = {(self.cx, self.cy): "forum", (self.cx, self.cy - 1): "forum"}
        if self.E["church"] == "domed":
            res[(self.cx + 1, self.cy)] = "church"
            res[(self.cx + 2, self.cy)] = "church"
        # early Christian basilica: near the wall in the SW quarter
        res[(1, 0 if not self.harbor else 1)] = "basilica_church"
        return res

    def _blocks(self):
        rng = self.rng
        res = self._reserved()
        mix = self.E["mix"]
        SW = 1.8          # sidewalk width (estimate; Pompeii 1.5-3 m)
        PD = 4.6          # portico depth along the main streets
        props = self._mb("StreetProps")
        for i, (x0, x1) in enumerate(self.bx):
            for j, (y0, y1) in enumerate(self.by):
                if (i, j) in res:
                    continue
                mb = self._mb(f"Block_{i}_{j}")
                mb.var = rng.random()
                # raised sidewalk slab with kerbs (0.3 m)
                mb.box(x0, y0, 0.0, x1, y1, 0.3, "TL_AshlarGrey", top_mat="TL_TravertineSlabs")
                # main-street fronts get a colonnaded portico (Ostia, Via della Foce type)
                main = (j == self.cy, i == self.cx - 1, j == self.cy - 1, i == self.cx)   # s, e, n, w on a main street
                ins = [SW + (PD if main[k] else 0.0) for k in range(4)]
                bx0, by0, bx1, by1 = x0 + ins[3], y0 + ins[0], x1 - ins[1], y1 - ins[2]
                for side in range(4):
                    if main[side]:
                        L = (x1 - x0) if side % 2 == 0 else (y1 - y0)
                        with mb.push((x0, y0, 0.3)):
                            with mb.push(*B._side_frame(side, x1 - x0, y1 - y0)):
                                with mb.push((SW + 0.6, 0.6, 0.0)):
                                    B.portico(mb, rng, L - 2 * (SW + 0.6), depth=PD + SW - 1.3, H=3.6, D=0.5,
                                              spacing=3.2, back_wall=False, mat_col="TL_Travertine")
                dc = max(abs(i - self.cx + 0.5) / self.E["nx"], abs(j - self.cy + 0.5) / self.E["ny"]) * 2
                lots = _split((bx0, by0, bx1, by1), rng, 18.0, 34.0)
                for (lx0, ly0, lx1, ly1) in lots:
                    street = (abs(ly0 - by0) < 0.5, abs(lx1 - bx1) < 0.5, abs(ly1 - by1) < 0.5, abs(lx0 - bx0) < 0.5)
                    g = rng.choice([0.0, 0.0, 0.0, 1.2])
                    lx0g, ly0g = lx0 + (0 if street[3] else g / 2), ly0 + (0 if street[0] else g / 2)
                    lx1g, ly1g = lx1 - (0 if street[1] else g / 2), ly1 - (0 if street[2] else g / 2)
                    w, d = lx1g - lx0g, ly1g - ly0g
                    kind = _pick(rng, mix, edge=dc)
                    mb.var = rng.random()
                    with mb.push((lx0g, ly0g, 0.3)):
                        if kind == "insula" and min(w, d) >= 10:
                            f0, f1 = self.E["ins_floors"]
                            fl = rng.randint(f0, f1)
                            if dc > 0.7:
                                fl = max(f0, fl - 1)
                            B.insula(mb, rng, w, d, fl, street=street)
                            self.assets.add("roman_insula_block")
                        elif kind == "domus" and min(w, d) >= 14:
                            fl = 2 if (self.era == "alt_1000" and rng.random() < 0.5) else 1
                            if w > d:
                                with mb.push((w, 0, 0), math.pi / 2):
                                    B.domus(mb, rng, d, w, street=(street[1], street[2], street[3], street[0]),
                                            floors=fl)
                            else:
                                B.domus(mb, rng, w, d, street=street, floors=fl)
                            self.assets.add("roman_domus")
                        elif kind == "ruin":
                            B.ruin(mb, rng, w, d)
                            self._garden_trees(mb, lx0g, ly0g, w, d, 0.3, 2)
                            self._shrubs(lx0g, ly0g, w, d, 0.35, rng.randint(4, 10))
                        else:
                            mb.poly([(0.5, 0.5, 0.05), (w - 0.5, 0.5, 0.05), (w - 0.5, d - 0.5, 0.05),
                                     (0.5, d - 0.5, 0.05)], "TL_Garden")
                            self._garden_trees(mb, lx0g, ly0g, w, d, 0.3, rng.randint(3, 8))
                            self._shrubs(lx0g, ly0g, w, d, 0.35, rng.randint(3, 8))
                            for k in range(int((d - 4) / 2.2)):
                                if rng.random() < 0.75:
                                    yy = 2.0 + k * 2.2
                                    mb.box(2.0, yy, 0.05, w - 2.0, yy + 1.2, 0.25, "TL_Earth" if k % 3 else
                                           "TL_Garden", top_mat=None)
                            for side in range(4):
                                L = w if side % 2 == 0 else d
                                with mb.push(*B._side_frame(side, w, d)):
                                    mb.box(0, 0, 0, L, 0.5, 1.8, "TL_PlasterWall")
                self._emit(mb)
                # street furniture on the sidewalk corners
                if rng.random() < 0.3:
                    B.fountain(props, rng, x0 + 1.0, y0 + 1.0, 0.3)
                if rng.random() < 0.25:
                    B.amphora_stack(props, rng, x1 - 1.0, y0 + 0.9, 0.3, n=rng.randint(3, 7))
        # stepping stones across every street near the block corners (Pompeii type)
        for i in range(len(self.bx) - 1):
            gx0, gx1 = self.bx[i][1], self.bx[i + 1][0]
            for j in range(len(self.by)):
                for yy in (self.by[j][0] + 2.6, self.by[j][1] - 2.6):
                    if rng.random() < 0.5:
                        self._stepping(props, rng, gx0, gx1, yy, axis="x")
        for j in range(len(self.by) - 1):
            gy0, gy1 = self.by[j][1], self.by[j + 1][0]
            for i in range(len(self.bx)):
                for xx in (self.bx[i][0] + 2.6, self.bx[i][1] - 2.6):
                    if rng.random() < 0.5:
                        self._stepping(props, rng, gy0, gy1, xx, axis="y")
        # parked carts in side streets
        for _ in range(int(len(self.bx) * len(self.by) * 0.35)):
            i = rng.randrange(len(self.bx) - 1)
            j = rng.randrange(len(self.by))
            gx = (self.bx[i][1] + self.bx[i + 1][0]) / 2 + rng.choice([-1.6, 1.6])
            gy = rng.uniform(self.by[j][0] + 6, self.by[j][1] - 6)
            B.cart(props, rng, gx, gy, 0.04, math.pi / 2 + rng.choice([0.0, math.pi]) + rng.uniform(-0.1, 0.1))
        self._emit(props)

    def _stepping(self, mb, rng, a0, a1, c, axis="x"):
        """2-3 raised stones across a street from kerb a0 to kerb a1 (crossing along `axis`)."""
        wdt = a1 - a0
        n = 3 if wdt > 8 else 2
        for k in range(n):
            t = a0 + wdt * (k + 1) / (n + 1)
            lw, ll = rng.uniform(0.55, 0.7), rng.uniform(0.9, 1.2)
            if axis == "x":
                mb.box(t - lw / 2, c - ll / 2, 0.0, t + lw / 2, c + ll / 2, 0.36, "TL_AshlarGrey")
            else:
                mb.box(c - ll / 2, t - lw / 2, 0.0, c + ll / 2, t + lw / 2, 0.36, "TL_AshlarGrey")

    def _shrubs(self, ox, oy, w, d, z, n):
        rng = self.rng
        pend = getattr(self, "_pending_trees", [])
        for _ in range(n):
            pend.append(("shrub", ox + rng.uniform(1.0, max(1.1, w - 1.0)), oy + rng.uniform(1.0, max(1.1, d - 1.0)), z))
        self._pending_trees = pend

    def _garden_trees(self, mb, ox, oy, w, d, z, n):
        rng = self.rng
        pend = getattr(self, "_pending_trees", [])
        for _ in range(n):
            x = ox + rng.uniform(2.5, max(2.6, w - 2.5))
            y = oy + rng.uniform(2.5, max(2.6, d - 2.5))
            pend.append((rng.choice(["broadleaf", "cypress", "olive", "pine"]), x, y, z))
        self._pending_trees = pend

    def _block_rect(self, i, j):
        return (self.bx[i][0], self.by[j][0], self.bx[i][1], self.by[j][1])

    # ------------------------------------------------------------------ forum
    def _forum(self):
        rng = self.rng
        x0, y0, _, _ = self._block_rect(self.cx, self.cy - 1)
        _, _, x1, y1 = self._block_rect(self.cx, self.cy)
        mb = self._mb("Forum")
        mb.var = 0.4
        z = 0.35
        mb.box(x0, y0, 0.0, x1, y1, z, "TL_AshlarGrey", top_mat="TL_TravertineSlabs")
        xc = (x0 + x1) / 2
        # temple (Capitolium) at the north end facing south
        tmp = MeshBuilder("tmp")
        tw, td = B.temple(tmp, rng)
        mb.var = 0.35
        with mb.push((xc, y1 - 4.0 - td, z)):
            B.temple(mb, random.Random(self.seed + 1))
        # altar in front of the temple
        ay0, ay1 = y1 - 4.0 - td - 9.5, y1 - 4.0 - td - 6.5
        mb.moulding(xc - 2.4, ay0, xc + 2.4, ay1, [(0.3, z), (0.3, z + 0.25), (0.12, z + 0.35), (0.0, z + 0.45)],
                    "TL_Marble", closed=False)
        mb.box(xc - 2.4, ay0, z + 0.45, xc + 2.4, ay1, z + 1.25, "TL_Marble", top=False)
        mb.moulding(xc - 2.4, ay0, xc + 2.4, ay1, [(0.0, z + 1.25), (0.12, z + 1.35), (0.25, z + 1.5),
                                                  (0.25, z + 1.62)], "TL_Marble", closed=True)
        for sx in (-1, 1):   # pulvini (bolsters) on the altar top
            B.beam(mb, (xc + sx * 2.05, ay0 - 0.25, z + 1.8), (xc + sx * 2.05, ay1 + 0.25, z + 1.8), 0.34, "TL_Marble")
        # small market: amphora stacks and carts near the temple steps
        for k in range(4):
            B.amphora_stack(mb, rng, xc + rng.choice([-1, 1]) * rng.uniform(12, 24),
                            y1 - 4.0 - td - rng.uniform(4, 30), z, n=rng.randint(4, 9))
        B.cart(mb, rng, xc - 18.0, y1 - 4.0 - td - 20.0, z, rng.uniform(0, 3.0))
        self.assets.add("roman_temple_corinthian_hexastyle")
        # basilica across the south end, long side facing the forum (north)
        L, D = 58.0, 30.0
        with mb.push((xc + 33.0, y0 + 3.0 + D, z), math.pi):
            mb.var = 0.55
            B.basilica(mb, rng, L=L, nave=16.0, aisle=7.0)
        self.assets.add("roman_basilica_civil")
        # porticoes on east and west sides, from the basilica to the temple's rear
        py0, py1 = y0 + 3.0 + D + 2.0, y1 - 3.0
        depth = 5.5
        with mb.push((x1 - 1.0 - depth - 0.7, py1, z), 1.5 * math.pi):
            B.portico(mb, rng, py1 - py0, depth=depth)
        with mb.push((x0 + 1.0 + depth + 0.7, py0, z), 0.5 * math.pi):
            B.portico(mb, rng, py1 - py0, depth=depth)
        # honorific statues along the plaza, market stalls in front of the porticoes
        for k in range(5):
            yy = py0 + 12 + k * 12
            for xx, rot in ((x0 + 10.5, -math.pi / 2), (x1 - 10.5, math.pi / 2)):
                B.statue(mb, rng, xx, yy, z, rot, mat=rng.choice(["TL_Marble", "TL_Bronze"]))
        for k in range(9):
            yy = py0 + 8 + k * 10.5
            for xx, rot in ((x0 + 15.5, -math.pi / 2), (x1 - 15.5, math.pi / 2)):
                if rng.random() < 0.75 and yy < y1 - 6.0 - td:
                    B.market_stall(mb, rng, xx, yy, z, rot, w=rng.uniform(2.6, 3.6), d=2.0)
        # equestrian-size monument base on the axis and a fountain basin
        mb.box(xc - 2.5, (y0 + y1) / 2 - 1.6, z, xc + 2.5, (y0 + y1) / 2 + 1.6, z + 2.6, "TL_Marble")
        B.statue(mb, rng, xc, (y0 + y1) / 2, z + 2.6, math.pi, mat="TL_Bronze", plinth=False, scale=1.6)
        self._emit(mb)
        self.forum_center = Vector((xc, (y0 + y1) / 2, 0.0))
        self.temple_front = Vector((xc, y1 - 4.0 - td, 0.0))
        self.forum_rect = (x0, y0, x1, y1)

    # ------------------------------------------------------------------ churches
    def _church(self):
        rng = self.rng
        # early Christian basilica (both eras; continuity)
        j = 0 if not self.harbor else 1
        x0, y0, x1, y1 = self._block_rect(1, j)
        mb = self._mb("EarlyChristianBasilica")
        mb.box(x0, y0, 0.0, x1, y1, 0.3, "TL_AshlarGrey", top_mat="TL_Earth")
        mb.var = 0.7
        with mb.push((x0 + 4.0, y0 + 14.0, 0.3)):
            B.basilica(mb, rng, L=44.0, nave=14.0, aisle=6.0, h_aisle=8.0, h_nave=15.0, church=True)
        # small campanile-free precinct wall + a few trees
        self._garden_trees(mb, x0 + 2, y0 + 2, x1 - x0 - 4, 10, 0.3, 3)
        self._emit(mb)
        self.assets.add("early_christian_basilica_church")
        self.early_church = Vector((x0 + 30.0, y0 + 30.0, 0.0))
        if self.E["church"] != "domed":
            return
        x0, y0, _, y1 = self._block_rect(self.cx + 1, self.cy)
        _, _, x1, _ = self._block_rect(self.cx + 2, self.cy)
        mb = self._mb("DomedChurch")
        mb.var = 0.5
        mb.box(x0, y0, 0.0, x1, y1, 0.35, "TL_AshlarGrey", top_mat="TL_TravertineSlabs")
        tmp = MeshBuilder("tmp")
        clen, cwid = B.domed_church(tmp, rng)
        ox = x0 + (x1 - x0 - clen) / 2
        with mb.push((ox, (y0 + y1) / 2, 0.35)):
            B.domed_church(mb, random.Random(self.seed + 2))
        self._emit(mb)
        self.assets.add("domed_basilica_church")
        self.church_center = Vector((ox + 18 + 6 + (22 + 4 + 22) / 2, (y0 + y1) / 2, 0.0))

    # ------------------------------------------------------------------ walls
    def _walls(self):
        rng = self.rng
        wx0, wy0, wx1, wy1 = self.wall
        mb = self._mb("Walls")
        mb.var = 0.45
        sides = [((wx0, wy0), 0.0, wx1 - wx0, self.cardo_x - wx0),           # south
                 ((wx1, wy0), 0.5 * math.pi, wy1 - wy0, self.decu_y - wy0),  # east
                 ((wx1, wy1), math.pi, wx1 - wx0, wx1 - self.cardo_x),       # north
                 ((wx0, wy1), 1.5 * math.pi, wy1 - wy0, wy1 - self.decu_y)]  # west
        spacing = self.E["wall_tower"]
        th = self.E["tower_h"]
        for (ox, oy), rot, L, gate_x in sides:
            with mb.push((ox, oy, 0), rot):
                gw = 33.0
                segs = [(0.0, gate_x - gw / 2), (gate_x + gw / 2, L)]
                with mb.push((gate_x, 0, 0)):
                    B.gate(mb, rng)
                for a, b in segs:
                    with mb.push((a, 0, 0)):
                        B.wall_run(mb, b - a, H=8.5)
                    n = max(1, int((b - a) / spacing))
                    for k in range(n + 1):
                        tx = a + (b - a) * k / n
                        if a > 0 and k == 0:
                            continue
                        if k == n:
                            continue  # next to a gate, or the corner tower of the next side
                        if rot == math.pi and abs((wx1 - tx) - self.aq_p0.x) < 12.0:
                            continue  # leave room for the aqueduct crossing
                        with mb.push((tx, 0, 0)):
                            B.tower(mb, rng, H=th + rng.uniform(-0.6, 0.6))
        self._emit(mb)
        self.assets.update({"late_roman_wall_tower", "roman_city_gate"})

    # ------------------------------------------------------------------ aqueduct
    def _aqueduct(self, perp):
        mb = self._mb("Aqueduct")
        mb.var = 0.5
        T = self.T
        z0 = 12.4
        grad = 0.0032
        p0, p1 = self.aq_p0, self.aq_p1
        segs = [(p0, p1, 0.0), (p1, p1 + self.aq_dir * self.aq_len2, (p1 - p0).length)]
        width = 2.6
        for a, b, s0 in segs:
            d = (b - a)
            L = d.length
            u = d.normalized()
            ang = math.atan2(u.y, u.x)
            off = Vector((-u.y, u.x)) * (-width / 2)

            def ztop(x, s0=s0):
                return z0 + grad * (s0 + x)

            def ground(x, a=a, u=u):
                q = a + u * x
                return T.h(q.x, q.y)
            o = a + off
            with mb.push((o.x, o.y, 0.0), ang):
                B.aqueduct_run(mb, L, ztop, ground, span=6.4, pier=2.4, width=width)
        # bend pier and castellum divisorium
        g = T.h(p1.x, p1.y)
        mb.box(p1.x - 2.0, p1.y - 2.0, g - 1.0, p1.x + 2.0, p1.y + 2.0, z0 + grad * 77 + 2.2, "TL_Ashlar")
        with mb.push((p0.x - 4.0, p0.y - 6.0, 0.0)):
            B.castellum(mb, self.rng)
        self._emit(mb)
        self.assets.add("roman_aqueduct_arcade")
        self.aq_mid = p1 + self.aq_dir * 380.0

    # ------------------------------------------------------------------ amphitheatre
    def _amphitheatre(self):
        mb = self._mb("Amphitheatre")
        mb.var = 0.5
        z = self.T.h(*self.amph_pos)
        with mb.push((self.amph_pos.x, self.amph_pos.y, z)):
            B.amphitheatre(mb, self.rng, a=56.0, b=44.0, H=19.0)
        self._emit(mb)
        self.assets.add("roman_amphitheatre")

    # ------------------------------------------------------------------ roads, tombs
    def _road(self, mb, pts, width=6.5):
        for a, b in zip(pts, pts[1:]):
            a, b = Vector(a), Vector(b)
            L = (b - a).length
            n = max(1, int(L / 8.0))
            u = (b - a).normalized()
            pn = Vector((-u.y, u.x)) * (width / 2)
            prev = None
            for k in range(n + 1):
                c = a + (b - a) * (k / n)
                zc = max(self.T.h(*(c + pn)), self.T.h(*(c - pn)), self.T.h(*c)) + 0.25
                cur = ((c - pn).x, (c - pn).y, zc), ((c + pn).x, (c + pn).y, zc)
                if prev is not None:
                    mb.poly([prev[0], cur[0], cur[1], prev[1]], "TL_Paving")
                prev = cur

    def _roads_and_tombs(self):
        rng = self.rng
        wx0, wy0, wx1, wy1 = self.wall
        mb = self._mb("Roads")
        mb.var = 0.5
        cyp = getattr(self, "_pending_trees", [])
        roads = [[(wx0 - 2, self.decu_y), (wx0 - 700, self.decu_y + 40), (wx0 - 2200, self.decu_y + 260)],
                 [(self.cardo_x, wy1 + 2), (self.cardo_x - 60, wy1 + 900), (self.cardo_x - 300, wy1 + 2600)],
                 [(wx1 + 2, self.decu_y), (wx1 + 900, self.decu_y - 80), (wx1 + 2600, self.decu_y - 400)]]
        if not self.harbor:
            roads.append([(self.cardo_x, wy0 - 2), (self.cardo_x + 40, wy0 - 900), (self.cardo_x + 200, wy0 - 2600)])
        self.roads = roads
        for r in roads:
            self._road(mb, r)
        self._emit(mb, self.coll_land)
        # necropolis along the first ~420 m of the west road, cypresses along the roads
        mt = self._mb("Tombs")
        a, b = Vector(roads[0][0]), Vector(roads[0][1])
        u = (b - a).normalized()
        pn = Vector((-u.y, u.x))
        s = 40.0
        while s < 430.0:
            for side in (-1, 1):
                if rng.random() < 0.7:
                    c = a + u * s + pn * side * rng.uniform(9.0, 13.0)
                    mt.var = rng.random()
                    with mt.push((c.x, c.y, self.T.h(c.x, c.y)), math.atan2(u.y, u.x)):
                        B.tomb(mt, rng)
            s += rng.uniform(11.0, 17.0)
        self._emit(mt, self.coll_land)
        self.assets.add("roman_roadside_tomb")
        for r in roads:
            for a, b in zip(r, r[1:]):
                a, b = Vector(a), Vector(b)
                u = (b - a).normalized()
                pn = Vector((-u.y, u.x))
                L = (b - a).length
                s = 30.0
                while s < min(L, 900.0):
                    for side in (-1, 1):
                        if rng.random() < 0.55:
                            c = a + u * s + pn * side * 6.5
                            cyp.append(("cypress", c.x, c.y, None))
                    s += 13.0
        self._pending_trees = cyp

    # ------------------------------------------------------------------ harbour
    def _harbor(self):
        rng = self.rng
        wx0, wy0, wx1, wy1 = self.wall
        yq = self.T.shore_y
        mb = self._mb("Harbor")
        mb.var = 0.5
        # quay platform along the shore
        mb.box(wx0 - 120, yq, -5.0, wx1 + 120, wy0 + 2, 0.55, "TL_Ashlar", top_mat="TL_TravertineSlabs")
        # moles enclosing the basin, lighthouse on the eastern mole head
        mw = 12.0
        xa, xb = self.cardo_x - 330, self.cardo_x + 330
        for x, sgn in ((xa, 1), (xb, -1)):
            mb.box(x - mw / 2, yq - 260, -6.0, x + mw / 2, yq, 1.3, "TL_Ashlar", top_mat="TL_TravertineSlabs")
            ex = x + sgn * 190
            mb.box(min(x, ex) - mw / 2, yq - 260 - mw, -6.0, max(x, ex) + mw / 2, yq - 260, 1.3, "TL_Ashlar",
                   top_mat="TL_TravertineSlabs")
        lh = Vector((xb - 190, yq - 266, 1.3))
        with mb.push((lh.x, lh.y, lh.z)):
            B.lighthouse(mb, rng)
        self.assets.add("roman_lighthouse")
        # warehouses (horrea) along the quay outside the walls
        for x in (wx0 - 110, wx0 - 50, wx1 + 4, wx1 + 64):
            mb.var = rng.random()
            with mb.push((x, yq + 3.0, 0.55)):
                B.horreum(mb, rng, w=50.0, d=22.0)
        self.assets.add("roman_horreum")
        self._emit(mb)
        # ships: moored along the quay and at anchor in the basin, two under sail outside
        ms = self._mb("Ships")
        wz = self.T.water_z
        k = 0
        xs = sorted(rng.uniform(xa + 30, xb - 30) for _ in range(7))
        for x in xs:
            ms.var = rng.random()
            L = rng.uniform(18.0, 26.0)
            with ms.push((x, yq - 6.5 - rng.uniform(0, 3), wz + 0.1), rng.uniform(-0.05, 0.05) + math.pi):
                B.ship(ms, rng, L=L, B=L * 0.29, depth=L * 0.14)
            k += 1
        for _ in range(4):
            ms.var = rng.random()
            p = Vector((rng.uniform(xa + 60, xb - 60), yq - rng.uniform(60, 200)))
            with ms.push((p.x, p.y, wz + 0.1), rng.uniform(0, math.tau)):
                B.ship(ms, rng, L=rng.uniform(16, 24))
        for _ in range(6):
            ms.var = rng.random()
            p = Vector((rng.uniform(xa + 20, xb - 20), yq - rng.uniform(15, 120)))
            with ms.push((p.x, p.y, wz + 0.05), rng.uniform(0, math.tau)):
                B.boat(ms, rng, L=rng.uniform(5.5, 8.0))
        for p, a in (((self.cardo_x - 120, yq - 520), 0.3), ((self.cardo_x + 260, yq - 760), 2.6)):
            ms.var = rng.random()
            with ms.push((p[0], p[1], wz + 0.1), a):
                B.ship(ms, rng, L=24.0, sail_set=True)
        self._emit(ms)
        self.assets.add("roman_merchant_ship_corbita")
        self.harbor_center = Vector((self.cardo_x, yq - 130, 0.0))

    # ------------------------------------------------------------------ mills
    def _plan_mills(self, perp):
        # Barbegal-type: a branch of the aqueduct feeds a cascade running down the
        # side of the valley the aqueduct bridges (top below the channel level)
        top = self.aq_p1 + self.aq_dir * 478.0 + perp * 66.0
        ang = math.atan2(-self.aq_dir.y, -self.aq_dir.x)
        self.mill_top = top
        self.mill_ang = ang
        ch = 12.4 + 0.0032 * (77.0 + 478.0)
        zt = min(self.T.natural(top.x, top.y), ch - 1.6)
        self.mill_z = zt
        self.mill_drop = 1.6
        self.mill_branch = self.aq_p1 + self.aq_dir * 478.0
        self.T.ramps.append((top.x, top.y, ang, 56.0, 34.0, zt, self.mill_drop / 7.0, 30.0))

    def _mills(self):
        mb = self._mb("Watermills")
        mb.var = 0.5
        with mb.push((self.mill_top.x, self.mill_top.y, self.mill_z + 0.2), self.mill_ang):
            B.watermill_cascade(mb, self.rng, steps=8, step_drop=self.mill_drop, step_len=7.0)
        # feeder channel from the aqueduct line to the head of the cascade
        src = self.mill_branch + Vector((-self.aq_dir.y, self.aq_dir.x)) * 3.0
        d = self.mill_top - src
        n = int(d.length / 6)
        for k in range(n):
            a = src + d * (k / n)
            b = src + d * ((k + 1) / n)
            z = max(self.T.h(a.x, a.y), self.T.h(b.x, b.y), self.mill_z + 0.5)
            u = (b - a)
            ang = math.atan2(u.y, u.x)
            with mb.push((a.x, a.y, z), ang):
                mb.box(0, -0.8, -0.6, u.length + 0.05, 0.8, 0.7, "TL_Ashlar")
        self._emit(mb)
        self.assets.add("barbegal_watermill_cascade")

    # ------------------------------------------------------------------ suburbs (alt_1000)
    def _suburbs(self):
        rng = self.rng
        wx0, wy0, wx1, wy1 = self.wall
        mb = self._mb("Suburbs")
        zones = [(wx0 - 230, self.decu_y - 120, wx0 - 40, self.decu_y + 140),
                 (self.cardo_x - 200, wy1 + 40, self.cardo_x - 40, wy1 + 200),
                 (wx1 + 40, self.decu_y + 20, wx1 + 200, self.decu_y + 160)]
        for (x0, y0, x1, y1) in zones:
            for lot in _split((x0, y0, x1, y1), rng, 18.0, 30.0):
                lx0, ly0, lx1, ly1 = lot
                if rng.random() < 0.3:
                    continue
                cx, cy = (lx0 + lx1) / 2, (ly0 + ly1) / 2
                if self._near_road(cx, cy, 10.0):
                    continue
                w, d = lx1 - lx0 - 3, ly1 - ly0 - 3
                z = min(self.T.h(lx0, ly0), self.T.h(lx1, ly1), self.T.h(lx0, ly1), self.T.h(lx1, ly0)) - 0.2
                mb.var = rng.random()
                with mb.push((lx0 + 1.5, ly0 + 1.5, z)):
                    mb.box(-0.5, -0.5, -2.0, w + 0.5, d + 0.5, 0.25, "TL_AshlarGrey", top_mat="TL_Earth")
                    if rng.random() < 0.6:
                        B.insula(mb, rng, w, d, rng.randint(2, 3), street=(True, True, True, True))
                    else:
                        B.domus(mb, rng, w, d, street=(True, False, False, False))
        self._emit(mb)

    def _near_road(self, x, y, dist):
        p = Vector((x, y))
        for r in getattr(self, "roads", []):
            for a, b in zip(r, r[1:]):
                a, b = Vector(a), Vector(b)
                ab = b - a
                t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
                if (a + ab * t - p).length < dist:
                    return True
        return False

    # ------------------------------------------------------------------ farms
    def _farms(self):
        rng = self.rng
        mb = self._mb("Farms")
        placed = 0
        tries = 0
        while placed < (14 if self.era == "alt_1000" else 11) and tries < 400:
            tries += 1
            a = rng.uniform(0, math.tau)
            r = rng.uniform(380.0, 1500.0)
            x, y = r * math.cos(a), r * math.sin(a)
            if self.T.city_dist(x, y) < 150 or self._near_road(x, y, 40.0) or self._near_aq(x, y, 60.0):
                continue
            hs = [self.T.h(x + dx, y + dy) for dx in (-20, 20) for dy in (-20, 20)]
            if max(hs) - min(hs) > 6.0 or min(hs) < 0.3:
                continue
            if (Vector((x, y)) - self.amph_pos).length < 140:
                continue
            mb.var = rng.random()
            z = min(hs) - 0.3
            rot = rng.choice([0.0, math.pi / 2]) + rng.uniform(-0.15, 0.15)
            with mb.push((x, y, z), rot):
                B.villa_rustica(mb, rng)
            pend = getattr(self, "_pending_trees", [])
            for gx in range(6):
                for gy in range(5):
                    px = x - 40 + gx * 9 + rng.uniform(-1, 1)
                    py = y + 26 + gy * 9 + rng.uniform(-1, 1)
                    pend.append(("olive", px, py, None))
            self._pending_trees = pend
            placed += 1
        self._emit(mb, self.coll_land)
        self.assets.add("roman_villa_rustica")

    def _near_aq(self, x, y, dist):
        p = Vector((x, y))
        a, b = self.aq_p1, self.aq_p1 + self.aq_dir * self.aq_len2
        ab = b - a
        t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
        return (a + ab * t - p).length < dist

    # ------------------------------------------------------------------ vegetation
    def _hedgerows(self, pend):
        """Tree lines along some centuriation boundaries (same grid as the ground shader)."""
        rng = self.rng
        cw, ch = 88.75, 44.4
        for _ in range(150):
            if rng.random() < 0.5:   # line of constant x
                i = rng.randint(-20, 20)
                x = cw * i - 3.0
                j0 = rng.randint(-40, 36)
                y0, y1 = ch * j0 - 7.0, ch * (j0 + rng.randint(1, 4)) - 7.0
                pts = [(x, y0 + t) for t in _frange(0, y1 - y0, rng.uniform(7, 11))]
            else:
                j = rng.randint(-40, 40)
                y = ch * j - 7.0
                i0 = rng.randint(-20, 18)
                x0, x1 = cw * i0 - 3.0, cw * (i0 + rng.randint(1, 3)) - 3.0
                pts = [(x0 + t, y) for t in _frange(0, x1 - x0, rng.uniform(7, 11))]
            kind = rng.choices(["broadleaf", "cypress", "pine"], [6, 2, 1])[0]
            for (x, y) in pts:
                if rng.random() < 0.85 and 150 < math.hypot(x, y) < 2200:
                    pend.append((kind, x + rng.uniform(-1, 1), y + rng.uniform(-1, 1), None))
        # olive groves / orchards in rows inside a few plots
        for _ in range(70):
            i, j = rng.randint(-18, 18), rng.randint(-36, 36)
            x0, y0 = cw * i - 3.0, ch * j - 7.0
            if not (250 < math.hypot(x0, y0) < 1900):
                continue
            for gx in range(1, 11):
                for gy in range(1, 5):
                    pend.append(("olive", x0 + gx * cw / 11 + rng.uniform(-0.8, 0.8),
                                 y0 + gy * ch / 5 + rng.uniform(-0.8, 0.8), None))

    def _vegetation(self):
        rng = self.rng
        T = self.T
        pend = getattr(self, "_pending_trees", [])
        self._hedgerows(pend)
        # countryside scatter: pine clusters, broadleaf hedgerows, olive groves on slopes
        for _ in range(520):
            a = rng.uniform(0, math.tau)
            r = rng.uniform(80.0, 1900.0) * (0.35 + 0.65 * rng.random())
            x, y = r * math.cos(a), r * math.sin(a)
            if T.city_dist(x, y) < 25:
                continue
            kind = rng.choices(["pine", "broadleaf", "cypress", "olive", "shrub"], [3, 4, 2, 3, 3])[0]
            n = rng.randint(2, 9) if kind != "cypress" else rng.randint(1, 4)
            for _k in range(n):
                px, py = x + rng.uniform(-28, 28), y + rng.uniform(-28, 28)
                pend.append((kind, px, py, None))
        # maquis / shrubs along the outside of the walls and on rough ground near the city
        wx0, wy0, wx1, wy1 = self.wall
        for _ in range(900):
            a = rng.uniform(0, math.tau)
            r = rng.uniform(0.0, 260.0) ** 1.0
            side = rng.randrange(4)
            if side == 0:
                x, y = rng.uniform(wx0 - 40, wx1 + 40), wy0 - rng.uniform(6, 60)
            elif side == 1:
                x, y = wx1 + rng.uniform(6, 60), rng.uniform(wy0 - 40, wy1 + 40)
            elif side == 2:
                x, y = rng.uniform(wx0 - 40, wx1 + 40), wy1 + rng.uniform(6, 60)
            else:
                x, y = wx0 - rng.uniform(6, 60), rng.uniform(wy0 - 40, wy1 + 40)
            pend.append(("shrub", x + r * 0.0 * math.cos(a), y, None))
        for _ in range(500):
            a = rng.uniform(0, math.tau)
            r = rng.uniform(250.0, 1400.0)
            cx_, cy_ = r * math.cos(a), r * math.sin(a)
            for _k in range(rng.randint(3, 9)):
                pend.append(("shrub", cx_ + rng.uniform(-12, 12), cy_ + rng.uniform(-12, 12), None))
        # grass tufts and scrub on uncultivated ground near the city, the aqueduct and the mills
        hot = [Vector((0.0, 0.0))]
        if self.E["mills"]:
            hot.append(self.mill_top.xy if hasattr(self.mill_top, "xy") else self.mill_top)
        hot.append(self.aq_p1 + self.aq_dir * 300.0)
        for c in hot:
            R = 900.0 if c.length < 1.0 else 260.0
            for _ in range(7000 if c.length < 1.0 else 6000):
                a = rng.uniform(0, math.tau)
                r = R * math.sqrt(rng.random())
                x, y = c.x + r * math.cos(a), c.y + r * math.sin(a)
                if T.city_dist(x, y) < 3.0:
                    continue
                k = rng.random()
                pend.append(("grass" if k < 0.45 else "shrub" if k < 0.93 else rng.choice(["olive", "pine", "cypress"]),
                             x, y, None))
        sc = N.TreeScatter(seed=self.seed + 17)
        for kind, x, y, z in pend:
            if z is None:
                if T.city_dist(x, y) < 4.0 or self._near_road(x, y, 4.5) or self._near_aq(x, y, 6.0):
                    continue
                if (Vector((x, y)) - self.amph_pos).length < 70:
                    continue
                if self.E["mills"] and (Vector((x, y)) - (self.mill_top - self.aq_dir * 28.0)).length < 42:
                    continue
                z = T.h(x, y)
                if self.harbor and z < 0.6:
                    continue
            sc.add(kind, x, y, z - 0.05)
        self.stats["trees"] = sc.emit(self.coll_veg)
        self.assets.add("mediterranean_trees")
        # vineyards: trained vine rows in a few centuriation plots near the farms
        mv = self._mb("Vineyards")
        cw, ch = 88.75, 44.4
        nv = 0
        tries = 0
        while nv < (10 if self.era == "alt_1000" else 7) and tries < 300:
            tries += 1
            ii, jj = rng.randint(-14, 14), rng.randint(-26, 26)
            px0, py0 = cw * ii - 3.0 + 3.0, ch * jj - 7.0 + 3.0
            px1, py1 = px0 + cw - 6.0, py0 + ch - 6.0
            cxp, cyp = (px0 + px1) / 2, (py0 + py1) / 2
            if not (280 < math.hypot(cxp, cyp) < 1300) or T.city_dist(cxp, cyp) < 120:
                continue
            if self._near_road(cxp, cyp, 60.0) or self._near_aq(cxp, cyp, 60.0):
                continue
            hs = [T.h(px, py) for px in (px0, px1) for py in (py0, py1)]
            if max(hs) - min(hs) > 8.0 or min(hs) < 0.5:
                continue
            yy = py0
            while yy <= py1:
                N.vine_row(mv, rng, (px0, yy), (px1, yy), T.h)
                yy += 2.4
            nv += 1
        self._emit(mv, self.coll_veg)

    # ------------------------------------------------------------------ camera targets
    def _poi(self):
        wx0, wy0, wx1, wy1 = self.wall
        fc = self.forum_center
        poi = {"focus": (fc.x, fc.y, 6.0), "view_az": 90.0, "lens": 30.0}
        P = self.p
        focus = P.get("camera_focus")
        if focus is None:
            focus = {"aqueduct": "aqueduct", "forum": "forum", "harbor": "harbor"}.get(P.get("_kind", ""), "forum")
        if focus == "aqueduct":
            m = self.aq_mid
            poi.update(focus=(m.x, m.y, 10.0), view_az=math.degrees(math.atan2(-self.aq_dir.y, -self.aq_dir.x)) + 25)
        elif focus == "harbor" and self.harbor:
            h = self.harbor_center
            poi.update(focus=(h.x, h.y, 2.0), view_az=-90.0)
        elif focus == "church" and hasattr(self, "church_center"):
            c = self.church_center
            poi.update(focus=(c.x, c.y, 15.0), view_az=0.0)
        legacy = bool(P.get("camera_legacy"))     # v1 camera paths (for before/after comparisons)
        if focus == "forum" and not legacy:
            # crane: from high over the forum looking north, down to a low 3/4 view of the temple
            tf = self.temple_front
            poi.update(crane_t0=(fc.x, fc.y + 250.0, 0.0), crane_t1=(tf.x, tf.y + 7.0, 9.5), crane_d0=330.0,
                       crane_h0=230.0, crane_d1=68.0, crane_h1=21.0, crane_side=-24.0, lens=32.0)
        # flyover: beside the mill cascade, along the aqueduct, over the north wall, past the
        # (domed) church towards the harbour / forum - low oblique heights (45-85 m)
        perp = Vector((-self.aq_dir.y, self.aq_dir.x))
        c = Vector((fc.x, fc.y))
        ch = self.church_center.xy if hasattr(self, "church_center") else c + Vector((60, 0))
        mill = self.mill_top if self.E["mills"] else self.aq_mid
        if self.harbor:
            end_t = self.harbor_center.xy + Vector((-30, -170))
        else:
            end_t = Vector((fc.x - 80, wy0 - 400))
        mill_c = (self.mill_top - self.aq_dir * 28.0) if self.E["mills"] else self.aq_mid
        pts = [mill_c + perp * 85 - self.aq_dir * 40, self.aq_p1 + self.aq_dir * 400 + perp * 80,
               self.aq_p1 + self.aq_dir * 170 + perp * 55, Vector((self.aq_p1.x + 40, wy1 + 15)),
               ch + Vector((-55, 95)), ch + Vector((-95, -55))]
        hs = [34.0, 44.0, 52.0, 62.0, 72.0, 82.0]
        poi["fly_path"] = [(q.x, q.y, h) for q, h in zip(pts, hs)]
        tg = [mill_c.xy if hasattr(mill_c, "xy") else mill_c, self.aq_p1 + self.aq_dir * 230, Vector((self.aq_p0.x, wy1)),
              ch + Vector((0, 20)), ch, end_t]
        tz = [(self.mill_z - 6.0) if self.E["mills"] else 4.0, 14.0, 10.0, 18.0, 16.0, -6.0]
        poi["fly_targets"] = [(q.x, q.y, z) for q, z in zip(tg, tz)]
        poi["fly_sun_az"] = math.degrees(math.atan2(self.aq_dir.y, self.aq_dir.x)) + 40.0
        if legacy:
            start = self.aq_p1 + self.aq_dir * 560.0
            if self.harbor:
                end, end_t = Vector((self.cardo_x + 30, fc.y - 40)), self.harbor_center.xy + Vector((-40, -520))
            else:
                end, end_t = Vector((fc.x - 30, fc.y - 70)), Vector((fc.x - 80, wy0 - 400))
            pts = [start + perp * 120, self.aq_p1 + self.aq_dir * 340 + perp * 110,
                   Vector((self.aq_p1.x + 40, wy1 - 40)), c + Vector((60, 40)), end]
            poi["fly_path"] = [(q.x, q.y, h) for q, h in zip(pts, [80.0, 85.0, 95.0, 110.0, 105.0])]
            tg = [self.aq_p1 + self.aq_dir * 420.0 + perp * 25.0, Vector((self.aq_p1.x, wy1 + 20)), c + Vector((40, 60)),
                  c + Vector((-10, -110)), end_t]
            poi["fly_targets"] = [(q.x, q.y, z) for q, z in zip(tg, [12.0, 10.0, 8.0, 6.0, -10.0])]
            poi["fly_sun_az"] = math.degrees(math.atan2(self.aq_dir.y, self.aq_dir.x)) + 62.0
        for k in ("view_az", "lens", "crane_h0", "crane_h1", "crane_d0", "crane_d1", "orbit_r", "orbit_h",
                  "orbit_sweep", "dolly_d0", "dolly_d1"):
            if k in P:
                poi[k] = P[k]
        self.poi = poi


def _frange(a, b, step):
    out = []
    x = a
    while x <= b:
        out.append(x)
        x += step
    return out


def _split(rect, rng, mn, mx):
    x0, y0, x1, y1 = rect
    w, d = x1 - x0, y1 - y0
    if w <= mx and d <= mx:
        return [rect]
    if w >= d:
        s = x0 + w * rng.uniform(0.38, 0.62)
        if s - x0 < mn or x1 - s < mn:
            s = x0 + w / 2
        return _split((x0, y0, s, y1), rng, mn, mx) + _split((s, y0, x1, y1), rng, mn, mx)
    s = y0 + d * rng.uniform(0.38, 0.62)
    if s - y0 < mn or y1 - s < mn:
        s = y0 + d / 2
    return _split((x0, y0, x1, s), rng, mn, mx) + _split((x0, s, x1, y1), rng, mn, mx)


def _pick(rng, mix, edge=0.0):
    keys = list(mix)
    w = []
    for k in keys:
        v = mix[k]
        if k in ("ruin", "garden"):
            v *= 0.5 + edge
        w.append(v)
    return rng.choices(keys, w)[0]


def build_city(params: dict, seed: int, stage=lambda f, m: None) -> City:
    return City(params, seed).build(stage)
