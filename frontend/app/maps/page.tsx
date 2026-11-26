"use client";

import { Map } from "lucide-react";
import { ProjectPage } from "@/components/common";
import { SceneList } from "@/components/scene-list";

export default function MapsPage() {
  return (
    <ProjectPage icon={Map} title="Maps"
      description="renderer=map 장면의 프리뷰와 MapSpec(카메라, 영토, 라벨, 경로)을 확인합니다. 지도 렌더는 로컬 지도 엔진이 수행합니다.">
      {(p) => <SceneList project={p} renderer="map" emptyText="이 프로젝트에는 지도 장면이 없습니다. 스토리보드가 생성되면 MAP 유형 장면이 여기에 표시됩니다." />}
    </ProjectPage>
  );
}
