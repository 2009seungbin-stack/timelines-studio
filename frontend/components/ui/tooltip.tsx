"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

/** Lightweight tooltip: shows on hover and keyboard focus; fixed positioning so it is never clipped by scroll containers. */
export function Tooltip({
  content, children, side = "right", className,
}: { content: React.ReactNode; children: React.ReactElement; side?: "right" | "top" | "bottom"; className?: string }) {
  const [pos, setPos] = React.useState<{ x: number; y: number } | null>(null);
  const id = React.useId();
  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    if (side === "right") setPos({ x: r.right + 8, y: r.top + r.height / 2 });
    else if (side === "top") setPos({ x: r.left + r.width / 2, y: r.top - 8 });
    else setPos({ x: r.left + r.width / 2, y: r.bottom + 8 });
  };
  const child = React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
    "aria-describedby": pos ? id : undefined,
    onMouseEnter: (e: React.MouseEvent<HTMLElement>) => show(e.currentTarget),
    onMouseLeave: () => setPos(null),
    onFocus: (e: React.FocusEvent<HTMLElement>) => show(e.currentTarget),
    onBlur: () => setPos(null),
  });
  const tf = side === "right" ? "translate(0,-50%)" : side === "top" ? "translate(-50%,-100%)" : "translate(-50%,0)";
  return (
    <>
      {child}
      {pos && (
        <div
          id={id}
          role="tooltip"
          style={{ position: "fixed", left: pos.x, top: pos.y, transform: tf, zIndex: 100 }}
          className={cn("pointer-events-none max-w-64 rounded-md border border-line2 bg-panel2 px-2.5 py-1.5 text-xs text-fg shadow-lg", className)}
        >
          {content}
        </div>
      )}
    </>
  );
}
