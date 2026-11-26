"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { FolderKanban } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Collapsible } from "@/components/ui/collapsible";
import { EmptyState, ErrorBox, Loading, PageHeader, RunStageButton, StateChip, Stat, Video } from "@/components/common";
import { StageGrid } from "@/components/stage-grid";
import { api, fileUrl } from "@/lib/api";
import { useAction, useApp, useAsync } from "@/lib/hooks";
import { PROJECT_STATES, RUN_STAGES } from "@/lib/types";
import { fmtDate, fmtDuration, fmtUsd } from "@/lib/utils";

function Detail({ id }: { id: string }) {
  const { projects, projectsLoading, setProjectId, reloadProjects, jobsVersion } = useApp();
  const project = projects.find((p) => p.id === id) ?? null;
  useEffect(() => { if (project) setProjectId(project.id); }, [project, setProjectId]);
  const history = useAsync(() => api.history(id), [id, jobsVersion]);
  const costs = useAsync(() => api.costs(id), [id, jobsVersion]);
  const a = useAction();
  const [target, setTarget] = useState("");

  if (projectsLoading) return <Loading />;
  if (!project) return <EmptyState title="프로젝트를 찾을 수 없습니다">id={id}</EmptyState>;
  return (
    <div className="space-y-5">
      <PageHeader icon={FolderKanban} title={project.title} description={project.topic} actions={<StateChip state={project.state} />} />
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="포맷" value={project.format} />
        <Stat label="목표 길이" value={fmtDuration(project.target_duration_s)} />
        <Stat label="언어" value={project.language} />
        <Stat label="비용" value={`${fmtUsd(project.spent_usd)} / ${fmtUsd(project.budget_usd)}`} />
      </div>

      <Card>
        <CardHeader><CardTitle>단계</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <StageGrid project={project} />
          <div className="flex flex-wrap gap-2">
            {RUN_STAGES.map((s) => <RunStageButton key={s} project={project} stage={s} variant="outline" />)}
          </div>
        </CardContent>
      </Card>

      {project.final_url ? (
        <Card><CardHeader><CardTitle>최종 영상</CardTitle></CardHeader>
          <CardContent><Video src={fileUrl(project.final_url)} className="max-w-3xl" />
            <p className="mt-2 text-xs text-muted">자동 렌더 결과입니다. 사람이 직접 보고 승인한 것이 아닙니다.</p></CardContent></Card>
      ) : null}

      <Collapsible title="고급: 상태 수동 전환 (기록됨)">
        <div className="flex items-end gap-2">
          <div className="w-60">
            <Select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="새 상태">
              <option value="">상태 선택...</option>
              {PROJECT_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
          </div>
          <Button variant="outline" disabled={!target || a.busy !== null}
            onClick={async () => { await a.exec("상태 전환", () => api.setState(project.id, target)); reloadProjects(); }}>전환</Button>
        </div>
        <div className="mt-2"><ErrorBox error={a.error} title="상태를 바꾸지 못했습니다" /></div>
      </Collapsible>

      <Card>
        <CardHeader><CardTitle>비용 내역</CardTitle></CardHeader>
        <CardContent>
          {costs.error ? <ErrorBox error={costs.error} /> : null}
          {costs.data && costs.data.entries.length === 0 && <p className="text-sm text-muted">기록된 비용이 없습니다.</p>}
          {costs.data && costs.data.entries.length > 0 && (
            <Table>
              <THead><TR><TH>시각</TH><TH>백엔드</TH><TH>모델</TH><TH>작업</TH><TH>비용</TH><TH>토큰 in/out</TH></TR></THead>
              <TBody>
                {costs.data.entries.map((e, i) => (
                  <TR key={i}><TD>{fmtDate(e.at)}</TD><TD>{e.backend}</TD><TD>{e.model}</TD><TD>{e.task}</TD>
                    <TD>{fmtUsd(e.cost_usd)}{e.estimated && <span className="ml-1 text-xs text-muted">(추정)</span>}</TD>
                    <TD>{e.tokens_in}/{e.tokens_out}</TD></TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>감사 로그</CardTitle></CardHeader>
        <CardContent>
          {history.error ? <ErrorBox error={history.error} /> : null}
          {history.data && history.data.length === 0 && <p className="text-sm text-muted">기록이 없습니다.</p>}
          {history.data && history.data.length > 0 && (
            <Table>
              <THead><TR><TH>시각</TH><TH>주체</TH><TH>동작</TH><TH>상세</TH></TR></THead>
              <TBody>
                {history.data.map((h, i) => (
                  <TR key={i}><TD className="whitespace-nowrap">{fmtDate(h.at)}</TD><TD>{h.actor}</TD><TD>{h.action}</TD>
                    <TD className="max-w-md break-words text-xs text-muted">{typeof h.detail === "string" ? h.detail : JSON.stringify(h.detail)}</TD></TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Inner() {
  const id = useSearchParams().get("id");
  if (!id) return <EmptyState title="프로젝트 id가 없습니다">주소에 <code>?id=...</code> 가 필요합니다. Dashboard에서 프로젝트를 선택하세요.</EmptyState>;
  return <Detail id={id} />;
}

export default function ProjectPage() {
  return <Suspense fallback={<Loading />}><Inner /></Suspense>;
}
