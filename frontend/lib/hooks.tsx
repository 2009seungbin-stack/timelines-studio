"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";
import { api, errorMessage } from "./api";
import type { Job, Project } from "./types";

/* ---------------------------------------------------------------- safe localStorage */
export function lsGet(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
export function lsSet(key: string, value: string | null) {
  try {
    if (value == null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch { /* storage unavailable */ }
}

/* ---------------------------------------------------------------- generic async hook */
export interface AsyncState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/**
 * Fetches on mount and whenever deps change. `fetcher === null` skips fetching.
 * Optional polling interval (ms). Keeps previous data while reloading.
 */
export function useAsync<T>(fetcher: (() => Promise<T>) | null, deps: unknown[], intervalMs?: number): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<boolean>(fetcher !== null);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const enabled = fetcher !== null;

  // reset data when deps (identity of request) change
  const depsKey = JSON.stringify(deps);
  useEffect(() => { setData(null); setError(null); }, [depsKey]);

  useEffect(() => {
    if (!enabled) { setLoading(false); return; }
    let alive = true;
    const run = async (first: boolean) => {
      if (first) setLoading(true);
      try {
        const r = await fetcherRef.current!();
        if (alive) { setData(r); setError(null); }
      } catch (e) {
        if (alive) setError(e);
      } finally {
        if (alive && first) setLoading(false);
      }
    };
    run(true);
    let id: ReturnType<typeof setInterval> | undefined;
    if (intervalMs) id = setInterval(() => run(false), intervalMs);
    return () => { alive = false; if (id) clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, depsKey, tick, intervalMs]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Artifact/other GET that treats 404 as "not produced yet" (data = null, notFound = true). */
export function isNotFound(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { status?: number }).status === 404;
}

/* ---------------------------------------------------------------- app context (projects + jobs) */
interface AppCtx {
  projects: Project[];
  projectsError: unknown;
  projectsLoading: boolean;
  reloadProjects: () => void;
  projectId: string | null;
  setProjectId: (id: string | null) => void;
  project: Project | null;
  jobs: Job[];
  jobsError: unknown;
  activeJobs: Job[];
  /** increments whenever a job reaches a terminal state or a new job is tracked; use as a refetch key */
  jobsVersion: number;
  refreshJobs: () => void;
  /** call after a POST that returned a job so it shows up immediately */
  trackJob: (job: Job) => void;
  jobsOpen: boolean;
  setJobsOpen: (v: boolean) => void;
  navOpen: boolean;
  setNavOpen: (v: boolean) => void;
}

const Ctx = createContext<AppCtx | null>(null);
const LS_PROJECT = "timelines.projectId";

export function AppProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectIdState] = useState<string | null>(null);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsError, setJobsError] = useState<unknown>(null);
  const [jobsVersion, setJobsVersion] = useState(0);
  const prevStatus = useRef<Map<string, string>>(new Map());
  const [jobsTick, setJobsTick] = useState(0);

  useEffect(() => { setProjectIdState(lsGet(LS_PROJECT)); }, []);
  const setProjectId = useCallback((id: string | null) => {
    setProjectIdState(id);
    lsSet(LS_PROJECT, id);
  }, []);

  const [projTick, setProjTick] = useState(0);
  const reloadProjects = useCallback(() => setProjTick((t) => t + 1), []);

  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState<unknown>(null);
  const [projectsLoading, setProjectsLoading] = useState(true);

  const activeCount = jobs.filter((j) => j.status === "queued" || j.status === "running").length;
  const hasActive = activeCount > 0;

  // projects: load, and refresh periodically while jobs are active (stage status changes)
  useEffect(() => {
    let alive = true;
    api.projects()
      .then((p) => { if (alive) { setProjects(p); setProjectsError(null); } })
      .catch((e) => { if (alive) setProjectsError(e); })
      .finally(() => { if (alive) setProjectsLoading(false); });
    return () => { alive = false; };
  }, [projTick, jobsVersion]);

  useEffect(() => {
    if (!hasActive) return;
    const id = setInterval(() => reloadProjects(), 4000);
    return () => clearInterval(id);
  }, [hasActive, reloadProjects]);

  // jobs polling: 2 s while any job is running/queued, 10 s otherwise (to notice jobs started elsewhere)
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const list = await api.jobs();
        if (!alive) return;
        let changed = false;
        for (const j of list) {
          const before = prevStatus.current.get(j.id);
          const terminal = j.status === "done" || j.status === "failed" || j.status === "cancelled";
          if (before !== undefined && before !== j.status && terminal) changed = true;
          if (before === undefined && prevStatus.current.size > 0) changed = true;
          prevStatus.current.set(j.id, j.status);
        }
        if (prevStatus.current.size === 0) list.forEach((j) => prevStatus.current.set(j.id, j.status));
        setJobs(list);
        setJobsError(null);
        if (changed) setJobsVersion((v) => v + 1);
      } catch (e) {
        if (alive) setJobsError(e);
      }
    };
    load();
    const id = setInterval(load, hasActive ? 2000 : 10000);
    return () => { alive = false; clearInterval(id); };
  }, [hasActive, jobsTick]);

  const refreshJobs = useCallback(() => setJobsTick((t) => t + 1), []);
  const trackJob = useCallback((job: Job) => {
    setJobs((cur) => [job, ...cur.filter((j) => j.id !== job.id)]);
    prevStatus.current.set(job.id, job.status);
    setJobsVersion((v) => v + 1);
    setJobsTick((t) => t + 1);
  }, []);

  // drop stale selection if the project no longer exists
  useEffect(() => {
    if (!projectsLoading && !projectsError && projectId && !projects.some((p) => p.id === projectId)) {
      setProjectId(projects.length ? projects[0].id : null);
    } else if (!projectsLoading && !projectId && projects.length) {
      setProjectId(projects[0].id);
    }
  }, [projects, projectsLoading, projectsError, projectId, setProjectId]);

  const project = useMemo(() => projects.find((p) => p.id === projectId) ?? null, [projects, projectId]);
  const activeJobs = useMemo(
    () => jobs.filter((j) => j.status === "queued" || j.status === "running"), [jobs],
  );

  const value: AppCtx = {
    projects, projectsError, projectsLoading, reloadProjects, projectId, setProjectId, project,
    jobs, jobsError, activeJobs, jobsVersion, refreshJobs, trackJob, jobsOpen, setJobsOpen, navOpen, setNavOpen,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("AppProvider missing");
  return c;
}

/** Start a job-returning action, register the job, and surface errors. */
export function useAction() {
  const { trackJob } = useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);
  const exec = useCallback(async (label: string, fn: () => Promise<Job | unknown>) => {
    setBusy(label); setError(null); setMessage(null);
    try {
      const r = await fn();
      if (r && typeof r === "object" && "status" in r && "kind" in r) {
        trackJob(r as Job);
        setMessage(`작업이 시작되었습니다: ${label}`);
      } else setMessage(`완료: ${label}`);
      return r;
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(null);
    }
  }, [trackJob]);
  return { busy, error, message, exec, errorText: error ? errorMessage(error) : null, clear: () => { setError(null); setMessage(null); } };
}
