"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ExternalLink, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  ArtifactBoundary, ClassBadge, JsonEditor, ProjectPage, RunStageButton, Section, Stat, useArtifact,
} from "@/components/common";
import type { Project, ResearchDossier, Scenario } from "@/lib/types";

function Dossier({ project, d, reload }: { project: Project; d: ResearchDossier; reload: () => void }) {
  const [filter, setFilter] = useState("ALL");
  const [onlyReview, setOnlyReview] = useState(false);
  const srcMap = useMemo(() => new Map(d.sources.map((s) => [s.id, s])), [d.sources]);
  const claims = d.claims.filter((c) => (filter === "ALL" || c.classification === filter) && (!onlyReview || c.needs_review));
  const count = (k: string) => d.claims.filter((c) => c.classification === k).length;
  const review = d.claims.filter((c) => c.needs_review).length;
  const unverified = d.sources.filter((s) => !s.verified_by_fetch).length;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="출처" value={d.sources.length} sub={unverified ? `${unverified}개는 실제 페이지 확인 안 됨` : "모두 확인됨"} />
        <Stat label="사실 (FACT)" value={count("FACT")} />
        <Stat label="해석 (INTERPRETATION)" value={count("INTERPRETATION")} />
        <Stat label="추측 (SPECULATION)" value={count("SPECULATION")} />
        <Stat label="검토 필요" value={review} sub={`충돌 ${d.conflicts.length}건`} />
      </div>

      <Section title="주장 (Claims)" right={
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={onlyReview} onChange={(e) => setOnlyReview(e.target.checked)} />검토 필요만
          </label>
          <Select className="h-8 w-40" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="분류 필터">
            <option value="ALL">모든 분류</option><option value="FACT">FACT</option>
            <option value="INTERPRETATION">INTERPRETATION</option><option value="SPECULATION">SPECULATION</option>
          </Select>
        </div>}>
        {claims.length === 0 ? <p className="text-sm text-muted">조건에 맞는 주장이 없습니다.</p> : (
          <Table>
            <THead><TR><TH>ID</TH><TH>분류</TH><TH>주장</TH><TH>출처</TH><TH>비고</TH></TR></THead>
            <TBody>
              {claims.map((c) => (
                <TR key={c.id}>
                  <TD className="whitespace-nowrap font-mono text-xs">{c.id}</TD>
                  <TD><ClassBadge value={c.classification} /></TD>
                  <TD className="min-w-64">{c.text}</TD>
                  <TD className="text-xs">
                    {c.source_ids.length ? c.source_ids.map((id) => (
                      <span key={id} className="mr-1 inline-block rounded bg-panel2 px-1 font-mono" title={srcMap.get(id)?.title}>{id}</span>
                    )) : <span className="text-muted">없음</span>}
                  </TD>
                  <TD className="min-w-40 space-y-1 text-xs">
                    {c.needs_review && <Badge tone="warn"><AlertTriangle className="h-3 w-3" />검토 필요</Badge>}
                    {c.scenario_ref && <div className="text-muted">시나리오: {c.scenario_ref}</div>}
                    {c.conflict_note && <div className="text-warn">{c.conflict_note}</div>}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Section>

      <Section title="충돌 (Conflicts)">
        {d.conflicts.length === 0 ? <p className="text-sm text-muted">기록된 충돌이 없습니다.</p> : (
          <ul className="space-y-2">
            {d.conflicts.map((c, i) => (
              <li key={i} className="rounded-md border border-line bg-bg p-3 text-sm">
                <div className="mb-1 flex flex-wrap gap-1">{c.claim_ids.map((id) => <span key={id} className="rounded bg-panel2 px-1 font-mono text-xs">{id}</span>)}</div>
                <p>{c.description}</p>
                <p className="mt-1 text-xs">{c.resolution ? <span className="text-ok"><CheckCircle2 className="mr-1 inline h-3 w-3" />해결: {c.resolution}</span> : <span className="text-warn">미해결</span>}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="출처 (Sources)">
        <Table>
          <THead><TR><TH>ID</TH><TH>제목</TH><TH>유형</TH><TH>저자/발행</TH><TH>연도</TH><TH>확인</TH><TH>라이선스</TH></TR></THead>
          <TBody>
            {d.sources.map((s) => (
              <TR key={s.id}>
                <TD className="font-mono text-xs">{s.id}</TD>
                <TD className="min-w-56">
                  {s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">{s.title}<ExternalLink className="h-3 w-3" /></a> : s.title}
                  {s.notes && <div className="text-xs text-muted">{s.notes}</div>}
                </TD>
                <TD><Badge>{s.source_type}</Badge></TD>
                <TD className="text-xs">{[s.author, s.publisher].filter(Boolean).join(" / ") || "-"}</TD>
                <TD className="text-xs">{s.year ?? "-"}</TD>
                <TD>{s.verified_by_fetch ? <Badge tone="ok">페이지 확인됨</Badge> : <Badge tone="warn">미확인</Badge>}</TD>
                <TD className="text-xs">{s.license ?? "-"}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Section>
      <JsonEditor projectId={project.id} name="research_dossier" value={d} onSaved={reload} />
    </div>
  );
}

function ScenarioView({ project, s, reload }: { project: Project; s: Scenario; reload: () => void }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="시나리오" value={<span className="text-sm">{s.title}</span>} />
        <Stat label="분기점" value={s.divergence_year} sub={s.divergence} />
        <Stat label="범위" value={<span className="text-sm">{s.geographic_scope}</span>} />
        <Stat label="기간" value={`${s.horizon_start} ~ ${s.horizon_end}`} />
      </div>
      <Table>
        <THead><TR><TH>연도</TH><TH>사건</TH><TH>분류</TH><TH>분야</TH><TH>원인</TH></TR></THead>
        <TBody>
          {[...s.events].sort((a, b) => a.year - b.year).map((e) => (
            <TR key={e.id}>
              <TD className="whitespace-nowrap font-mono text-xs">{e.year}</TD>
              <TD className="min-w-64"><div className="font-medium">{e.title}</div><div className="text-xs text-muted">{e.description}</div></TD>
              <TD><ClassBadge value={e.classification} /></TD><TD className="text-xs">{e.domain}</TD>
              <TD className="font-mono text-xs">{e.caused_by.join(", ") || "-"}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <JsonEditor projectId={project.id} name="scenario" value={s} onSaved={reload} title="고급: 시나리오 JSON 편집" />
    </div>
  );
}

function Body({ project }: { project: Project }) {
  const dossier = useArtifact(project.id, "research_dossier");
  const scenario = useArtifact(project.id, "scenario");
  return (
    <div className="space-y-6">
      <ArtifactBoundary state={dossier} emptyTitle="리서치 자료가 아직 없습니다"
        emptyHint="오른쪽 위의 '리서치 실행' 버튼으로 research 단계를 실행하세요. 결과는 출처가 연결된 주장 목록으로 저장됩니다.">
        {(d) => <Dossier project={project} d={d} reload={dossier.reload} />}
      </ArtifactBoundary>
      <Section title="시나리오 (Scenario)" right={<RunStageButton project={project} stage="scenario" variant="outline" label="시나리오 실행" />}>
        <ArtifactBoundary state={scenario} emptyTitle="시나리오가 아직 없습니다" emptyHint="리서치를 검토한 뒤 시나리오 단계를 실행하세요.">
          {(s) => <ScenarioView project={project} s={s} reload={scenario.reload} />}
        </ArtifactBoundary>
      </Section>
    </div>
  );
}

export default function ResearchPage() {
  return (
    <ProjectPage icon={Search} title="Research"
      description="출처와 주장을 사실 / 해석 / 추측으로 구분해 검토합니다. 출처 없는 사실 주장은 저장되지 않습니다."
      actions={(p) => <RunStageButton project={p} stage="research" label="리서치 실행" />}>
      {(p) => <Body project={p} />}
    </ProjectPage>
  );
}
