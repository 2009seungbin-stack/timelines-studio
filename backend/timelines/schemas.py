"""Structured JSON contracts exchanged between TIMELINES Studio modules.

Every stage reads and writes one of these models (validated with Pydantic) so a
failed stage can be re-run from its saved input without repeating earlier work.
`python -m timelines.cli export-schemas` writes JSON Schema files to docs/schemas/.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

FactClass = Literal["FACT", "INTERPRETATION", "SPECULATION"]
ProjectState = Literal[
    "IDEA", "RESEARCHING", "RESEARCH_REVIEW", "SCRIPTING", "SCRIPT_REVIEW", "STORYBOARD",
    "ASSET_PRODUCTION", "RENDERING", "EDITING", "LOCALIZATION", "FINAL_REVIEW", "READY",
    "PUBLISHED", "FAILED",
]
PROJECT_STATES: tuple[str, ...] = ProjectState.__args__  # type: ignore[attr-defined]
SceneType = Literal[
    "MAP", "3D_RECONSTRUCTION", "ARCHITECTURE_CUTAWAY", "TIMELINE", "HISTORICAL_DOCUMENT",
    "DATA_VISUALIZATION", "TEXT_GRAPHIC", "COMPARISON", "SIMULATION",
]
NUMBER_RE = re.compile(r"\d[\d,.]*\s*(%|percent|million|billion|thousand|km|people|ships|legions)", re.I)


class Strict(BaseModel):
    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------- research
class Source(Strict):
    id: str
    title: str
    author: Optional[str] = None
    publisher: Optional[str] = None
    year: Optional[str] = None
    url: Optional[str] = None
    source_type: Literal["academic", "university", "museum", "encyclopedia", "primary",
                         "secondary", "archaeology", "map", "dataset"]
    accessed: Optional[date] = None
    verified_by_fetch: bool = False          # True only if the page was actually retrieved
    license: Optional[str] = None            # datasets / reusable media
    notes: Optional[str] = None


class Claim(Strict):
    id: str
    text: str
    classification: FactClass
    source_ids: list[str] = Field(default_factory=list)
    scenario_ref: Optional[str] = None       # SPECULATION: which scenario/event it belongs to
    conflict_note: Optional[str] = None
    needs_review: bool = False

    @model_validator(mode="after")
    def _evidence(self):
        if self.classification in ("FACT", "INTERPRETATION") and not self.source_ids:
            raise ValueError(f"{self.id}: {self.classification} claims need at least one source")
        if self.classification == "SPECULATION" and self.source_ids and not self.scenario_ref:
            # sources may support plausibility, but speculation must point at its scenario
            raise ValueError(f"{self.id}: SPECULATION needs scenario_ref")
        return self


class Conflict(Strict):
    claim_ids: list[str]
    description: str
    resolution: Optional[str] = None


class ResearchDossier(Strict):
    topic: str
    sources: list[Source]
    claims: list[Claim]
    conflicts: list[Conflict] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refs(self):
        ids = {s.id for s in self.sources}
        for c in self.claims:
            missing = [s for s in c.source_ids if s not in ids]
            if missing:
                raise ValueError(f"{c.id}: unknown sources {missing}")
        return self


# ---------------------------------------------------------------- scenario
class MapChange(Strict):
    entity: str                              # territory entity id, e.g. "rome_west"
    action: Literal["hold", "gain", "lose", "split", "merge", "appear"]
    region: str                              # region id known to the map engine
    note: Optional[str] = None


class Quantity(Strict):
    label: str
    value: str
    source_ids: list[str]                    # quantities without sources are rejected


class ScenarioEvent(Strict):
    id: str
    year: int
    title: str
    description: str
    domain: Literal["political", "economic", "technology", "urban", "migration", "culture",
                    "trade", "geography", "military", "religion"]
    classification: FactClass
    caused_by: list[str] = Field(default_factory=list)
    basis_claim_ids: list[str] = Field(default_factory=list)
    quantities: list[Quantity] = Field(default_factory=list)
    map_changes: list[MapChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_unsourced_numbers(self):
        if self.classification == "SPECULATION" and NUMBER_RE.search(self.description):
            raise ValueError(f"{self.id}: speculative event states a number; move it to quantities with sources")
        return self


class Scenario(Strict):
    id: str
    title: str
    starting_point_year: int
    divergence: str
    divergence_year: int
    geographic_scope: str
    horizon_start: int
    horizon_end: int
    constraints: list[str]
    assumptions: list[str]
    events: list[ScenarioEvent]

    @model_validator(mode="after")
    def _causality(self):
        seen: dict[str, int] = {}
        for ev in sorted(self.events, key=lambda e: e.year):
            for parent in ev.caused_by:
                if parent not in seen:
                    raise ValueError(f"{ev.id}: cause {parent} missing or later than the event")
            if ev.classification == "SPECULATION" and ev.year > self.divergence_year and not ev.caused_by \
                    and ev.id != self.events[0].id:
                raise ValueError(f"{ev.id}: post-divergence event without a recorded cause")
            seen[ev.id] = ev.year
        return self


# ---------------------------------------------------------------- script
class ScriptSegment(Strict):
    scene_id: str
    section: Literal["hook", "background", "real_history", "divergence", "impact", "outcome",
                     "limits", "conclusion"]
    narration: str
    visual_description: str
    scene_type: SceneType
    classification: FactClass
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    est_duration_s: float = 0.0
    required_assets: list[str] = Field(default_factory=list)
    camera_direction: str = ""
    animation_instructions: str = ""


class Script(Strict):
    title: str
    language: str = "en"
    target_duration_s: float
    segments: list[ScriptSegment]
    words_per_minute: float = 150.0

    @model_validator(mode="after")
    def _estimate(self):
        for seg in self.segments:
            if not seg.est_duration_s:
                seg.est_duration_s = round(len(seg.narration.split()) / self.words_per_minute * 60 + 0.6, 2)
        return self


# ---------------------------------------------------------------- render specs
class CameraKey(Strict):
    t: float                                  # seconds from scene start
    lon: float
    lat: float
    zoom: float                               # degrees of longitude visible across the frame
    ease: Literal["linear", "inout", "out"] = "inout"


class Territory(Strict):
    entity: str
    label: str
    source: str                               # geo layer id in the map registry
    feature_filter: dict[str, Any] = Field(default_factory=dict)
    region: Optional[str] = None              # named region (for derived alt-history regions)
    color: str = "#9c2f2f"
    certainty: Literal["firm", "approximate", "hypothetical"] = "approximate"
    appear_at: float = 0.0
    disappear_at: Optional[float] = None
    fade_s: float = 0.8


class MapLabel(Strict):
    text: str
    lon: float
    lat: float
    kind: Literal["city", "region", "sea", "note"] = "city"
    appear_at: float = 0.0
    disappear_at: Optional[float] = None


class Route(Strict):
    name: str
    coords: list[tuple[float, float]]         # (lon, lat)
    kind: Literal["sea", "land", "river"] = "sea"
    draw_from: float = 0.0
    draw_to: float = 2.0


class Caption(Strict):
    text: str
    start: float
    end: float
    role: Literal["date", "title", "note"] = "title"


class MapSpec(Strict):
    scene_id: str
    duration_s: float
    fps: int = 30
    width: int = 1920
    height: int = 1080
    classification: FactClass
    camera: list[CameraKey]
    territories: list[Territory] = Field(default_factory=list)
    labels: list[MapLabel] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    captions: list[Caption] = Field(default_factory=list)
    modern_borders: bool = False              # only when explicitly comparing to today
    tilt_3d: bool = False                     # render the same map on a tilted plane in Blender


class Scene3DSpec(Strict):
    scene_id: str
    kind: Literal["roman_city", "aqueduct", "forum", "harbor", "custom"]
    duration_s: float
    fps: int = 30
    width: int = 1920
    height: int = 1080
    seed: int = 7
    era_label: str = ""
    classification: FactClass
    camera: Literal["orbit", "dolly_in", "crane_down", "flyover", "static"] = "orbit"
    lighting: Literal["golden_hour", "noon", "overcast", "dusk"] = "golden_hour"
    quality: Literal["preview", "final"] = "preview"
    params: dict[str, Any] = Field(default_factory=dict)


class GraphicSpec(Strict):
    scene_id: str
    duration_s: float
    fps: int = 30
    width: int = 1920
    height: int = 1080
    classification: FactClass
    style: Literal["title_card", "timeline", "comparison", "end_card", "quote"]
    lines: list[str]
    items: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------- storyboard / timeline
class Transition(Strict):
    type: Literal["cut", "crossfade", "dip_black"] = "crossfade"
    duration_s: float = 0.6


class StoryboardScene(Strict):
    scene_id: str
    scene_type: SceneType
    start_s: float = 0.0
    end_s: float = 0.0
    classification: FactClass
    narration_segment: str
    camera_movement: str
    asset_refs: list[str] = Field(default_factory=list)
    animation_instructions: str = ""
    transition: Transition = Field(default_factory=Transition)
    renderer: Literal["map", "blender", "graphic"]
    spec: dict[str, Any]                      # MapSpec | Scene3DSpec | GraphicSpec as dict
    render_status: Literal["pending", "preview", "preview_approved", "final", "failed"] = "pending"


class Storyboard(Strict):
    title: str
    fps: int = 30
    width: int = 1920
    height: int = 1080
    scenes: list[StoryboardScene]


class TimelineClip(Strict):
    scene_id: str
    file: str
    start_s: float
    duration_s: float
    transition_in: Transition


class TimelineAudio(Strict):
    file: str
    start_s: float
    role: Literal["narration", "music", "sfx"]
    gain_db: float = 0.0


class SubtitleCue(Strict):
    index: int
    start_s: float
    end_s: float
    text: str


class Timeline(Strict):
    title: str
    language: str
    fps: int
    width: int
    height: int
    duration_s: float
    clips: list[TimelineClip]
    audio: list[TimelineAudio]
    subtitles: list[SubtitleCue]


# ---------------------------------------------------------------- QA / publishing
class QCCheck(Strict):
    id: str
    name: str
    status: Literal["pass", "fail", "warn", "manual"]
    details: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class QCReport(Strict):
    project_id: str
    output: str
    created_at: str
    checks: list[QCCheck]
    technical_pass: bool
    human_review_required: list[str]
    user_approval: Literal["unverified", "approved", "rejected"] = "unverified"


class PublishPackage(Strict):
    title_candidates: list[str]
    description: str
    chapters: list[dict[str, Any]]
    tags: list[str]
    sources_block: str
    synthetic_content_disclosure: dict[str, Any]
    language: str
    approved_for_upload: bool = False


SCHEMAS: dict[str, type[BaseModel]] = {
    "research_dossier": ResearchDossier, "scenario": Scenario, "script": Script,
    "map_spec": MapSpec, "scene3d_spec": Scene3DSpec, "graphic_spec": GraphicSpec,
    "storyboard": Storyboard, "timeline": Timeline, "qc_report": QCReport,
    "publish_package": PublishPackage,
}
