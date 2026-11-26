"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import {
  AlertTriangle, CheckCircle2, CircleDashed, FolderOpen, Loader2, Play, RefreshCw, XCircle, type LucideIcon,
} from "lucide-react";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible } from "@/components/ui/collapsible";
import { Textarea } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ApiError, errorMessage, api } from "@/lib/api";
import { isNotFound, useAction, useApp, useAsync } from "@/lib/hooks";
import type { ArtifactMap, ArtifactName, FactClass, Job, JobStatus, Project, ProjectState, RunStage, StageStatus } from "@/lib/types";
import { cn, fmtDuration } from "@/lib/utils";

/* ---------------------------------------------------------------- chips */
const STATE_TONE: Record<ProjectState, Tone> = {
  IDEA: "neutral", RESEARCHING: "info", RESEARCH_REVIEW: "warn", SCRIPTING: "info", SCRIPT_REVIEW: "warn",
  STORYBOARD: "violet", ASSET_PRODUCTION: "violet", RENDERING: "info", EDITING: "accent",
  LOCALIZATION: "accent", FINAL_REVIEW: "warn", READY: "ok", PUBLISHED: "ok", FAILED: "bad",
};
const STATE_KO: Record<ProjectState, string> = {
  IDEA: "아이디어", RESEARCHING: "리서치 중", RESEARCH_REVIEW: "리서치 검토", SCRIPTING: "대본 작성 중",
  SCRIPT_REVIEW: "대본 검토", STORYBOARD: "스토리보드", ASSET_PRODUCTION: "에셋 제작", RENDERING: "렌더링",
  EDITING: "편집", LOCALIZATION: "현지화", FINAL_REVIEW: "최종 검토", READY: "준비 완료",
  PUBLISHED: "게시됨", FAILED: "실패",
};
export function StateChip({ state }: { state: string }) {
  const tone = STATE_TONE[state as ProjectState] ?? "neutral";
  const ko = STATE_KO[state as ProjectState];
  return <Badge tone={tone} title={ko}>{state}</Badge>;
}

