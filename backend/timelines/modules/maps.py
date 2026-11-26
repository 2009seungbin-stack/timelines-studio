"""Historical Map Engine: MapSpec -> MP4 (Skia vector rendering piped to FFmpeg).

Cartographic rules from the brief:
  * historical borders are drawn apart from modern ones (modern borders only on request);
  * borders of poorly documented periods are never drawn as hard lines ("approximate" = feathered
    edge + dashed outline; "hypothetical" = hatched fill + dashed outline + ALTERNATE HISTORY badge);
  * every map carries its data attribution and a classification badge.
Projection: equirectangular with a 40N standard parallel (low distortion for the Mediterranean).
"""
from __future__ import annotations

import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
import skia
from shapely.geometry import box, shape
from shapely.ops import unary_union

from .. import config
from ..schemas import MapSpec

K = math.cos(math.radians(40))
CLIP = box(-30, 10, 75, 66)          # Europe / Mediterranean / Near East working window
PALETTE = {
    "sea_top": "#15212b", "sea_bottom": "#0d151c", "land": "#cdbf9e", "land_shadow": "#7d6f52",
    "coast": "#efe6cf", "river": "#47697e", "lake": "#22394a", "label": "#f4ecd8", "halo": "#0b1117",
    "city": "#f4ecd8", "route_sea": "#e8c872", "route_land": "#d9a35f",
}
CLASS_BADGE = {
    "FACT": ("HISTORICAL MAP", "#3e7c59"),
    "INTERPRETATION": ("HISTORICAL MAP · BORDERS APPROXIMATE", "#8a6d2f"),
    "SPECULATION": ("ALTERNATE HISTORY · HYPOTHETICAL", "#7a3b8f"),
}


def color(hexstr: str, alpha: float = 1.0) -> int:
    h = hexstr.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return skia.Color(r, g, b, int(max(0, min(1, alpha)) * 255))


# ------------------------------------------------------------------ geometry
def registry() -> dict[str, dict]:
    reg = config.GEO_ROOT / "registry.json"
    layers = json.loads(reg.read_text("utf-8")) if reg.exists() else []
    if isinstance(layers, dict):
        layers = layers.get("layers", [])
    return {layer["id"]: layer for layer in layers}


def _geojson(path: Path) -> list[dict]:
    data = json.loads(path.read_text("utf-8"))
    return data["features"] if data.get("type") == "FeatureCollection" else [data]


def _match(props: dict, flt: dict) -> bool:
    for key, want in flt.items():
        have = props.get(key)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


def _allow_unclear() -> bool:
    import os
    return os.environ.get("TIMELINES_ALLOW_UNCLEAR_LICENSES") == "1"


@lru_cache(maxsize=64)
def layer_geometry(source: str, filter_json: str = "{}", region: str | None = None):
    """Shapely geometry for a registry layer (filtered) or a named region file in data/geo/regions."""
    if region:
        path = config.GEO_ROOT / "regions" / f"{region}.geojson"
        feats = _geojson(path)
    else:
        layer = registry().get(source)
        if layer is None:
            raise KeyError(f"geo layer {source} is not in data/geo/registry.json")
        if layer.get("commercial_use") != "yes" and not _allow_unclear():
            raise PermissionError(f"geo layer {source}: commercial use '{layer.get('commercial_use')}' - "
                                  "not allowed in renders (set TIMELINES_ALLOW_UNCLEAR_LICENSES=1 for internal tests)")
        path = config.GEO_ROOT / layer["file"]
        feats = _geojson(path)
        flt = json.loads(filter_json)
        feats = [f for f in feats if _match(f.get("properties") or {}, flt)]
    if not feats:
        raise ValueError(f"no features for source={source} filter={filter_json} region={region}")
    geom = unary_union([shape(f["geometry"]).buffer(0) for f in feats if f.get("geometry")])
    return geom.intersection(CLIP)


