// Types mirror docs/API.md and backend/timelines/schemas.py (Pydantic models).

export type FactClass = "FACT" | "INTERPRETATION" | "SPECULATION";
export const PROJECT_STATES = [
  "IDEA", "RESEARCHING", "RESEARCH_REVIEW", "SCRIPTING", "SCRIPT_REVIEW", "STORYBOARD",
  "ASSET_PRODUCTION", "RENDERING", "EDITING", "LOCALIZATION", "FINAL_REVIEW", "READY",
  "PUBLISHED", "FAILED",
] as const;
export type ProjectState = (typeof PROJECT_STATES)[number];
export type StageStatus = "missing" | "ready" | "stale" | "running" | "failed";
export type SceneType =
  | "MAP" | "3D_RECONSTRUCTION" | "ARCHITECTURE_CUTAWAY" | "TIMELINE" | "HISTORICAL_DOCUMENT"
  | "DATA_VISUALIZATION" | "TEXT_GRAPHIC" | "COMPARISON" | "SIMULATION";
export type ProjectFormat = "alt_history" | "history_explainer" | "documentary";
export const RUN_STAGES = [
  "research", "scenario", "script", "storyboard", "tts", "previews", "finals",
  "compose", "qa", "publish_prep", "finalize",
] as const;
export type RunStage = (typeof RUN_STAGES)[number];
export type ArtifactName =
  | "research_dossier" | "scenario" | "script" | "storyboard" | "timeline" | "qc_report" | "publish_package";

// ---------------- API objects
export interface ToolInfo { ok: boolean; path?: string | null; version?: string | null }
export interface SystemInfo {
  tools: Partial<Record<"blender" | "ffmpeg" | "node" | "claude_cli" | "codex_cli", ToolInfo>>;
  gpu: string | null;
  data_root?: string;
  video_root?: string;
  disk_free_gb: Record<string, number>;
  queue: { workers: number; gpu_busy: boolean };
}
export interface Settings {
  budget_usd: number;
  default_backend: string;
  default_model: Record<string, string>;
  tts_provider: string;
  tts_voice: string;
  keys: Record<string, boolean>;
}
export interface StageInfo {
  stage: string;
  status: StageStatus;
  updated_at: string | null;
  artifact: string | null;
}
export interface Project {
  id: string;
  title: string;
  topic: string;
  format: ProjectFormat | string;
  state: ProjectState;
  language: string;
  target_duration_s: number;
  created_at: string;
  updated_at: string;
  video_dir?: string;
  final_mp4: string | null;
  final_url: string | null;
  stages: StageInfo[];
  budget_usd: number;
  spent_usd: number;
}
export interface CreateProjectBody {
  title: string;
  topic: string;
  format: ProjectFormat;
  target_duration_s: number;
  language: string;
}
export interface JobMetrics {
  exec_s?: number; cpu_s?: number; gpu?: boolean; api_cost_usd?: number;
  render_s?: number; output_bytes?: number; cache_hit?: boolean;
}
export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export interface Job {
  id: string;
  project_id: string | null;
  kind: string;
  stage: string | null;
  status: JobStatus;
  progress: number;
  message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  attempts: number;
  metrics: JobMetrics | null;
  result: unknown;
  error: string | null;
}
export type RenderStatus = "pending" | "preview" | "preview_approved" | "final" | "failed";
export interface SceneRow {
  scene_id: string;
  scene_type: SceneType | string;
  renderer: "map" | "blender" | "graphic" | string;
  classification: FactClass;
  start_s: number;
  end_s: number;
  narration: string;
  render_status: RenderStatus;
  preview_url: string | null;
  final_url: string | null;
  thumb_url: string | null;
  spec: Record<string, unknown>;
  // not listed in API.md; shown only when the backend includes them
  transition?: { type: string; duration_s: number };
  approval_note?: string | null;
}
export interface AudioClip { scene_id: string; file_url: string; duration_s: number; text: string }
export interface HistoryEntry { at: string; actor: string; action: string; detail: unknown }

