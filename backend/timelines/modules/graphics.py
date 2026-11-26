"""Text / timeline / comparison graphics (Skia -> FFmpeg). Shares the map palette and type system so
the channel has one design language: Cinzel display caps, EB Garamond text, Inter for UI badges."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Callable

import skia

from .. import config
from ..schemas import GraphicSpec
from .maps import Fonts, color, text

BADGES = {"FACT": ("HISTORICAL RECORD", "#3e7c59"), "INTERPRETATION": ("HISTORIANS DISAGREE", "#8a6d2f"),
          "SPECULATION": ("ALTERNATE HISTORY · HYPOTHETICAL", "#7a3b8f")}


def _expo_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def _in(t: float, start: float, dur: float = 0.7) -> float:
    return _expo_out((t - start) / dur)


class Backdrop:
    def __init__(self, w: int, h: int):
        surf = skia.Surface(w, h)
        c = surf.getCanvas()
        bg = skia.GradientShader.MakeRadial(skia.Point(w * 0.5, h * 0.42), math.hypot(w, h) * 0.6,
                                            [color("#1d2a33"), color("#0c1218")], [0.0, 1.0])
        c.drawPaint(skia.Paint(Shader=bg))
        noise = skia.PerlinNoiseShader.MakeFractalNoise(0.8, 0.8, 3, 11)
        c.drawPaint(skia.Paint(Shader=noise, Alphaf=0.05, BlendMode=skia.BlendMode.kOverlay))
        self.image = surf.makeImageSnapshot()

    def draw(self, canvas, t: float, duration: float, w: int, h: int) -> None:
        s = 1.0 + 0.03 * (t / max(duration, 1e-6))          # slow push-in
        canvas.save()
        canvas.translate(w / 2, h / 2)
        canvas.scale(s, s)
        canvas.translate(-w / 2, -h / 2)
        canvas.drawImage(self.image, 0, 0, skia.SamplingOptions(skia.FilterMode.kLinear))
        canvas.restore()


def _badge(canvas, fonts: Fonts, cls: str, w: int, u: float, a: float) -> None:
    label, col = BADGES[cls]
    font = skia.Font(fonts.sans, 19 * u)
    bw = font.measureText(label) + 34 * u
    rect = skia.Rect.MakeXYWH(w - 96 * u - bw, 64 * u, bw, 40 * u)
    canvas.drawRRect(skia.RRect.MakeRectXY(rect, 6 * u, 6 * u), skia.Paint(AntiAlias=True, Color=color(col, 0.92 * a)))
    text(canvas, label, rect.centerX(), rect.top() + 27 * u, fonts.sans, 19 * u, color("#ffffff", a), align="center")


def _fade_out(t: float, duration: float) -> float:
    return min(1.0, max(0.0, (duration - t) / 0.5))


def draw_graphic(canvas, spec: GraphicSpec, t: float, fonts: Fonts, back: Backdrop) -> None:
    w, h, u = spec.width, spec.height, spec.width / 1920.0
    back.draw(canvas, t, spec.duration_s, w, h)
    out = _fade_out(t, spec.duration_s)
    gold, ink = "#c9a227", "#f4ecd8"
    if spec.style in ("title_card", "end_card", "quote"):
        a1 = _in(t, 0.15) * out
        y = h * 0.46 - (1 - a1) * 18 * u
        size = 92 if spec.style == "title_card" else 64
        main_font = fonts.display if spec.style != "quote" else fonts.italic
        text(canvas, spec.lines[0], w / 2, y, main_font, size * u, color(ink, a1), align="center",
             tracking=0.04 if spec.style != "quote" else 0)
        rule = _in(t, 0.45, 0.9) * out
        canvas.drawRect(skia.Rect.MakeXYWH(w / 2 - 160 * u * rule, y + 34 * u, 320 * u * rule, 2 * u),
                        skia.Paint(Color=color(gold, rule)))
        for i, line in enumerate(spec.lines[1:]):
            a = _in(t, 0.7 + 0.25 * i) * out
            text(canvas, line, w / 2, y + (100 + 54 * i) * u - (1 - a) * 12 * u, fonts.italic, 38 * u,
                 color("#d8cfba", a), align="center")
    elif spec.style == "timeline":
        a0 = _in(t, 0.1) * out
        text(canvas, spec.lines[0].upper(), 120 * u, 170 * u, fonts.display, 52 * u, color(ink, a0), tracking=0.08)
        n = max(1, len(spec.items))
        x0, x1, y = 180 * u, w - 180 * u, h * 0.56
        span = spec.duration_s - 1.4
        grow = _in(t, 0.3, 1.2) * out
        canvas.drawRect(skia.Rect.MakeXYWH(x0, y - 1.5 * u, (x1 - x0) * grow, 3 * u),
                        skia.Paint(Color=color("#8d8064", grow)))
        for i, item in enumerate(spec.items):
            start = 0.6 + span * i / n
            a = _in(t, start) * out
            if a <= 0:
                continue
            x = x0 + (x1 - x0) * (i + 0.5) / n
            col = BADGES.get(item.get("classification", "FACT"), BADGES["FACT"])[1]
            canvas.drawCircle(x, y, 10 * u * a, skia.Paint(AntiAlias=True, Color=color(gold, a)))
            canvas.drawCircle(x, y, 4 * u * a, skia.Paint(AntiAlias=True, Color=color("#0c1218", a)))
            up = i % 2 == 0
            ty = y - 60 * u if up else y + 92 * u
            text(canvas, str(item.get("year", "")), x, ty - (1 - a) * 14 * u, fonts.display, 46 * u,
                 color(ink, a), align="center")
            for j, line in enumerate(str(item.get("label", "")).split("\n")):
                ly = (ty - 52 * u - 34 * u * (len(str(item.get('label', '')).split('\n')) - 1 - j)) if up \
                    else ty + 44 * u + 34 * u * j
                text(canvas, line, x, ly, fonts.serif, 29 * u, color("#d8cfba", a), align="center")
            if item.get("classification") and item["classification"] != "FACT":
                canvas.drawRect(skia.Rect.MakeXYWH(x - 24 * u, y + 18 * u, 48 * u, 3 * u),
                                skia.Paint(Color=color(col, a)))
    elif spec.style == "comparison":
        a0 = _in(t, 0.1) * out
        heads = spec.lines[:2] if len(spec.lines) >= 2 else ["", ""]
        n = max(1, len(spec.items))
        block = 120 * u + n * 96 * u                      # heading + rows, centred vertically
        top = (h - block) / 2 + 40 * u
        for k, head in enumerate(heads):
            cx = w * (0.29 if k == 0 else 0.71)
            text(canvas, head.upper(), cx, top, fonts.display, 58 * u, color(ink, a0), align="center",
                 tracking=0.08)
            grow = _in(t, 0.35, 0.9) * out
            canvas.drawRect(skia.Rect.MakeXYWH(cx - 120 * u * grow, top + 28 * u, 240 * u * grow, 2 * u),
                            skia.Paint(Color=color(gold, grow)))
        canvas.drawRect(skia.Rect.MakeXYWH(w / 2 - 1, top - 70 * u, 2, (block + 40 * u) * a0),
                        skia.Paint(Color=color("#8d8064", 0.7 * a0)))
        for i, item in enumerate(spec.items):
            a = _in(t, 0.6 + 0.5 * i) * out
            y = top + 120 * u + i * 96 * u - (1 - a) * 12 * u
            text(canvas, str(item.get("left", "")), w * 0.29, y, fonts.serif, 46 * u, color("#e6dcc4", a), align="center")
            text(canvas, str(item.get("right", "")), w * 0.71, y, fonts.serif, 46 * u, color("#e6dcc4", a), align="center")
    _badge(canvas, fonts, spec.classification, w, u, _in(t, 0.2) * out)


def render_graphic(spec: GraphicSpec, out_mp4: Path, *, preview: bool = False,
                   progress: Callable[[float, str], None] | None = None) -> dict:
    if preview:
        spec = spec.model_copy(update={"width": spec.width // 2, "height": spec.height // 2})
    fonts, back = Fonts(), Backdrop(spec.width, spec.height)
    n = round(spec.duration_s * spec.fps)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [config.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
           "-s", f"{spec.width}x{spec.height}", "-r", str(spec.fps), "-i", "-", "-c:v", "libx264", "-preset", "medium",
           "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    surf, thumb = skia.Surface(spec.width, spec.height), None
    try:
        for i in range(n):
            c = surf.getCanvas()
            c.clear(skia.ColorBLACK)
            draw_graphic(c, spec, i / spec.fps, fonts, back)
            img = surf.makeImageSnapshot()
            proc.stdin.write(img.toarray(colorType=skia.kRGBA_8888_ColorType).tobytes())
            if i == int(n * 0.7):
                thumb = img
            if progress and i % 15 == 0:
                progress(i / n, f"graphic {spec.scene_id} {i}/{n}")
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
            "width": spec.width, "height": spec.height}


def overlay_png(badge: str, classification: str, era: str, w: int, h: int, path: Path) -> Path:
    """Transparent label layer for 3D shots: classification badge (top right) + era (bottom left)."""
    fonts, u = Fonts(), w / 1920.0
    surf = skia.Surface(w, h)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    col = BADGES.get(classification, BADGES["FACT"])[1]
    font = skia.Font(fonts.sans, 19 * u)
    bw = font.measureText(badge) + 34 * u
    rect = skia.Rect.MakeXYWH(w - 96 * u - bw, 64 * u, bw, 40 * u)
    c.drawRRect(skia.RRect.MakeRectXY(rect, 6 * u, 6 * u), skia.Paint(AntiAlias=True, Color=color(col, 0.92)))
    text(c, badge, rect.centerX(), rect.top() + 27 * u, fonts.sans, 19 * u, color("#ffffff"), align="center")
    if era:
        shade = skia.GradientShader.MakeLinear([skia.Point(0, h - 260 * u), skia.Point(0, h)],
                                               [color("#000000", 0.0), color("#000000", 0.45)])
        c.drawRect(skia.Rect.MakeXYWH(0, h - 260 * u, w, 260 * u), skia.Paint(Shader=shade))
        text(c, era, 96 * u, h - 96 * u, fonts.display, 54 * u, color("#fff6e0"), halo=color("#0b1117", 0.5),
             halo_w=6 * u, tracking=0.05)
    surf.makeImageSnapshot().save(str(path), skia.kPNG)
    return path


def apply_overlay(video: Path, png: Path, out: Path) -> None:
    cmd = [config.ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video), "-loop", "1", "-i", str(png),
           "-filter_complex", "[1:v]format=rgba,fade=in:st=0.4:d=0.7:alpha=1[o];[0:v][o]overlay=0:0:shortest=1",
           "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           str(out)]
    subprocess.run(cmd, check=True)
