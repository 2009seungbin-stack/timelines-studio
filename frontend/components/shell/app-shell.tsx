"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ChevronsLeft, ChevronsRight, ListChecks, Menu, WifiOff } from "lucide-react";
import { AppProvider, lsGet, lsSet, useApp } from "@/lib/hooks";
import { NAV } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Select } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { JobRow, StateChip } from "@/components/common";

function norm(p: string) { return p.replace(/\/+$/, "") || "/"; }

function NavList({ expanded, onNavigate }: { expanded: boolean; onNavigate?: () => void }) {
  const path = norm(usePathname() ?? "/");
  return (
    <nav aria-label="주 메뉴" className="flex flex-col gap-0.5 px-2">
      {NAV.map((n) => {
        const active = norm(n.href) === path || (n.href !== "/" && path === "/project" && false);
        const Icon = n.icon;
        const link = (
          <Link
            href={n.href}
            onClick={onNavigate}
            aria-label={n.label}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex h-9 items-center gap-3 rounded-md px-2.5 text-sm transition-colors",
              active ? "bg-accent/15 text-accent" : "text-muted hover:bg-panel2 hover:text-fg",
            )}
          >
            <Icon className="h-[18px] w-[18px] shrink-0" />
            {expanded && <span className="truncate">{n.label}</span>}
          </Link>
        );
        return expanded ? <div key={n.href}>{link}</div> : (
          <Tooltip key={n.href} side="right" content={<div><div className="font-medium">{n.label}</div><div className="text-muted">{n.desc}</div></div>}>
            {link}
          </Tooltip>
        );
      })}
    </nav>
  );
}

function Logo({ expanded }: { expanded: boolean }) {
  return (
    <Link href="/" className="flex h-12 items-center gap-2.5 px-4" aria-label="TIMELINES Studio 대시보드">
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-accent text-[11px] font-bold text-white">T</div>
      {expanded && <span className="text-sm font-semibold tracking-wide">TIMELINES <span className="text-muted">Studio</span></span>}
    </Link>
  );
}

function JobsDrawer() {
  const { jobsOpen, setJobsOpen, jobs, jobsError } = useApp();
  return (
    <Dialog open={jobsOpen} onClose={() => setJobsOpen(false)} title="작업(Jobs)" side>
      <div className="space-y-2 p-4">
        {jobsError ? <p className="text-sm text-bad">작업 목록을 불러오지 못했습니다.</p> : null}
        {!jobsError && jobs.length === 0 && <p className="py-8 text-center text-sm text-muted">작업 내역이 없습니다.</p>}
        {jobs.slice(0, 60).map((j) => <JobRow key={j.id} job={j} />)}
        {jobs.length > 60 && <p className="text-center text-xs text-muted">최근 60개만 표시합니다.</p>}
      </div>
    </Dialog>
  );
}

function TopBar() {
  const { projects, projectId, setProjectId, project, activeJobs, setJobsOpen, setNavOpen, jobsError } = useApp();
  return (
    <header className="sticky top-0 z-30 flex h-12 items-center gap-3 border-b border-line bg-bg/90 px-3 backdrop-blur md:px-5">
      <Button variant="ghost" size="icon" className="md:hidden" aria-label="메뉴 열기" onClick={() => setNavOpen(true)}>
        <Menu className="h-5 w-5" />
      </Button>
      <div className="flex min-w-0 items-center gap-2">
        <label htmlFor="project-select" className="sr-only">프로젝트 선택</label>
        <Select
          id="project-select"
          className="h-8 w-44 sm:w-72"
          value={projectId ?? ""}
          onChange={(e) => setProjectId(e.target.value || null)}
          disabled={projects.length === 0}
        >
          {projects.length === 0 && <option value="">프로젝트 없음</option>}
          {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </Select>
        {project && <span className="hidden sm:inline-flex"><StateChip state={project.state} /></span>}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {jobsError ? (
          <Badge tone="bad"><WifiOff className="h-3 w-3" />백엔드 연결 안 됨</Badge>
        ) : null}
        <Button variant="outline" size="sm" onClick={() => setJobsOpen(true)} aria-label="작업 패널 열기">
          <ListChecks className="h-4 w-4" />
          <span className="hidden sm:inline">작업</span>
          {activeJobs.length > 0 && (
            <span className="rounded-full bg-info/20 px-1.5 text-[11px] font-semibold text-info">{activeJobs.length}</span>
          )}
        </Button>
      </div>
    </header>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { navOpen, setNavOpen } = useApp();
  const [expanded, setExpanded] = useState(false);
  useEffect(() => { setExpanded(lsGet("timelines.navExpanded") === "1"); }, []);
  const toggle = () => { setExpanded((v) => { lsSet("timelines.navExpanded", v ? "0" : "1"); return !v; }); };
  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-panel md:flex",
          expanded ? "w-56" : "w-14",
        )}
      >
        <Logo expanded={expanded} />
        <div className="min-h-0 flex-1 overflow-y-auto py-2"><NavList expanded={expanded} /></div>
        <div className="border-t border-line p-2">
          <Tooltip content={expanded ? "사이드바 접기" : "사이드바 펼치기"}>
            <Button variant="ghost" size="icon" className="w-full" onClick={toggle} aria-label={expanded ? "사이드바 접기" : "사이드바 펼치기"}>
              {expanded ? <ChevronsLeft className="h-4 w-4" /> : <ChevronsRight className="h-4 w-4" />}
            </Button>
          </Tooltip>
        </div>
      </aside>

      <Dialog open={navOpen} onClose={() => setNavOpen(false)} title="TIMELINES Studio" side className="max-w-64">
        <div className="py-2"><NavList expanded onNavigate={() => setNavOpen(false)} /></div>
      </Dialog>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-5 md:px-6">{children}</main>
      </div>
      <JobsDrawer />
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return <AppProvider><Shell>{children}</Shell></AppProvider>;
}
