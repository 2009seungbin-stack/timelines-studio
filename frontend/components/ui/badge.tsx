import * as React from "react";
import { cn } from "@/lib/utils";

export type Tone = "neutral" | "ok" | "warn" | "bad" | "info" | "violet" | "accent";

const tones: Record<Tone, string> = {
  neutral: "bg-panel2 text-muted border-line2",
  ok: "bg-ok/12 text-ok border-ok/35",
  warn: "bg-warn/12 text-warn border-warn/35",
  bad: "bg-bad/12 text-bad border-bad/35",
  info: "bg-info/12 text-info border-info/35",
  violet: "bg-violet/12 text-violet border-violet/35",
  accent: "bg-accent/12 text-accent border-accent/35",
};

export function Badge({ tone = "neutral", className, ...p }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium leading-none whitespace-nowrap", tones[tone], className)}
      {...p}
    />
  );
}
