"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, Loader2, Settings } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible } from "@/components/ui/collapsible";
import { Input, Label } from "@/components/ui/input";
import { ErrorBox, Loading, Notice, PageHeader } from "@/components/common";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Settings as S } from "@/lib/types";

function Form({ s, onSaved }: { s: S; onSaved: () => void }) {
  const [budget, setBudget] = useState(String(s.budget_usd));
  const [backend, setBackend] = useState(s.default_backend);
  const [models, setModels] = useState<Record<string, string>>(s.default_model ?? {});
  const [provider, setProvider] = useState(s.tts_provider);
  const [voice, setVoice] = useState(s.tts_voice);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [ok, setOk] = useState(false);
  const bn = Number(budget);
  useEffect(() => { setOk(false); }, [budget, backend, models, provider, voice]);
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      await api.updateSettings({ budget_usd: bn, default_backend: backend, default_model: models, tts_provider: provider, tts_voice: voice });
      setOk(true); onSaved();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader><CardTitle>기본 설정</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          <div><Label htmlFor="s-budget">프로젝트 예산 (USD)</Label><Input id="s-budget" type="number" min={0} step={0.5} value={budget} onChange={(e) => setBudget(e.target.value)} /></div>
          <div><Label htmlFor="s-backend">기본 에이전트 백엔드</Label><Input id="s-backend" value={backend} onChange={(e) => setBackend(e.target.value)} placeholder="claude_code" /></div>
          <div><Label htmlFor="s-tts">TTS 제공자</Label><Input id="s-tts" value={provider} onChange={(e) => setProvider(e.target.value)} /></div>
          <div><Label htmlFor="s-voice">TTS 음성</Label><Input id="s-voice" value={voice} onChange={(e) => setVoice(e.target.value)} /></div>
        </div>
        <Collapsible title="백엔드별 기본 모델">
          <div className="grid gap-3 md:grid-cols-2">
            {Object.keys(models).length === 0 && <p className="text-sm text-muted">설정된 기본 모델이 없습니다.</p>}
            {Object.entries(models).map(([k, v]) => (
              <div key={k}><Label htmlFor={`m-${k}`}>{k}</Label><Input id={`m-${k}`} value={v} onChange={(e) => setModels({ ...models, [k]: e.target.value })} /></div>
            ))}
          </div>
        </Collapsible>
        <ErrorBox error={err} title="설정을 저장하지 못했습니다" />
        <div className="flex items-center gap-3">
          <Button variant="primary" disabled={busy || !isFinite(bn) || bn < 0} onClick={save}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}저장</Button>
          {ok && <span className="flex items-center gap-1 text-xs text-ok"><CheckCircle2 className="h-3.5 w-3.5" />저장되었습니다</span>}
        </div>
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const st = useAsync(() => api.settings(), []);
  return (
    <div>
      <PageHeader icon={Settings} title="Settings" description="예산, 기본 백엔드/모델, TTS 제공자와 음성을 설정하고 API 키 설정 여부를 확인합니다." />
      {st.error ? <ErrorBox error={st.error} title="설정을 불러오지 못했습니다" /> : null}
      {st.loading && !st.data ? <Loading /> : null}
      {st.data && (
        <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
          <Form key={JSON.stringify(st.data)} s={st.data} onSaved={st.reload} />
          <Card>
            <CardHeader><CardTitle>API 키</CardTitle><KeyRound className="h-4 w-4 text-muted" /></CardHeader>
            <CardContent className="space-y-2">
              {Object.entries(st.data.keys).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between rounded border border-line bg-bg px-3 py-2">
                  <code className="text-xs">{k}</code><Badge tone={v ? "ok" : "neutral"}>{v ? "설정됨" : "없음"}</Badge>
                </div>
              ))}
              <Notice tone="info">키 값은 화면에 표시되지 않으며 이 화면에서 바꿀 수 없습니다. 백엔드의 환경 변수 또는 .env 파일로 설정하세요.</Notice>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