def _ring(path: skia.Path, coords) -> None:
    pts = np.asarray(coords, dtype=float)
    if len(pts) < 2:
        return
    path.moveTo(pts[0, 0] * K, -pts[0, 1])
    for x, y in pts[1:, :2]:
        path.lineTo(x * K, -y)


def to_path(geom) -> skia.Path:
    path = skia.Path()
    path.setFillType(skia.PathFillType.kEvenOdd)
    geoms = getattr(geom, "geoms", [geom])
    for g in geoms:
        if g.geom_type == "Polygon":
            _ring(path, g.exterior.coords)
            path.close()
            for hole in g.interiors:
                _ring(path, hole.coords)
                path.close()
        elif g.geom_type in ("LineString", "LinearRing"):
            _ring(path, g.coords)
        elif g.geom_type in ("MultiPolygon", "MultiLineString", "GeometryCollection"):
            sub = to_path(g)
            path.addPath(sub)
    return path


@lru_cache(maxsize=1)
def land_geometry():
    feats = _geojson(config.GEO_ROOT / "basemap" / "ne_50m_land.geojson")
    geoms = [shape(f["geometry"]) for f in feats if f.get("geometry")]
    return unary_union([g.intersection(CLIP) for g in geoms if g.intersects(CLIP)]).buffer(0)


@lru_cache(maxsize=8)
def basemap_paths() -> dict[str, skia.Path]:
    out = {}
    for key, name, simplify in (("land", "ne_50m_land", 0.01), ("lakes", "ne_50m_lakes", 0.01),
                                ("rivers", "ne_50m_rivers_lake_centerlines", 0.005)):
        p = config.GEO_ROOT / "basemap" / f"{name}.geojson"
        if not p.exists():
            raise FileNotFoundError(f"basemap layer missing: {p} (Natural Earth, public domain)")
        geoms = [shape(f["geometry"]) for f in _geojson(p) if f.get("geometry")]
        geom = unary_union([g.intersection(CLIP) for g in geoms if g.intersects(CLIP)])
        out[key] = to_path(geom.simplify(simplify, preserve_topology=True))
    return out


# ------------------------------------------------------------------ camera
def _ease(t: float, kind: str) -> float:
    if kind == "linear":
        return t
    if kind == "out":
        return 1 - (1 - t) ** 3
    return t * t * (3 - 2 * t) if t < 1 else 1.0


def camera_at(spec: MapSpec, t: float) -> tuple[float, float, float]:
    keys = sorted(spec.camera, key=lambda k: k.t)
    if t <= keys[0].t:
        return keys[0].lon, keys[0].lat, keys[0].zoom
    for a, b in zip(keys, keys[1:]):
        if a.t <= t <= b.t:
            u = _ease((t - a.t) / max(1e-6, b.t - a.t), b.ease)
            # interpolate zoom geometrically so zooming feels uniform
            zoom = math.exp(math.log(a.zoom) + (math.log(b.zoom) - math.log(a.zoom)) * u)
            return a.lon + (b.lon - a.lon) * u, a.lat + (b.lat - a.lat) * u, zoom
    k = keys[-1]
    return k.lon, k.lat, k.zoom


def _matrix(spec: MapSpec, t: float) -> skia.Matrix:
    lon, lat, zoom = camera_at(spec, t)
    scale = spec.width / (zoom * K)
    m = skia.Matrix()
    m.setTranslate(spec.width / 2, spec.height / 2)
    m.preScale(scale, scale)
    m.preTranslate(-lon * K, lat)
    return m


def _project(m: skia.Matrix, lon: float, lat: float) -> tuple[float, float]:
    p = m.mapXY(lon * K, -lat)
    return p.x(), p.y()


def _xf(path: skia.Path, m: skia.Matrix) -> skia.Path:
    p = skia.Path(path)
    p.transform(m)
    return p


