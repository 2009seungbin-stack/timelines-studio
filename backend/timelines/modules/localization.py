"""Localization (Phase 3): translated narration, per-language TTS, retimed storyboard and subtitles.

Flow for one language: translate the English Script narration with an agent (JSON-schema reply,
validated scene by scene) -> save edit/artifacts/script_<lang>.json -> TTS every segment into
edit/audio/<lang>/ -> retime a COPY of the storyboard to the new take lengths (same algorithm as the
pipeline's tts timing pass) -> save edit/artifacts/storyboard_<lang>.json -> write
edit/audio/<lang>/subtitles_<lang>.srt from the provider's word boundaries.

The English artifacts (script.json, storyboard.json, edit/audio/en/) are never written here, and no
video is rendered. Translation and TTS are machine output: a human (or agent) cultural review with
`cultural_review_prompt(lang)` is still required before publication.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from .. import agents
from ..schemas import Script, Storyboard

LANGS: dict[str, dict] = {
    "ko": {"name": "Korean", "native": "한국어", "voice": "ko-KR-InJoonNeural", "max_chars": 20, "spaced": True},
    "ja": {"name": "Japanese", "native": "日本語", "voice": "ja-JP-KeitaNeural", "max_chars": 20, "spaced": False},
    "es": {"name": "Spanish", "native": "Español", "voice": "es-ES-AlvaroNeural", "max_chars": 42, "spaced": True},
}

TRANSLATION_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["segments"],
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scene_id", "narration"],
                "properties": {"scene_id": {"type": "string"}, "narration": {"type": "string"}},
            },
        }
    },
}

SYSTEM_TRANSLATOR = (
    "You translate narration for TIMELINES, a history / alternate-history documentary channel. Each segment "
    "is classified FACT (established by sources), INTERPRETATION (scholars disagree) or SPECULATION "
    "(alternate-history premise). The translation must keep that distinction audible. Never add facts, "
    "numbers, names, dates or sources that are not in the English text.")


def _lang(lang: str) -> dict:
    if lang not in LANGS:
        raise ValueError(f"unsupported language {lang!r}; expected one of {sorted(LANGS)}")
    return LANGS[lang]


# ------------------------------------------------------------------ translation
def _translation_prompt(script: Script, lang: str, glossary: dict[str, str] | None) -> str:
    info = _lang(lang)
    items = [{"scene_id": s.scene_id, "classification": s.classification, "narration": s.narration}
             for s in script.segments]
    rules = [
        f"Translate the narration of every segment below from English into {info['name']} ({info['native']}).",
        "Translate the narration field only. Return one item per input segment, in the same scene_id order, "
        "with scene_id copied exactly.",
        "Keep years, dates, numbers and proper names consistent across all segments (use one rendering of each "
        "name throughout, the standard one for this language).",
        "Keep the hedging explicit: INTERPRETATION segments must still say that scholars interpret or disagree; "
        "SPECULATION segments must still say it is a supposition / hypothetical scenario (for example English "
        "'suppose', 'in this scenario', 'imagine'). Never turn speculation or interpretation into a plain "
        "statement of fact, and never add hedging to a FACT segment that has none.",
        f"Use a natural spoken documentary register for {info['name']}: sentences a narrator reads aloud, not "
        "literal word-for-word English structure, and a length close to the original.",
        "Add no facts, explanations, numbers or names that are not in the English text; drop nothing.",
    ]
    if glossary:
        rules.append("Use exactly these renderings (glossary): "
                     + json.dumps(glossary, ensure_ascii=False))
    return ("\n".join(f"- {r}" for r in rules)
            + f"\n\nTITLE: {script.title}\nSEGMENTS:\n" + json.dumps(items, ensure_ascii=False, indent=1))


def _validate_reply(script: Script, data) -> dict[str, str]:
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        raise ValueError("translation reply is not an object with a 'segments' list")
    expected = [s.scene_id for s in script.segments]
    out: dict[str, str] = {}
    unknown, dupes, empty = [], [], []
    for item in data["segments"]:
        if not isinstance(item, dict):
            raise ValueError(f"translation item is not an object: {item!r}")
        sid, text = item.get("scene_id"), item.get("narration")
        if sid not in expected:
            unknown.append(sid)
            continue
        if sid in out:
            dupes.append(sid)
            continue
        if not isinstance(text, str) or not text.strip():
            empty.append(sid)
            continue
        out[sid] = text.strip()
    missing = [sid for sid in expected if sid not in out and sid not in empty]
    problems = [f"{label}: {ids}" for label, ids in
                (("missing", missing), ("duplicated", dupes), ("unknown", unknown), ("empty", empty)) if ids]
    if problems:
        raise ValueError("translation reply invalid - " + "; ".join(problems))
    return out


def translate_script(script: Script, lang: str, *, backend: str | None = None, project_id: str | None = None,
                     glossary: dict[str, str] | None = None) -> Script:
    """Translate narration only. Every scene_id must come back exactly once with non-empty text
    (ValueError otherwise). Returns a new Script with language=lang; all other fields are copied."""
    _lang(lang)
    if script.language == lang:
        raise ValueError(f"script is already in {lang}")
    req = agents.AgentRequest(prompt=_translation_prompt(script, lang, glossary), task=f"translate_{lang}",
                              project_id=project_id, json_schema=TRANSLATION_SCHEMA, system=SYSTEM_TRANSLATOR,
                              write_access=False, timeout_s=1800)
    res = agents.run(req, backend)
    data = res.structured
    if data is None and res.text:
        data = agents._parse_json(res.text)
    texts = _validate_reply(script, data)
    payload = script.model_dump()
    payload["language"] = lang
    for seg in payload["segments"]:
        seg["narration"] = texts[seg["scene_id"]]
    return Script.model_validate(payload)


def cultural_review_prompt(lang: str) -> str:
    """Checklist for the human/agent reviewer of a translated script and its subtitles."""
    info = _lang(lang)
    extra = {
        "ko": "Korean: 존댓말 narration register (합니다/입니다체) used consistently; foreign names in standard "
              "외래어 표기법 (e.g. 로마, 콘스탄티노폴리스); era terms 기원전/서기 used correctly.",
        "ja": "Japanese: です・ます or documentary だ・である register used consistently (not mixed); katakana "
              "renderings of Latin/Greek names follow common usage; 紀元前/西暦 used correctly.",
        "es": "Spanish: peninsular Spanish (es-ES voice) vocabulary; Hispanicised historical names where standard "
              "(Constantinopla, Odoacro, Rómulo Augústulo); a. C. / d. C. era notation.",
    }[lang]
    return "\n".join([
        f"Cultural review checklist - {info['name']} ({lang})",
        "1. Names: every person, people, place and empire uses one standard rendering for this language, "
        "consistently across narration, subtitles and on-screen text; no untranslated English left over.",
        "2. Honorifics / register: titles (emperor, king, pope) and the narrator's politeness level are natural "
        "and consistent for this audience.",
        "3. Dates and numbers: years, centuries, BCE/CE notation, ordinal and number formats follow local "
        "conventions; no year or number changed in translation.",
        "4. Hedging: INTERPRETATION and SPECULATION segments still sound hedged ('suppose', 'in this scenario'); "
        "no speculation reads as fact.",
        "5. Sensitive terms: ethnic/religious group names, 'barbarian', conquest/colonial vocabulary and "
        "modern-border references are neutral and not offensive in this language and region.",
        "6. Fidelity: nothing added or dropped compared with the English; numbers and names match the sources.",
        "7. Listening: the TTS pronounces names and numbers correctly (play every take; machine checks are not "
        "listening).",
        extra,
    ])


# ------------------------------------------------------------------ timing
def retime_storyboard(storyboard: Storyboard, durations: dict[str, float], pad_before: float,
                      pad_after: float) -> Storyboard:
    """Pure version of pipeline.stage_tts's timing pass on a deep copy.
    scene length = max(min_duration_s, narration + pads, 3.0); starts are contiguous; spec duration_s =
    length + the next scene's transition handle (none if the next transition is a cut)."""
    sb = storyboard.model_copy(deep=True)
    scenes = sb.scenes
    t = 0.0
    for i, scene in enumerate(scenes):
        narr = durations.get(scene.scene_id)
        min_len = float(scene.spec.get("min_duration_s", 0) or 0)
        length = max(min_len, (narr if narr is not None else 0) + pad_before + pad_after, 3.0)
        scene.start_s, scene.end_s = round(t, 3), round(t + length, 3)
        nxt = scenes[i + 1] if i + 1 < len(scenes) else None
        handle = nxt.transition.duration_s if nxt is not None and nxt.transition.type != "cut" else 0
        scene.spec["duration_s"] = round(length + handle, 3)
        if min_len:
            scene.spec["min_duration_s"] = min_len
        else:
            scene.spec.pop("min_duration_s", None)
        t += length
    return sb


