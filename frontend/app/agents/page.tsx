"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Bot, Cloud, Loader2, Send, Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible } from "@/components/ui/collapsible";
import { Label, Select, Textarea } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ErrorBox, JobBadge, Loading, Notice, PageHeader } from "@/components/common";
import { api } from "@/lib/api";
import { useApp, useAsync } from "@/lib/hooks";
import type { AgentResult, AgentTask, Job } from "@/lib/types";
import { fmtDate, fmtUsd } from "@/lib/utils";

const TASKS: { value: AgentTask; label: string }[] = [
  { value: "free", label: "자유 질문 (free)" }, { value: "research", label: "리서치 (research)" },
  { value: "scenario", label: "시나리오 (scenario)" }, { value: "script", label: "대본 (script)" },
  { value: "review", label: "검토 (review)" },
];

function JobResult({ jobId, onResult }: { jobId: string; onResult: (r: AgentResult | null) => void }) {
  const { jobsVersion } = useApp();
  const st = useAsync(() => api.job(jobId), [jobId, jobsVersion], 2000);
  const j: Job | null = st.data;
  const done = j && (j.status === "done" || j.status === "failed" || j.status === "cancelled");
  const res = (j?.result ?? null) as AgentResult | null;
  useEffect(() => { if (j?.status === "done") onResult(res); }, [j?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (st.error) return <ErrorBox error={st.error} />;
  if (!j) return <Loading />;
  return (
    <Card>
      <CardHeader><CardTitle>실행 결과</CardTitle><JobBadge status={j.status} /></CardHeader>
      <CardContent className="space-y-3">
        {!done && <><Progress value={j.progress} /><p className="text-xs text-muted">{j.message ?? "처리 중..."}</p></>}
        {j.error && <ErrorBox error={j.error} title="에이전트 작업 실패" />}
        {res?.text && <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded bg-bg p-3 font-sans text-sm leading-relaxed">{res.text}</pre>}
        {j.status === "done" && !res?.text && <p className="text-sm text-muted">텍스트 결과가 없습니다.</p>}
        {j.status === "done" && (
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
            <span>세션 ID: <code className="select-all text-fg">{res?.session_id ?? "없음"}</code></span>
            <span>비용: {res?.cost_usd != null ? fmtUsd(res.cost_usd) : "알 수 없음"}</span>
          </div>
        )}
        {res?.structured != null && (
          <Collapsible title="structured 출력"><pre className="max-h-72 overflow-auto font-mono text-[11px]">{JSON.stringify(res.structured, null, 2)}</pre></Collapsible>
        )}
      </CardContent>
    </Card>
  );
}

export default function AgentsPage() {
  const { projects, projectId, trackJob } = useApp();
  const backends = useAsync(() => api.agents(), [], 20000);
  const sessions = useAsync(() => api.agentSessions(), []);
  const [backend, setBackend] = useState("");
  const [model, setModel] = useState("");
  const [task, setTask] = useState<AgentTask>("free");
  const [proj, setProj] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [write, setWrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<AgentResult | null>(null);

  useEffect(() => { setProj((p) => p || projectId || ""); }, [projectId]);
  const list = backends.data ?? [];
  useEffect(() => {
    if (!backend && list.length) setBackend((list.find((b) => b.available) ?? list[0]).id);
  }, [list, backend]);
  const cur = list.find((b) => b.id === backend);
  useEffect(() => { setModel(""); setSessionId(""); setWrite(false); }, [backend]);
  const sess = useMemo(() => (sessions.data ?? []).filter((s) => s.backend === backend && (!proj || !s.project_id || s.project_id === proj)), [sessions.data, backend, proj]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!cur || !prompt.trim()) return;
    setBusy(true); setErr(null); setLastResult(null);
    try {
      const j = await api.runAgent({
        backend, prompt: prompt.trim(), task,
        ...(proj ? { project_id: proj } : {}), ...(sessionId ? { session_id: sessionId } : {}),
        ...(model ? { model } : {}), ...(write ? { write_access: true } : {}),
      });
      trackJob(j); setJobId(j.id);
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader icon={Bot} title="Agents" description="Claude Code / Codex 로컬 세션과 API 제공자에게 작업을 맡깁니다. 세션 ID로 이전 대화를 이어갈 수 있습니다." />
      {backends.error ? <ErrorBox error={backends.error} title="에이전트 목록을 불러오지 못했습니다" /> : null}
      {backends.loading && !backends.data ? <Loading /> : null}
      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {list.map((b) => (
          <Card key={b.id} className={b.id === backend ? "border-accent/60" : undefined}>
            <CardContent className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-sm font-semibold">{b.kind === "session" ? <Terminal className="h-3.5 w-3.5 text-muted" /> : <Cloud className="h-3.5 w-3.5 text-muted" />}{b.label}</span>
                <Badge tone={b.available ? "ok" : "bad"}>{b.available ? "사용 가능" : "사용 불가"}</Badge>
              </div>
              <div className="flex gap-1"><Badge>{b.kind === "session" ? "세션" : "API"}</Badge><span className="font-mono text-[10px] text-muted">{b.id}</span></div>
              <p className="text-xs text-muted">{b.detail}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,560px)_1fr]">
        <Card>
          <CardHeader><CardTitle>프롬프트 실행</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="ag-backend">백엔드</Label>
                  <Select id="ag-backend" value={backend} onChange={(e) => setBackend(e.target.value)} disabled={list.length === 0}>
                    {list.map((b) => <option key={b.id} value={b.id} disabled={!b.available}>{b.label}{b.available ? "" : " (사용 불가)"}</option>)}
                  </Select>
                </div>
                <div>
                  <Label htmlFor="ag-model">모델</Label>
                  <Select id="ag-model" value={model} onChange={(e) => setModel(e.target.value)}>
                    <option value="">기본값 (설정)</option>
                    {(cur?.models ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
                  </Select>
                </div>
                <div>
                  <Label htmlFor="ag-task">작업 유형</Label>
                  <Select id="ag-task" value={task} onChange={(e) => setTask(e.target.value as AgentTask)}>
                    {TASKS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                  </Select>
                </div>
                <div>
                  <Label htmlFor="ag-proj">프로젝트 (선택)</Label>
                  <Select id="ag-proj" value={proj} onChange={(e) => setProj(e.target.value)}>
                    <option value="">프로젝트 없음</option>
                    {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
                  </Select>
                </div>
              </div>
              <div>
                <Label htmlFor="ag-session">이어갈 세션 (선택)</Label>
                <Select id="ag-session" value={sessionId} onChange={(e) => setSessionId(e.target.value)}>
                  <option value="">새 세션</option>
                  {sess.map((s) => <option key={s.session_id} value={s.session_id}>{s.title || s.session_id} · {s.turns}턴 · {fmtDate(s.updated_at)}</option>)}
                </Select>
                {sessions.error ? <p className="mt-1 text-xs text-bad">세션 목록 오류: {(sessions.error as Error).message}</p> : null}
                <Label htmlFor="ag-session-manual" className="mt-2">또는 세션 ID 직접 입력</Label>
                <input id="ag-session-manual" value={sessionId} onChange={(e) => setSessionId(e.target.value.trim())} placeholder="session id"
                  className="h-9 w-full rounded-md border border-line2 bg-bg px-3 font-mono text-xs" />
              </div>
              <div>
                <Label htmlFor="ag-prompt">프롬프트</Label>
                <Textarea id="ag-prompt" rows={7} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="에이전트에게 맡길 작업을 적으세요" />
              </div>
              <Collapsible title="고급 옵션">
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={write} onChange={(e) => setWrite(e.target.checked)} />
                  <span>write_access 허용 (에이전트가 프로젝트 파일을 수정할 수 있음)
                    {write && <span className="mt-1 block text-xs text-warn">에이전트가 파일을 직접 쓸 수 있습니다. 필요한 경우에만 켜세요.</span>}</span>
                </label>
              </Collapsible>
              <ErrorBox error={err} title="실행을 시작하지 못했습니다" />
              {cur && !cur.available && <Notice tone="warn">선택한 백엔드를 사용할 수 없습니다: {cur.detail}</Notice>}
              <Button type="submit" variant="primary" disabled={busy || !cur?.available || !prompt.trim()}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}실행
              </Button>
            </form>
          </CardContent>
        </Card>
        <div className="space-y-4">
          {jobId ? <JobResult key={jobId} jobId={jobId} onResult={setLastResult} /> : (
            <Card><CardContent><p className="text-sm text-muted">실행 결과가 여기에 표시됩니다. 비용과 세션 ID가 함께 기록됩니다.</p></CardContent></Card>
          )}
          {lastResult?.session_id && (
            <Button variant="outline" size="sm" onClick={() => { setSessionId(lastResult.session_id!); sessions.reload(); }}>이 세션 이어서 실행하기</Button>
          )}
        </div>
      </div>
    </div>
  );
}
