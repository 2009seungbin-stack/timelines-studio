import {
  AudioLines, BarChart3, Bot, Box, Clapperboard, Film, Languages, LayoutDashboard, Lightbulb, Map,
  Package, ScrollText, Search, Send, Settings, ShieldCheck, type LucideIcon,
} from "lucide-react";

export interface NavItem { href: string; label: string; desc: string; icon: LucideIcon }

export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", desc: "프로젝트 현황, 작업 큐, 시스템 상태", icon: LayoutDashboard },
  { href: "/ideas/", label: "Ideas", desc: "새 프로젝트 만들기와 아이디어 목록", icon: Lightbulb },
  { href: "/research/", label: "Research", desc: "출처, 주장(사실/해석/추측), 충돌 검토", icon: Search },
  { href: "/scripts/", label: "Scripts", desc: "대본 세그먼트와 예상 길이", icon: ScrollText },
  { href: "/storyboard/", label: "Storyboard", desc: "장면 목록, 프리뷰/최종 렌더, 승인", icon: Clapperboard },
  { href: "/maps/", label: "Maps", desc: "지도 장면과 MapSpec", icon: Map },
  { href: "/studio3d/", label: "3D Studio", desc: "Blender 장면 검토와 승인", icon: Box },
  { href: "/assets/", label: "Assets", desc: "3D/이미지 에셋 라이브러리", icon: Package },
  { href: "/timeline/", label: "Timeline", desc: "최종 편집 타임라인과 출력물", icon: Film },
  { href: "/audio/", label: "Audio", desc: "내레이션 클립과 TTS", icon: AudioLines },
  { href: "/localization/", label: "Localization", desc: "다국어(ko, ja, es) 현지화 상태", icon: Languages },
  { href: "/qc/", label: "Quality Control", desc: "자동 QC 결과와 사람 검토 항목", icon: ShieldCheck },
  { href: "/publishing/", label: "Publishing", desc: "게시 패키지(제목, 설명, 챕터, 태그)", icon: Send },
  { href: "/analytics/", label: "Analytics", desc: "채널/영상 트렌드와 분석 연결 상태", icon: BarChart3 },
  { href: "/agents/", label: "Agents", desc: "Claude Code / Codex 세션과 API 제공자", icon: Bot },
  { href: "/settings/", label: "Settings", desc: "예산, 기본 모델, TTS, API 키 상태", icon: Settings },
];
