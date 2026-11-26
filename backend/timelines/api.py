"""FastAPI server (contract: docs/API.md). Run: python -m timelines.cli serve"""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from . import agents, config, db, jobs, pipeline
from .schemas import PROJECT_STATES, SCHEMAS
from .storage import VideoFolder, validation_errors

app = FastAPI(title="TIMELINES Studio", version=config.VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _start() -> None:
    jobs.start_workers()


def _iso(d) -> str | None:
    if not d:
        return None
    from datetime import timezone
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def _file_url(pid: str, folder: VideoFolder, path: Path | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    return f"/files/{pid}/{folder.rel(path)}"


def project_dict(p: db.Project, full: bool = True) -> dict:
    folder = VideoFolder(p.video_dir)
    final = folder.latest_final()
    out = {"id": p.id, "title": p.title, "topic": p.topic, "format": p.format, "state": p.state,
           "language": p.language, "target_duration_s": p.target_duration_s, "created_at": _iso(p.created_at),
           "updated_at": _iso(p.updated_at), "video_dir": p.video_dir, "final_mp4": str(final) if final else None,
           "final_url": _file_url(p.id, folder, final), "budget_usd": p.budget_usd,
           "spent_usd": round(agents.project_spent(p.id), 4),
           "session_cost_usd": round(agents.project_spent(p.id, billed_only=False) - agents.project_spent(p.id), 4)}
    if full:
        stages = folder.stage_status()
        with db.session() as s:
            running = {j.stage for j in s.scalars(select(db.Job).where(db.Job.project_id == p.id,
                                                                       db.Job.status.in_(["queued", "running"])))}
            failed = {}
            for j in s.scalars(select(db.Job).where(db.Job.project_id == p.id).order_by(db.Job.created_at)):
                failed[j.stage] = j.status == "failed"
        stage_map = {"research_dossier": "research", "scenario": "scenario", "script": "script",
                     "storyboard": "storyboard", "timeline": "compose", "qc_report": "qa", "publish_package": "publish_prep"}
        for st in stages:
            run_name = stage_map.get(st["stage"], st["stage"])
            st["stage"] = run_name
            if run_name in running:
                st["status"] = "running"
            elif failed.get(run_name):
                st["status"] = "failed"
            if st["updated_at"]:
                from datetime import datetime, timezone
                st["updated_at"] = datetime.fromtimestamp(st["updated_at"], timezone.utc).isoformat()
        out["stages"] = stages
    return out


# ------------------------------------------------------------------ system
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": config.VERSION}


@app.get("/api/system")
def system() -> dict:
    return {"tools": config.tool_report(), "gpu": config.gpu_name(), "data_root": str(config.DATA),
            "video_root": str(config.VIDEO_ROOT), "disk_free_gb": config.disk_free_gb(),
            "queue": {"workers": 3, "gpu_busy": jobs.gpu_busy()}}


@app.get("/api/settings")
def get_settings() -> dict:
    s = db.settings()
    s["keys"] = {k: bool(os.environ.get(k)) for k in config.API_KEYS}
    return s


@app.put("/api/settings")
def put_settings(body: dict = Body(...)) -> dict:
    db.put_settings(body)
    return get_settings()


# ------------------------------------------------------------------ projects
@app.get("/api/projects")
def list_projects() -> list[dict]:
    with db.session() as s:
        return [project_dict(p) for p in s.scalars(select(db.Project).order_by(db.Project.updated_at.desc()))]


@app.post("/api/projects")
def create_project(body: dict = Body(...)) -> dict:
    if not body.get("title") or not body.get("topic"):
        raise HTTPException(422, [{"loc": ["title"], "msg": "title and topic are required"}])
    p = pipeline.create_project(body["title"], body["topic"], body.get("format", "alt_history"),
                                float(body.get("target_duration_s", 90)), body.get("language", "en"))
    return project_dict(p)


def _proj(pid: str) -> db.Project:
    try:
        return pipeline.get_project(pid)
    except KeyError:
        raise HTTPException(404, "project not found") from None


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    return project_dict(_proj(pid))


@app.post("/api/projects/{pid}/state")
def set_state(pid: str, body: dict = Body(...)) -> dict:
    if body.get("state") not in PROJECT_STATES:
        raise HTTPException(422, [{"loc": ["state"], "msg": "unknown state"}])
    if body["state"] == "PUBLISHED":
        raise HTTPException(409, "PUBLISHED is set only after an approved upload")
    pipeline.set_state(pid, body["state"], actor="user")
    return project_dict(_proj(pid))


@app.get("/api/projects/{pid}/artifacts/{name}")
def get_artifact(pid: str, name: str) -> Any:
    if name not in SCHEMAS:
        raise HTTPException(404, "unknown artifact")
    data = VideoFolder(_proj(pid).video_dir).load(name)
    if data is None:
        raise HTTPException(404, "artifact not created yet")
    return data


@app.put("/api/projects/{pid}/artifacts/{name}")
def put_artifact(pid: str, name: str, body: Any = Body(...)) -> Any:
    if name not in SCHEMAS:
        raise HTTPException(404, "unknown artifact")
    errs = validation_errors(name, body)
    if errs:
        raise HTTPException(422, errs)
    saved = VideoFolder(_proj(pid).video_dir).save(name, body)
    db.log(pid, "user", "artifact_edited", artifact=name)
    return saved


@app.post("/api/projects/{pid}/run")
def run_stage(pid: str, body: dict = Body(...)) -> dict:
    _proj(pid)
    stage = body.get("stage")
    if stage not in jobs.HANDLERS:
        raise HTTPException(422, [{"loc": ["stage"], "msg": f"unknown stage {stage}"}])
    return jobs.as_dict(jobs.enqueue(stage, project_id=pid, params=body.get("options") or {}))


@app.get("/api/projects/{pid}/scenes")
def scenes(pid: str) -> list[dict]:
    p = _proj(pid)
    folder = VideoFolder(p.video_dir)
    sb = folder.load("storyboard")
    if not sb:
        return []
    out = []
    for sc in sb["scenes"]:
        prev = pipeline._outputs(folder, sc["scene_id"], True)
        fin = folder.root / "edit" / "scenes" / f"{sc['scene_id']}_final.mp4"
        thumb = next((x for x in (fin.with_suffix(".jpg"), prev.with_suffix(".jpg")) if x.exists()), None)
        out.append({**{k: sc.get(k) for k in ("scene_id", "scene_type", "renderer", "classification", "start_s",
                                               "end_s", "render_status", "spec", "transition")},
                    "narration": sc.get("narration_segment"), "preview_url": _file_url(pid, folder, prev),
                    "final_url": _file_url(pid, folder, fin), "thumb_url": _file_url(pid, folder, thumb)})
    return out


@app.post("/api/projects/{pid}/scenes/{scene_id}/render")
def render_scene(pid: str, scene_id: str, body: dict = Body(default={})) -> dict:
    p = _proj(pid)
    quality = body.get("quality", "preview")
    sb = VideoFolder(p.video_dir).load_model("storyboard")
    scene = next((s for s in (sb.scenes if sb else []) if s.scene_id == scene_id), None)
    if scene is None:
        raise HTTPException(404, "scene not found")
    if quality == "final" and scene.render_status not in ("preview_approved", "final"):
        raise HTTPException(409, "final render needs an approved preview")
    return jobs.as_dict(jobs.enqueue("render_scene", project_id=pid, params={"scene_id": scene_id, "quality": quality}))


@app.post("/api/projects/{pid}/scenes/{scene_id}/approve")
def approve(pid: str, scene_id: str, body: dict = Body(...)) -> dict:
    _proj(pid)
    try:
        return pipeline.approve_scene(pid, scene_id, bool(body.get("approved")), body.get("note", ""), "user")
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc)) from None
    except KeyError:
        raise HTTPException(404, "scene not found") from None