# ------------------------------------------------------------------ drawing
class Fonts:
    def __init__(self):
        def tf(name):
            f = config.font(name)
            return skia.Typeface.MakeFromFile(f) if f else skia.Typeface("Georgia")
        self.display = tf("Cinzel-SemiBold.ttf")
        self.display_regular = tf("Cinzel-Regular.ttf")
        self.serif = tf("EBGaramond-Medium.ttf")
        self.italic = tf("EBGaramond-Italic.ttf")
        self.sans = tf("Inter-SemiBold.ttf")
        self.sans_medium = tf("Inter-Medium.ttf")


def _alpha_window(t: float, start: float, end: float | None, fade: float) -> float:
    a = min(1.0, max(0.0, (t - start) / fade)) if fade > 0 else float(t >= start)
    if end is not None:
        a *= min(1.0, max(0.0, (end - t) / fade)) if fade > 0 else float(t < end)
    return a


def text(canvas, s: str, x: float, y: float, tf, size: float, fill: int, *, halo: int | None = None,
         halo_w: float = 0, align: str = "left", tracking: float = 0.0) -> float:
    font = skia.Font(tf, size)
    font.setSubpixel(True)
    font.setEdging(skia.Font.Edging.kAntiAlias)
    if tracking:
        width = sum(font.measureText(ch) for ch in s) + tracking * size * (len(s) - 1)
    else:
        width = font.measureText(s)
    if align == "center":
        x -= width / 2
    elif align == "right":
        x -= width
    paints = []
    if halo is not None and halo_w > 0:
        paints.append(skia.Paint(AntiAlias=True, Color=halo, Style=skia.Paint.kStroke_Style, StrokeWidth=halo_w,
                                 StrokeJoin=skia.Paint.kRound_Join))
    paints.append(skia.Paint(AntiAlias=True, Color=fill))
    for paint in paints:
        if tracking:
            cx = x
            for ch in s:
                canvas.drawString(ch, cx, y, font, paint)
                cx += font.measureText(ch) + tracking * size
        else:
            canvas.drawString(s, x, y, font, paint)
    return width


def _hatch_shader(col: int, spacing: float = 9.0) -> skia.Shader:
    surf = skia.Surface(int(spacing), int(spacing))
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(AntiAlias=True, Color=col, StrokeWidth=1.6, Style=skia.Paint.kStroke_Style)
    c.drawLine(0, spacing, spacing, 0, paint)
    c.drawLine(-1, 1, 1, -1, paint)
    c.drawLine(spacing - 1, spacing + 1, spacing + 1, spacing - 1, paint)
    img = surf.makeImageSnapshot()
    return img.makeShader(skia.TileMode.kRepeat, skia.TileMode.kRepeat)