# ------------------------------------------------------------------ subtitles
_CJK = r"　-ヿ㐀-䶿一-鿿＀-￯"


def _unspace(text: str) -> str:
    """cues_from_words joins words with spaces; Japanese is written without them."""
    return re.sub(rf"(?<=[{_CJK}]) +(?=[{_CJK}])", "", text)


# ------------------------------------------------------------------ end to end
def localize(project_id: str, folder, lang: str, *, backend: str | None = None,
             progress: Callable[[float, str], None] | None = None, voice: str | None = None,
             provider: str = "import", rate: str = "+0%", glossary: dict[str, str] | None = None,
             retranslate: bool = False) -> dict:
    """translate -> script_<lang>.json -> TTS into edit/audio/<lang>/ -> storyboard_<lang>.json ->
    subtitles_<lang>.srt. No video render; English artifacts are left untouched."""
    from . import audio
    from ..pipeline import PAD_AFTER, PAD_BEFORE

    info = _lang(lang)
    voice = voice or info["voice"]
    report = progress or (lambda frac, msg: None)
    script = folder.load_model("script")
    storyboard = folder.load_model("storyboard")
    if script is None or storyboard is None:
        raise FileNotFoundError("localization needs the saved script and storyboard artifacts")
    if lang == script.language:
        raise ValueError(f"the source script is already {lang}; nothing to localize")

    art_dir = Path(folder.root) / "edit" / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    script_path = art_dir / f"script_{lang}.json"
    src_hash = hashlib.sha256("|".join(s.narration for s in script.segments).encode()).hexdigest()[:16]
    hash_path = art_dir / f"script_{lang}.source_hash"
    if (not retranslate and script_path.exists() and hash_path.exists()
            and hash_path.read_text().strip() == src_hash):
        # Reuse the saved translation (import workflow: narration is voiced in the ElevenLabs web app
        # between runs, so the text must not change underneath the recorded takes).
        translated = Script.model_validate_json(script_path.read_text("utf-8"))
    else:
        report(0.0, f"translating to {info['name']}")
        translated = translate_script(script, lang, backend=backend, project_id=project_id, glossary=glossary)
        script_path.write_text(json.dumps(translated.model_dump(mode="json"), ensure_ascii=False, indent=2), "utf-8")
        hash_path.write_text(src_hash)

    out = Path(folder.root) / "edit" / "audio" / lang
    out.mkdir(parents=True, exist_ok=True)
    takes: dict[str, dict] = {}
    n = len(translated.segments)
    for i, seg in enumerate(translated.segments):
        report(0.1 + 0.8 * i / max(1, n), f"TTS {lang} {seg.scene_id}")
        key = hashlib.sha256(f"{provider}|{voice}|{rate}|{seg.narration}".encode()).hexdigest()[:16]
        meta = out / f"narr_{seg.scene_id}.json"
        if meta.exists():
            cached = json.loads(meta.read_text("utf-8"))
            if cached.get("key") == key and Path(cached.get("file", "")).exists():
                takes[seg.scene_id] = cached
                continue
        rec = audio.synth_segment(seg.narration, voice, out, f"narr_{seg.scene_id}", provider, rate)
        rec["key"] = key
        meta.write_text(json.dumps(rec, ensure_ascii=False, indent=2), "utf-8")
        takes[seg.scene_id] = rec

    report(0.9, "retiming storyboard")
    sb = retime_storyboard(storyboard, {sid: t["duration_s"] for sid, t in takes.items()}, PAD_BEFORE, PAD_AFTER)
    sb_path = art_dir / f"storyboard_{lang}.json"
    sb_path.write_text(json.dumps(sb.model_dump(mode="json"), ensure_ascii=False, indent=2), "utf-8")

    cues = []
    for scene in sb.scenes:
        take = takes.get(scene.scene_id)
        if take:
            cues += audio.cues_from_words(take["words"], scene.start_s + PAD_BEFORE, max_chars=info["max_chars"])
    if not info["spaced"]:
        for c in cues:
            c["text"] = _unspace(c["text"])
    srt = out / f"subtitles_{lang}.srt"
    audio.write_srt(cues, srt)

    duration = sb.scenes[-1].end_s if sb.scenes else 0.0
    report(1.0, f"{lang} narration ready")
    return {"lang": lang, "segments": len(translated.segments), "duration_s": round(duration, 2), "voice": voice,
            "provider": provider, "script": str(script_path), "storyboard": str(sb_path), "srt": str(srt),
            "subtitle_cues": len(cues), "review_checklist": cultural_review_prompt(lang)}
