"use client";

import { AudioLines } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorBox, Loading, ProjectPage, RunStageButton, Stat } from "@/components/common";
import { api, fileUrl } from "@/lib/api";
import { useApp, useAsync } from "@/lib/hooks";
import type { Project } from "@/lib/types";
import { fmtDuration } from "@/lib/utils";

function Body({ project }: { project: Project }) {
  const { jobsVersion } = useApp();
  const st = useAsync(() => api.audio(project.id), [project.id, jobsVersion]);
  if (st.loading && !st.data) return <Loading />;
  if (st.error) return <ErrorBox error={st.error} title="오디오 목록을 불러오지 못했습니다" />;
  const clips = st.data ?? [];
  if (clips.length === 0) return <EmptyState title="내레이션 클립이 없습니다">대본이 준비된 뒤 'TTS 실행'을 누르면 세그먼트별 내레이션 오디오가 생성됩니다. 설정의 TTS 제공자/음성도 확인하세요.</EmptyState>;
  const total = clips.reduce((a, c) => a + (c.duration_s || 0), 0);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3"><Stat label="클립 수" value={clips.length} /><Stat label="총 길이" value={fmtDuration(total)} /></div>
      <p className="text-xs text-muted">생성된 음성은 사람이 직접 들어 발음/억양을 확인하기 전까지 검수되지 않은 상태입니다.</p>
      {clips.map((c) => (
        <Card key={c.scene_id}>
          <CardContent className="grid gap-3 md:grid-cols-[minmax(0,320px)_1fr] md:items-center">
            <div>
              <div className="mb-1 flex items-center justify-between text-xs"><span className="font-mono font-semibold">{c.scene_id}</span><span className="text-muted">{fmtDuration(c.duration_s)} ({c.duration_s.toFixed(1)}s)</span></div>
              <audio src={fileUrl(c.file_url) ?? undefined} controls preload="none" className="w-full" />
            </div>
            <p className="text-sm leading-relaxed text-fg/90">{c.text}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function AudioPage() {
  return (
    <ProjectPage icon={AudioLines} title="Audio" description="장면별 내레이션 클립을 재생하고 TTS 단계를 실행합니다."
      actions={(p) => <RunStageButton project={p} stage="tts" label="TTS 실행" />}>
      {(p) => <Body project={p} />}
    </ProjectPage>
  );
}