const STAGE_TONE: Record<StageStatus, Tone> = { missing: "neutral", ready: "ok", stale: "warn", running: "info", failed: "bad" };
const STAGE_KO: Record<StageStatus, string> = { missing: "없음", ready: "준비됨", stale: "오래됨", running: "실행 중", failed: "실패" };
export function StageChip({ status }: { status: StageStatus | string }) {
  const s = status as StageStatus;
  return (
    <Badge tone={STAGE_TONE[s] ?? "neutral"}>
      {s === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
      {STAGE_KO[s] ?? status}
    </Badge>
  );
}
export const STAGE_LABEL: Record<string, string> = {
  research: "리서치", scenario: "시나리오", script: "대본", storyboard: "스토리보드", tts: "내레이션(TTS)",
  previews: "프리뷰 렌더", finals: "최종 렌더", compose: "합성/편집", qa: "품질 검사", publish_prep: "게시 준비",
  finalize: "최종화",
};

const JOB_TONE: Record<JobStatus, Tone> = { queued: "neutral", running: "info", done: "ok", failed: "bad", cancelled: "warn" };
const JOB_KO: Record<JobStatus, string> = { queued: "대기", running: "실행 중", done: "완료", failed: "실패", cancelled: "취소됨" };
export function JobBadge({ status }: { status: JobStatus }) {
  return <Badge tone={JOB_TONE[status]}>{JOB_KO[status]}</Badge>;
}

const CLASS_TONE: Record<FactClass, Tone> = { FACT: "ok", INTERPRETATION: "warn", SPECULATION: "violet" };
const CLASS_KO: Record<FactClass, string> = { FACT: "사실", INTERPRETATION: "해석", SPECULATION: "추측/가정" };
export function ClassBadge({ value }: { value: FactClass | string }) {
  return <Badge tone={CLASS_TONE[value as FactClass] ?? "neutral"} title={CLASS_KO[value as FactClass]}>{value}</Badge>;
}

export function sceneTypeColor(t: string): string {
  const map: Record<string, string> = {
    MAP: "#4f8cff", "3D_RECONSTRUCTION": "#a78bfa", ARCHITECTURE_CUTAWAY: "#c084fc", TIMELINE: "#5ec2e8",
    HISTORICAL_DOCUMENT: "#f5b942", DATA_VISUALIZATION: "#3ecf8e", TEXT_GRAPHIC: "#94a3b8",
    COMPARISON: "#f08a5d", SIMULATION: "#f0616d",
  };
  return map[t] ?? "#64748b";
}

/* ---------------------------------------------------------------- layout helpers */
export function PageHeader({
  icon: Icon, title, description, actions,
}: { icon: LucideIcon; title: string; description: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-panel text-accent">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
          <p className="mt-0.5 max-w-3xl text-sm text-muted">{description}</p>
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon = CircleDashed, title, children }: { icon?: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line2 px-6 py-10 text-center">
      <Icon className="mb-3 h-7 w-7 text-muted" />
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="mt-1.5 max-w-lg text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, title = "오류" }: { error: unknown; title?: string }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  const errs = e?.validationErrors;
  return (
    <div role="alert" className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2.5 text-sm text-bad">
      <div className="flex items-center gap-2 font-medium"><XCircle className="h-4 w-4" />{title}</div>
      {errs ? (
        <ul className="mt-1.5 space-y-0.5 font-mono text-xs">
          {errs.map((x, i) => <li key={i}><span className="opacity-70">{x.loc}</span> : {x.msg}</li>)}
        </ul>
      ) : (
        <p className="mt-1 whitespace-pre-wrap break-words text-xs">{errorMessage(error)}</p>
      )}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "ok"; children: ReactNode }) {
  const cls = { info: "border-info/35 bg-info/8 text-info", warn: "border-warn/40 bg-warn/8 text-warn", ok: "border-ok/35 bg-ok/8 text-ok" }[tone];
  return (
    <div className={cn("flex items-start gap-2 rounded-lg border px-3 py-2 text-sm", cls)}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="text-fg/90">{children}</div>
    </div>
  );
}

export function Loading({ label = "불러오는 중..." }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted">
      <Loader2 className="h-4 w-4 animate-spin" />{label}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-bg px-3 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="text-base font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- project-scoped page wrapper */
export function ProjectPage({
  icon, title, description, actions, children,
}: {
  icon: LucideIcon; title: string; description: string;
  actions?: (p: Project) => ReactNode;
  children: (p: Project) => ReactNode;
}) {
  const { project, projects, projectsLoading, projectsError } = useApp();
  return (
    <div>
      <PageHeader icon={icon} title={title} description={description} actions={project && actions ? actions(project) : undefined} />
      {projectsError ? <ErrorBox error={projectsError} title="프로젝트 목록을 불러오지 못했습니다" /> : null}
      {projectsLoading ? <Loading /> : !projectsError && !project ? (
        <EmptyState icon={FolderOpen} title={projects.length ? "프로젝트를 선택하세요" : "프로젝트가 없습니다"}>
          {projects.length ? "상단 바의 프로젝트 선택기에서 작업할 프로젝트를 고르세요." : (
            <>먼저 <Link href="/ideas/" className="text-accent underline">Ideas</Link> 페이지에서 프로젝트를 만드세요.</>
          )}
        </EmptyState>
      ) : null}
      {project ? children(project) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- artifact loading */
export function useArtifact<N extends ArtifactName>(projectId: string, name: N) {
  const { jobsVersion } = useApp();
  const st = useAsync<ArtifactMap[N] | null>(
    async () => {
      try { return await api.artifact(projectId, name); }
      catch (e) { if (isNotFound(e)) return null; throw e; }
    },
    [projectId, name, jobsVersion],
  );
  return { ...st, notFound: !st.loading && !st.error && st.data === null };
}

export function RunStageButton({
  project, stage, label, variant = "primary", disabled, disabledReason, options,
}: {
  project: Project; stage: RunStage; label?: string; variant?: "primary" | "secondary" | "outline";
  disabled?: boolean; disabledReason?: string; options?: Record<string, unknown>;
}) {
  const a = useAction();
  const running = project.stages.find((s) => s.stage === stage)?.status === "running";
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant={variant}
        disabled={!!disabled || running || a.busy !== null}
        title={disabledReason}
        onClick={() => a.exec(label ?? STAGE_LABEL[stage] ?? stage, () => api.run(project.id, stage, options))}
      >
        {running || a.busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
        {label ?? `${STAGE_LABEL[stage] ?? stage} 실행`}
      </Button>
      {a.errorText && <span className="max-w-xs text-right text-xs text-bad">{a.errorText}</span>}
    </div>
  );
}

/** Wraps a loaded artifact with loading / 404 / error states. */
export function ArtifactBoundary<T>({
  state, emptyTitle, emptyHint, children, action,
}: {
  state: { data: T | null; error: unknown; loading: boolean; notFound: boolean };
  emptyTitle: string; emptyHint: ReactNode; action?: ReactNode;
  children: (d: T) => ReactNode;
}) {
  if (state.loading && state.data === null) return <Loading />;
  if (state.error) return <ErrorBox error={state.error} title="아티팩트를 불러오지 못했습니다" />;
  if (state.notFound || state.data === null) {
    return <EmptyState title={emptyTitle}>{emptyHint}{action && <div className="mt-3 flex justify-center">{action}</div>}</EmptyState>;
  }
  return <>{children(state.data)}</>;
}

/* ---------------------------------------------------------------- JSON editor */
export function JsonEditor({
  projectId, name, value, onSaved, title = "고급: JSON 직접 편집",
}: { projectId: string; name: ArtifactName; value: unknown; onSaved?: () => void; title?: string }) {
  return (
    <Collapsible title={title}>
      <JsonEditorBody key={JSON.stringify(value).length + name} projectId={projectId} name={name} value={value} onSaved={onSaved} />
    </Collapsible>
  );
}

function JsonEditorBody({ projectId, name, value, onSaved }: { projectId: string; name: ArtifactName; value: unknown; onSaved?: () => void }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [parseErr, setParseErr] = useState<string | null>(null);
  const [apiErr, setApiErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const validate = (t: string) => {
    try { JSON.parse(t); setParseErr(null); return true; }
    catch (e) { setParseErr((e as Error).message); return false; }
  };
  const save = async () => {
    setSaved(false); setApiErr(null);
    if (!validate(text)) return;
    setBusy(true);
    try {
      await api.putArtifact(projectId, name, JSON.parse(text));
      setSaved(true);
      onSaved?.();
    } catch (e) { setApiErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        저장하면 서버가 스키마를 검증합니다. 저장된 아티팩트의 하위 단계는 <b>오래됨(stale)</b>으로 표시됩니다. 스키마 오류(422)는 아래에 표시됩니다.
      </p>
      <Textarea
        value={text}
        spellCheck={false}
        onChange={(e) => { setText(e.target.value); setSaved(false); validate(e.target.value); }}
        className="h-80 font-mono text-xs"
        aria-label={`${name} JSON`}
      />
      {parseErr && <p className="text-xs text-bad">JSON 문법 오류: {parseErr}</p>}
      <ErrorBox error={apiErr} title="서버가 저장을 거부했습니다" />
      <div className="flex items-center gap-3">
        <Button variant="primary" onClick={save} disabled={busy || !!parseErr}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}저장 (PUT)
        </Button>
        <Button variant="ghost" onClick={() => { setText(JSON.stringify(value, null, 2)); setParseErr(null); setApiErr(null); setSaved(false); }}>되돌리기</Button>
        {saved && <span className="flex items-center gap-1 text-xs text-ok"><CheckCircle2 className="h-3.5 w-3.5" />저장되었습니다</span>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- jobs */
export function JobRow({ job, compact = false }: { job: Job; compact?: boolean }) {
  const { refreshJobs, trackJob } = useApp();
  const a = useAction();
  const active = job.status === "queued" || job.status === "running";
  return (
    <div className="rounded-md border border-line bg-bg p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <JobBadge status={job.status} />
            <span className="truncate text-sm font-medium">{job.kind}{job.stage ? ` / ${STAGE_LABEL[job.stage] ?? job.stage}` : ""}</span>
          </div>
          <div className="mt-0.5 truncate text-xs text-muted">
            {job.project_id ? `${job.project_id} · ` : ""}{job.message ?? ""}
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          {active && (
            <Button size="sm" variant="outline" disabled={a.busy !== null} onClick={async () => { await a.exec("취소", () => api.cancelJob(job.id)); refreshJobs(); }}>취소</Button>
          )}
          {(job.status === "failed" || job.status === "cancelled") && (
            <Button size="sm" variant="outline" disabled={a.busy !== null}
              onClick={async () => { const r = await a.exec("재시도", () => api.retryJob(job.id)); if (r) trackJob(r as Job); }}>
              <RefreshCw className="h-3 w-3" />재시도
            </Button>
          )}
        </div>
      </div>
      {active && <Progress value={job.progress} className="mt-2" />}
      {!compact && job.error && <p className="mt-2 whitespace-pre-wrap break-words text-xs text-bad">{job.error}</p>}
      {a.errorText && <p className="mt-1 text-xs text-bad">{a.errorText}</p>}
      {!compact && job.metrics && job.status !== "queued" && (
        <p className="mt-1.5 text-[11px] text-muted">
          {job.metrics.exec_s != null && `실행 ${fmtDuration(job.metrics.exec_s)} `}
          {job.metrics.gpu ? "· GPU " : ""}
          {job.metrics.api_cost_usd ? `· API $${job.metrics.api_cost_usd.toFixed(3)} ` : ""}
          {job.metrics.cache_hit ? "· 캐시 적중" : ""}
        </p>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- media */
export function Video({ src, poster, className }: { src: string | null; poster?: string | null; className?: string }) {
  if (!src) return null;
  return <video src={src} poster={poster ?? undefined} controls preload="metadata" className={cn("w-full rounded-md", className)} />;
}

export function Section({ title, right, children, className }: { title: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <h2 className="text-sm font-semibold">{title}</h2>
        {right}
      </div>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
