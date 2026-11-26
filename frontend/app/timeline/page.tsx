"use client";

import { useEffect, useState } from "react";
import { Download, Film } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  ArtifactBoundary, JsonEditor, ProjectPage, RunStageButton, sceneTypeColor, Section, Stat, useArtifact, Video,
} from "@/components/common";
import { API_BASE, api, fileUrl } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Project, Timeline } from "@/lib/types";
import { fmtClock, fmtDuration } from "@/lib/utils";

function Lane({ label, children, height = 28 }: { label: string; children: React.ReactNode; height?: number }) {
  return (
    <div className="flex items-stretch gap-2">
      <div className="w-16 shrink-0 pt-1 text-right text-[11px] text-muted">{label}</div>
      <div className="relative flex-1 rounded bg-bg" style={{ height }}>{children}</div>
    </div>
  );
}

function pct(v: number, total: number) { return `${Math.max(0, Math.min(100, (v / total) * 100))}%`; }

/** Probe sibling output files next to the final MP4 (SRT / WAV / JSON / XML) with a 1-byte range request. */
function useSiblingOutputs(finalUrl: string | null) {
  const [found, setFound] = useState<{ ext: string; url: string }[]>([]);
  useEffect(() => {
    setFound([]);
    if (!finalUrl) return;
    let alive = true;
    const base = finalUrl.replace(/\.[^./]+$/, "");
    Promise.all(["srt", "wav", "json", "xml"].map(async (ext) => {
      const url = `${base}.${ext}`;
      try {
        const r = await fetch(`${API_BASE}${url}`, { headers: { Range: "bytes=0-0" }, cache: "no-store" });
        return r.ok ? { ext, url } : null;
      } catch { return null; }
    })).then((r) => { if (alive) setFound(r.filter((x): x is { ext: string; url: string } => x !== null)); });
    return () => { alive = false; };
  }, [finalUrl]);
  return found;
}

function TimelineView({ project, t, types, reload }: { project: Project; t: Timeline; types: Map<string, string>; reload: () => void }) {
  const total = Math.max(t.duration_s, ...t.clips.map((c) => c.start_s + c.duration_s), 0.001);
  const ticks = Array.from({ length: Math.min(40, Math.floor(total / Math.max(1, Math.ceil(total / 20))) + 1) }, (_, i) => i * Math.max(1, Math.ceil(total / 20)));
  const roles = (["narration", "music", "sfx"] as const).filter((r) => t.audio.some((a) => a.role === r));
  const rel = (f: string) => (/^([a-zA-Z]:|\/)/.test(f) ? null : fileUrl(`/files/${encodeURIComponent(project.id)}/${f.replace(/\\/g, "/")}`));
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="제목" value={<span className="text-sm">{t.title}</span>} />
        <Stat label="길이" value={fmtDuration(t.duration_s)} />
        <Stat label="해상도" value={`${t.width}x${t.height}`} sub={`${t.fps} fps`} />
        <Stat label="클립 / 오디오" value={`${t.clips.length} / ${t.audio.length}`} />
        <Stat label="자막 큐" value={t.subtitles.length} sub={t.language} />
      </div>

      <Section title="타임라인">
        <div className="overflow-x-auto">
          <div className="min-w-[640px] space-y-1.5">
            <Lane label="" height={18}>
              {ticks.map((s) => (
                <div key={s} className="absolute top-0 h-full border-l border-line2 pl-1 text-[10px] text-muted" style={{ left: pct(s, total) }}>{fmtClock(s).replace(/\.0$/, "")}</div>
              ))}
            </Lane>
            <Lane label="영상" height={44}>
              {t.clips.map((c, i) => {
                const ty = types.get(c.scene_id);
                return (
                  <div key={`${c.scene_id}-${i}`} title={`${c.scene_id}${ty ? ` (${ty})` : ""}\n${fmtClock(c.start_s)} +${c.duration_s.toFixed(1)}s\n전환: ${c.transition_in.type} ${c.transition_in.duration_s}s`}
                    className="absolute top-1 bottom-1 overflow-hidden rounded border border-black/40 px-1 text-[10px] font-medium text-black/80"
                    style={{ left: pct(c.start_s, total), width: pct(c.duration_s, total), background: ty ? sceneTypeColor(ty) : "#64748b" }}>
                    {c.scene_id}
                  </div>
                );
              })}
            </Lane>
            {roles.map((r) => (
              <Lane key={r} label={r === "narration" ? "내레이션" : r === "music" ? "음악" : "효과음"}>
                {t.audio.filter((a) => a.role === r).map((a, i) => (
                  <div key={i} title={`${a.file}\n시작 ${fmtClock(a.start_s)} · ${a.gain_db} dB`}
                    className="absolute top-1 bottom-1 rounded bg-ok/40 border border-ok/60" style={{ left: pct(a.start_s, total), width: "0.6%", minWidth: 4 }} />
                ))}
              </Lane>
            ))}
            <Lane label="자막">
              {t.subtitles.map((s) => (
                <div key={s.index} title={`${fmtClock(s.start_s)}-${fmtClock(s.end_s)}\n${s.text}`}
                  className="absolute top-1 bottom-1 rounded-sm bg-warn/45 border border-warn/70"
                  style={{ left: pct(s.start_s, total), width: pct(s.end_s - s.start_s, total), minWidth: 2 }} />
              ))}
            </Lane>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {Array.from(new Set(t.clips.map((c) => types.get(c.scene_id)).filter((x): x is string => !!x))).map((ty) => (
            <span key={ty} className="inline-flex items-center gap-1.5 text-[11px] text-muted"><span className="h-2 w-2 rounded-sm" style={{ background: sceneTypeColor(ty) }} />{ty}</span>
          ))}
          {t.clips.some((c) => !types.get(c.scene_id)) && <span className="text-[11px] text-muted">회색 = 장면 유형을 알 수 없음</span>}
        </div>
        <p className="mt-2 text-[11px] text-muted">오디오 블록은 시작 위치만 표시됩니다 (타임라인 JSON에 오디오 길이가 없습니다).</p>
      </Section>

      <Section title="오디오 파일 / 자막 큐">
        <div className="grid gap-4 lg:grid-cols-2">
          <ul className="space-y-1 text-xs">
            {t.audio.map((a, i) => {
              const u = rel(a.file);
              return <li key={i} className="flex items-center gap-2"><Badge>{a.role}</Badge>
                {u ? <a className="truncate text-accent hover:underline" href={u} target="_blank" rel="noreferrer">{a.file}</a> : <span className="truncate">{a.file}</span>}
                <span className="ml-auto shrink-0 text-muted">{fmtClock(a.start_s)} · {a.gain_db} dB</span></li>;
            })}
            {t.audio.length === 0 && <li className="text-muted">오디오 트랙이 없습니다.</li>}
          </ul>
          <ul className="max-h-64 space-y-1 overflow-y-auto text-xs">
            {t.subtitles.map((s) => <li key={s.index}><span className="font-mono text-muted">{fmtClock(s.start_s)}</span> {s.text}</li>)}
            {t.subtitles.length === 0 && <li className="text-muted">자막 큐가 없습니다.</li>}
          </ul>
        </div>
      </Section>
      <JsonEditor projectId={project.id} name="timeline" value={t} onSaved={reload} />
    </div>
  );
}