@app.get("/api/projects/{pid}/audio")
def audio_list(pid: str) -> list[dict]:
    p = _proj(pid)
    folder = VideoFolder(p.video_dir)
    out = []
    for meta in sorted((folder.root / "edit" / "audio").rglob("narr_*.json")):
        rec = json.loads(meta.read_text("utf-8"))
        out.append({"scene_id": meta.stem.replace("narr_", ""), "language": meta.parent.name,
                    "file_url": _file_url(pid, folder, Path(rec["file"])), "duration_s": rec["duration_s"],
                    "text": rec["text"], "voice": rec.get("voice"), "provider": rec.get("provider")})
    return out


@app.get("/api/projects/{pid}/outputs")
def outputs(pid: str) -> dict:
    p = _proj(pid)
    folder = VideoFolder(p.video_dir)
    final = folder.latest_final()
    if not final:
        return {}
    base = final.stem
    cands = {"mp4": final, "wav": folder.root / "edit" / "audio" / f"{base}_mix.wav",
             "srt": next((folder.root / "edit" / "audio").glob(f"{base}_*.srt"), None),
             "timeline_json": folder.root / "edit" / f"{base}_timeline.json",
             "premiere_xml": folder.root / "edit" / "premiere" / f"{base}.xml"}
    return {k: _file_url(pid, folder, v) for k, v in cands.items() if v}