export interface AgentBackend {
  id: string; // claude_code | codex | anthropic_api | openai_api | gemini_api
  label: string;
  kind: "session" | "api";
  available: boolean;
  detail: string;
  models: string[];
}
export type AgentTask = "free" | "research" | "scenario" | "script" | "review";
export interface AgentRunBody {
  backend: string;
  prompt: string;
  project_id?: string;
  task: AgentTask;
  session_id?: string;
  model?: string;
  write_access?: boolean;
}
export interface AgentSession {
  backend: string; session_id: string; project_id: string | null;
  title: string; updated_at: string; turns: number;
}
export interface AgentResult {
  text?: string; session_id?: string | null; cost_usd?: number | null; structured?: unknown;
}
export interface CostEntry {
  at: string; backend: string; model: string; task: string; cost_usd: number;
  tokens_in: number; tokens_out: number; estimated: boolean;
}
export interface Costs { budget_usd: number; spent_usd: number; entries: CostEntry[] }

export interface AssetRow {
  asset_id: string; name: string; period: string; region: string; category: string;
  polygon_count: number | null; materials: unknown; license: string; source: string;
  accuracy_notes: string; preview_url: string | null; file_path: string;
}
export interface TrendStatus { configured: boolean; reason: string }
export interface TrendChannel {
  channel_id: string; title: string; handle: string; subscribers: number;
  video_count: number; collected_at: string;
}
export interface TrendVideo {
  video_id: string; channel_title: string; title: string; published_at: string;
  duration_s: number; views: number; views_per_day: number; views_per_subscriber: number;
  age_days: number; growth_per_day: number | null;
}
export interface AnalyticsStatus { connected: boolean; reason: string }

// ---------------- Artifacts (schemas.py)
export interface Source {
  id: string; title: string; author?: string | null; publisher?: string | null; year?: string | null;
  url?: string | null;
  source_type: "academic" | "university" | "museum" | "encyclopedia" | "primary" | "secondary" | "archaeology" | "map" | "dataset";
  accessed?: string | null; verified_by_fetch: boolean; license?: string | null; notes?: string | null;
}
export interface Claim {
  id: string; text: string; classification: FactClass; source_ids: string[];
  scenario_ref?: string | null; conflict_note?: string | null; needs_review: boolean;
}
export interface Conflict { claim_ids: string[]; description: string; resolution?: string | null }
export interface ResearchDossier { topic: string; sources: Source[]; claims: Claim[]; conflicts: Conflict[] }

export interface ScriptSegment {
  scene_id: string;
  section: "hook" | "background" | "real_history" | "divergence" | "impact" | "outcome" | "limits" | "conclusion";
  narration: string; visual_description: string; scene_type: SceneType; classification: FactClass;
  claim_ids: string[]; source_ids: string[]; est_duration_s: number; required_assets: string[];
  camera_direction: string; animation_instructions: string;
}
export interface Script {
  title: string; language: string; target_duration_s: number; segments: ScriptSegment[]; words_per_minute: number;
}
export interface Transition { type: "cut" | "crossfade" | "dip_black"; duration_s: number }
export interface TimelineClip { scene_id: string; file: string; start_s: number; duration_s: number; transition_in: Transition }
export interface TimelineAudio { file: string; start_s: number; role: "narration" | "music" | "sfx"; gain_db: number }
export interface SubtitleCue { index: number; start_s: number; end_s: number; text: string }
export interface Timeline {
  title: string; language: string; fps: number; width: number; height: number; duration_s: number;
  clips: TimelineClip[]; audio: TimelineAudio[]; subtitles: SubtitleCue[];
}
export interface QCCheck {
  id: string; name: string; status: "pass" | "fail" | "warn" | "manual"; details: string; data: Record<string, unknown>;
}
export interface QCReport {
  project_id: string; output: string; created_at: string; checks: QCCheck[];
  technical_pass: boolean; human_review_required: string[]; user_approval: "unverified" | "approved" | "rejected";
}
export interface PublishPackage {
  title_candidates: string[]; description: string; chapters: Record<string, unknown>[]; tags: string[];
  sources_block: string; synthetic_content_disclosure: Record<string, unknown>; language: string;
  approved_for_upload: boolean;
}
export interface ScenarioEvent {
  id: string; year: number; title: string; description: string; domain: string;
  classification: FactClass; caused_by: string[];
}
export interface Scenario {
  id: string; title: string; starting_point_year: number; divergence: string; divergence_year: number;
  geographic_scope: string; horizon_start: number; horizon_end: number; constraints: string[];
  assumptions: string[]; events: ScenarioEvent[];
}
export interface ArtifactMap {
  research_dossier: ResearchDossier; scenario: Scenario; script: Script;
  storyboard: unknown; timeline: Timeline; qc_report: QCReport; publish_package: PublishPackage;
}
