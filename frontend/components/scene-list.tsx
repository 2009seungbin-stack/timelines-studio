"use client";

import { useState } from "react";
import { Check, Film, ImageOff, Loader2, X } from "lucide-react";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { ClassBadge, EmptyState, ErrorBox, Loading, Notice, sceneTypeColor, Video } from "@/components/common";
import { api, fileUrl } from "@/lib/api";
import { useAction, useApp, useAsync } from "@/lib/hooks";
import type { Project, RenderStatus, SceneRow } from "@/lib/types";
import { fmtClock } from "@/lib/utils";

const RS_TONE: Record<RenderStatus, Tone> = { pending: "neutral", preview: "info", preview_approved: "ok", final: "ok", failed: "bad" };
const RS_KO: Record<RenderStatus, string> = {
  pending: "렌더 전", preview: "프리뷰 완료 (승인 대기)", preview_approved: "프리뷰 승인됨", final: "최종 렌더 완료", failed: "실패",
};

export function useScenes(projectId: string) {
  const { jobsVersion, activeJobs } = useApp();
  return useAsync(() => api.scenes(projectId), [projectId, jobsVersion], activeJobs.length > 0 ? 4000 : undefined);
}

function SpecSummary({ s }: { s: SceneRow }) {
  const sp = s.spec as Record<string, unknown>;
  const len = (k: string) => (Array.isArray(sp[k]) ? (sp[k] as unknown[]).length : null);
  const bits: string[] = [];
  if (s.renderer === "map") {
    for (const [k, l] of [["camera", "카메라 키"], ["territories", "영토"], ["labels", "라벨"], ["routes", "경로"], ["captions", "자막"]] as const) {
      const n = len(k); if (n != null) bits.push(`${l} ${n}`);
    }
    if (sp.modern_borders) bits.push("현대 국경 표시");
    if (sp.tilt_3d) bits.push("3D 기울임");
  } else if (s.renderer === "blender") {
    for (const k of ["kind", "camera", "lighting", "quality", "seed", "era_label"]) if (sp[k] !== undefined && sp[k] !== "") bits.push(`${k}: ${String(sp[k])}`);
  } else {
    for (const k of ["style"]) if (sp[k] !== undefined) bits.push(`${k}: ${String(sp[k])}`);
    const n = len("lines"); if (n != null) bits.push(`줄 ${n}`);
  }
  return bits.length ? <p className="text-xs text-muted">{bits.join(" · ")}</p> : null;
}

