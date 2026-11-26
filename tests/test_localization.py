"""Localization module tests - no network: agents.run is monkeypatched, no TTS is synthesised."""
import json

import pytest

from timelines import agents, config
from timelines.modules import localization
from timelines.modules.localization import cultural_review_prompt, retime_storyboard, translate_script
from timelines.schemas import Script, Storyboard

SAMPLE = config.ROOT / "samples" / "roman_empire"


def _sample_storyboard(order: list[str]) -> Storyboard:
    data = json.loads((SAMPLE / "storyboard.json").read_text("utf-8"))
    by_id = {s["scene_id"]: s for s in data["scenes"]}
    data["scenes"] = [by_id[sid] for sid in order]
    return Storyboard.model_validate(data)


def _script() -> Script:
    return Script.model_validate(json.loads((SAMPLE / "script.json").read_text("utf-8")))


# ------------------------------------------------------------------ retime_storyboard
def test_retime_crossfade_and_dip_black_handles():
    # S01 (its own cut-in is irrelevant), S02 enters with crossfade 0.8, S07 with dip_black 1.0
    sb = _sample_storyboard(["S01", "S02", "S07"])
    before = sb.model_dump()
    out = retime_storyboard(sb, {"S01": 4.0, "S02": 1.0, "S07": 6.25}, pad_before=0.35, pad_after=0.5)

    lengths = [4.85, 3.0, 7.1]                   # 4.0+0.85 ; max(1.85, 3.0) ; 6.25+0.85
    starts = [0.0, 4.85, 7.85]
    for scene, length, start in zip(out.scenes, lengths, starts):
        assert scene.start_s == pytest.approx(start)
        assert scene.end_s == pytest.approx(start + length)
    assert out.scenes[0].spec["duration_s"] == pytest.approx(4.85 + 0.8)   # next is crossfade 0.8
    assert out.scenes[1].spec["duration_s"] == pytest.approx(3.0 + 1.0)    # next is dip_black 1.0
    assert out.scenes[2].spec["duration_s"] == pytest.approx(7.1)          # last scene: no handle
    assert all("min_duration_s" not in s.spec for s in out.scenes)
    assert sb.model_dump() == before                                       # input untouched (deep copy)
    assert out is not sb and out.scenes[0].spec is not sb.scenes[0].spec


def test_retime_cut_has_no_handle_and_min_duration_wins():
    sb = _sample_storyboard(["S02", "S01", "S03"])   # S01 enters with a cut
    sb.scenes[1].spec["min_duration_s"] = 9.0
    out = retime_storyboard(sb, {"S02": 2.5, "S01": 1.2}, pad_before=0.35, pad_after=0.5)   # S03 has no take

    assert [s.end_s - s.start_s for s in out.scenes] == pytest.approx([3.35, 9.0, 3.0])
    assert [s.start_s for s in out.scenes] == pytest.approx([0.0, 3.35, 12.35])
    assert out.scenes[0].spec["duration_s"] == pytest.approx(3.35)          # next transition is a cut
    assert out.scenes[1].spec["duration_s"] == pytest.approx(9.0 + 0.6)     # S03 crossfade 0.6
    assert out.scenes[1].spec["min_duration_s"] == 9.0
    assert out.scenes[2].spec["duration_s"] == pytest.approx(3.0)


# ------------------------------------------------------------------ translate_script
class _FakeResult:
    def __init__(self, structured):
        self.structured, self.text, self.session_id, self.backend = structured, "", None, "fake"


def _patch_agent(monkeypatch, reply_fn):
    calls = []

    def fake_run(req, backend=None):
        calls.append((req, backend))
        return _FakeResult(reply_fn(req))
    monkeypatch.setattr(agents, "run", fake_run)
    return calls


def test_translate_script_ok(monkeypatch):
    script = _script()
    calls = _patch_agent(monkeypatch, lambda req: {"segments": [
        {"scene_id": s.scene_id, "narration": f"[es] {s.scene_id} narración"} for s in script.segments]})
    out = translate_script(script, "es", backend="claude_code", project_id="prj_x",
                           glossary={"Odoacer": "Odoacro"})

    assert out is not script and out.language == "es" and script.language == "en"
    assert [s.scene_id for s in out.segments] == [s.scene_id for s in script.segments]
    for new, old in zip(out.segments, script.segments):
        assert new.narration == f"[es] {old.scene_id} narración"
        assert new.model_dump(exclude={"narration"}) == old.model_dump(exclude={"narration"})
    assert out.title == script.title and out.target_duration_s == script.target_duration_s
    req, backend = calls[0]
    assert backend == "claude_code" and req.project_id == "prj_x"
    assert req.json_schema["additionalProperties"] is False
    assert req.json_schema["properties"]["segments"]["items"]["additionalProperties"] is False
    assert "Odoacro" in req.prompt and "SPECULATION" in req.prompt and "suppose" in req.prompt


def test_translate_script_missing_scene_raises(monkeypatch):
    script = _script()
    _patch_agent(monkeypatch, lambda req: {"segments": [
        {"scene_id": s.scene_id, "narration": "texto"} for s in script.segments[:-1]]})
    with pytest.raises(ValueError, match="missing"):
        translate_script(script, "es", backend="claude_code", project_id=None, glossary=None)


@pytest.mark.parametrize("mutate, word", [
    (lambda segs: segs + [dict(segs[0])], "duplicated"),
    (lambda segs: [dict(segs[0], narration="  ")] + segs[1:], "empty"),
    (lambda segs: segs + [{"scene_id": "S99", "narration": "x"}], "unknown"),
])
def test_translate_script_other_invalid_replies(monkeypatch, mutate, word):
    script = _script()
    base = [{"scene_id": s.scene_id, "narration": "texto"} for s in script.segments]
    _patch_agent(monkeypatch, lambda req: {"segments": mutate(base)})
    with pytest.raises(ValueError, match=word):
        translate_script(script, "ja", backend="claude_code", project_id=None, glossary=None)


def test_unsupported_language_and_review_prompt():
    with pytest.raises(ValueError):
        translate_script(_script(), "fr", backend="claude_code", project_id=None, glossary=None)
    for lang in localization.LANGS:
        text = cultural_review_prompt(lang)
        assert "Names" in text and "Dates" in text and "Sensitive" in text and "Honorifics" in text
    assert localization.LANGS["ko"]["voice"] == "ko-KR-InJoonNeural"
    assert localization.LANGS["ja"]["voice"] == "ja-JP-KeitaNeural"
    assert localization.LANGS["es"]["voice"] == "es-ES-AlvaroNeural"