@app.get("/api/projects/{pid}/history")
def history(pid: str) -> list[dict]:
    with db.session() as s:
        rows = s.scalars(select(db.History).where(db.History.project_id == pid).order_by(db.History.at.desc()))
        return [{"at": _iso(r.at), "actor": r.actor, "action": r.action, "detail": r.detail} for r in rows]


# ------------------------------------------------------------------ jobs
@app.get("/api/jobs")
def list_jobs(project_id: str | None = None, status: str | None = None) -> list[dict]:
    with db.session() as s:
        q = select(db.Job).order_by(db.Job.created_at.desc()).limit(200)
        if project_id:
            q = q.where(db.Job.project_id == project_id)
        if status:
            q = q.where(db.Job.status == status)
        return [jobs.as_dict(j) for j in s.scalars(q)]


@app.get("/api/jobs/{jid}")
def get_job(jid: str) -> dict:
    with db.session() as s:
        j = s.get(db.Job, jid)
        if j is None:
            raise HTTPException(404, "job not found")
        return jobs.as_dict(j)


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str) -> dict:
    jobs.cancel(jid)
    return get_job(jid)


@app.post("/api/jobs/{jid}/retry")
def retry_job(jid: str) -> dict:
    return jobs.as_dict(jobs.retry(jid))


# ------------------------------------------------------------------ agents / costs
@jobs.handler("agent")
def _agent_job(ctx: jobs.JobContext) -> dict:
    p = ctx.params
    prompt = p["prompt"]
    if ctx.project_id:
        folder = VideoFolder(pipeline.get_project(ctx.project_id).video_dir)
        prompt = (f"[TIMELINES project {ctx.project_id}; video folder {folder.root}; artifacts in "
                  f"{folder.artifacts}]\n\n{prompt}")
    res = agents.run(agents.AgentRequest(prompt=prompt, task=p.get("task", "free"), project_id=ctx.project_id,
                                         model=p.get("model"), session_id=p.get("session_id"),
                                         write_access=bool(p.get("write_access")),
                                         cwd=str(config.ROOT)), p["backend"])
    return res.as_dict()


@app.get("/api/agents")
def list_agents() -> list[dict]:
    return agents.list_backends()


@app.post("/api/agents/run")
def run_agent(body: dict = Body(...)) -> dict:
    if body.get("backend") not in agents.BACKENDS or not body.get("prompt"):
        raise HTTPException(422, [{"loc": ["backend"], "msg": "backend and prompt are required"}])
    return jobs.as_dict(jobs.enqueue("agent", project_id=body.get("project_id"), kind="agent", params=body))


@app.get("/api/agents/sessions")
def sessions(project_id: str | None = None) -> list[dict]:
    with db.session() as s:
        q = select(db.AgentSession).order_by(db.AgentSession.updated_at.desc())
        if project_id:
            q = q.where(db.AgentSession.project_id == project_id)
        return [{"backend": r.backend, "session_id": r.session_id, "project_id": r.project_id, "title": r.title,
                 "turns": r.turns, "updated_at": _iso(r.updated_at)} for r in s.scalars(q)]


@app.get("/api/costs")
def costs(project_id: str | None = None) -> dict:
    with db.session() as s:
        q = select(db.CostEntry).order_by(db.CostEntry.at.desc())
        if project_id:
            q = q.where(db.CostEntry.project_id == project_id)
        entries = [{"at": _iso(r.at), "backend": r.backend, "model": r.model, "task": r.task, "cost_usd": r.cost_usd,
                    "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "estimated": r.estimated,
                    "billed": r.backend not in agents.SESSION_BACKENDS} for r in s.scalars(q)]
    return {"budget_usd": agents.project_budget(project_id), "spent_usd": agents.project_spent(project_id),
            "entries": entries}


