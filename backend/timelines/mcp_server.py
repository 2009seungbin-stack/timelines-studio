"""MCP stdio server: lets a Claude Code or Codex session drive TIMELINES Studio.

Register (Claude Code):  claude mcp add timelines -- <venv python> -m timelines.mcp_server
Register (Codex):        [mcp_servers.timelines] command=<venv python>, args=["-m","timelines.mcp_server"],
                         env={PYTHONPATH="<timelines_studio>/backend"}
Stage jobs run in this process's worker threads; approvals made here are recorded with actor "mcp".
"""
from __future__ import annotations

import json
import time

try:                                    # mcp >= 2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:                     # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from . import db, jobs, pipeline
from .api import project_dict  # noqa: F401 - also registers the agent/trends job handlers
from .schemas import SCHEMAS
from .storage import VideoFolder, validation_errors

mcp = FastMCP("timelines")
_started = False


def _workers():
    global _started
    if not _started:
        jobs.start_workers()
        _started = True


@mcp.tool()
def list_projects() -> list[dict]:
    """List TIMELINES projects with state, stages and final video path."""
    from sqlalchemy import select
    with db.session() as s:
        return [project_dict(p) for p in s.scalars(select(db.Project))]


@mcp.tool()
def create_project(title: str, topic: str, target_duration_s: float = 90, format: str = "alt_history") -> dict:
    """Create a project and its retention-managed video folder under ultradedit/research/timelines_videos."""
    return project_dict(pipeline.create_project(title, topic, format, target_duration_s))


@mcp.tool()
def get_artifact(project_id: str, name: str) -> dict | None:
    """Read a stage artifact: research_dossier, scenario, script, storyboard, timeline, qc_report, publish_package."""
    return VideoFolder(pipeline.get_project(project_id).video_dir).load(name)


@mcp.tool()
def save_artifact(project_id: str, name: str, data_json: str) -> dict:
    """Validate and save an artifact (JSON string). Returns validation errors instead of saving if invalid."""
    data = json.loads(data_json)
    errs = validation_errors(name, data)
    if errs:
        return {"saved": False, "errors": errs}
    VideoFolder(pipeline.get_project(project_id).video_dir).save(name, data)
    db.log(project_id, "mcp", "artifact_edited", artifact=name)
    return {"saved": True}


@mcp.tool()
def artifact_schema(name: str) -> dict:
    """JSON Schema of an artifact type."""
    return SCHEMAS[name].model_json_schema()


@mcp.tool()
def run_stage(project_id: str, stage: str, options_json: str = "{}", wait: bool = True, timeout_s: int = 3600) -> dict:
    """Run a pipeline stage (research, scenario, script, storyboard, tts, previews, review_previews, finals,
    compose, qa, publish_prep, finalize, render_scene). With wait=True blocks until it finishes."""
    _workers()
    job = jobs.enqueue(stage, project_id=project_id, params=json.loads(options_json))
    if not wait:
        return jobs.as_dict(job)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        with db.session() as s:
            row = s.get(db.Job, job.id)
            if row.status in ("done", "failed", "cancelled"):
                return jobs.as_dict(row)
        time.sleep(2)
    return {"id": job.id, "status": "still running"}


@mcp.tool()
def job_status(job_id: str) -> dict:
    """Status, progress, metrics and result of a job."""
    with db.session() as s:
        return jobs.as_dict(s.get(db.Job, job_id))


@mcp.tool()
def approve_scene(project_id: str, scene_id: str, approved: bool, note: str) -> dict:
    """Approve or reject a scene preview (gate for the expensive final render). Recorded as actor 'mcp'."""
    return pipeline.approve_scene(project_id, scene_id, approved, note, "mcp")


@mcp.tool()
def project_files(project_id: str) -> dict:
    """Absolute paths of previews, final scene renders, final MP4 and QC report for viewing."""
    folder = VideoFolder(pipeline.get_project(project_id).video_dir)
    return {"previews": sorted(str(p) for p in (folder.root / "work" / "previews").glob("*.mp4")),
            "scenes": sorted(str(p) for p in (folder.root / "edit" / "scenes").glob("*.mp4")),
            "final": [str(p) for p in (folder.root / "final").glob("*.mp4")],
            "qc": sorted(str(p) for p in (folder.root / "retention_records").glob("qc_*.json"))}


if __name__ == "__main__":
    mcp.run()
