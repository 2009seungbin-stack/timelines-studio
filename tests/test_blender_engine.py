"""Tests for the Blender 3D production engine (timelines.modules.blender3d)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from timelines.schemas import Scene3DSpec  # noqa: E402
from timelines.modules.blender3d import engine as E  # noqa: E402


def _spec(**kw):
    base = dict(scene_id="T01", kind="roman_city", duration_s=8, fps=30, width=1920, height=1080, seed=7,
                era_label="c. 476 CE", classification="INTERPRETATION", camera="crane_down", lighting="dusk",
                params={"era": "late_antique_476"})
    base.update(kw)
    return Scene3DSpec(**base)


# ---------------------------------------------------------------- frame math
@pytest.mark.parametrize("dur,fps,expected", [(8, 30, 240), (12, 30, 360), (0.5, 30, 15), (1.0, 24, 24),
                                              (2.5, 25, 63), (0.01, 30, 1), (3.3333, 30, 100)])
def test_frame_count(dur, fps, expected):
    assert E.frame_count(dur, fps) == expected


def test_frame_count_rejects_non_positive():
    with pytest.raises(ValueError):
        E.frame_count(0, 30)


# ---------------------------------------------------------------- argument building
def test_blender_command(tmp_path):
    cmd = E.build_blender_command("blender.exe", tmp_path / "s.json", tmp_path)
    assert cmd[0] == "blender.exe"
    assert "-b" in cmd and "--factory-startup" in cmd
    assert cmd[cmd.index("--python") + 1] == str(E.ENTRY_SCRIPT)
    tail = cmd[cmd.index("--") + 1:]
    assert tail[:4] == ["--spec", str(tmp_path / "s.json"), "--out", str(tmp_path)]
    assert E.ENTRY_SCRIPT.exists()


def test_output_paths_and_quality(tmp_path):
    p = E.output_paths(_spec(quality="final"), tmp_path)
    assert p["video"].name == "T01_final.mp4"
    assert p["blend"].suffix == ".blend"
    assert p["frames"].parent == tmp_path


def test_ffmpeg_command(tmp_path):
    cmd = E.build_ffmpeg_command(tmp_path, 30, tmp_path / "o.mp4")
    assert "libx264" in cmd and "yuv420p" in cmd and cmd[cmd.index("-crf") + 1] == "18"
    assert cmd[cmd.index("-framerate") + 1] == "30"


def test_unsupported_kind(tmp_path):
    with pytest.raises(ValueError):
        E.render_scene(_spec(kind="custom"), tmp_path)


def test_blender_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "DEFAULT_BLENDER", tmp_path / "nope.exe")
    monkeypatch.delenv("TIMELINES_BLENDER", raising=False)
    monkeypatch.setattr(E.shutil, "which", lambda name: None)
    with pytest.raises(E.BlenderNotFound):
        E.find_blender(tmp_path / "missing.exe")


# ---------------------------------------------------------------- real render (tiny)
def _blender_available():
    try:
        E.find_blender()
        return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    except E.BlenderNotFound:
        return False


@pytest.mark.skipif(not _blender_available(), reason="Blender/FFmpeg not installed")
def test_tiny_real_render():
    tmp_path = ROOT / "data" / "dev_renders" / "_pytest_tiny"   # stay inside timelines_studio
    shutil.rmtree(tmp_path, ignore_errors=True)
    spec = _spec(scene_id="TINY", duration_s=0.5, fps=30, width=320, height=180, quality="preview",
                 camera="orbit", lighting="golden_hour", params={"era": "late_antique_476", "nx": 4, "ny": 4})
    events = []
    res = E.render_scene(spec, tmp_path, progress=lambda f, m: events.append((f, m)))
    assert res["frames"] == 15
    assert Path(res["video"]).exists() and Path(res["blend"]).exists() and Path(res["thumb"]).exists()
    info = E.probe_video(Path(res["video"]))
    assert info["frames"] == 15
    assert (info["width"], info["height"]) == (160, 90)      # preview = half resolution
    assert abs(info["fps"] - 30) < 1e-6
    assert not (tmp_path / "TINY_preview_frames").exists()   # frame folder removed after verification
    assert "roman_temple_corinthian_hexastyle" in res["assets_used"]
    assert events and events[-1][0] == 1.0
    assert any("frame" in m for _, m in events)
    shutil.rmtree(tmp_path, ignore_errors=True)
