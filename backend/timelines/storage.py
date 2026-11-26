"""Per-video folder layout, artifact persistence and the ultradedit retention workflow.

Layout (ultradedit VIDEO_STORAGE_GUIDE):
  <video_id>/sources/           research dossier snapshot, scenario inputs, provenance
  <video_id>/edit/artifacts/    validated stage JSON (script, storyboard, timeline ...)
  <video_id>/edit/scenes/       approved final scene renders + .blend files (inputs of the edit)
  <video_id>/edit/audio/        narration takes, mix, subtitles
  <video_id>/edit/premiere/     FCP7 XML for Premiere
  <video_id>/work/              previews, frame folders, caches (removable after finalization)
  <video_id>/final/             one selected final MP4
  <video_id>/retention_records/ QC reports, cleanup journal
  <video_id>/evidence/qc_tmp/   disposable inspection frames (qc_cleanup)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from . import config
from .schemas import SCHEMAS

ARTIFACT_ORDER = ["research_dossier", "scenario", "script", "storyboard", "timeline", "qc_report",
                  "publish_package"]
# stage -> artifacts it produces; used to mark downstream work stale after an edit
DOWNSTREAM = {
    "research_dossier": ["scenario", "script", "storyboard", "timeline", "qc_report", "publish_package"],
    "scenario": ["script", "storyboard", "timeline", "qc_report", "publish_package"],
    "script": ["storyboard", "timeline", "qc_report", "publish_package"],
    "storyboard": ["timeline", "qc_report", "publish_package"],
    "timeline": ["qc_report", "publish_package"],
    "qc_report": ["publish_package"],
    "publish_package": [],
}


def _retention():
    sys.path.insert(0, str(config.RESEARCH))
    import video_retention  # type: ignore
    return video_retention


class VideoFolder:
    def __init__(self, path: str | Path):
        self.root = Path(path)

    # folders ---------------------------------------------------------------
    @property
    def artifacts(self) -> Path:
        return self.root / "edit" / "artifacts"

    def sub(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def create(self, video_id: str) -> dict:
        config.VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
        if (self.root / "video_retention.json").exists():
            result = {"status": "existing"}
        else:
            result = _retention().init(self.root, video_id)
        for p in ("edit/artifacts", "edit/scenes", "edit/audio", "edit/premiere", "work/previews",
                  "evidence/qc_tmp", "sources"):
            self.sub(*p.split("/"))
        return result

    def begin_revision(self) -> dict:
        return _retention().begin(self.root)

    # artifacts -------------------------------------------------------------
    def artifact_path(self, name: str) -> Path:
        if name not in SCHEMAS:
            raise KeyError(name)
        return self.artifacts / f"{name}.json"

    def load(self, name: str) -> dict | None:
        p = self.artifact_path(name)
        return json.loads(p.read_text("utf-8")) if p.exists() else None

    def load_model(self, name: str) -> BaseModel | None:
        data = self.load(name)
        return SCHEMAS[name].model_validate(data) if data is not None else None

    def save(self, name: str, data: dict | BaseModel, *, mark_stale: bool = True) -> dict:
        model = data if isinstance(data, BaseModel) else SCHEMAS[name].model_validate(data)
        payload = json.loads(model.model_dump_json())
        p = self.artifact_path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(p)
        meta = self._meta()
        meta[name] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "stale": False}
        if mark_stale:
            for down in DOWNSTREAM.get(name, []):
                if down in meta:
                    meta[down]["stale"] = True
        self._write_meta(meta)
        return payload

    def _meta(self) -> dict[str, Any]:
        p = self.artifacts / "_status.json"
        return json.loads(p.read_text("utf-8")) if p.exists() else {}

    def _write_meta(self, meta: dict) -> None:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        (self.artifacts / "_status.json").write_text(json.dumps(meta, indent=2), "utf-8")

    def stage_status(self) -> list[dict]:
        meta = self._meta()
        out = []
        for name in ARTIFACT_ORDER:
            p = self.artifact_path(name)
            if not p.exists():
                status = "missing"
            else:
                status = "stale" if meta.get(name, {}).get("stale") else "ready"
            out.append({"stage": name, "status": status, "artifact": name,
                        "updated_at": p.stat().st_mtime if p.exists() else None})
        return out

    def rel(self, path: str | Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()

    def latest_final(self) -> Path | None:
        finals = sorted((self.root / "final").glob("*.mp4"))
        manifest = self.root / "video_retention.json"
        if manifest.exists():
            sel = (json.loads(manifest.read_text("utf-8")).get("final") or {}).get("path")
            if sel and Path(sel).exists():
                return Path(sel)
        return finals[-1] if finals else None


def validation_errors(name: str, data: Any) -> list[dict] | None:
    try:
        SCHEMAS[name].model_validate(data)
        return None
    except ValidationError as exc:
        return [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
