"use client";

import Link from "next/link";
import { Cpu, HardDrive, LayoutDashboard, Wallet } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  EmptyState, ErrorBox, JobRow, Loading, PageHeader, StateChip, Stat,
} from "@/components/common";
import { StageGrid } from "@/components/stage-grid";
import { api } from "@/lib/api";
import { useApp, useAsync } from "@/lib/hooks";
import type { Project } from "@/lib/types";
import { fmtDuration, fmtUsd } from "@/lib/utils";

function ProjectCard({ p }: { p: Project }) {
  const over = p.budget_usd > 0 && p.spent_usd > p.budget_usd;
  return (
    <Card>
      <CardHeader>
        <div className="min-w-0">
          <Link href={`/project/?id=${encodeURIComponent(p.id)}`} className="block truncate text-sm font-semibold hover:text-accent">{p.title}</Link>
          <div className="truncate text-xs text-muted">{p.topic}</div>
        </div>
        <StateChip state={p.state} />
      </CardHeader>
      <CardContent className="space-y-3">
        <StageGrid project={p} />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          <span>{p.format}</span>
          <span>목표 {fmtDuration(p.target_duration_s)}</span>
          <span>{p.language}</span>
          <span>비용 {fmtUsd(p.spent_usd)} / {fmtUsd(p.budget_usd)}</span>
          {over && <Badge tone="bad">예산 초과</Badge>}
        </div>
      </CardContent>
    </Card>
  );
}

function SystemPanel() {
  const sys = useAsync(() => api.system(), [], 15000);
  const d = sys.data;
  return (
    <Card>
      <CardHeader><CardTitle>시스템</CardTitle><Cpu className="h-4 w-4 text-muted" /></CardHeader>
      <CardContent className="space-y-3">
        {sys.error ? <ErrorBox error={sys.error} title="시스템 정보를 불러오지 못했습니다" /> : null}
        {sys.loading && !d && <Loading />}
        {d && (
          <>
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {(["blender", "ffmpeg", "node", "claude_cli", "codex_cli"] as const).map((k) => {
                const t = d.tools[k];
                return (
                  <div key={k} className="flex items-center justify-between gap-2 rounded border border-line bg-bg px-2.5 py-1.5" title={t?.path ?? undefined}>
                    <span className="text-xs">{k}</span>
                    {t ? <Badge tone={t.ok ? "ok" : "bad"}>{t.ok ? (t.version ? t.version.slice(0, 18) : "사용 가능") : "없음"}</Badge> : <Badge>알 수 없음</Badge>}
                  </div>
                );
              })}
            </div>
            <div className="flex items-center gap-2 text-xs">
              <Cpu className="h-3.5 w-3.5 text-muted" />
              <span className="text-muted">GPU</span>
              <span>{d.gpu ?? "감지되지 않음"}</span>
              <Badge tone={d.queue.gpu_busy ? "warn" : "ok"}>{d.queue.gpu_busy ? "사용 중" : "유휴"}</Badge>
              <span className="text-muted">워커 {d.queue.workers}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <HardDrive className="h-3.5 w-3.5 text-muted" />
              <span className="text-muted">여유 공간</span>
              {Object.entries(d.disk_free_gb).map(([k, v]) => (
                <Badge key={k} tone={v < 15 ? "bad" : v < 40 ? "warn" : "neutral"}>{k}: {v.toFixed(1)} GB</Badge>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { projects, projectsError, projectsLoading, activeJobs, jobsError } = useApp();
  const settings = useAsync(() => api.settings(), []);
  const totalSpent = projects.reduce((a, p) => a + (p.spent_usd || 0), 0);
  const budget = settings.data?.budget_usd ?? null;
  const ratio = budget && budget > 0 ? totalSpent / budget : 0;

  return (
    <div>
      <PageHeader icon={LayoutDashboard} title="Dashboard" description="프로젝트 진행 상태, 실행 중인 작업, 시스템 상태와 비용을 한눈에 확인합니다." />
      <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-muted">프로젝트</h2>
          {projectsError ? <ErrorBox error={projectsError} title="프로젝트를 불러오지 못했습니다" /> : null}
          {projectsLoading ? <Loading /> : !projectsError && projects.length === 0 ? (
            <EmptyState title="프로젝트가 없습니다">
              <Link href="/ideas/" className="text-accent underline">Ideas</Link> 페이지에서 첫 프로젝트를 만드세요.
            </EmptyState>
          ) : projects.map((p) => <ProjectCard key={p.id} p={p} />)}
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>실행 중 / 대기 작업</CardTitle><Badge tone={activeJobs.length ? "info" : "neutral"}>{activeJobs.length}</Badge></CardHeader>
            <CardContent className="space-y-2">
              {jobsError ? <ErrorBox error={jobsError} title="작업 목록 오류" /> : null}
              {!jobsError && activeJobs.length === 0 && <p className="text-sm text-muted">실행 중인 작업이 없습니다.</p>}
              {activeJobs.map((j) => <JobRow key={j.id} job={j} compact />)}
            </CardContent>
          </Card>
          <SystemPanel />
          <Card>
            <CardHeader><CardTitle>비용</CardTitle><Wallet className="h-4 w-4 text-muted" /></CardHeader>
            <CardContent className="space-y-3">
              {settings.error ? <ErrorBox error={settings.error} title="설정을 불러오지 못했습니다" /> : null}
              <div className="grid grid-cols-2 gap-2">
                <Stat label="사용 (모든 프로젝트)" value={fmtUsd(totalSpent)} />
                <Stat label="예산 (설정)" value={budget != null ? fmtUsd(budget) : "-"} />
              </div>
              {budget != null && budget > 0 && <Progress value={ratio} tone={ratio > 1 ? "bad" : ratio > 0.8 ? "warn" : "accent"} />}
              <p className="text-xs text-muted">API 비용만 집계됩니다. 세션(Claude Code/Codex) 사용량은 추정치일 수 있습니다.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
