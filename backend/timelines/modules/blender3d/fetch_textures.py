"""Download the CC0 Poly Haven textures/HDRIs used by the Blender engine.

    python -m timelines.modules.blender3d.fetch_textures      (from backend/)

Files go to data/textures/<asset>/<asset>_<map>_<res>.jpg (HDRIs: .hdr) and
data/textures/LICENSES.json records {asset, url, license, downloaded_at, files}.
Poly Haven assets are CC0 (https://polyhaven.com/license). Already present files
are not downloaded again.
"""
from __future__ import annotations

import datetime as _dt
import json
import urllib.request
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parents[4]
TEX_DIR = STUDIO_ROOT / "data" / "textures"
UA = {"User-Agent": "timelines-studio-texture-fetch/1.0"}

# asset -> (resolution, maps). Map keys as in the Poly Haven files API.
TEXTURES = {
    "clay_roof_tiles_02": ("2k", ["Diffuse", "Rough", "nor_gl"]),
    "plastered_wall_04": ("1k", ["Diffuse", "Rough", "nor_gl"]),
    "red_brick_plaster_patch_02": ("1k", ["Diffuse", "Rough", "nor_gl"]),
    "medieval_red_brick": ("1k", ["Diffuse", "Rough", "nor_gl"]),
    "large_sandstone_blocks_01": ("1k", ["Diffuse", "Rough", "nor_gl"]),
    "marble_01": ("1k", ["Diffuse", "Rough", "nor_gl"]),
    "cobblestone_large_01": ("1k", ["Diffuse", "Rough", "nor_gl"]),
    "aerial_grass_rock": ("1k", ["Diffuse", "nor_gl"]),
    "aerial_rocks_02": ("1k", ["Diffuse", "nor_gl"]),
    "coast_sand_01": ("1k", ["Diffuse", "nor_gl"]),
    "dirt": ("1k", ["Diffuse", "Rough", "nor_gl"]),
    "weathered_brown_planks": ("1k", ["Diffuse", "Rough", "nor_gl"]),
    "bark_brown_02": ("1k", ["Diffuse", "nor_gl"]),
}
HDRIS = {
    "qwantani_dusk_2_puresky": "2k",
    "kloppenheim_06_puresky": "2k",
}


def _get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def _download(url, dst: Path):
    if dst.exists() and dst.stat().st_size > 0:
        return
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r, open(tmp, "wb") as fh:
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            fh.write(b)
    tmp.replace(dst)


def fetch_all(verbose=True) -> list[dict]:
    TEX_DIR.mkdir(parents=True, exist_ok=True)
    lic_path = TEX_DIR / "LICENSES.json"
    old = {e["asset"]: e for e in json.loads(lic_path.read_text("utf-8"))} if lic_path.exists() else {}
    out = []
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    for asset, (res, maps) in TEXTURES.items():
        files = _get_json(f"https://api.polyhaven.com/files/{asset}")
        d = TEX_DIR / asset
        d.mkdir(exist_ok=True)
        got = []
        for m in maps:
            url = files[m][res]["jpg"]["url"]
            dst = d / f"{asset}_{m.lower()}_{res}.jpg"
            _download(url, dst)
            got.append(dst.name)
        out.append(dict(asset=asset, type="texture", url=f"https://polyhaven.com/a/{asset}", license="CC0",
                        downloaded_at=old.get(asset, {}).get("downloaded_at", now), files=got))
        if verbose:
            print("ok", asset, got)
    for asset, res in HDRIS.items():
        files = _get_json(f"https://api.polyhaven.com/files/{asset}")
        d = TEX_DIR / asset
        d.mkdir(exist_ok=True)
        dst = d / f"{asset}_{res}.hdr"
        _download(files["hdri"][res]["hdr"]["url"], dst)
        out.append(dict(asset=asset, type="hdri", url=f"https://polyhaven.com/a/{asset}", license="CC0",
                        downloaded_at=old.get(asset, {}).get("downloaded_at", now), files=[dst.name]))
        if verbose:
            print("ok", asset)
    lic_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    fetch_all()
