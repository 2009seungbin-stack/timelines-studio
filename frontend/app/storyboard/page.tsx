"use client";

import { Clapperboard } from "lucide-react";
import { JsonEditor, ProjectPage, RunStageButton, useArtifact, ArtifactBoundary } from "@/components/common";
import { SceneList } from "@/components/scene-list";
import type { Project } from "@/lib/types";

function Body({ project }: { project: Project }) {
  const sb = useArtifact(project.id, "storyboard");
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start gap-2">
        <RunStageButton project={project} stage="storyboard" label="스토리보드 생성" variant="secondary" />
        <RunStageButton project={project} stage="previews" label="전체 프리뷰 렌더" variant="outline" />
        <RunStageButton project={project} stage="finals" label="전체 최종 렌더" variant="outline" />
      </div>
      <p className="text-xs text-muted">최종 렌더는 해당 장면의 프리뷰가 승인된 뒤에만 가능합니다. 승인은 사람이 프리뷰를 직접 확인한 뒤 눌러야 합니다.</p>
      <SceneList project={project} emptyText="스토리보드 단계를 실행하면 대본의 각 세그먼트가 장면으로 변환됩니다." />
      <ArtifactBoundary state={sb} emptyTitle="스토리보드 JSON이 없습니다" emptyHint="스토리보드를 생성하면 JSON 편집기를 사용할 수 있습니다.">
        {(d) => <JsonEditor projectId={project.id} name="storyboard" value={d} onSaved={sb.reload} />}
      </ArtifactBoundary>
    </div>
  );
}

export default function StoryboardPage() {
  return (
    <ProjectPage icon={Clapperboard} title="Storyboard"
      description="장면별 시간 범위, 렌더러, 분류, 전환과 렌더 상태를 확인하고 프리뷰를 승인한 뒤 최종 렌더를 실행합니다.">
      {(p) => <Body project={p} />}
    </ProjectPage>
  );
}