@app.get("/api/tts/voices")
def tts_voices(provider: str = "elevenlabs") -> dict:
    from .modules import audio
    if provider != "elevenlabs":
        raise HTTPException(422, "voice listing is available for elevenlabs")
    if not os.environ.get("ELEVENLABS_API_KEY"):
        return {"configured": False, "reason": "ELEVENLABS_API_KEY is not set (.env)", "voices": []}
    return {"configured": True, "voices": audio.PROVIDERS["elevenlabs"].voices()}


# ------------------------------------------------------------------ assets / trends / analytics
@app.get("/api/assets")
def assets(q: str = "", period: str = "", region: str = "", category: str = "") -> list[dict]:
    out = []
    for meta in sorted(config.ASSET_ROOT.glob("*/meta.json")):
        m = json.loads(meta.read_text("utf-8"))
        hay = json.dumps(m, ensure_ascii=False).lower()
        if q and q.lower() not in hay:
            continue
        if period and period.lower() not in str(m.get("historical_period", "")).lower():
            continue
        if region and region.lower() not in str(m.get("geographic_region", "")).lower():
            continue
        if category and category.lower() != str(m.get("category", "")).lower():
            continue
        prev = meta.parent / "preview.jpg"
        out.append({**m, "preview_url": f"/assets-files/{meta.parent.name}/preview.jpg" if prev.exists() else None})
    return out


@app.get("/assets-files/{asset_id}/{name}")
def asset_file(asset_id: str, name: str):
    p = (config.ASSET_ROOT / asset_id / name).resolve()
    if not p.is_relative_to(config.ASSET_ROOT.resolve()) or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/api/trends/status")
def trends_status() -> dict:
    from .modules import trends
    return trends.status()


@app.get("/api/trends/channels")
def trends_channels() -> list[dict]:
    with db.session() as s:
        return [{"channel_id": c.channel_id, "title": c.title, "handle": c.handle, "subscribers": c.subscribers,
                 "video_count": c.video_count, "collected_at": _iso(c.collected_at)} for c in s.scalars(select(db.Channel))]


@app.post("/api/trends/channels")
def trends_add(body: dict = Body(...)) -> dict:
    from .modules import trends
    if not trends.status()["configured"]:
        raise HTTPException(409, trends.status()["reason"])
    return trends.add_channel(body["handle_or_id"])


@jobs.handler("trends_collect")
def _trends_job(ctx: jobs.JobContext) -> dict:
    from .modules import trends
    return trends.collect(progress=ctx.progress)


@app.post("/api/trends/collect")
def trends_collect() -> dict:
    from .modules import trends
    if not trends.status()["configured"]:
        raise HTTPException(409, trends.status()["reason"])
    return jobs.as_dict(jobs.enqueue("trends_collect", kind="trends"))


@app.get("/api/trends/videos")
def trends_videos() -> list[dict]:
    from .modules import trends
    return trends.videos()


@app.get("/api/analytics/status")
def analytics_status() -> dict:
    return {"connected": False, "reason": "YouTube Analytics needs OAuth for the channel owner; not set up yet. "
                                          "No analytics are estimated for channels without authorised access."}


# ------------------------------------------------------------------ files (Range support)
@app.get("/files/{pid}/{rel:path}")
def files(pid: str, rel: str, request: Request):
    root = Path(_proj(pid).video_dir).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404)
    size = path.stat().st_size
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    rng = request.headers.get("range")
    if not rng:
        return FileResponse(path, media_type=ctype, headers={"Accept-Ranges": "bytes"})
    start_s, _, end_s = rng.replace("bytes=", "").partition("-")
    start = int(start_s) if start_s else max(0, size - int(end_s))
    end = min(int(end_s), size - 1) if end_s and start_s else size - 1
    end = min(end, start + 8 * 1024 * 1024 - 1)          # stream large files in 8 MB ranges
    with path.open("rb") as f:
        f.seek(start)
        data = f.read(end - start + 1)
    return Response(data, status_code=206, media_type=ctype,
                    headers={"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes",
                             "Content-Length": str(len(data))})


@app.exception_handler(PermissionError)
def _perm(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


_front = config.ROOT / "frontend" / "out"
if _front.exists():
    app.mount("/", StaticFiles(directory=_front, html=True), name="frontend")
