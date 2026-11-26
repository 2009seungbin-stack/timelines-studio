"use client";

import { Fragment } from "react";
import { Send } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ArtifactBoundary, JsonEditor, Notice, ProjectPage, RunStageButton, Section, useArtifact } from "@/components/common";
import type { Project, PublishPackage } from "@/lib/types";

function Pkg({ project, p, reload }: { project: Project; p: PublishPackage; reload: () => void }) {
  const dis = p.synthetic_content_disclosure ?? {};
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">언어</span><Badge>{p.language}</Badge>
        <span className="ml-3 text-muted">업로드 승인 플래그</span>
        <Badge tone={p.approved_for_upload ? "warn" : "neutral"}>{p.approved_for_upload ? "approved_for_upload = true" : "false"}</Badge>
      </div>
      <Section title="제목 후보">
        <ol className="list-decimal space-y-1 pl-5">{p.title_candidates.map((t, i) => <li key={i}>{t}</li>)}</ol>
        {p.title_candidates.length === 0 && <p className="text-sm text-muted">후보가 없습니다.</p>}
      </Section>
      <Section title="설명"><pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{p.description}</pre></Section>
      <Section title="챕터">
        {p.chapters.length === 0 ? <p className="text-sm text-muted">챕터가 없습니다.</p> : (
          <Table><THead><TR>{Object.keys(p.chapters[0]).map((k) => <TH key={k}>{k}</TH>)}</TR></THead>
            <TBody>{p.chapters.map((c, i) => <TR key={i}>{Object.keys(p.chapters[0]).map((k) => <TD key={k}>{String(c[k] ?? "")}</TD>)}</TR>)}</TBody></Table>
        )}
      </Section>
      <Section title="태그"><div className="flex flex-wrap gap-1.5">{p.tags.map((t) => <Badge key={t}>{t}</Badge>)}{p.tags.length === 0 && <span className="text-sm text-muted">태그가 없습니다.</span>}</div></Section>
      <Section title="출처 블록 (설명란용)"><pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{p.sources_block || "-"}</pre></Section>
      <Section title="합성 콘텐츠 고지 (Synthetic content disclosure)">
        {Object.keys(dis).length === 0 ? <p className="text-sm text-warn">고지 정보가 비어 있습니다. 업로드 전에 반드시 채워야 합니다.</p> : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            {Object.entries(dis).map(([k, v]) => <Fragment key={k}><dt className="text-muted">{k}</dt><dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd></Fragment>)}
          </dl>
        )}
      </Section>
      <JsonEditor projectId={project.id} name="publish_package" value={p} onSaved={reload} />
    </div>
  );
}

function Body({ project }: { project: Project }) {
  const st = useArtifact(project.id, "publish_package");
  return (
    <div className="space-y-4">
      <Notice tone="info">
        YouTube 업로드는 이 화면에서 제공하지 않습니다. 업로드에는 <b>사용자의 명시적 승인</b>과 OAuth 설정이 필요합니다. 여기서는 게시 패키지만 준비하고 검토합니다.
        <div className="mt-2"><Button size="sm" variant="outline" disabled title="사용자 승인 및 OAuth 설정이 필요합니다">업로드 (사용 불가)</Button></div>
      </Notice>
      <ArtifactBoundary state={st} emptyTitle="게시 패키지가 아직 없습니다" emptyHint="QC까지 마친 뒤 '게시 준비 실행'으로 제목 후보, 설명, 챕터, 태그를 만듭니다."
        action={<RunStageButton project={project} stage="publish_prep" label="게시 준비 실행" />}>
        {(p) => <Pkg project={project} p={p} reload={st.reload} />}
      </ArtifactBoundary>
    </div>
  );
}

export default function PublishingPage() {
  return (
    <ProjectPage icon={Send} title="Publishing" description="제목 후보, 설명, 챕터, 태그, 출처 블록, 합성 콘텐츠 고지를 검토합니다."
      actions={(p) => <RunStageButton project={p} stage="publish_prep" label="게시 준비 실행" />}>
      {(p) => <Body project={p} />}
    </ProjectPage>
  );
}
