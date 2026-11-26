"use client";

import { ScrollText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  ArtifactBoundary, ClassBadge, JsonEditor, ProjectPage, RunStageButton, Stat, sceneTypeColor, useArtifact,
} from "@/components/common";
import type { Project, Script } from "@/lib/types";
import { fmtDuration } from "@/lib/utils";

const SECTION_KO: Record<string, string> = {
  hook: "후킹", background: "배경", real_history: "실제 역사", divergence: "분기점", impact: "영향",
  outcome: "결과", limits: "한계", conclusion: "결론",
};

function ScriptView({ project, s, reload }: { project: Project; s: Script; reload: () => void }) {
  const total = s.segments.reduce((a, g) => a + (g.est_duration_s || 0), 0);
  const ratio = s.target_duration_s > 0 ? total / s.target_duration_s : 0;
  const diff = total - s.target_duration_s;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="제목" value={<span className="text-sm">{s.title}</span>} />
        <Stat label="예상 총 길이" value={fmtDuration(total)} sub={`${s.segments.length}개 세그먼트 · ${s.words_per_minute} wpm`} />
        <Stat label="목표 길이" value={fmtDuration(s.target_duration_s)} />
        <Stat label="차이" value={`${diff >= 0 ? "+" : "-"}${fmtDuration(Math.abs(diff))}`} sub={`목표 대비 ${(ratio * 100).toFixed(0)}%`} />
      </div>
      <Progress value={ratio} tone={ratio > 1.1 || ratio < 0.8 ? "warn" : "ok"} />
      <div className="space-y-3">
        {s.segments.map((g, i) => (
          <Card key={g.scene_id}>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-muted">#{i + 1}</span>
                <span className="font-mono text-sm font-semibold">{g.scene_id}</span>
                <Badge tone="accent">{SECTION_KO[g.section] ?? g.section}</Badge>
                <span className="inline-flex items-center gap-1.5 rounded border border-line2 px-1.5 py-0.5 text-[11px]">
                  <span className="h-2 w-2 rounded-full" style={{ background: sceneTypeColor(g.scene_type) }} />{g.scene_type}
                </span>
                <ClassBadge value={g.classification} />
                <span className="ml-auto text-xs tabular-nums text-muted">{fmtDuration(g.est_duration_s)}</span>
              </div>
              <div>
                <div className="mb-0.5 text-[11px] font-medium text-muted">내레이션</div>
                <p className="leading-relaxed">{g.narration}</p>
              </div>
              <div>
                <div className="mb-0.5 text-[11px] font-medium text-muted">화면 설명</div>
                <p className="text-sm text-fg/80">{g.visual_description}</p>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                <span>출처: {g.source_ids.length ? g.source_ids.map((x) => <code key={x} className="mr-1 rounded bg-panel2 px-1">{x}</code>) : "없음"}</span>
                {g.claim_ids.length > 0 && <span>주장: {g.claim_ids.join(", ")}</span>}
                {g.required_assets.length > 0 && <span>에셋: {g.required_assets.join(", ")}</span>}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <JsonEditor projectId={project.id} name="script" value={s} onSaved={reload} />
    </div>
  );
}

function Body({ project }: { project: Project }) {
  const st = useArtifact(project.id, "script");
  return (
    <ArtifactBoundary state={st} emptyTitle="대본이 아직 없습니다"
      emptyHint="시나리오가 준비되면 '대본 실행'으로 세그먼트별 내레이션과 화면 설명을 생성합니다.">
      {(s) => <ScriptView project={project} s={s} reload={st.reload} />}
    </ArtifactBoundary>
  );
}

export default function ScriptsPage() {
  return (
    <ProjectPage icon={ScrollText} title="Scripts"
      description="세그먼트별 내레이션, 화면 설명, 출처와 예상 길이를 검토합니다. 대본은 사람이 검토하기 전까지 승인되지 않은 초안입니다."
      actions={(p) => <RunStageButton project={p} stage="script" label="대본 실행" />}>
      {(p) => <Body project={p} />}
    </ProjectPage>
  );
}
