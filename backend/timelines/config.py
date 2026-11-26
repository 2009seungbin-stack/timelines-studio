"""Paths, environment and external tool discovery. API keys come only from the environment / .env."""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]            # timelines_studio/
WORKSPACE = ROOT.parent                                # ultradedit/
RESEARCH = WORKSPACE / "research"
VERSION = "0.1.0"


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_env()

DATA = Path(os.environ.get("TIMELINES_DATA", ROOT / "data"))
DB_PATH = Path(os.environ.get("TIMELINES_DB", DATA / "timelines.db"))
# Video projects must live below ultradedit/research (VIDEO_STORAGE_POLICY project_roots).
VIDEO_ROOT = Path(os.environ.get("TIMELINES_VIDEO_ROOT", RESEARCH / "timelines_videos"))
ASSET_ROOT = DATA / "assets"
GEO_ROOT = DATA / "geo"
CACHE_ROOT = DATA / "cache"
FONTS = ROOT / "backend" / "timelines" / "fonts"
RETENTION_TOOL = RESEARCH / "video_retention.py"
QC_CLEANUP_TOOL = RESEARCH / "qc_cleanup.py"
GPU_LOCK_DIR = RESEARCH / "portfolio_flagship_20261029"
PORT = int(os.environ.get("TIMELINES_PORT", "8790"))
API_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "YOUTUBE_API_KEY", "ELEVENLABS_API_KEY")

for p in (DATA, ASSET_ROOT, GEO_ROOT, CACHE_ROOT):
    p.mkdir(parents=True, exist_ok=True)


def _which(name: str, *fallbacks: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for f in fallbacks:
        if Path(f).exists():
            return f
    return None


@lru_cache
def blender_exe() -> str | None:
    env = os.environ.get("BLENDER_EXE")
    if env and Path(env).exists():
        return env
    cands = sorted(Path(r"C:\Program Files\Blender Foundation").glob("Blender*/blender.exe"), reverse=True)
    return str(cands[0]) if cands else _which("blender")


def ffmpeg_exe() -> str:
    return _which("ffmpeg") or "ffmpeg"


def ffprobe_exe() -> str:
    return _which("ffprobe") or "ffprobe"


def cli_exe(name: str) -> str | None:
    """claude / codex are npm shims (.cmd on Windows)."""
    for cand in (f"{name}.cmd", name, f"{name}.exe"):
        found = shutil.which(cand)
        if found:
            return found
    return None


def _version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        text = (out.stdout or out.stderr).strip().splitlines()
        return text[0] if text else None
    except Exception:  # noqa: BLE001
        return None


@lru_cache
def tool_report() -> dict:
    tools = {}
    for key, path, cmd in (
        ("blender", blender_exe(), ["--version"]),
        ("ffmpeg", _which("ffmpeg"), ["-version"]),
        ("node", _which("node"), ["--version"]),
        ("claude_cli", cli_exe("claude"), ["--version"]),
        ("codex_cli", cli_exe("codex"), ["--version"]),
    ):
        tools[key] = {"ok": bool(path), "path": path, "version": _version([path, *cmd]) if path else None}
    return tools


def gpu_name() -> str | None:
    smi = _which("nvidia-smi")
    if not smi:
        return None
    return _version([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"])


def disk_free_gb() -> dict[str, float]:
    out = {}
    for letter in ("C", "E"):
        try:
            out[letter] = round(shutil.disk_usage(f"{letter}:/").free / 1e9, 1)
        except OSError:
            pass
    return out


def font(name: str) -> str | None:
    """Resolve a bundled/OS font for graphics. Bundled fonts take precedence."""
    for cand in (FONTS / name, Path(r"C:\Windows\Fonts") / name):
        if cand.exists():
            return str(cand)
    return None
