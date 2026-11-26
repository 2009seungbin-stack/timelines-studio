"use client";

import { Box } from "lucide-react";
import { ProjectPage } from "@/components/common";
import { SceneList } from "@/components/scene-list";

export default function Studio3DPage() {
  return (
    <ProjectPage icon={Box} title="3D Studio"
      description="renderer=blender 장면을 검토합니다. 프리뷰를 직접 보고 승인 또는 반려(메모 포함)한 뒤 최종 렌더를 실행하세요. GPU 작업은 한 번에 하나씩 실행됩니다.">
      {(p) => <SceneList project={p} renderer="blender" showNote emptyText="이 프로젝트에는 Blender 장면이 없습니다." />}
    </ProjectPage>
  );
}
