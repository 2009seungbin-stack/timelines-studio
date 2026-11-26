"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

export interface TabItem { value: string; label: React.ReactNode }

export function Tabs({
  items, value, onChange, className,
}: { items: TabItem[]; value: string; onChange: (v: string) => void; className?: string }) {
  return (
    <div role="tablist" className={cn("inline-flex gap-1 rounded-md border border-line bg-panel p-1", className)}>
      {items.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          type="button"
          onClick={() => onChange(t.value)}
          className={cn(
            "rounded px-3 py-1 text-xs font-medium transition-colors cursor-pointer",
            value === t.value ? "bg-panel2 text-fg shadow-sm" : "text-muted hover:text-fg",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
