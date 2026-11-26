"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Lightbulb, Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorBox, Loading, Notice, PageHeader, StateChip } from "@/components/common";
import { api } from "@/lib/api";
import { useApp } from "@/lib/hooks";
import type { ProjectFormat } from "@/lib/types";
import { fmtDate, fmtDuration } from "@/lib/utils";

const FORMATS: { value: ProjectFormat; label: string }[] = [
  { value: "alt_history", label: "대체역사 (alt_history)" },
  { value: "history_explainer", label: "역사 해설 (history_explainer)" },
  { value: "documentary", label: "다큐멘터리 (documentary)" },
];

export default function IdeasPage() {
  const { projects, projectsLoading, projectsError, reloadProjects, setProjectId } = useApp();
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [format, setFormat] = useState<ProjectFormat>("alt_history");
  const [minutes, setMinutes] = useState("8");
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);

  const mins = Number(minutes);
  const valid = title.trim().length > 0 && topic.trim().length > 0 && isFinite(mins) && mins > 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true); setError(null); setCreatedId(null);
    try {
      const p = await api.createProject({
        title: title.trim(), topic: topic.trim(), format,
        target_duration_s: Math.round(mins * 60), language,
      });
      setCreatedId(p.id);
      setProjectId(p.id);
      reloadProjects();
      setTitle(""); setTopic("");
    } catch (err) { setError(err); } finally { setBusy(false); }
  };

  const ideas = projects.filter((p) => p.state === "IDEA");

  return (
    <div>
      <PageHeader icon={Lightbulb} title="Ideas" description="새 영상 프로젝트를 만들고, 아직 리서치가 시작되지 않은 아이디어 목록을 확인합니다." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,420px)_1fr]">
        <Card>
          <CardHeader><CardTitle>새 프로젝트</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-3">
              <div>
                <Label htmlFor="idea-title">제목</Label>
                <Input id="idea-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: 로마가 멸망하지 않았다면" required />
              </div>
              <div>
                <Label htmlFor="idea-topic">주제 / 핵심 질문</Label>
                <Textarea id="idea-topic" rows={3} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="분기점(what-if), 다루고 싶은 범위, 시청자가 얻을 것" required />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="idea-format">포맷</Label>
                  <Select id="idea-format" value={format} onChange={(e) => setFormat(e.target.value as ProjectFormat)}>
                    {FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </Select>
                </div>
                <div>
                  <Label htmlFor="idea-lang">언어</Label>
                  <Select id="idea-lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
                    <option value="en">en (영어)</option>
                    <option value="ko">ko (한국어)</option>
                    <option value="ja">ja (일본어)</option>
                    <option value="es">es (스페인어)</option>
                  </Select>
                </div>
              </div>
              <div>
                <Label htmlFor="idea-min">목표 길이 (분)</Label>
                <Input id="idea-min" type="number" min={0.5} step={0.5} value={minutes} onChange={(e) => setMinutes(e.target.value)} />
              </div>
              <ErrorBox error={error} title="프로젝트를 만들지 못했습니다" />
              {createdId && <Notice tone="ok">프로젝트가 생성되었습니다 (<Link className="underline" href={`/project/?id=${encodeURIComponent(createdId)}`}>{createdId}</Link>). 상단에서 선택되었습니다.</Notice>}
              <Button type="submit" variant="primary" disabled={!valid || busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}프로젝트 만들기
              </Button>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-muted">IDEA 상태 프로젝트 ({ideas.length})</h2>
          {projectsError ? <ErrorBox error={projectsError} title="목록을 불러오지 못했습니다" /> : null}
          {projectsLoading ? <Loading /> : !projectsError && ideas.length === 0 ? (
            <EmptyState title="IDEA 상태의 프로젝트가 없습니다">왼쪽 양식으로 새 프로젝트를 만들 수 있습니다. 진행 중인 프로젝트는 Dashboard에서 확인하세요.</EmptyState>
          ) : ideas.map((p) => (
            <Card key={p.id}>
              <CardContent className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link href={`/project/?id=${encodeURIComponent(p.id)}`} className="font-medium hover:text-accent">{p.title}</Link>
                  <p className="mt-0.5 line-clamp-2 text-sm text-muted">{p.topic}</p>
                  <p className="mt-1 text-xs text-muted">{p.format} · {p.language} · 목표 {fmtDuration(p.target_duration_s)} · {fmtDate(p.created_at)}</p>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <StateChip state={p.state} />
                  <Button size="sm" variant="outline" onClick={() => setProjectId(p.id)}>선택</Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