class BaseLayer:
    """Static basemap (land, coast glow, shadow, lakes, rivers, paper grain) rendered once per scene
    at the scene's highest needed resolution, then drawn through the camera matrix each frame."""

    MAX_SIDE = 6144

    def __init__(self, spec: MapSpec):
        paths = basemap_paths()
        samples = [camera_at(spec, spec.duration_s * i / 40) for i in range(41)]
        xs, ys, ppus = [], [], []
        for lon, lat, zoom in samples:
            half_w = zoom * K / 2
            half_h = half_w * spec.height / spec.width
            xs += [lon * K - half_w, lon * K + half_w]
            ys += [-lat - half_h, -lat + half_h]
            ppus.append(spec.width / (zoom * K))
        pad = 0.08 * (max(xs) - min(xs))
        self.x0, self.y0 = min(xs) - pad, min(ys) - pad
        span_x, span_y = max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad
        self.ppu = min(max(ppus), self.MAX_SIDE / span_x, self.MAX_SIDE / span_y)
        W, H = int(span_x * self.ppu) + 1, int(span_y * self.ppu) + 1
        u = spec.width / 1920.0 * (self.ppu / max(ppus))   # image px == output px at the closest view
        surf = skia.Surface(W, H)
        c = surf.getCanvas()
        c.clear(skia.ColorTRANSPARENT)
        m = skia.Matrix()
        m.setScale(self.ppu, self.ppu)
        m.preTranslate(-self.x0, -self.y0)
        land = _xf(paths["land"], m)
        c.drawPath(land, skia.Paint(AntiAlias=True, Color=color(PALETTE["coast"], 0.10),
                                    MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 9 * u)))
        sh = skia.Path(land)
        sh.offset(2.5 * u, 3.5 * u)
        c.drawPath(sh, skia.Paint(AntiAlias=True, Color=color("#000000", 0.45),
                                  MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 4 * u)))
        shader = skia.GradientShader.MakeLinear([skia.Point(0, 0), skia.Point(0, H)],
                                                [color("#d8cba9"), color("#b9aa86")])
        c.drawPath(land, skia.Paint(AntiAlias=True, Shader=shader))
        # paper grain: fractal noise kept inside the land
        c.save()
        c.clipPath(land, doAntiAlias=True)
        noise = skia.PerlinNoiseShader.MakeFractalNoise(0.9 / max(1.0, u), 0.9 / max(1.0, u), 3, 7)
        c.drawPaint(skia.Paint(Shader=noise, Alphaf=0.10, BlendMode=skia.BlendMode.kMultiply))
        inner = skia.Paint(AntiAlias=True, Color=color("#6f5f42", 0.35), Style=skia.Paint.kStroke_Style,
                           StrokeWidth=14 * u, MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 8 * u))
        c.drawPath(land, inner)                       # soft inner shading along the coast
        c.restore()
        c.drawPath(_xf(paths["lakes"], m), skia.Paint(AntiAlias=True, Color=color(PALETTE["lake"])))
        c.drawPath(_xf(paths["rivers"], m), skia.Paint(AntiAlias=True, Color=color(PALETTE["river"], 0.85),
                                                        Style=skia.Paint.kStroke_Style, StrokeWidth=1.3 * u))
        c.drawPath(land, skia.Paint(AntiAlias=True, Color=color(PALETTE["land_shadow"], 0.9),
                                    Style=skia.Paint.kStroke_Style, StrokeWidth=1.0 * u))
        self.image = surf.makeImageSnapshot()
        # bilinear without mipmaps: views never shrink the cached image by more than ~2x, and CPU
        # trilinear sampling was 0.5 s/frame at 1080p.
        self.sampling = skia.SamplingOptions(skia.FilterMode.kLinear)
        w, h = spec.width, spec.height
        bg = skia.Surface(w, h)
        sea = skia.GradientShader.MakeLinear([skia.Point(0, 0), skia.Point(0, h)],
                                             [color(PALETTE["sea_top"]), color(PALETTE["sea_bottom"])])
        bg.getCanvas().drawPaint(skia.Paint(Shader=sea))
        self.sea = bg.makeImageSnapshot()
        vg = skia.Surface(w, h)
        vg.getCanvas().clear(skia.ColorTRANSPARENT)
        vig = skia.GradientShader.MakeRadial(skia.Point(w / 2, h / 2), math.hypot(w, h) * 0.62,
                                             [color("#000000", 0.0), color("#000000", 0.0), color("#000000", 0.55)],
                                             [0.0, 0.6, 1.0])
        vg.getCanvas().drawPaint(skia.Paint(Shader=vig))
        self.vignette = vg.makeImageSnapshot()

    def draw(self, canvas, m: skia.Matrix) -> None:
        canvas.save()
        canvas.concat(m)
        canvas.translate(self.x0, self.y0)
        canvas.scale(1 / self.ppu, 1 / self.ppu)
        canvas.drawImage(self.image, 0, 0, self.sampling)
        canvas.restore()


def _reserved_zones(spec: MapSpec, t: float, u: float) -> list[skia.Rect]:
    w, h = spec.width, spec.height
    zones = [skia.Rect.MakeXYWH(w - 560 * u, 40 * u, 520 * u, 80 * u),          # badge
             skia.Rect.MakeXYWH(w * 0.45, h - 60 * u, w * 0.55, 60 * u)]          # attribution
    for cap in spec.captions:
        if cap.start - 0.5 <= t <= cap.end + 0.5:
            if cap.role == "date":
                zones.append(skia.Rect.MakeXYWH(70 * u, 60 * u, 560 * u, 125 * u))
            elif cap.role == "title":
                zones.append(skia.Rect.MakeXYWH(80 * u, h - 240 * u, 1100 * u, 100 * u))
            else:
                zones.append(skia.Rect.MakeXYWH(100 * u, h - 150 * u, 1100 * u, 60 * u))
    return zones


