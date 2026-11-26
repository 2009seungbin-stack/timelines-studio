import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from timelines import config
from timelines.schemas import (Claim, ResearchDossier, Scenario, Script, Timeline, TimelineClip, Transition)

SAMPLE = config.ROOT / "samples" / "roman_empire"


def test_fact_needs_source():
    with pytest.raises(ValidationError):
        Claim(id="c1", text="x", classification="FACT")
    Claim(id="s1", text="maybe", classification="SPECULATION")


def test_sample_artifacts_validate():
    d = ResearchDossier.model_validate_json((SAMPLE / "research" / "research_dossier.json").read_text("utf-8"))
    sc = Scenario.model_validate_json((SAMPLE / "scenario.json").read_text("utf-8"))
    s = Script.model_validate_json((SAMPLE / "script.json").read_text("utf-8"))
    ids = {c.id for c in d.claims}
    assert all(c in ids for seg in s.segments for c in seg.claim_ids)
    assert all(b in ids for ev in sc.events for b in ev.basis_claim_ids)


def test_scenario_rejects_uncaused_event_and_unsourced_numbers():
    base = json.loads((SAMPLE / "scenario.json").read_text("utf-8"))
    broken = json.loads(json.dumps(base))
    broken["events"][2]["caused_by"] = []
    with pytest.raises(ValidationError):
        Scenario.model_validate(broken)
    numeric = json.loads(json.dumps(base))
    numeric["events"][1]["description"] = "Grain shipments rise by 40 percent."
    with pytest.raises(ValidationError):
        Scenario.model_validate(numeric)


def test_subtitle_cues_readable():
    from timelines.modules.audio import cues_from_words
    words = [{"text": w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in
             enumerate("In 476, the general Odoacer deposed Romulus Augustulus, the last emperor of Rome's western half. "
                       "Historians call it the end.".split())]
    cues = cues_from_words(words, offset=1.0)
    assert cues[0]["start"] == pytest.approx(1.0)
    assert all(len(line) <= 46 for c in cues for line in c["text"].split("\n"))
    assert all(a["end"] <= b["start"] for a, b in zip(cues, cues[1:]))


def _color_clip(path: Path, color: str, dur: float):
    subprocess.run([config.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x180:r=30:d={dur}", "-pix_fmt", "yuv420p", str(path)], check=True)


def test_compose_crossfade_duration(tmp_path):
    from timelines.modules.editor import compose
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _color_clip(a, "red", 2.5)            # 2.0 s scene + 0.5 s handle
    _color_clip(b, "blue", 2.0)
    wav = tmp_path / "s.wav"
    subprocess.run([config.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo", "-t", "4", str(wav)], check=True)
    tl = Timeline(title="t", language="en", fps=30, width=320, height=180, duration_s=4.0,
                  clips=[TimelineClip(scene_id="A", file=str(a), start_s=0, duration_s=2.5,
                                      transition_in=Transition(type="cut", duration_s=0)),
                         TimelineClip(scene_id="B", file=str(b), start_s=2.0, duration_s=2.0,
                                      transition_in=Transition(type="crossfade", duration_s=0.5))],
                  audio=[], subtitles=[])
    out = tmp_path / "o.mp4"
    compose(tl, wav, out)
    from timelines.modules.audio import ffprobe_duration
    assert abs(ffprobe_duration(out) - 4.0) < 0.1


def test_map_render_small(tmp_path):
    from timelines.modules.maps import render_map
    from timelines.schemas import MapSpec
    spec = MapSpec(scene_id="T", duration_s=0.5, width=320, height=180, classification="FACT",
                   camera=[{"t": 0, "lon": 14, "lat": 40, "zoom": 40}],
                   territories=[{"entity": "r", "label": "Rome", "source": "awmc_117"}],
                   labels=[{"text": "Roma", "lon": 12.49, "lat": 41.89}])
    res = render_map(spec, tmp_path / "m.mp4")
    assert res["frames"] == 15 and Path(res["video"]).stat().st_size > 0


def test_unclear_license_layer_refused():
    from timelines.modules.maps import layer_geometry
    with pytest.raises(PermissionError):
        layer_geometry("oured_500", "{}", None)


def test_api_project_lifecycle():
    from fastapi.testclient import TestClient
    from timelines.api import app
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"]
    p = c.post("/api/projects", json={"title": "Test Rome", "topic": "test", "target_duration_s": 60}).json()
    assert p["state"] == "IDEA" and Path(p["video_dir"]).joinpath("video_retention.json").exists()
    bad = c.put(f"/api/projects/{p['id']}/artifacts/script", json={"title": "x"})
    assert bad.status_code == 422
    ok = c.put(f"/api/projects/{p['id']}/artifacts/script",
               json=json.loads((SAMPLE / "script.json").read_text("utf-8")))
    assert ok.status_code == 200
    stages = {s["stage"]: s["status"] for s in c.get(f"/api/projects/{p['id']}").json()["stages"]}
    assert stages["script"] == "ready"
    assert c.post(f"/api/projects/{p['id']}/state", json={"state": "PUBLISHED"}).status_code == 409
    agents = {a["id"]: a for a in c.get("/api/agents").json()}
    assert {"claude_code", "codex", "anthropic_api", "openai_api", "gemini_api"} <= set(agents)
    assert c.get("/api/settings").json()["keys"].keys() >= {"ANTHROPIC_API_KEY"}


def test_budget_blocks_api_backend(monkeypatch):
    from timelines import agents
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(agents, "project_spent", lambda *a, **k: 10.0)
    monkeypatch.setattr(agents, "project_budget", lambda *a, **k: 5.0)
    with pytest.raises(agents.BudgetExceeded):
        agents.BACKENDS["anthropic_api"].run(agents.AgentRequest(prompt="hi"))
