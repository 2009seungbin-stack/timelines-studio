"use client";

import { Languages } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Notice, ProjectPage, StageChip } from "@/components/common";
import type { Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

const TARGETS = [
  { code: "ko", label: "한국어" },
  { code: "ja", label: "일본어" },
  { code: "es", label: "스페인어" },
];

function Body({ project }: { project: Project }) {
  const locStages = project.stages.filter((s) => /locali[sz]|^loc[_-]|subtitle_|dub/i.test(s.stage));
  const forLang = (code: string) => locStages.find((s) => new RegExp(`(^|[_-])${code}($|[_-])`, "i").test(s.stage));
  const reported = locStages.length > 0;
  return (
    <div className="space-y-4">
      {!reported && (
        <Notice tone="warn">
          <b>Phase 3 (예정)</b> - 백엔드가 이 프로젝트의 현지화 단계를 보고하지 않습니다. 다국어 자막/더빙 생성은 아직 구현되지 않았거나 활성화되지 않았습니다.
          아래 상태는 표시만 하며 실행 버튼은 제공하지 않습니다.
        </Notice>
      )}
      <p className="text-xs text-muted">원본 언어: <b>{project.language}</b> · 프로젝트 상태: {project.state}</p>
      <div className="grid gap-3 md:grid-cols-3">
        {TARGETS.map((t) => {
          const st = forLang(t.code);
          return (
            <Card key={t.code}>
              <CardContent className="space-y-2">
                <div className="flex items-center justify-between"><div className="font-semibold">{t.label} <span className="font-mono text-xs text-muted">{t.code}</span></div>
                  {st ? <StageChip status={st.status} /> : <Badge>{reported ? "단계 없음" : "Phase 3"}</Badge>}</div>
                <p className="text-xs text-muted">{st ? `갱신 ${fmtDate(st.updated_at)}` : "아직 생성되지 않았습니다."}</p>
              </CardContent>
            </Card>
          );
        })}
      </div>
      {reported && (
        <div className="space-y-1 text-xs text-muted">
          <div>백엔드가 보고한 현지화 관련 단계:</div>
          {locStages.map((s) => <div key={s.stage} className="flex items-center gap-2"><code>{s.stage}</code><StageChip status={s.status} /></div>)}
        </div>
      )}
    </div>
  );
}

export default function LocalizationPage() {
  return (
    <ProjectPage icon={Languages} title="Localization" description="목표 언어(ko, ja, es)별 번역/자막/더빙 상태를 확인합니다. 번역본은 원어민 검수 전까지 초안입니다.">
      {(p) => <Body project={p} />}
    </ProjectPage>
  );
}