function Body({ project }: { project: Project }) {
  const st = useArtifact(project.id, "timeline");
  const scenes = useAsync(() => api.scenes(project.id), [project.id]);
  const types = new Map<string, string>((scenes.data ?? []).map((s) => [s.scene_id, s.scene_type]));
  const outputs = useSiblingOutputs(project.final_url);
  return (
    <div className="space-y-5">
      {project.final_url ? (
        <Section title="최종 MP4" right={<div className="flex gap-2">{outputs.map((o) => (
          <a key={o.ext} href={fileUrl(o.url) ?? "#"} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded border border-line2 px-2 py-1 text-xs hover:bg-panel2"><Download className="h-3 w-3" />.{o.ext}</a>
        ))}</div>}>
          <Video src={fileUrl(project.final_url)} className="max-w-3xl" />
          <p className="mt-2 text-xs text-muted">자동 합성 결과입니다. 사람이 처음부터 끝까지 재생하며 확인하기 전에는 검수 완료가 아닙니다.</p>
        </Section>
      ) : null}
      <ArtifactBoundary state={st} emptyTitle="타임라인이 아직 없습니다"
        emptyHint="내레이션(TTS)과 최종 렌더가 끝난 뒤 '합성/편집' 단계를 실행하면 타임라인이 만들어집니다."
        action={<RunStageButton project={project} stage="compose" label="합성/편집 실행" />}>
        {(t) => <TimelineView project={project} t={t} types={types} reload={st.reload} />}
      </ArtifactBoundary>
    </div>
  );
}

export default function TimelinePage() {
  return (
    <ProjectPage icon={Film} title="Timeline"
      description="장면 클립, 오디오, 자막 큐로 구성된 최종 편집 타임라인과 출력 파일입니다."
      actions={(p) => <RunStageButton project={p} stage="compose" label="합성/편집 실행" />}>
      {(p) => <Body project={p} />}
    </ProjectPage>
  );
}
