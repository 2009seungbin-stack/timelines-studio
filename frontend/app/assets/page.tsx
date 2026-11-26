"use client";

import { useEffect, useState } from "react";
import { ImageOff, Package } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { EmptyState, ErrorBox, Loading, PageHeader } from "@/components/common";
import { api, fileUrl } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { fmtNum } from "@/lib/utils";

export default function AssetsPage() {
  const [f, setF] = useState({ q: "", period: "", region: "", category: "" });
  const [applied, setApplied] = useState(f);
  useEffect(() => { const t = setTimeout(() => setApplied(f), 300); return () => clearTimeout(t); }, [f]);
  const st = useAsync(() => api.assets(applied), [applied.q, applied.period, applied.region, applied.category]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const filtered = Object.values(applied).some(Boolean);
  return (
    <div>
      <PageHeader icon={Package} title="Assets" description="사용 가능한 3D / 이미지 에셋의 시대, 지역, 라이선스, 폴리곤 수와 고증 메모를 확인합니다." />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div><Label htmlFor="a-q">검색</Label><Input id="a-q" value={f.q} onChange={set("q")} placeholder="이름, 키워드" /></div>
        <div><Label htmlFor="a-p">시대</Label><Input id="a-p" value={f.period} onChange={set("period")} placeholder="예: 1st century" /></div>
        <div><Label htmlFor="a-r">지역</Label><Input id="a-r" value={f.region} onChange={set("region")} placeholder="예: Rome" /></div>
        <div><Label htmlFor="a-c">분류</Label><Input id="a-c" value={f.category} onChange={set("category")} placeholder="예: architecture" /></div>
      </div>
      {st.error ? <ErrorBox error={st.error} title="에셋을 불러오지 못했습니다" /> : null}
      {st.loading && !st.data ? <Loading /> : st.data && st.data.length === 0 ? (
        <EmptyState title={filtered ? "조건에 맞는 에셋이 없습니다" : "등록된 에셋이 없습니다"}>
          {filtered ? "필터를 줄여 보세요." : "백엔드의 에셋 라이브러리 폴더에 에셋이 추가되면 여기에 표시됩니다."}
        </EmptyState>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {(st.data ?? []).map((a) => {
            const img = fileUrl(a.preview_url);
            return (
              <Card key={a.asset_id} className="overflow-hidden">
                <div className="aspect-video bg-black">
                  {img ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={img} alt={a.name} loading="lazy" className="h-full w-full object-cover" />
                    : <div className="flex h-full items-center justify-center text-muted"><ImageOff className="h-6 w-6" /></div>}
                </div>
                <div className="space-y-2 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold">{a.name}</h3>
                    <span className="font-mono text-[10px] text-muted">{a.asset_id}</span>
                  </div>
                  <div className="flex flex-wrap gap-1"><Badge tone="accent">{a.category}</Badge><Badge>{a.period}</Badge><Badge>{a.region}</Badge></div>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                    <dt className="text-muted">폴리곤</dt><dd>{a.polygon_count != null ? fmtNum(a.polygon_count) : "-"}</dd>
                    <dt className="text-muted">라이선스</dt><dd>{a.license || "-"}</dd>
                    <dt className="text-muted">출처</dt><dd className="break-words">{a.source || "-"}</dd>
                  </dl>
                  {a.accuracy_notes && <p className="rounded bg-bg p-2 text-xs text-muted"><span className="font-medium text-warn">고증 메모:</span> {a.accuracy_notes}</p>}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
