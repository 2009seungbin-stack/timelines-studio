"""Stage orchestration. Every stage reads saved, schema-validated artifacts and writes new ones, so a
failed stage is retried from its own inputs. Project state follows the stages."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from . import agents, config, db, jobs
from .schemas import (SCHEMAS, GraphicSpec, MapSpec, ResearchDossier, Scenario, Scene3DSpec, Script, Storyboard,
                      SubtitleCue, Timeline, TimelineAudio, TimelineClip)
from .storage import VideoFolder

RENDERER_VERSION = {"map": "maps-0.5", "graphic": "graphics-0.3", "blender": "blender-0.3"}
PAD_BEFORE, PAD_AFTER = 0.15, 0.25


# ------------------------------------------------------------------ projects
def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "video"


def create_project(title: str, topic: str, fmt: str = "alt_history", target_duration_s: float = 90,
                   language: str = "en", budget_usd: float | None = None) -> db.Project:
    pid = db.new_id("prj")
    video_id = f"tl_{slug(title)}_{datetime.now():%Y%m%d}_{pid[-4:]}"
    folder = VideoFolder(config.VIDEO_ROOT / video_id)
    folder.create(video_id)
    proj = db.Project(id=pid, title=title, topic=topic, format=fmt, target_duration_s=target_duration_s,
                      language=language, video_dir=str(folder.root),
                      budget_usd=budget_usd if budget_usd is not None else float(db.get_setting("budget_usd")))
    with db.session() as s:
        s.add(proj)
        s.commit()
    db.log(pid, "user", "project_created", title=title, video_dir=str(folder.root))
    return proj


def get_project(pid: str) -> db.Project:
    with db.session() as s:
        p = s.get(db.Project, pid)
        if p is None:
            raise KeyError(pid)
        return p


def folder_of(pid: str) -> VideoFolder:
    return VideoFolder(get_project(pid).video_dir)


def set_state(pid: str, state: str, actor: str = "system") -> None:
    with db.session() as s:
        p = s.get(db.Project, pid)
        if p.state != state:
            db.log(pid, actor, "state", frm=p.state, to=state)
            p.state = state
            s.commit()


# ------------------------------------------------------------------ agent-backed stages
def _agent(ctx: jobs.JobContext, task: str, prompt: str, schema: dict, system: str, model_cls=None,
           repairs: int = 2) -> dict:
    """Ask the configured agent for a schema-shaped JSON object. If the reply fails validation, the errors
    are sent back into the SAME session (resume) so the agent repairs its own output."""
    backend = ctx.params.get("backend") or db.get_setting("default_backend")
    req = agents.AgentRequest(prompt=prompt, task=task, project_id=ctx.project_id, json_schema=schema,
                              system=system, model=ctx.params.get("model"), write_access=False, timeout_s=3600)
    for attempt in range(repairs + 1):
        res = agents.run(req, backend)
        ctx.metrics["agent_backend"] = backend
        ctx.metrics["agent_session"] = res.session_id
        data = res.structured
        if not isinstance(data, dict):
            err = "Reply was not one JSON object."
        elif model_cls is None:
            return data
        else:
            from pydantic import ValidationError
            try:
                model_cls.model_validate(data)
                ctx.metrics["agent_repairs"] = attempt
                return data
            except ValidationError as exc:
                err = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:20])
        if attempt == repairs or not res.session_id or agents.BACKENDS[backend].kind != "session":
            raise RuntimeError(f"{backend} output failed validation after {attempt + 1} attempt(s): {err}")
        ctx.progress(0.5, f"agent repair {attempt + 1}: {err[:120]}")
        req = agents.AgentRequest(prompt=f"Your JSON failed validation: {err}. Return the corrected full JSON object.",
                                  task=task + "_repair", project_id=ctx.project_id, json_schema=schema,
                                  model=ctx.params.get("model"), session_id=res.session_id, timeout_s=3600)
    raise RuntimeError("unreachable")


SYSTEM_HISTORIAN = (
    "You work for TIMELINES, a history / alternate-history documentary channel. Separate FACT (established "
    "by sources), INTERPRETATION (scholars disagree) and SPECULATION (alternate-history premise). Never invent "
    "sources, URLs, quotes, page numbers or statistics. If a number has no source, leave it out. Never present "
    "speculation as fact. Neutral, non-sensational wording.")


@jobs.handler("research")
def stage_research(ctx: jobs.JobContext) -> dict:
    folder, proj = folder_of(ctx.project_id), get_project(ctx.project_id)
    set_state(ctx.project_id, "RESEARCHING")
    seed = ctx.params.get("dossier_file")
    if seed is not None and not str(seed).strip():
        raise ValueError("dossier_file is empty")
    if seed:                                                  # imported, already-researched dossier
        data = json.loads(Path(seed).read_text("utf-8"))
        shutil.copy2(seed, folder.sub("sources") / "research_dossier_input.json")
        actor = "import"
    else:
        prompt = (f"Research topic: {proj.topic}\nCollect reliable sources (academic, university, museum, "
                  "encyclopedia, archaeology, primary sources) using web search and fetch. Set verified_by_fetch "
                  "true only for pages you actually retrieved. Write short neutral claims with source ids; record "
                  "conflicts between sources; mark uncertain claims needs_review.")
        ctx.progress(0.1, "agent researching")
        data = _agent(ctx, "research", prompt, ResearchDossier.model_json_schema(), SYSTEM_HISTORIAN, ResearchDossier)
        actor = "agent"
    folder.save("research_dossier", data)
    set_state(ctx.project_id, "RESEARCH_REVIEW")
    d = ResearchDossier.model_validate(data)
    db.log(ctx.project_id, actor, "research_saved", sources=len(d.sources), claims=len(d.claims))
    return {"sources": len(d.sources), "claims": len(d.claims), "conflicts": len(d.conflicts),
            "needs_review": sum(c.needs_review for c in d.claims)}


@jobs.handler("scenario")
def stage_scenario(ctx: jobs.JobContext) -> dict:
    folder, proj = folder_of(ctx.project_id), get_project(ctx.project_id)
    seed = ctx.params.get("scenario_file")
    if seed:
        data = json.loads(Path(seed).read_text("utf-8"))
        shutil.copy2(seed, folder.sub("sources") / "scenario_input.json")
    else:
        dossier = folder.load("research_dossier")
        prompt = (f"Build one plausible alternate-history scenario for: {proj.topic}\n"
                  "Use the dossier claims as the factual baseline (basis_claim_ids). Every post-divergence event "
                  "must name its causes (caused_by) and be classified SPECULATION. Map changes reference regions "
                  "by id. Do not invent numbers.\nDOSSIER:\n" + json.dumps(dossier, ensure_ascii=False))
        data = _agent(ctx, "scenario", prompt, Scenario.model_json_schema(), SYSTEM_HISTORIAN, Scenario)
    folder.save("scenario", data)
    sc = Scenario.model_validate(data)
    return {"events": len(sc.events)}


@jobs.handler("script")
def stage_script(ctx: jobs.JobContext) -> dict:
    folder, proj = folder_of(ctx.project_id), get_project(ctx.project_id)
    set_state(ctx.project_id, "SCRIPTING")
    if folder.load("research_dossier") is None:
        raise FileNotFoundError("run the research stage first (script claims must cite the dossier)")
    if proj.format == "alt_history" and folder.load("scenario") is None:
        raise FileNotFoundError("alternate-history projects need a validated scenario before the script")
    seed = ctx.params.get("script_file")
    if seed:
        data = json.loads(Path(seed).read_text("utf-8"))
        shutil.copy2(seed, folder.sub("sources") / "script_input.json")
    else:
        prompt = (f"Write the narration script for a {proj.target_duration_s:.0f}-second video: {proj.title}.\n"
                  "Structure: hook (strong question + visual), background, real history, divergence, impact, "
                  "outcome, limits, conclusion - scaled to the length (about 150 words per minute). One scene per "
                  "segment. Factual segments cite claim_ids from the dossier; speculative segments are classified "
                  "SPECULATION and say so in the narration. scene_type from: MAP, 3D_RECONSTRUCTION, TIMELINE, "
                  "TEXT_GRAPHIC, COMPARISON.\nDOSSIER:\n" + json.dumps(folder.load("research_dossier"), ensure_ascii=False)
                  + "\nSCENARIO:\n" + json.dumps(folder.load("scenario"), ensure_ascii=False))
        data = _agent(ctx, "script", prompt, Script.model_json_schema(), SYSTEM_HISTORIAN, Script)
    script = Script.model_validate(data)
    dossier = folder.load_model("research_dossier")
    known = {c.id for c in dossier.claims} if dossier else set()
    unknown = [(s.scene_id, c) for s in script.segments for c in s.claim_ids if c not in known]
    if unknown:
        raise ValueError(f"script cites unknown claims: {unknown}")
    folder.save("script", script)
    set_state(ctx.project_id, "SCRIPT_REVIEW")
    est = sum(s.est_duration_s for s in script.segments)
    return {"segments": len(script.segments), "estimated_s": round(est, 1), "target_s": proj.target_duration_s}


@jobs.handler("storyboard")
def stage_storyboard(ctx: jobs.JobContext) -> dict:
    folder = folder_of(ctx.project_id)
    set_state(ctx.project_id, "STORYBOARD")
    seed = ctx.params.get("storyboard_file")
    if seed:
        data = json.loads(Path(seed).read_text("utf-8"))
        shutil.copy2(seed, folder.sub("sources") / "storyboard_input.json")
    else:
        from .modules.maps import registry
        layers = [{k: v for k, v in layer.items() if k in ("id", "period", "commercial_use", "feature_properties")}
                  for layer in registry().values() if layer.get("kind") == "historical"]
        prompt = ("Turn this script into a storyboard. renderer 'map' scenes carry a MapSpec in spec, 'blender' "
                  "scenes a Scene3DSpec (kind roman_city with params.era late_antique_476 or alt_1000), 'graphic' "
                  "scenes a GraphicSpec. Use only geo layers with commercial_use 'yes'. Speculative territories use "
                  "certainty 'hypothetical'. Durations are placeholders; narration timing fixes them later.\n"
                  "GEO LAYERS:\n" + json.dumps(layers) + "\nSCRIPT:\n" + json.dumps(folder.load("script")))
        data = _agent(ctx, "storyboard", prompt, Storyboard.model_json_schema(), SYSTEM_HISTORIAN, Storyboard)
    sb = Storyboard.model_validate(data)
    for scene in sb.scenes:                                   # validate render specs up front
        _spec_model(scene.renderer).model_validate(_spec_for_render(scene))
    folder.save("storyboard", sb)
    return {"scenes": len(sb.scenes)}


def _spec_model(renderer: str):
    return {"map": MapSpec, "blender": Scene3DSpec, "graphic": GraphicSpec}[renderer]


# ------------------------------------------------------------------ narration + timing
@jobs.handler("tts")
def stage_tts(ctx: jobs.JobContext) -> dict:
    from .modules import audio
    folder, proj = folder_of(ctx.project_id), get_project(ctx.project_id)
    script = folder.load_model("script")
    sb = folder.load_model("storyboard")
    settings = db.settings()
    provider = ctx.params.get("provider") or settings["tts_provider"]
    if provider == "elevenlabs":
        voice = ctx.params.get("voice") or (settings["elevenlabs"].get("voice_id") or {}).get(script.language)
        if not voice:
            raise ValueError("choose an ElevenLabs voice_id for this language in Settings (GET /api/tts/voices)")
    else:
        voice = ctx.params.get("voice") or settings["tts_voice"].get(script.language, "en-US-AndrewNeural")
    rate = ctx.params.get("rate", "+0%")
    out = folder.sub("edit", "audio", script.language)
    takes = {}
    for i, seg in enumerate(script.segments):
        ctx.progress(i / len(script.segments), f"TTS {seg.scene_id}")
        key = hashlib.sha256(f"{provider}|{voice}|{rate}|{seg.narration}".encode()).hexdigest()[:16]
        meta = out / f"narr_{seg.scene_id}.json"
        if meta.exists() and json.loads(meta.read_text("utf-8")).get("key") == key:
            takes[seg.scene_id] = json.loads(meta.read_text("utf-8"))
            continue
        rec = audio.synth_segment(seg.narration, voice, out, f"narr_{seg.scene_id}", provider, rate)
        rec["key"] = key
        meta.write_text(json.dumps(rec, ensure_ascii=False, indent=2), "utf-8")
        takes[seg.scene_id] = rec
    # timing pass: each scene = pad + narration + pad (or its minimum visual length)
    t = 0.0
    scenes = sb.scenes
    for i, scene in enumerate(scenes):
        take = takes.get(scene.scene_id)
        min_len = float(scene.spec.get("min_duration_s", 0) or 0)
        length = max(min_len, (take["duration_s"] if take else 0) + PAD_BEFORE + PAD_AFTER, 3.0)
        scene.start_s, scene.end_s = round(t, 3), round(t + length, 3)
        handle = scenes[i + 1].transition.duration_s if i + 1 < len(scenes) and scenes[i + 1].transition.type != "cut" else 0
        scene.spec["duration_s"] = round(length + handle, 3)
        scene.spec.pop("min_duration_s", None) if not min_len else None
        if min_len:
            scene.spec["min_duration_s"] = min_len
        t += length
    folder.save("storyboard", sb, mark_stale=True)
    total = sum(s.end_s - s.start_s for s in scenes)
    return {"takes": len(takes), "voice": voice, "provider": provider, "duration_s": round(total, 2),
            "target_s": proj.target_duration_s}


# ------------------------------------------------------------------ rendering
def _spec_for_render(scene) -> dict:
    spec = dict(scene.spec)
    spec.pop("min_duration_s", None)
    spec["scene_id"] = scene.scene_id
    spec["classification"] = scene.classification
    return spec


def _render_cpu(renderer: str, spec: dict, out: str, preview: bool) -> dict:
    """Top-level so ProcessPoolExecutor can pickle it on Windows."""
    if renderer == "map":
        from .modules.maps import render_map
        return render_map(MapSpec.model_validate(spec), Path(out), preview=preview)
    from .modules.graphics import render_graphic
    return render_graphic(GraphicSpec.model_validate(spec), Path(out), preview=preview)


def _render_blender(spec: dict, out_dir: Path, preview: bool, use_lock: bool, ctx=None) -> dict:
    """Blender render + label overlay (classification badge and era are composited, never modelled in 3D)."""
    from .memguard import wait_for_memory
    from .modules.blender3d.engine import render_scene
    from .modules.graphics import apply_overlay, overlay_png
    wait_for_memory(f"blender {spec.get('scene_id')}")
    spec = dict(spec)
    spec["quality"] = "preview" if preview else "final"
    model = Scene3DSpec.model_validate(spec)
    res = render_scene(model, out_dir, use_gpu_lock=use_lock,
                       progress=(lambda v, m: ctx.progress(v, m)) if ctx else None)
    ov = (model.params or {}).get("overlay")
    badge = (ov or {}).get("badge") or {"SPECULATION": "ALTERNATE HISTORY · HYPOTHETICAL RECONSTRUCTION"}.get(
        model.classification, "APPROXIMATE RECONSTRUCTION")
    w, h = int(res.get("width", model.width)), int(res.get("height", model.height))
    png = overlay_png(badge, model.classification, (ov or {}).get("era", model.era_label), w, h,
                      Path(out_dir) / "overlay.png")
    labelled = Path(out_dir) / (Path(res["video"]).stem + "_labelled.mp4")
    apply_overlay(Path(res["video"]), png, labelled)
    res["video_raw"], res["video"] = res["video"], str(labelled)
    return res


def _cache_key(renderer: str, spec: dict, preview: bool) -> str:
    blob = json.dumps({"r": RENDERER_VERSION[renderer], "s": spec, "p": preview}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def _outputs(folder: VideoFolder, scene_id: str, preview: bool) -> Path:
    return (folder.sub("work", "previews") if preview else folder.sub("edit", "scenes")) / \
        f"{scene_id}_{'preview' if preview else 'final'}.mp4"


def render_scenes(ctx: jobs.JobContext, preview: bool, only: list[str] | None = None) -> dict:
    folder = folder_of(ctx.project_id)
    sb = folder.load_model("storyboard")
    set_state(ctx.project_id, "ASSET_PRODUCTION" if preview else "RENDERING")
    todo, results, skipped = [], {}, []
    for scene in sb.scenes:
        if only and scene.scene_id not in only:
            continue
        if not preview and scene.render_status not in ("preview_approved", "final"):
            skipped.append(scene.scene_id)                     # final render waits for preview approval
            continue
        spec = _spec_for_render(scene)
        out = _outputs(folder, scene.scene_id, preview)
        key = _cache_key(scene.renderer, spec, preview)
        keyfile = out.with_suffix(".key")
        if out.exists() and keyfile.exists() and keyfile.read_text() == key:
            results[scene.scene_id] = {"video": str(out), "cache_hit": True}
            continue
        todo.append((scene, spec, out, key))
    cpu = [x for x in todo if x[0].renderer != "blender"]
    gpu = [x for x in todo if x[0].renderer == "blender"]
    done = 0
    if cpu:
        # Each 1080p map worker holds a large basemap image + an ffmpeg encoder; this machine has a small
        # page file (C: nearly full), so parallelism is capped (override: TIMELINES_RENDER_WORKERS).
        import os
        workers = int(os.environ.get("TIMELINES_RENDER_WORKERS", "3"))
        with ProcessPoolExecutor(max_workers=max(1, min(workers, len(cpu)))) as pool:
            futs = {pool.submit(_render_cpu, sc.renderer, spec, str(out), preview): (sc, out, key)
                    for sc, spec, out, key in cpu}
            for fut in as_completed(futs):
                sc, out, key = futs[fut]
                results[sc.scene_id] = fut.result()
                out.with_suffix(".key").write_text(key)
                done += 1
                ctx.progress(done / max(1, len(todo)), f"rendered {sc.scene_id}")
    for sc, spec, out, key in gpu:
        ctx.progress(done / max(1, len(todo)), f"Blender {sc.scene_id} ({'preview' if preview else 'final'})")
        res = _render_blender(spec, out.parent / f"{sc.scene_id}_{'preview' if preview else 'final'}_blender",
                              preview, use_lock=True, ctx=None)
        shutil.copy2(res["video"], out)
        if res.get("thumb"):
            shutil.copy2(res["thumb"], out.with_suffix(".jpg"))
        res["video"] = str(out)
        results[sc.scene_id] = res
        out.with_suffix(".key").write_text(key)
        done += 1
        ctx.add_metric("render_s", float(res.get("render_s", 0)))
    # record status
    sb = folder.load_model("storyboard")
    for scene in sb.scenes:
        if scene.scene_id in results:
            if preview and scene.render_status in ("pending", "failed", "preview"):
                scene.render_status = "preview"
            elif not preview:
                scene.render_status = "final"
    folder.save("storyboard", sb, mark_stale=False)
    ctx.add_metric("output_bytes", sum(Path(r["video"]).stat().st_size for r in results.values()))
    (folder.sub("retention_records") / f"render_{'preview' if preview else 'final'}_log.json").write_text(
        json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("video", "frames", "render_s", "cache_hit",
                                                                   "engine", "attribution")}
                    for k, v in results.items()}, indent=2), "utf-8")
    return {"rendered": sorted(results), "skipped_waiting_approval": skipped}


@jobs.handler("previews")
def stage_previews(ctx: jobs.JobContext) -> dict:
    return render_scenes(ctx, preview=True, only=ctx.params.get("scenes"))


@jobs.handler("finals")
def stage_finals(ctx: jobs.JobContext) -> dict:
    return render_scenes(ctx, preview=False, only=ctx.params.get("scenes"))


@jobs.handler("render_scene", gpu=True)
def stage_render_scene(ctx: jobs.JobContext) -> dict:
    """Single-scene (re)render from the UI. Runs in the GPU lane (holds the workspace GPU lock)."""
    folder = folder_of(ctx.project_id)
    sb = folder.load_model("storyboard")
    scene = next(s for s in sb.scenes if s.scene_id == ctx.params["scene_id"])
    preview = ctx.params.get("quality", "preview") == "preview"
    if not preview and scene.render_status not in ("preview_approved", "final"):
        raise PermissionError("final render needs an approved preview")
    spec, out = _spec_for_render(scene), _outputs(folder, scene.scene_id, preview)
    if scene.renderer == "blender":
        res = _render_blender(spec, out.parent / f"{scene.scene_id}_{'preview' if preview else 'final'}_blender",
                              preview, use_lock=False, ctx=ctx)
        shutil.copy2(res["video"], out)
        if res.get("thumb"):
            shutil.copy2(res["thumb"], out.with_suffix(".jpg"))
    else:
        res = _render_cpu(scene.renderer, spec, str(out), preview)
    out.with_suffix(".key").write_text(_cache_key(scene.renderer, spec, preview))
    sb = folder.load_model("storyboard")
    for s in sb.scenes:
        if s.scene_id == scene.scene_id:
            s.render_status = "preview" if preview else "final"
    folder.save("storyboard", sb, mark_stale=False)
    return {"video": str(out)}


def approve_scene(pid: str, scene_id: str, approved: bool, note: str, actor: str) -> dict:
    folder = folder_of(pid)
    sb = folder.load_model("storyboard")
    for s in sb.scenes:
        if s.scene_id == scene_id:
            if not _outputs(folder, scene_id, True).exists():
                raise FileNotFoundError("no preview rendered yet")
            s.render_status = "preview_approved" if approved else "failed"
            folder.save("storyboard", sb, mark_stale=False)
            db.log(pid, actor, "scene_review", scene=scene_id, approved=approved, note=note)
            return json.loads(s.model_dump_json())
    raise KeyError(scene_id)


@jobs.handler("review_previews")
def stage_review_previews(ctx: jobs.JobContext) -> dict:
    """Optional agent review of preview frames (Claude Code session reads the JPG thumbnails and frames).
    Recorded as an agent decision, never as user approval."""
    from .modules import qa as _qa  # noqa: F401  (ensures ffmpeg helpers import cleanly)
    folder = folder_of(ctx.project_id)
    sb = folder.load_model("storyboard")
    tmp = folder.sub("evidence", "qc_tmp")
    decisions = {}
    for scene in sb.scenes:
        if scene.render_status != "preview":
            continue
        prev = _outputs(folder, scene.scene_id, True)
        frames = []
        for k, frac in enumerate((0.15, 0.5, 0.85)):
            f = tmp / f"qc_frame_{scene.scene_id}_{k}.png"
            dur = float(scene.spec.get("duration_s", 5))
            import subprocess
            subprocess.run([config.ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{dur * frac:.2f}", "-i",
                            str(prev), "-frames:v", "1", str(f)], check=True)
            frames.append(str(f))
        schema = {"type": "object", "additionalProperties": False, "required": ["approve", "problems"],
                  "properties": {"approve": {"type": "boolean"}, "problems": {"type": "array", "items": {"type": "string"}}}}
        prompt = (f"You are the visual reviewer of a premium history documentary. Read these preview frames of "
                  f"scene {scene.scene_id} ({scene.scene_type}, {scene.classification}): {frames}. Intended: "
                  f"{scene.narration_segment[:400]} / camera: {scene.camera_movement}. Reject for floating or "
                  "intersecting geometry, plastic materials, flat lighting, unreadable text, wrong labels, "
                  "historically wrong decoration, empty composition. Approve only if a viewer would accept it.")
        res = agents.run(agents.AgentRequest(prompt=prompt, task="preview_review", project_id=ctx.project_id,
                                             json_schema=schema, cwd=str(folder.root)), ctx.params.get("backend", "claude_code"))
        d = res.structured or {}
        decisions[scene.scene_id] = d
        if d.get("approve"):
            approve_scene(ctx.project_id, scene.scene_id, True, "agent review: " + "; ".join(d.get("problems", [])),
                          f"agent:{res.backend}")
        else:
            db.log(ctx.project_id, f"agent:{res.backend}", "scene_review", scene=scene.scene_id, approved=False,
                   problems=d.get("problems"))
    (folder.sub("retention_records") / "preview_review.json").write_text(json.dumps(decisions, indent=2), "utf-8")
    return decisions


# ------------------------------------------------------------------ compose / QA / publish / finalize
def _next_version(folder: VideoFolder) -> int:
    nums = [int(m.group(1)) for p in (folder.root / "final").glob("*.mp4") if (m := re.search(r"_v(\d+)\.mp4$", p.name))]
    return max(nums, default=0) + 1


@jobs.handler("compose")
def stage_compose(ctx: jobs.JobContext) -> dict:
    from .modules import audio, editor
    folder, proj = folder_of(ctx.project_id), get_project(ctx.project_id)
    set_state(ctx.project_id, "EDITING")
    sb = folder.load_model("storyboard")
    script = folder.load_model("script")
    missing = [s.scene_id for s in sb.scenes if not _outputs(folder, s.scene_id, False).exists()]
    if missing:
        raise FileNotFoundError(f"final scene renders missing: {missing}")
    adir = folder.sub("edit", "audio", script.language)
    narration, cues = [], []
    for scene in sb.scenes:
        meta = adir / f"narr_{scene.scene_id}.json"
        if not meta.exists():
            continue
        rec = json.loads(meta.read_text("utf-8"))
        start = scene.start_s + PAD_BEFORE
        narration.append({"scene_id": scene.scene_id, "file": rec["file"], "start_s": start,
                          "duration_s": rec["duration_s"], "text": rec["text"]})
        cues += audio.cues_from_words(rec["words"], start)
    duration = sb.scenes[-1].end_s
    version = _next_version(folder)
    base = f"{folder.root.name}_v{version:02d}"
    mix_wav = folder.sub("edit", "audio") / f"{base}_mix.wav"
    music = ctx.params.get("music")
    audio.mix(narration, duration, mix_wav, Path(music) if music else None)
    srt = folder.sub("edit", "audio") / f"{base}_{script.language}.srt"
    audio.write_srt(cues, srt)
    clips = [TimelineClip(scene_id=s.scene_id, file=str(_outputs(folder, s.scene_id, False)), start_s=s.start_s,
                          duration_s=float(s.spec["duration_s"]), transition_in=s.transition) for s in sb.scenes]
    timeline = Timeline(title=proj.title, language=script.language, fps=sb.fps, width=sb.width, height=sb.height,
                        duration_s=duration, clips=clips,
                        audio=[TimelineAudio(file=n["file"], start_s=n["start_s"], role="narration") for n in narration]
                        + [TimelineAudio(file=str(mix_wav), start_s=0, role="narration")],
                        subtitles=[SubtitleCue(index=i + 1, start_s=c["start"], end_s=c["end"], text=c["text"])
                                   for i, c in enumerate(cues)])
    folder.save("timeline", timeline)
    final = folder.sub("final") / f"{base}.mp4"
    from .memguard import wait_for_memory
    wait_for_memory("final encode", progress=ctx.progress)
    ctx.progress(0.3, "encoding final")
    res = editor.compose(timeline, mix_wav, final)
    xml = editor.write_fcp7_xml(timeline, mix_wav, narration, folder.sub("edit", "premiere") / f"{base}.xml")
    editor.write_timeline_json(timeline, folder.sub("edit") / f"{base}_timeline.json")
    (folder.sub("edit") / f"{base}_narration.json").write_text(json.dumps(narration, ensure_ascii=False, indent=2), "utf-8")
    ctx.add_metric("output_bytes", res["bytes"])
    return {"final": str(final), "srt": str(srt), "wav": str(mix_wav), "xml": xml["file"], "duration_s": duration,
            "version": version}


def _licenses(folder: VideoFolder) -> list[dict]:
    from .modules.maps import registry
    from .modules.audio import PROVIDERS
    sb = folder.load_model("storyboard")
    reg = registry()
    out = [{"item": "fonts: Cinzel, EB Garamond, Inter (SIL OFL 1.1)", "commercial_use": "yes"},
           {"item": "Natural Earth basemap", "commercial_use": "yes", "note": "public domain"}]
    for scene in sb.scenes:
        for terr in scene.spec.get("territories", []):
            layer = reg.get(terr.get("source"), {})
            out.append({"item": f"geo layer {terr.get('source')}", "commercial_use": layer.get("commercial_use", "unknown"),
                        "note": layer.get("license", "")})
        if scene.renderer == "blender":
            out.append({"item": f"3D scene {scene.scene_id}", "commercial_use": "yes",
                        "note": "original procedural geometry (TIMELINES Studio bpy generator)"})
    narr = list((folder.root / "edit" / "audio").rglob("narr_*.json"))
    if narr:
        prov = json.loads(narr[0].read_text("utf-8")).get("provider", "edge")
        plan = str((db.get_setting("elevenlabs") or {}).get("plan") or "")
        status = "unclear" if prov == "edge" else ("yes" if plan.startswith("paid") else "check_plan")
        out.append({"item": f"narration ({'ElevenLabs web app' if prov == 'import' else prov})",
                    "commercial_use": status, "note": PROVIDERS[prov].license_note + (f" Plan: {plan}" if plan else "")})
    uniq = {json.dumps(x, sort_keys=True): x for x in out}
    return list(uniq.values())


@jobs.handler("qa")
def stage_qa(ctx: jobs.JobContext) -> dict:
    from .modules import qa
    folder, proj = folder_of(ctx.project_id), get_project(ctx.project_id)
    set_state(ctx.project_id, "FINAL_REVIEW")
    final = sorted((folder.root / "final").glob("*.mp4"))[-1]
    base = final.stem
    timeline = folder.load_model("timeline")
    narration = json.loads((folder.root / "edit" / f"{base}_narration.json").read_text("utf-8"))
    srt = next((folder.root / "edit" / "audio").glob(f"{base}_*.srt"))
    report = qa.run_qc(proj.id, folder.root, final, timeline, folder.load_model("script"),
                       folder.load_model("storyboard"), folder.load_model("research_dossier"), narration, srt,
                       extra={"licenses": _licenses(folder)})
    folder.save("qc_report", report, mark_stale=False)
    report_path = folder.sub("retention_records") / f"qc_{base}.json"
    report_path.write_text(report.model_dump_json(indent=2), "utf-8")
    cleanup = None
    if report.technical_pass:
        cleanup = qa.cleanup_inspection_frames(folder.root, report_path)
    db.log(proj.id, "system", "qc", technical_pass=report.technical_pass, report=str(report_path))
    return {"technical_pass": report.technical_pass, "report": str(report_path),
            "fails": [c.id for c in report.checks if c.status == "fail"],
            "human_review_required": report.human_review_required, "inspection_cleanup": cleanup}


@jobs.handler("publish_prep")
def stage_publish(ctx: jobs.JobContext) -> dict:
    from .modules.publishing import build_package
    folder = folder_of(ctx.project_id)
    credits = sorted({x["note"] if x["item"].startswith("geo") and x.get("note") else x["item"] for x in _licenses(folder)
                      if not x["item"].startswith("TTS")})
    from .modules.maps import registry
    reg = registry()
    credits = ["Base map: Made with Natural Earth (public domain)",
               "Roman Empire extents: Ancient World Mapping Center (awmc.unc.edu), ODbL 1.0 - derived from the "
               "Barrington Atlas; this video is a Produced Work",
               "Fonts: Cinzel, EB Garamond, Inter (SIL Open Font License)",
               "3D reconstructions: original procedural models (approximate)"]
    if "cities" in reg:
        credits.append("Place coordinates: Pleiades (pleiades.stoa.org), CC BY 3.0")
    pkg = build_package(folder.load_model("script"), folder.load_model("storyboard"),
                        folder.load_model("research_dossier"), credits,
                        title_candidates=ctx.params.get("titles"))
    folder.save("publish_package", pkg, mark_stale=False)
    return {"chapters": len(pkg.chapters), "titles": pkg.title_candidates}


@jobs.handler("finalize")
def stage_finalize(ctx: jobs.JobContext) -> dict:
    """ultradedit retention: seal the selected final + sources + edit project, then maybe_finish
    (removes registered intermediates only after the matching QC passed)."""
    import sys
    sys.path.insert(0, str(config.RESEARCH))
    import video_retention  # type: ignore
    folder = folder_of(ctx.project_id)
    report = folder.load_model("qc_report")
    if not report or not report.technical_pass:
        raise PermissionError("final QC has not passed; nothing is sealed or deleted")
    final = Path(report.output)
    base = final.stem
    qc_path = folder.root / "retention_records" / f"qc_{base}.json"
    timeline = folder.load_model("timeline")
    missing = [c.file for c in timeline.clips if not Path(c.file).exists()] + \
              [a.file for a in timeline.audio if not Path(a.file).exists()]
    if missing:
        raise FileNotFoundError(f"edit dependencies missing: {missing}")
    sources = [folder.root / "sources"]
    if not any((folder.root / "sources").iterdir()):
        (folder.root / "sources" / "README.txt").write_text("Research inputs are in edit/artifacts.", "utf-8")
    result = video_retention.seal(folder.root, final, qc_path, sources=sources, essential=[folder.root / "edit"],
                                  native_projects=[folder.root / "edit" / "premiere"], dependencies_verified=True,
                                  video_id=folder.root.name)
    cleanup = video_retention.maybe_finish(folder.root, qc_path)
    set_state(ctx.project_id, "READY")
    db.log(ctx.project_id, "system", "finalized", seal=result, cleanup=cleanup)
    return {"seal": result, "cleanup": cleanup}


@jobs.handler("localize")
def stage_localize(ctx: jobs.JobContext) -> dict:
    """Phase 3: translate narration, voice it, retime a per-language storyboard and write subtitles.
    English artifacts stay untouched; video for the language is composed later from storyboard_<lang>."""
    from .modules import localization
    folder = folder_of(ctx.project_id)
    set_state(ctx.project_id, "LOCALIZATION")
    out = {}
    for lang in ctx.params.get("langs", ["ko", "ja", "es"]):
        out[lang] = localization.localize(ctx.project_id, folder, lang,
                                          backend=ctx.params.get("backend") or db.get_setting("default_backend"),
                                          provider=ctx.params.get("provider") or db.get_setting("tts_provider"),
                                          voice=ctx.params.get("voice"), progress=ctx.progress)
    return out


PIPELINE = ["research", "scenario", "script", "storyboard", "tts", "previews", "finals", "compose", "qa",
            "publish_prep", "finalize"]


def artifact_schema(name: str) -> dict:
    return SCHEMAS[name].model_json_schema()


def run_all(pid: str, params: dict[str, Any] | None = None, stop_after: str | None = None) -> list[dict]:
    """Synchronous end-to-end run used by the CLI (each stage is still recorded as a job)."""
    out = []
    params = params or {}
    for stage in PIPELINE:
        res = jobs.run_inline(stage, pid, params.get(stage, {}))
        out.append(res)
        if res["status"] != "done":
            set_state(pid, "FAILED")
            break
        if stage == stop_after:
            break
    return out
