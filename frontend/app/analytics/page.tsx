"use client";

import { useState } from "react";
import { BarChart3, Loader2, Plus, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { api } from "@/lib/api";
import { useAction, useApp, useAsync } from "@/lib/hooks";
import { fmtDate, fmtDuration, fmtNum } from "@/lib/utils";

export default function AnalyticsPage() {
  const { jobsVersion } = useApp();
  const status = useAsync(() => api.analyticsStatus(), []);
  const ts = useAsync(() => api.trendsStatus(), []);
  const channels = useAsync(() => api.trendChannels(), [jobsVersion]);
  const videos = useAsync(() => api.trendVideos(), [jobsVersion]);
  const a = useAction();
  const [handle, setHandle] = useState("");
  const configured = ts.data?.configured === true;
  const sorted = [...(videos.data ?? [])].sort((x, y) => y.views_per_day - x.views_per_day);

  return (
    <div className="space-y-5">
      <PageHeader icon={BarChart3} title="Analytics" description="경쟁/참고 채널의 트렌드 데이터와 내 채널 분석 연결 상태를 확인합니다. 성장률은 스냅샷이 2개 이상일 때만 계산됩니다."
        actions={
          <Button variant="primary" disabled={!configured || a.busy !== null} title={!configured ? ts.data?.reason ?? "상태 확인 중" : undefined}
            onClick={async () => { await a.exec("트렌드 수집", () => api.trendCollect()); }}>
            {a.busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}데이터 수집
          </Button>} />
      <ErrorBox error={a.error} title="수집을 시작하지 못했습니다" />
      {a.message && <p className="text-xs text-ok">{a.message}</p>}

      <div className="grid gap-3 md:grid-cols-2">
        <Section title="YouTube Analytics (내 채널)">
          {status.error ? <ErrorBox error={status.error} /> : status.data ? (
            <div className="space-y-2"><Badge tone={status.data.connected ? "ok" : "neutral"}>{status.data.connected ? "연결됨" : "연결 안 됨"}</Badge>
              {status.data.reason && <p className="text-sm text-muted">{status.data.reason}</p>}</div>) : <Loading />}
        </Section>
        <Section title="트렌드 수집 (YouTube Data API)">
          {ts.error ? <ErrorBox error={ts.error} /> : ts.data ? (
            <div className="space-y-2"><Badge tone={ts.data.configured ? "ok" : "warn"}>{ts.data.configured ? "설정됨" : "설정되지 않음"}</Badge>
              {ts.data.reason && <p className="text-sm text-muted">{ts.data.reason}</p>}</div>) : <Loading />}
        </Section>
      </div>

      <Section title="추적 채널" right={
        <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (!handle.trim()) return; await a.exec("채널 추가", async () => { const r = await api.addTrendChannel(handle.trim()); channels.reload(); return r; }); setHandle(""); }}>
          <Input className="h-8 w-48" value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@handle 또는 채널 ID" aria-label="채널 핸들 또는 ID" disabled={!configured} />
          <Button size="sm" variant="outline" type="submit" disabled={!configured || !handle.trim() || a.busy !== null} title={!configured ? "YOUTUBE_API_KEY 설정이 필요합니다" : undefined}><Plus className="h-3 w-3" />추가</Button>
        </form>}>
        {channels.error ? <ErrorBox error={channels.error} /> : channels.loading && !channels.data ? <Loading /> : (channels.data ?? []).length === 0 ? (
          <EmptyState title="추적 중인 채널이 없습니다">{configured ? "채널 핸들을 추가한 뒤 데이터를 수집하세요." : "먼저 YOUTUBE_API_KEY를 설정해야 채널을 추가하고 수집할 수 있습니다."}</EmptyState>
        ) : (
          <Table><THead><TR><TH>채널</TH><TH>핸들</TH><TH>구독자</TH><TH>영상 수</TH><TH>수집 시각</TH></TR></THead>
            <TBody>{(channels.data ?? []).map((c) => <TR key={c.channel_id}><TD>{c.title}</TD><TD className="text-xs">{c.handle}</TD><TD className="tabular-nums">{fmtNum(c.subscribers)}</TD><TD className="tabular-nums">{fmtNum(c.video_count)}</TD><TD className="text-xs">{fmtDate(c.collected_at)}</TD></TR>)}</TBody></Table>
        )}
      </Section>

      <Section title="영상 트렌드 (조회수/일 기준 정렬)">
        {videos.error ? <ErrorBox error={videos.error} /> : videos.loading && !videos.data ? <Loading /> : sorted.length === 0 ? (
          <EmptyState title="수집된 영상 데이터가 없습니다">트렌드 데이터는 수집을 실행한 뒤에 표시됩니다. 표시되는 값은 모두 실제 수집 결과입니다.</EmptyState>
        ) : (
          <>
            <Table>
              <THead><TR><TH>영상</TH><TH>채널</TH><TH>게시일</TH><TH>길이</TH><TH>조회수</TH><TH>조회수/일</TH><TH>조회수/구독자</TH><TH>성장/일</TH></TR></THead>
              <TBody>
                {sorted.map((v) => (
                  <TR key={v.video_id}>
                    <TD className="min-w-64"><a className="text-accent hover:underline" target="_blank" rel="noreferrer" href={`https://www.youtube.com/watch?v=${encodeURIComponent(v.video_id)}`}>{v.title}</a></TD>
                    <TD className="text-xs">{v.channel_title}</TD><TD className="whitespace-nowrap text-xs">{fmtDate(v.published_at).split(" ")[0]} ({fmtNum(v.age_days)}일)</TD>
                    <TD className="whitespace-nowrap text-xs">{fmtDuration(v.duration_s)}</TD>
                    <TD className="tabular-nums">{fmtNum(v.views)}</TD><TD className="tabular-nums">{fmtNum(v.views_per_day, 1)}</TD>
                    <TD className="tabular-nums">{fmtNum(v.views_per_subscriber, 3)}</TD>
                    <TD className="tabular-nums">{v.growth_per_day == null ? <span className="text-muted" title="스냅샷이 2개 미만">-</span> : fmtNum(v.growth_per_day, 1)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <div className="mt-3"><Notice tone="info">성장/일 열의 '-'는 스냅샷이 2개 미만이라 계산할 수 없다는 뜻입니다 (0이 아닙니다).</Notice></div>
          </>
        )}
      </Section>
    </div>
  );
}
