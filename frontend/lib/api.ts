import type {
  AgentBackend, AgentRunBody, AgentSession, AnalyticsStatus, ArtifactMap, ArtifactName, AssetRow,
  AudioClip, Costs, CreateProjectBody, HistoryEntry, Job, Project, RunStage, SceneRow, Settings,
  SystemInfo, TrendChannel, TrendStatus, TrendVideo,
} from "./types";

export const API_BASE: string = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
  /** FastAPI 422: list of {loc, msg} */
  get validationErrors(): { loc: string; msg: string }[] | null {
    if (this.status !== 422 || !Array.isArray(this.detail)) return null;
    return (this.detail as { loc?: unknown[]; msg?: string }[]).map((d) => ({
      loc: Array.isArray(d.loc) ? d.loc.join(".") : String(d.loc ?? ""),
      msg: String(d.msg ?? ""),
    }));
  }
}

function formatDetail(detail: unknown): string {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (d && typeof d === "object" && "msg" in d) {
          const o = d as { loc?: unknown[]; msg: string };
          return `${Array.isArray(o.loc) ? o.loc.join(".") : ""}: ${o.msg}`;
        }
        return JSON.stringify(d);
      })
      .join("\n");
  }
  return JSON.stringify(detail);
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

/** Resolve a URL returned by the backend (e.g. /files/...) against the API base. */
export function fileUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  if (/^(https?:|data:|blob:)/i.test(u)) return u;
  return `${API_BASE}${u.startsWith("/") ? "" : "/"}${u}`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch (e) {
    throw new ApiError(0, null, "백엔드에 연결할 수 없습니다. 서버(127.0.0.1:8790)가 실행 중인지 확인하세요.");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in (data as object) ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, detail, `${res.status} ${formatDetail(detail) || res.statusText}`);
  }
  return data as T;
}

function qs(params: Record<string, string | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
}

const enc = encodeURIComponent;

export const api = {
  health: () => request<{ ok: boolean; version: string }>("GET", "/api/health"),
  system: () => request<SystemInfo>("GET", "/api/system"),
  settings: () => request<Settings>("GET", "/api/settings"),
  updateSettings: (b: Partial<Settings>) => request<Settings>("PUT", "/api/settings", b),

  projects: () => request<Project[]>("GET", "/api/projects"),
  project: (id: string) => request<Project>("GET", `/api/projects/${enc(id)}`),
  createProject: (b: CreateProjectBody) => request<Project>("POST", "/api/projects", b),
  setState: (id: string, state: string) => request<Project>("POST", `/api/projects/${enc(id)}/state`, { state }),
  artifact: <N extends ArtifactName>(id: string, name: N) =>
    request<ArtifactMap[N]>("GET", `/api/projects/${enc(id)}/artifacts/${name}`),
  putArtifact: (id: string, name: ArtifactName, body: unknown) =>
    request<unknown>("PUT", `/api/projects/${enc(id)}/artifacts/${name}`, body),
  run: (id: string, stage: RunStage, options?: Record<string, unknown>) =>
    request<Job>("POST", `/api/projects/${enc(id)}/run`, options ? { stage, options } : { stage }),
  scenes: (id: string) => request<SceneRow[]>("GET", `/api/projects/${enc(id)}/scenes`),
  renderScene: (id: string, sceneId: string, quality: "preview" | "final") =>
    request<Job>("POST", `/api/projects/${enc(id)}/scenes/${enc(sceneId)}/render`, { quality }),
  approveScene: (id: string, sceneId: string, approved: boolean, note: string) =>
    request<SceneRow>("POST", `/api/projects/${enc(id)}/scenes/${enc(sceneId)}/approve`, { approved, note }),
  audio: (id: string) => request<AudioClip[]>("GET", `/api/projects/${enc(id)}/audio`),
  history: (id: string) => request<HistoryEntry[]>("GET", `/api/projects/${enc(id)}/history`),

  jobs: (p?: { project_id?: string; status?: string }) =>
    request<Job[]>("GET", `/api/jobs${qs({ project_id: p?.project_id, status: p?.status })}`),
  job: (id: string) => request<Job>("GET", `/api/jobs/${enc(id)}`),
  cancelJob: (id: string) => request<Job>("POST", `/api/jobs/${enc(id)}/cancel`),
  retryJob: (id: string) => request<Job>("POST", `/api/jobs/${enc(id)}/retry`),

  agents: () => request<AgentBackend[]>("GET", "/api/agents"),
  runAgent: (b: AgentRunBody) => request<Job>("POST", "/api/agents/run", b),
  agentSessions: (project_id?: string) =>
    request<AgentSession[]>("GET", `/api/agents/sessions${qs({ project_id })}`),

  costs: (project_id?: string) => request<Costs>("GET", `/api/costs${qs({ project_id })}`),
  assets: (p: { q?: string; period?: string; region?: string; category?: string }) =>
    request<AssetRow[]>("GET", `/api/assets${qs(p)}`),

  trendsStatus: () => request<TrendStatus>("GET", "/api/trends/status"),
  trendChannels: () => request<TrendChannel[]>("GET", "/api/trends/channels"),
  addTrendChannel: (handle_or_id: string) => request<unknown>("POST", "/api/trends/channels", { handle_or_id }),
  trendCollect: () => request<Job>("POST", "/api/trends/collect"),
  trendVideos: () => request<TrendVideo[]>("GET", "/api/trends/videos"),
  analyticsStatus: () => request<AnalyticsStatus>("GET", "/api/analytics/status"),
};
