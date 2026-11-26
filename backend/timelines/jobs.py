"""Local persistent job queue (SQLite) with a CPU pool and a single GPU lane.

Redis/Celery are not installed on this machine; this queue keeps the same contract
(enqueue -> worker -> status/metrics/result) so a Celery adapter can replace it later.
GPU jobs also take the workspace-wide gpu_lock so Blender never competes with ASR/demucs.
"""
from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, select

from . import db

Handler = Callable[["JobContext"], Any]
HANDLERS: dict[str, Handler] = {}
GPU_STAGES: set[str] = set()


class Cancelled(Exception):
    pass


def handler(name: str, *, gpu: bool = False):
    def wrap(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        if gpu:
            GPU_STAGES.add(name)
        return fn
    return wrap


class JobContext:
    def __init__(self, job: db.Job):
        self.job_id = job.id
        self.project_id = job.project_id
        self.stage = job.stage
        self.params = dict(job.params or {})
        self.metrics: dict[str, Any] = {}
        self._last = 0.0

    def progress(self, value: float, message: str = "") -> None:
        if cancel_requested(self.job_id):
            raise Cancelled("cancelled by user")
        t = time.monotonic()
        if t - self._last < 0.5 and value < 1:
            return
        self._last = t
        with db.session() as s:
            row = s.get(db.Job, self.job_id)
            row.progress = max(0.0, min(1.0, float(value)))
            if message:
                row.message = message[:500]
            s.commit()

    def add_metric(self, key: str, value: float) -> None:
        self.metrics[key] = round(self.metrics.get(key, 0) + value, 3)


_cancel: set[str] = set()


def cancel_requested(job_id: str) -> bool:
    return job_id in _cancel


def enqueue(stage: str, *, project_id: str | None = None, kind: str = "stage", params: dict | None = None,
            status: str = "queued") -> db.Job:
    if stage not in HANDLERS:
        raise KeyError(f"unknown stage {stage}")
    job = db.Job(id=db.new_id("job"), project_id=project_id, kind=kind, stage=stage,
                 params=params or {}, gpu=stage in GPU_STAGES, status=status,
                 started_at=db.now() if status == "running" else None)
    with db.session() as s:
        s.add(job)
        s.commit()
    _wake.set()
    return job


def cancel(job_id: str) -> None:
    with db.session() as s:
        row = s.get(db.Job, job_id)
        if row is None:
            raise KeyError(job_id)
        if row.status == "queued":
            row.status = "cancelled"
            row.finished_at = db.now()
        elif row.status == "running":
            _cancel.add(job_id)
        s.commit()


def retry(job_id: str) -> db.Job:
    with db.session() as s:
        row = s.get(db.Job, job_id)
        params = dict(row.params or {})
        params["retry_of"] = job_id
        params["attempt"] = (row.attempts or 1) + 1
        return enqueue(row.stage, project_id=row.project_id, kind=row.kind, params=params)


def as_dict(job: db.Job) -> dict:
    def iso(d: datetime | None) -> str | None:
        if not d:
            return None
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
    return {"id": job.id, "project_id": job.project_id, "kind": job.kind, "stage": job.stage,
            "status": job.status, "progress": job.progress, "message": job.message,
            "created_at": iso(job.created_at), "started_at": iso(job.started_at),
            "finished_at": iso(job.finished_at), "attempts": job.attempts, "metrics": job.metrics or {},
            "result": job.result, "error": job.error, "params": job.params}


def _claim(gpu: bool) -> db.Job | None:
    with _claim_lock, db.session() as s:
        q = select(db.Job).where(db.Job.status == "queued", db.Job.gpu == gpu).order_by(db.Job.created_at).limit(1)
        row = s.scalars(q).first()
        if row is None:
            return None
        row.status = "running"
        row.started_at = db.now()
        row.attempts = (row.params or {}).get("attempt", 1)
        s.commit()
        return row


def _spent(project_id: str | None, since: datetime) -> float:
    with db.session() as s:
        q = select(func.coalesce(func.sum(db.CostEntry.cost_usd), 0.0)).where(db.CostEntry.at >= since)
        if project_id:
            q = q.where(db.CostEntry.project_id == project_id)
        return float(s.scalar(q) or 0.0)


def _run(job: db.Job) -> None:
    ctx = JobContext(job)
    t0, c0, started = time.monotonic(), time.thread_time(), db.now()
    status, result, error = "done", None, None
    try:
        if job.gpu:
            from .gpu import gpu_slot
            with gpu_slot(f"timelines {job.stage} {job.project_id}"):
                result = HANDLERS[job.stage](ctx)
        else:
            result = HANDLERS[job.stage](ctx)
    except Cancelled as exc:
        status, error = "cancelled", str(exc)
    except Exception as exc:  # noqa: BLE001 - recorded on the job for retry
        status, error = "failed", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-4000:]}"
    finally:
        _cancel.discard(job.id)
    metrics = {"exec_s": round(time.monotonic() - t0, 2), "cpu_s": round(time.thread_time() - c0, 2),
               "gpu": job.gpu, "api_cost_usd": round(_spent(job.project_id, started), 4),
               "retries": max(0, (job.params or {}).get("attempt", 1) - 1), **ctx.metrics}
    with db.session() as s:
        row = s.get(db.Job, job.id)
        row.status, row.error, row.metrics = status, error, metrics
        row.result = result if isinstance(result, (dict, list, str, int, float, type(None))) else str(result)
        row.finished_at = db.now()
        if status == "done":
            row.progress = 1.0
        s.commit()
    if status == "failed" and job.project_id and job.kind == "stage":
        db.log(job.project_id, "system", "stage_failed", stage=job.stage, job=job.id, error=(error or "")[:400])


_wake = threading.Event()
_claim_lock = threading.Lock()
_started = False


def _worker(gpu: bool) -> None:
    while True:
        job = _claim(gpu)
        if job is None:
            _wake.wait(2.0)
            _wake.clear()
            continue
        _run(job)


def start_workers(cpu_workers: int = 2) -> None:
    global _started
    if _started:
        return
    _started = True
    with db.session() as s:                     # jobs interrupted by a restart
        for row in s.scalars(select(db.Job).where(db.Job.status == "running")):
            row.status, row.error, row.finished_at = "failed", "interrupted: server restarted", db.now()
        s.commit()
    for i in range(cpu_workers):
        threading.Thread(target=_worker, args=(False,), daemon=True, name=f"cpu-{i}").start()
    threading.Thread(target=_worker, args=(True,), daemon=True, name="gpu-0").start()


def run_inline(stage: str, project_id: str | None = None, params: dict | None = None) -> dict:
    """Run a stage synchronously (CLI / tests) while still recording a job row."""
    job = enqueue(stage, project_id=project_id, params=params, status="running")
    _run(job)
    with db.session() as s:
        return as_dict(s.get(db.Job, job.id))


def gpu_busy() -> bool:
    with db.session() as s:
        return bool(s.scalar(select(func.count()).select_from(db.Job).where(db.Job.gpu.is_(True), db.Job.status == "running")))
