import { cn } from "@/lib/utils";

export function Progress({ value, tone = "accent", className }: { value: number; tone?: "accent" | "ok" | "bad" | "warn"; className?: string }) {
  const pct = Math.max(0, Math.min(1, isFinite(value) ? value : 0)) * 100;
  const color = { accent: "bg-accent", ok: "bg-ok", bad: "bg-bad", warn: "bg-warn" }[tone];
  return (
    <div
      role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-line", className)}
    >
      <div className={cn("h-full rounded-full transition-all duration-500", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}
