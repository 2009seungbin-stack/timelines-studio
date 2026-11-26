import { StageChip, STAGE_LABEL } from "@/components/common";
import type { Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

export function StageGrid({ project }: { project: Project }) {
  if (!project.stages?.length) return <p className="text-xs text-muted">단계 정보가 없습니다.</p>;
  return (
    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 xl:grid-cols-4">
      {project.stages.map((s) => (
        <div key={s.stage} className="flex items-center justify-between gap-2 rounded border border-line bg-bg px-2 py-1" title={s.updated_at ? `갱신 ${fmtDate(s.updated_at)}` : undefined}>
          <span className="truncate text-[11px] text-muted">{STAGE_LABEL[s.stage] ?? s.stage}</span>
          <StageChip status={s.status} />
        </div>
      ))}
    </div>
  );
}