def _place(x: float, y: float, tw: float, size: float, zones: list[skia.Rect], u: float,
           centered: bool = False) -> tuple[float, float]:
    """Try right / left / below / above the anchor; return the first spot that avoids reserved zones."""
    cands = ([(x - tw / 2, y + size * 0.35), (x - tw / 2, y + size * 1.5), (x - tw / 2, y - size * 0.9)] if centered
             else [(x + 9 * u, y + 7 * u), (x - 9 * u - tw, y + 7 * u), (x - tw / 2, y + size * 1.35),
                   (x - tw / 2, y - size * 0.75)])
    base_x, base_y = cands[-2] if not centered else cands[1]
    cands += [(base_x, base_y + size * k) for k in (1.2, 2.4, 3.6, 4.8)]   # step further away if needed
    for cx, cy in cands:
        r = skia.Rect.MakeXYWH(cx - 4 * u, cy - size, tw + 8 * u, size * 1.3)
        if not any(skia.Rect.Intersects(r, z) for z in zones):
            return cx, cy
    return cands[0]


def draw_frame(canvas, spec: MapSpec, t: float, fonts: Fonts, base: "BaseLayer",
               territories: list[tuple], attribution: str) -> None:
    w, h = spec.width, spec.height
    u = w / 1920.0
    m = _matrix(spec, t)
    _, _, zoom = camera_at(spec, t)

    canvas.drawImage(base.sea, 0, 0)
    base.draw(canvas, m)

    # territories ---------------------------------------------------
    for terr, path, border in territories:
        a = _alpha_window(t, terr.appear_at, terr.disappear_at, terr.fade_s)
        if a <= 0.001:
            continue
        p = _xf(path, m)
        if terr.certainty == "hypothetical":
            canvas.drawPath(p, skia.Paint(AntiAlias=True, Color=color(terr.color, 0.30 * a)))
            canvas.drawPath(p, skia.Paint(AntiAlias=True, Shader=_hatch_shader(color(terr.color, 0.55 * a), 10 * u)))
        elif terr.certainty == "approximate":
            canvas.drawPath(p, skia.Paint(AntiAlias=True, Color=color(terr.color, 0.62 * a),
                                          MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 7 * u)))
        else:
            canvas.drawPath(p, skia.Paint(AntiAlias=True, Color=color(terr.color, 0.62 * a)))
        stroke = skia.Paint(AntiAlias=True, Color=color(terr.color, 0.95 * a), Style=skia.Paint.kStroke_Style,
                            StrokeWidth=(2.2 if terr.certainty == "firm" else 1.6) * u,
                            StrokeJoin=skia.Paint.kRound_Join)
        if terr.certainty != "firm":
            stroke.setPathEffect(skia.DashPathEffect.Make([7 * u, 5 * u], 0))
        canvas.drawPath(_xf(border, m), stroke)

    # routes ----------------------------------------------------------
    for route in spec.routes:
        prog = min(1.0, max(0.0, (t - route.draw_from) / max(1e-6, route.draw_to - route.draw_from)))
        if prog <= 0:
            continue
        rp = skia.Path()
        pts = [_project(m, lon, lat) for lon, lat in route.coords]
        rp.moveTo(*pts[0])
        for pt in pts[1:]:
            rp.lineTo(*pt)
        meas = skia.PathMeasure(rp, False)
        seg = skia.Path()
        meas.getSegment(0, meas.getLength() * prog, seg, True)
        col = PALETTE["route_sea"] if route.kind == "sea" else PALETTE["route_land"]
        glow = skia.Paint(AntiAlias=True, Color=color(col, 0.35), Style=skia.Paint.kStroke_Style, StrokeWidth=6 * u,
                          MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 3 * u))
        line = skia.Paint(AntiAlias=True, Color=color(col), Style=skia.Paint.kStroke_Style, StrokeWidth=2.4 * u,
                          StrokeCap=skia.Paint.kRound_Cap)
        if route.kind == "sea":
            line.setPathEffect(skia.DashPathEffect.Make([10 * u, 6 * u], -t * 30 * u))
        canvas.drawPath(seg, glow)
        canvas.drawPath(seg, line)
        if 0 < prog < 1:
            pos_tan = meas.getPosTan(meas.getLength() * prog)
            pos = pos_tan[0] if isinstance(pos_tan, tuple) else None
            if pos is not None:
                canvas.drawCircle(pos.x(), pos.y(), 4.5 * u, skia.Paint(AntiAlias=True, Color=color(col)))

    # labels (kept clear of the caption / badge zones) -------------
    reserved = _reserved_zones(spec, t, u)
    for lab in spec.labels:
        a = _alpha_window(t, lab.appear_at, lab.disappear_at, 0.5)
        if a <= 0.001:
            continue
        x, y = _project(m, lab.lon, lab.lat)
        if not (-200 < x < w + 200 and -100 < y < h + 100):
            continue
        if lab.kind == "city":
            canvas.drawCircle(x, y, 5.5 * u, skia.Paint(AntiAlias=True, Color=color(PALETTE["halo"], 0.8 * a)))
            canvas.drawCircle(x, y, 3.6 * u, skia.Paint(AntiAlias=True, Color=color(PALETTE["city"], a)))
            tw = skia.Font(fonts.serif, 27 * u).measureText(lab.text)
            tx, ty = _place(x, y, tw, 27 * u, reserved, u)
            text(canvas, lab.text, tx, ty, fonts.serif, 27 * u, color(PALETTE["label"], a),
                 halo=color(PALETTE["halo"], 0.85 * a), halo_w=5 * u)
        elif lab.kind == "region":
            text(canvas, lab.text.upper(), x, y, fonts.display, 30 * u, color("#fff6e0", a),
                 halo=color(PALETTE["halo"], 0.7 * a), halo_w=6 * u, align="center", tracking=0.16)
        elif lab.kind == "sea":
            text(canvas, lab.text, x, y, fonts.italic, 30 * u, color("#9fb6c4", 0.9 * a), align="center",
                 tracking=0.10)
        else:
            tw = skia.Font(fonts.sans_medium, 24 * u).measureText(lab.text)
            tx, ty = _place(x, y, tw, 24 * u, reserved, u, centered=True)
            text(canvas, lab.text, tx, ty, fonts.sans_medium, 24 * u, color("#f4ecd8", a),
                 halo=color(PALETTE["halo"], 0.85 * a), halo_w=5 * u)

    # vignette ------------------------------------------------------
    canvas.drawImage(base.vignette, 0, 0)

    # captions ------------------------------------------------------
    for cap in spec.captions:
        a = _alpha_window(t, cap.start, cap.end, 0.45)
        if a <= 0.001:
            continue
        if cap.role == "date":
            text(canvas, cap.text, 96 * u, 150 * u, fonts.display, 76 * u, color("#fff6e0", a),
                 halo=color(PALETTE["halo"], 0.55 * a), halo_w=8 * u, tracking=0.06)
        elif cap.role == "title":
            bar_y = h - 170 * u
            canvas.drawRect(skia.Rect.MakeXYWH(96 * u, bar_y - 48 * u, 4 * u, 62 * u),
                            skia.Paint(Color=color("#c9a227", a)))
            text(canvas, cap.text, 118 * u, bar_y, fonts.display_regular, 40 * u, color("#fff6e0", a),
                 halo=color(PALETTE["halo"], 0.6 * a), halo_w=6 * u, tracking=0.05)
        else:
            text(canvas, cap.text, 118 * u, h - 112 * u, fonts.italic, 30 * u, color("#e6dcc4", a),
                 halo=color(PALETTE["halo"], 0.6 * a), halo_w=5 * u)

    badge, bcol = CLASS_BADGE[spec.classification]
    if spec.classification == "FACT" and any(tr.certainty != "firm" for tr in spec.territories):
        badge = "HISTORICAL MAP · BORDERS APPROXIMATE"
    elif spec.classification == "INTERPRETATION":
        badge = "HISTORICAL MAP · INTERPRETATION"
    font = skia.Font(fonts.sans, 19 * u)
    bw = font.measureText(badge) + 34 * u
    rect = skia.Rect.MakeXYWH(w - 96 * u - bw, 64 * u, bw, 40 * u)
    canvas.drawRRect(skia.RRect.MakeRectXY(rect, 6 * u, 6 * u), skia.Paint(AntiAlias=True, Color=color(bcol, 0.92)))
    text(canvas, badge, rect.centerX(), rect.top() + 27 * u, fonts.sans, 19 * u, color("#ffffff"), align="center")
    text(canvas, attribution, w - 40 * u, h - 30 * u, fonts.sans_medium, 15 * u, color("#cfc6b0", 0.75),
         align="right")