function SceneCard({ project, s, showNote, onChanged }: { project: Project; s: SceneRow; showNote: boolean; onChanged: () => void }) {
  const a = useAction();
  const [note, setNote] = useState("");
  const [view, setView] = useState<"preview" | "final">(s.final_url ? "final" : "preview");
  const src = fileUrl(view === "final" ? s.final_url : s.preview_url);
  const thumb = fileUrl(s.thumb_url);
  const canFinal = s.render_status === "preview_approved" || s.render_status === "final";
  const hasBoth = !!s.preview_url && !!s.final_url;
  const approve = (approved: boolean) => a.exec(approved ? "프리뷰 승인" : "프리뷰 반려", async () => {
    const r = await api.approveScene(project.id, s.scene_id, approved, note); onChanged(); return r;
  });
  const busy = a.busy !== null;
  const conflict = a.error && (a.error as { status?: number }).status === 409;

  return (
    <Card className="overflow-hidden">
      <div className="grid gap-0 md:grid-cols-[minmax(0,360px)_1fr]">
        <div className="border-b border-line bg-black md:border-b-0 md:border-r">
          {src ? <Video src={src} poster={thumb} className="rounded-none" /> : thumb ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumb} alt={`${s.scene_id} 썸네일`} className="aspect-video w-full object-cover" />
          ) : (
            <div className="flex aspect-video w-full flex-col items-center justify-center gap-1 text-muted"><ImageOff className="h-6 w-6" /><span className="text-xs">렌더 결과 없음</span></div>
          )}
          {hasBoth && <div className="bg-panel p-1.5"><Tabs items={[{ value: "preview", label: "프리뷰" }, { value: "final", label: "최종" }]} value={view} onChange={(v) => setView(v as "preview" | "final")} /></div>}
        </div>
        <div className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold">{s.scene_id}</span>
            <span className="inline-flex items-center gap-1.5 rounded border border-line2 px-1.5 py-0.5 text-[11px]">
              <span className="h-2 w-2 rounded-full" style={{ background: sceneTypeColor(s.scene_type) }} />{s.scene_type}
            </span>
            <Badge>{s.renderer}</Badge>
            <ClassBadge value={s.classification} />
            <Badge tone={RS_TONE[s.render_status] ?? "neutral"}>{RS_KO[s.render_status] ?? s.render_status}</Badge>
            <span className="ml-auto font-mono text-xs text-muted">{fmtClock(s.start_s)} - {fmtClock(s.end_s)} ({(s.end_s - s.start_s).toFixed(1)}s)</span>
          </div>
          {s.transition && <p className="text-xs text-muted">전환: {s.transition.type} {s.transition.duration_s}s</p>}
          <p className="text-sm leading-relaxed text-fg/90">{s.narration || <span className="text-muted">내레이션 없음</span>}</p>
          <SpecSummary s={s} />
          {s.approval_note && <p className="text-xs text-muted">검토 메모: {s.approval_note}</p>}

          <div className="space-y-2 border-t border-line pt-3">
            {showNote && <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="검토 메모 (반려 시 사유를 적으세요)" aria-label="검토 메모" />}
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" disabled={busy} onClick={() => a.exec("프리뷰 렌더", () => api.renderScene(project.id, s.scene_id, "preview"))}>
                {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Film className="h-3 w-3" />}프리뷰 렌더
              </Button>
              <Button size="sm" variant="outline" disabled={busy || !s.preview_url} title={!s.preview_url ? "프리뷰를 먼저 렌더하세요" : undefined} onClick={() => approve(true)}>
                <Check className="h-3 w-3" />프리뷰 승인
              </Button>
              {showNote && (
                <Button size="sm" variant="outline" disabled={busy || !s.preview_url} onClick={() => approve(false)}><X className="h-3 w-3" />반려</Button>
              )}
              <Button size="sm" variant="primary" disabled={busy || !canFinal}
                title={!canFinal ? "프리뷰가 승인되어야 최종 렌더를 실행할 수 있습니다" : undefined}
                onClick={() => a.exec("최종 렌더", () => api.renderScene(project.id, s.scene_id, "final"))}>
                최종 렌더
              </Button>
            </div>
            {conflict ? <Notice tone="warn">{(a.error as Error).message} - 최종 렌더 전에 프리뷰 승인이 필요합니다.</Notice>
              : <ErrorBox error={a.error} title="요청이 실패했습니다" />}
            {a.message && !a.error && <p className="text-xs text-ok">{a.message}</p>}
          </div>
          <Collapsible title="스펙(spec) 보기">
            <pre className="max-h-80 overflow-auto rounded bg-bg p-3 font-mono text-[11px] leading-relaxed">{JSON.stringify(s.spec, null, 2)}</pre>
          </Collapsible>
        </div>
      </div>
    </Card>
  );
}

export function SceneList({
  project, renderer, showNote = false, emptyText,
}: { project: Project; renderer?: string; showNote?: boolean; emptyText: string }) {
  const st = useScenes(project.id);
  if (st.loading && !st.data) return <Loading />;
  if (st.error) return <ErrorBox error={st.error} title="장면 목록을 불러오지 못했습니다" />;
  const scenes = (st.data ?? []).filter((s) => !renderer || s.renderer === renderer);
  if (scenes.length === 0) return <EmptyState title="장면이 없습니다">{emptyText}</EmptyState>;
  return (
    <div className="space-y-4">
      {scenes.map((s) => <SceneCard key={s.scene_id} project={project} s={s} showNote={showNote} onChanged={st.reload} />)}
    </div>
  );
}
