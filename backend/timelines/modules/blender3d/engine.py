"""TIMELINES Studio - Blender 3D production engine (host side).

`render_scene(spec, out_dir)` writes the spec JSON, runs Blender headless with the
procedural bpy generators in ``bpy_scripts/``, saves the scene as a .blend,
renders JPEG frames, encodes an H.264 MP4 whose frame count equals
round(duration_s * fps), writes a thumbnail from the middle frame and removes the
frame folder it created once the MP4 is verified.

No AI image/video generation is involved: all geometry, materials, lights and
cameras are created by code through the Blender Python API.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from timelines.schemas import Scene3DSpec

MODULE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = MODULE_DIR / "bpy_scripts"
ENTRY_SCRIPT = SCRIPTS_DIR / "render_scene.py"
STUDIO_ROOT = MODULE_DIR.parents[3]          # .../timelines_studio
DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
from ... import config as _config
GPU_LOCK_DIR = str(_config.GPU_LOCK_DIR)
FALLBACK_LOCK = STUDIO_ROOT / "data" / "dev_renders" / ".gpu_fallback.lock"
SUPPORTED_KINDS = ("roman_city", "aqueduct", "forum", "harbor")

ProgressFn = Callable[[float, str], None]


class BlenderNotFound(RuntimeError):
    """Blender executable could not be located."""


class RenderFailed(RuntimeError):
    """Blender or FFmpeg failed. ``log_tail`` holds the last lines of the log."""

    def __init__(self, message: str, log_tail: str = "", log_path: str | None = None):
        super().__init__(f"{message}\n--- log tail ---\n{log_tail}" if log_tail else message)
        self.log_tail = log_tail
        self.log_path = log_path


# --------------------------------------------------------------------------- helpers
def frame_count(duration_s: float, fps: int) -> int:
    """Frames for a clip: round-half-up(duration * fps), at least 1."""
    if duration_s <= 0 or fps <= 0:
        raise ValueError("duration_s and fps must be positive")
    return max(1, int(math.floor(duration_s * fps + 0.5)))


def find_blender(blender_exe: Path | str | None = None) -> Path:
    cands = []
    if blender_exe:
        cands.append(Path(blender_exe))
    if os.environ.get("TIMELINES_BLENDER"):
        cands.append(Path(os.environ["TIMELINES_BLENDER"]))
    cands.append(DEFAULT_BLENDER)
    w = shutil.which("blender")
    if w:
        cands.append(Path(w))
    for c in cands:
        if c.is_file():
            return c
    raise BlenderNotFound(f"Blender not found (tried: {', '.join(str(c) for c in cands)}). "
                          "Pass blender_exe or set TIMELINES_BLENDER.")


def output_paths(spec: Scene3DSpec, out_dir: Path) -> dict[str, Path]:
    base = f"{spec.scene_id}_{spec.quality}"
    return {
        "spec": out_dir / f"{base}.spec.json",
        "frames": out_dir / f"{base}_frames",
        "blend": out_dir / f"{base}.blend",
        "video": out_dir / f"{base}.mp4",
        "thumb": out_dir / f"{base}_thumb.jpg",
        "log": out_dir / f"{base}.log",
        "result": out_dir / f"{base}.result.json",
    }


def build_blender_command(blender: Path | str, spec_json: Path | str, out_dir: Path | str,
                          script: Path | str = ENTRY_SCRIPT, extra: list[str] | None = None) -> list[str]:
    """Headless Blender invocation used for every scene render."""
    cmd = [str(blender), "-b", "--factory-startup", "--python-exit-code", "1", "--python", str(script),
           "--", "--spec", str(spec_json), "--out", str(out_dir)]
    if extra:
        cmd.extend(extra)
    return cmd


def build_ffmpeg_command(frames_dir: Path, fps: int, video: Path, crf: int = 18) -> list[str]:
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-start_number", "1",
            "-i", str(frames_dir / "f_%04d.jpg"), "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-r", str(fps),
            "-movflags", "+faststart", str(video)]


def probe_video(video: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=nb_read_packets,width,height,r_frame_rate,codec_name,pix_fmt", "-of", "json",
                        str(video)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RenderFailed(f"ffprobe failed on {video}", r.stderr[-2000:])
    st = json.loads(r.stdout)["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    return {"frames": int(st["nb_read_packets"]), "width": int(st["width"]), "height": int(st["height"]),
            "fps": float(num) / float(den), "codec": st.get("codec_name"), "pix_fmt": st.get("pix_fmt")}


@contextmanager
def gpu_lock_ctx(label: str, enabled: bool = True):
    """Serialise GPU work through the shared gpu_lock (one GPU job at a time).

    If the shared lock folder is unavailable (gpu_lock raises FileNotFoundError when
    its drive/folder is missing) a fallback lock inside timelines_studio/data is used
    and a warning is printed, so renders still never overlap each other.
    """
    if not enabled:
        yield "disabled"
        return
    cm = None
    mode = "shared"
    try:
        if GPU_LOCK_DIR not in sys.path:
            sys.path.insert(0, GPU_LOCK_DIR)
        from gpu_lock import gpu_slot  # type: ignore
        try:
            from ...gpu import clear_dead_timelines_lock
            clear_dead_timelines_lock()
        except ImportError:
            pass
        cm = gpu_slot(label)
        cm.__enter__()
    except (FileNotFoundError, ImportError, OSError) as exc:
        print(f"[blender3d] WARNING shared GPU lock unavailable ({exc}); using fallback lock {FALLBACK_LOCK}",
              file=sys.stderr)
        cm = _fallback_slot(label)
        cm.__enter__()
        mode = "fallback"
    try:
        yield mode
    finally:
        cm.__exit__(None, None, None)


@contextmanager
def _fallback_slot(label: str, poll: float = 5.0, stale_s: float = 3 * 3600):
    FALLBACK_LOCK.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(FALLBACK_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{label}|{os.getpid()}|{time.time():.0f}".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - FALLBACK_LOCK.stat().st_mtime > stale_s:
                    FALLBACK_LOCK.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            time.sleep(poll)
    try:
        yield
    finally:
        FALLBACK_LOCK.unlink(missing_ok=True)


# --------------------------------------------------------------------------- main API
_FRAME_RE = re.compile(r"TL_FRAME (\d+) (\d+) ([\d.]+)")
_STAGE_RE = re.compile(r"TL_STAGE ([\d.]+) (.*)")
_BFRA_RE = re.compile(r"^Fra:(\d+)")


def render_scene(spec: Scene3DSpec, out_dir: Path, *, blender_exe: Path | None = None, use_gpu_lock: bool = True,
                 progress: Optional[ProgressFn] = None) -> dict:
    """Render a Scene3DSpec to MP4 (+ .blend, thumbnail). See module docstring."""
    if spec.kind not in SUPPORTED_KINDS:
        raise ValueError(f"Scene3DSpec.kind={spec.kind!r} is not supported by the procedural engine "
                         f"(supported: {SUPPORTED_KINDS})")
    blender = find_blender(blender_exe)
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    P = output_paths(spec, out_dir)
    n = frame_count(spec.duration_s, spec.fps)

    def report(f: float, msg: str):
        if progress:
            try:
                progress(max(0.0, min(1.0, f)), msg)
            except Exception:
                pass

    payload = spec.model_dump()
    payload["frame_count"] = n
    payload["_paths"] = {k: str(v) for k, v in P.items()}
    P["spec"].write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if P["frames"].exists():
        shutil.rmtree(P["frames"])
    P["frames"].mkdir(parents=True)
    for k in ("video", "thumb", "result"):
        P[k].unlink(missing_ok=True)

    cmd = build_blender_command(blender, P["spec"], out_dir)
    report(0.0, "waiting for GPU slot" if use_gpu_lock else "starting Blender")
    tail: deque[str] = deque(maxlen=60)
    frame_times: list[float] = []
    t_lock = time.time()
    with gpu_lock_ctx(f"timelines blender {spec.scene_id}", use_gpu_lock) as lock_mode:
        lock_wait = time.time() - t_lock
        t0 = time.time()
        with open(P["log"], "w", encoding="utf-8", errors="replace") as logf:
            logf.write("CMD " + " ".join(cmd) + "\n")
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", cwd=str(SCRIPTS_DIR))
            assert proc.stdout is not None
            for line in proc.stdout:
                logf.write(line)
                line = line.rstrip()
                tail.append(line)
                m = _FRAME_RE.search(line)
                if m:
                    i, tot, dt = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    frame_times.append(dt)
                    report(0.15 + 0.8 * i / max(tot, 1), f"rendered frame {i}/{tot}")
                    continue
                m = _STAGE_RE.search(line)
                if m:
                    report(0.15 * float(m.group(1)), m.group(2))
            rc = proc.wait()
        render_s = time.time() - t0
    if rc != 0:
        raise RenderFailed(f"Blender exited with code {rc} for {spec.scene_id}", "\n".join(tail), str(P["log"]))
    frames = sorted(P["frames"].glob("f_*.jpg"))
    if len(frames) != n:
        raise RenderFailed(f"expected {n} frames, Blender wrote {len(frames)}", "\n".join(tail), str(P["log"]))

    report(0.96, "encoding MP4")
    r = subprocess.run(build_ffmpeg_command(P["frames"], spec.fps, P["video"]), capture_output=True, text=True)
    if r.returncode != 0 or not P["video"].exists():
        raise RenderFailed("ffmpeg encode failed", r.stderr[-3000:], str(P["log"]))
    info = probe_video(P["video"])
    if info["frames"] != n:
        raise RenderFailed(f"MP4 has {info['frames']} frames, expected {n}", "", str(P["log"]))
    mid = frames[(n - 1) // 2]
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(mid), "-vf",
                        "scale='min(960,iw)':-2", "-q:v", "3", str(P["thumb"])], capture_output=True, text=True)
    if r.returncode != 0:
        shutil.copyfile(mid, P["thumb"])
    # the MP4 is verified -> remove only the frame folder this call created
    shutil.rmtree(P["frames"], ignore_errors=True)

    result = {}
    if P["result"].exists():
        result = json.loads(P["result"].read_text(encoding="utf-8"))
    out = {
        "video": str(P["video"]),
        "blend": str(P["blend"]),
        "thumb": str(P["thumb"]),
        "frames": n,
        "fps": spec.fps,
        "width": info["width"],
        "height": info["height"],
        "render_s": round(render_s, 2),
        "engine": result.get("engine", "BLENDER_EEVEE"),
        "quality": spec.quality,
        "assets_used": result.get("assets_used", []),
        "bpy_script": str(ENTRY_SCRIPT),
        "log": str(P["log"]),
        # extra diagnostics
        "per_frame_s": round(sum(frame_times) / len(frame_times), 3) if frame_times else None,
        "build_s": result.get("build_s"),
        "polygons": result.get("polygons"),
        "lock_wait_s": round(lock_wait, 1),
        "gpu_lock": lock_mode,
        "spec_json": str(P["spec"]),
    }
    report(1.0, "done")
    return out
