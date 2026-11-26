import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtDuration(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return "-";
  const t = Math.round(s);
  const m = Math.floor(t / 60);
  const sec = t % 60;
  return m > 0 ? `${m}분 ${String(sec).padStart(2, "0")}초` : `${sec}초`;
}
export function fmtClock(s: number): string {
  const t = Math.max(0, s);
  const m = Math.floor(t / 60);
  return `${m}:${(t % 60).toFixed(1).padStart(4, "0")}`;
}
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ko-KR", { hour12: false });
}
export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n == null || !isFinite(n)) return "-";
  return n.toLocaleString("ko-KR", { maximumFractionDigits: digits });
}
export function fmtUsd(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "-";
  return `$${n.toFixed(2)}`;
}
export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "-";
  if (n > 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n > 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${(n / 1e3).toFixed(0)} KB`;
}
