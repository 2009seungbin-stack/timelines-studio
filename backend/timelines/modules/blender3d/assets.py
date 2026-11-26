"""Reusable procedural asset library (host side).

`build_asset_library()` runs Blender once with ``bpy_scripts/build_assets.py``,
which calls the same generator functions the city scenes use, and writes for each
asset ``data/assets/<asset_id>/{asset.blend, preview.jpg, meta.json}``.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from .engine import SCRIPTS_DIR, STUDIO_ROOT, RenderFailed, find_blender, gpu_lock_ctx

ASSET_SCRIPT = SCRIPTS_DIR / "build_assets.py"
ASSETS_DIR = STUDIO_ROOT / "data" / "assets"


def list_assets(assets_dir: Path = ASSETS_DIR) -> list[dict]:
    out = []
    for meta in sorted(Path(assets_dir).glob("*/meta.json")):
        try:
            out.append(json.loads(meta.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def build_asset_library(blender_exe: Optional[Path] = None, *, asset_ids: Optional[Iterable[str]] = None,
                        out_dir: Path = ASSETS_DIR, previews: bool = True, use_gpu_lock: bool = True) -> list[dict]:
    """Build (or rebuild) the asset library and return the list of meta.json dicts."""
    blender = find_blender(blender_exe)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(blender), "-b", "--factory-startup", "--python-exit-code", "1", "--python", str(ASSET_SCRIPT),
           "--", "--out", str(out_dir)]
    ids = list(asset_ids) if asset_ids else []
    if ids:
        cmd += ["--ids", ",".join(ids)]
    if not previews:
        cmd.append("--no-preview")
    log = out_dir / "_build_assets.log"
    with gpu_lock_ctx("timelines blender assets", use_gpu_lock and previews):
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(SCRIPTS_DIR))
    log.write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    if r.returncode != 0 or "TL_DONE" not in r.stdout:
        raise RenderFailed("asset library build failed", "\n".join((r.stdout + r.stderr).splitlines()[-40:]),
                           str(log))
    metas = list_assets(out_dir)
    if ids:
        metas = [m for m in metas if m["asset_id"] in ids]
    return metas
