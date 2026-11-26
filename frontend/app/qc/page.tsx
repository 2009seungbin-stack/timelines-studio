"use client";

import { AlertTriangle, CheckCircle2, CircleHelp, ShieldCheck, XCircle } from "lucide-react";
import { Badge, type Tone } from "@/components/ui/badge";
import { Collapsible } from "@/components/ui/collapsible";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ArtifactBoundary, JsonEditor, Notice, ProjectPage, RunStageButton, Section, Stat, useArtifact } from "@/components/common";
import type { Project, QCReport } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

const ST: Record<string, { tone: Tone; label: string; icon: typeof XCircle }> = {
  pass: { tone: "ok", label: "통과", icon: CheckCircle2 },
  fail: { tone: "bad", label: "실패", icon: XCircle },
  warn: { tone: "warn", label: "경고", icon: AlertTriangle },
  manual: { tone: "violet", label: "수동 확인", icon: CircleHelp },
};

function Report({ project, r, reload }: { project: Project; r: QCReport; reload: () => void }) {
  const n = (s: string) => r.checks.filter((c) => c.status === s).length;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="기술 검사" value={r.technical_pass ? <span className="text-ok">통과</span> : <span className="text-bad">미통과</span>} sub="자동 검사 기준" />
        <Stat label="통과" value={n("pass")} /><Stat label="실패" value={n("fail")} />
        <Stat label="경고" value={n("warn")} /><Stat label="수동 확인" value={n("manual")} />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
        <span>대상: <code>{r.output}</code></span><span>생성 {fmtDate(r.created_at)}</span>
        <span className="inline-flex items-center gap-1">사용자 승인: <Badge tone={r.user_approval === "approved" ? "ok" : r.user_approval === "rejected" ? "bad" : "neutral"}>
          {{ unverified: "미확인", approved: "승인됨", rejected: "반려됨" }[r.user_approval]}</Badge></span>
      </div>

      <Section title="검사 항목">
        <Table>
          <THead><TR><TH>결과</TH><TH>검사</TH><TH>상세</TH><TH>데이터</TH></TR></THead>
          <TBody>
            {r.checks.map((c) => {
              const s = ST[c.status] ?? ST.manual; const Icon = s.icon;
              return (
                <TR key={c.id}>
                  <TD><Badge tone={s.tone}><Icon className="h-3 w-3" />{s.label}</Badge></TD>
                  <TD className="min-w-48"><div className="font-medium">{c.name}</div><div className="font-mono text-[10px] text-muted">{c.id}</div></TD>
                  <TD className="min-w-64 text-sm text-fg/85">{c.details || "-"}</TD>
                  <TD>{Object.keys(c.data ?? {}).length > 0 ? (
                    <Collapsible title="보기"><pre className="max-h-48 overflow-auto font-mono text-[11px]">{JSON.stringify(c.data, null, 2)}</pre></Collapsible>) : <span className="text-muted">-</span>}</TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </Section>

      <Section title="사람이 직접 확인해야 할 항목">
        {r.human_review_required.length === 0 ? <p className="text-sm text-muted">보고된 항목이 없습니다. 그래도 사람의 시청 확인은 필요합니다.</p> : (
          <ul className="list-disc space-y-1 pl-5 text-sm">{r.human_review_required.map((h, i) => <li key={i}>{h}</li>)}</ul>
        )}
      </Section>
      <JsonEditor projectId={project.id} name="qc_report" value={r} onSaved={reload} />
    </div>
  );
}

function Body({ project }: { project: Project }) {
  const st = useArtifact(project.id, "qc_report");
  return (
    <div className="space-y-4">
      <Notice tone="warn">
        자동 QC는 사람이 영상을 보고 듣는 것이 아니며 승인도 아닙니다. 'technical_pass'는 측정 가능한 기술 항목(해상도, 길이, 오디오 레벨 등)만 의미합니다.
        사실 정확성, 역사적 고증, 연출 품질은 반드시 사람이 확인해야 합니다.
      </Notice>
      <ArtifactBoundary state={st} emptyTitle="QC 보고서가 아직 없습니다" emptyHint="최종 영상이 합성된 뒤 'QC 실행'으로 자동 검사를 수행하세요."
        action={<RunStageButton project={project} stage="qa" label="QC 실행" />}>
        {(r) => <Report project={project} r={r} reload={st.reload} />}
      </ArtifactBoundary>
    </div>
  );
}

export default function QCPage() {
  return (
    <ProjectPage icon={ShieldCheck} title="Quality Control" description="자동 검사 결과와 사람이 확인해야 할 항목을 모아 봅니다."
      actions={(p) => <RunStageButton project={p} stage="qa" label="QC 실행" />}>
      {(p) => <Body project={p} />}
    </ProjectPage>
  );
}