def _attribution(spec: MapSpec) -> str:
    reg = registry()
    parts = ["Base map: Natural Earth"]
    for terr in spec.territories:
        layer = reg.get(terr.source) or {}
        credit = layer.get("short_credit") or ("Borders: AWMC, ODbL 1.0" if terr.source.startswith(("awmc", "derived"))
                                               else None)
        if terr.region:
            credit = "Hypothetical region drawn by TIMELINES"
        if credit and credit not in parts:
            parts.append(credit)
    if any(t.certainty != "firm" for t in spec.territories):
        parts.append("Borders approximate")
    return " · ".join(parts)


def render_map(spec: MapSpec, out_mp4: Path, *, preview: bool = False,
               progress: Callable[[float, str], None] | None = None) -> dict:
    """Render a MapSpec to H.264. Preview = half resolution."""
    if preview:
        spec = spec.model_copy(update={"width": spec.width // 2, "height": spec.height // 2})
    fonts = Fonts()
    base = BaseLayer(spec)
    territories = []
    for terr in spec.territories:
        geom = layer_geometry(terr.source, json.dumps(terr.feature_filter, sort_keys=True), terr.region)
        land = land_geometry()
        fill = geom.intersection(land).simplify(0.02, preserve_topology=True)   # empires drawn on land only
        border = geom.boundary.intersection(land.buffer(-0.08)).simplify(0.02)  # land borders, not coasts
        territories.append((terr, to_path(fill), to_path(border)))
    attribution = _attribution(spec)
    n = round(spec.duration_s * spec.fps)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [config.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
           "-s", f"{spec.width}x{spec.height}", "-r", str(spec.fps), "-i", "-", "-c:v", "libx264",
           "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    surface = skia.Surface(spec.width, spec.height)
    thumb = None
    try:
        for i in range(n):
            t = i / spec.fps
            canvas = surface.getCanvas()
            canvas.clear(skia.ColorBLACK)
            draw_frame(canvas, spec, t, fonts, base, territories, attribution)
            img = surface.makeImageSnapshot()
            arr = img.toarray(colorType=skia.kRGBA_8888_ColorType)
            proc.stdin.write(arr.tobytes())
            if i == int(n * 0.6):
                thumb = img
            if progress and i % 15 == 0:
                progress(i / n, f"map {spec.scene_id} frame {i}/{n}")
    finally:
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err[-800:]}")
    thumb_path = out_mp4.with_suffix(".jpg")
    if thumb is not None:
        thumb.save(str(thumb_path), skia.kJPEG)
    return {"video": str(out_mp4), "thumb": str(thumb_path), "frames": n, "fps": spec.fps,
            "width": spec.width, "height": spec.height, "attribution": attribution}
