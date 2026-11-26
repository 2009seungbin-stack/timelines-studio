import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { AppShell } from "@/components/shell/app-shell";

export const metadata: Metadata = {
  title: "TIMELINES Studio",
  description: "다국어 역사 / 대체역사 유튜브 채널을 위한 로컬 AI 제작 스튜디오",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, colorScheme: "dark" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" className="dark">
      <body><AppShell>{children}</AppShell></body>
    </html>
  );
}
