"""SQLite (local) / PostgreSQL (set TIMELINES_DATABASE_URL) persistence via SQLAlchemy 2."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from . import config


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    topic: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(40), default="alt_history")
    state: Mapped[str] = mapped_column(String(30), default="IDEA")
    language: Mapped[str] = mapped_column(String(8), default="en")
    target_duration_s: Mapped[float] = mapped_column(Float, default=90)
    video_dir: Mapped[str] = mapped_column(Text)
    budget_usd: Mapped[float] = mapped_column(Float, default=5.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class History(Base):
    __tablename__ = "history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(40))          # stage | scene_render | agent | trends
    stage: Mapped[str] = mapped_column(String(60))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    gpu: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CostEntry(Base):
    __tablename__ = "costs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    backend: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80), default="")
    task: Mapped[str] = mapped_column(String(60), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backend: Mapped[str] = mapped_column(String(40))
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    turns: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class Channel(Base):
    __tablename__ = "trend_channels"
    channel_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    handle: Mapped[str] = mapped_column(String(120), default="")
    subscribers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoSnapshot(Base):
    __tablename__ = "trend_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(20), index=True)
    channel_id: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float] = mapped_column(Float)
    views: Mapped[int] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscribers_at_capture: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


DEFAULT_SETTINGS = {
    "budget_usd": 5.0,                       # per project, API spend ceiling
    "dev_budget_usd": 20.0,                  # ceiling for API-billed development sessions (project_id "dev")
    "default_backend": "claude_code_api",
    "default_model": {"claude_code": "sonnet", "claude_code_api": "opus", "codex": "", "anthropic_api": "claude-opus-5-5",
                      "openai_api": "gpt-5", "gemini_api": "gemini-2.5-pro"},
    "tts_provider": "import",                # narration made in the ElevenLabs web app (browser), then imported
    # ElevenLabs: voice_id per language (set in Settings after listing /api/tts/voices)
    "elevenlabs": {"model_id": "eleven_multilingual_v2", "voice_id": {"en": None, "ko": None, "ja": None, "es": None},
                   "voice_settings": None,
                   "plan": "paid (user, 2026-11-26)", "workflow": "browser only (web app), no API key"},
    "tts_voice": {"en": "en-US-AndrewNeural", "ko": "ko-KR-InJoonNeural", "ja": "ja-JP-KeitaNeural",
                  "es": "es-ES-AlvaroNeural"},
    "prices": {},                            # model -> [usd_per_mtok_in, usd_per_mtok_out] overrides
}

_url = os.environ.get("TIMELINES_DATABASE_URL") or f"sqlite:///{config.DB_PATH.as_posix()}"
engine = create_engine(_url, future=True, connect_args={"check_same_thread": False, "timeout": 30}
                       if _url.startswith("sqlite") else {})

if _url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _pragma(conn, _):  # noqa: ANN001
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

SessionLocal = sessionmaker(engine, expire_on_commit=False)
Base.metadata.create_all(engine)


def get_setting(key: str) -> Any:
    with SessionLocal() as s:
        row = s.get(Setting, key)
        return row.value if row else DEFAULT_SETTINGS.get(key)


def settings() -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    with SessionLocal() as s:
        for row in s.scalars(select(Setting)):
            out[row.key] = row.value
    return out


def put_settings(values: dict[str, Any]) -> dict[str, Any]:
    with SessionLocal() as s:
        for k, v in values.items():
            if k not in DEFAULT_SETTINGS:
                continue
            row = s.get(Setting, k)
            if row:
                row.value = v
            else:
                s.add(Setting(key=k, value=v))
        s.commit()
    return settings()


def log(project_id: str, actor: str, action: str, **detail: Any) -> None:
    with SessionLocal() as s:
        s.add(History(project_id=project_id, actor=actor, action=action, detail=json.loads(json.dumps(detail, default=str))))
        s.commit()


def session() -> Session:
    return SessionLocal()
