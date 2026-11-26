# TIMELINES Studio

역사·대체역사 다큐 채널 **TIMELINES**용 로컬 제작 플랫폼. AI가 영상을 "생성"하지 않고, 조사·대본·지도·Blender 3D·
그래픽·내레이션·편집 도구를 코드로 조작해 완성 영상을 만든다. 모든 단계는 스키마 검증된 JSON을 주고받고,
실패한 단계는 저장된 입력에서 다시 시작한다.

## 실행

```powershell
# 처음 한 번 (이미 설치돼 있으면 생략됨)
.\start.ps1            # venv/프론트 빌드 확인 → http://127.0.0.1:8790 열고 서버 시작
```
수동 실행: `cd backend; ..\.venv\Scripts\python.exe -m timelines.cli serve`
프론트 개발: `cd frontend; $env:NEXT_PUBLIC_API_BASE="http://127.0.0.1:8790"; npm run dev`
테스트: `.venv\Scripts\python.exe -m pytest tests -q`

`.env` (`.env.example` 참고): `ANTHROPIC_API_KEY`(설정됨), `OPENAI_API_KEY`, `GEMINI_API_KEY`, `YOUTUBE_API_KEY`.
키가 없으면 해당 기능은 "설정 안 됨"으로 표시되고 가짜 데이터를 보여주지 않는다.

## 에이전트 연동 (API + Claude Code / Codex 세션)

| 백엔드 | 방식 | 과금 | 용도 |
|---|---|---|---|
| `claude_code_api` (기본) | `claude -p` (Read/Grep/WebSearch/WebFetch, `--json-schema`, `--resume`) | ANTHROPIC_API_KEY, 프로젝트 예산에 합산 | 자료조사·시나리오·대본·스토리보드, 개발 세션 |
| `anthropic_api` | Messages API, structured output, 서버측 refusal fallback | API 키, 예산 합산 | 짧은 구조화 작업 |
| `claude_code` | `claude -p` (API 키 제거) | 구독 | 같은 작업을 구독으로 |
| `codex` | `codex exec --json --output-schema`, `codex exec resume` | 구독 | 2차 작업/검토 |
| `openai_api`, `gemini_api` | REST | API 키 (가격표는 설정에서 지정, 미지정 시 보수적 추정) | 선택 |

- 에이전트 출력이 스키마 검증에 실패하면 **같은 세션에 오류를 되돌려** 최대 2회 스스로 고치게 한다.
- 예산: 프로젝트별 `budget_usd`(기본 $5), 개발 세션 `dev_budget_usd`($20). 초과 시 API 호출 거부.
- **MCP 서버**: Claude Code/Codex 세션이 스튜디오를 직접 조작.
  `claude mcp add timelines -- "<timelines_studio>\.venv\Scripts\python.exe" -m timelines.mcp_server`
  (환경변수 `PYTHONPATH=<timelines_studio>\backend`). 도구: list_projects, create_project, get/save_artifact,
  artifact_schema, run_stage, job_status, approve_scene, project_files. (등록은 아직 하지 않음)

## 제작 흐름 (docs/ARCHITECTURE.md)

research → scenario → script → storyboard → tts → previews → (승인) → finals → compose → qa → publish_prep → finalize
(+ Phase 3 `localize`). 웹 UI, CLI(`python -m timelines.cli run <project> <stage>`), MCP 어디서나 같은 작업 큐로 실행된다.

### 내레이션 = ElevenLabs 웹(유료 플랜), 브라우저로만
사용자 지정(2026-11-26). ElevenLabs 웹앱에서 장면별로 생성 → `edit/audio/<lang>/import/narr_<scene>.mp3` →
`tts` 단계 `provider=import`가 Whisper 단어 타이밍으로 자막·장면 길이를 맞춘다. 생성 음성은 늘이거나 줄이지 않는다.
`backend/timelines/tools_import_take.py <video_dir> <scene>`가 최신 다운로드를 옮기고 원본 파일명을 기록한다.

### 기존 편집 워크플로우 연계
- 저장: `research/timelines_videos/<video_id>/` — `video_retention.init/seal/maybe_finish` (원본·편집 재료·최종 MP4 1개 보존, 검증된 중간물만 정리).
- 검수 프레임: `evidence/qc_tmp/` → QC 통과 시 `qc_cleanup.cleanup_after_qc` 자동 호출.
- GPU: Blender 렌더는 `gpu_lock`(E:\Flagship_work) 직렬화. 지도/그래픽은 CPU 프로세스 3개 병렬.
- Premiere: `edit/premiere/<video>_vNN.xml` (xmeml v4, 컷만 — 크로스페이드는 내보내지 않음, Premiere 가져오기 미검증).

## 모듈 상태 (사실대로)

| # | 모듈 | 상태 |
|---|---|---|
| 1 | Project Manager | 구현: 프로젝트/상태 14종/이력/산출물 stale 추적, 보관 폴더 생성 |
| 2 | Trend Research | 코드 구현(YouTube Data API, 스냅샷 2개 이상일 때만 성장률). **YOUTUBE_API_KEY 없음 → 실데이터 미수집** |
| 3 | Historical Research Agent | 구현·실행됨: 에이전트 조사(웹), FACT/INTERPRETATION/SPECULATION, 충돌 기록. 샘플 dossier 33개 출처(29개 실제 조회)·31 주장 |
| 4 | Alternate History Simulation | 구현: 분기점·인과 그래프 검증(원인 없는 사건/출처 없는 수치 거부), 지도 변화 |
| 5 | Scriptwriting | 구현·실행됨(에이전트 생성 경로 시험 완료), 주장 ID 검증, 발화 시간 추정 |
| 6 | Storyboard Director | 구현: 장면별 MapSpec/Scene3DSpec/GraphicSpec, 전환, 내레이션 길이로 재타이밍 |
| 7 | Historical Map Engine | 구현: Natural Earth + AWMC(ODbL) 영토, 추정/가상 국경 구분 표시, 라벨 충돌 회피, 카메라 이동, 교역로 애니메이션. 상업 라이선스 불명 레이어는 렌더 거부. 3D 기울임 지도는 미구현 |
| 8 | Blender 3D Engine | 구현: bpy 절차 생성 로마 도시(476 / 가상 1000년), 에셋 17종, 프리뷰→승인→최종 게이트. **품질 미달(사용자 평가) → 개선 진행 중** |
| 9 | Animation Director | 부분: 카메라 프리셋(orbit/dolly/crane/flyover), 지도 키프레임. 자동 연출 판단은 없음 |
| 10 | Asset Library | 구현: data/assets 메타(시대·지역·폴리곤·재질·라이선스·근거) 검색 API |
| 11 | Voice & Audio | 구현: ElevenLabs(웹 가져오기)/Edge, 단어 타이밍 자막, Whisper 대조, -14 LUFS 믹스. 배경음악 슬롯만 있음(음원 없음) |
| 12 | Video Editing | 구현: FFmpeg 크로스페이드/딥투블랙 합성, MP4·SRT·WAV·타임라인 JSON·FCP7 XML |
| 13 | Localization | 구현(API 개발 세션 작성): 번역·문화 검토 목록·언어별 재타이밍·자막. 실제 번역/음성 미실행 |
| 14 | QA | 구현: 출력 파일 실측(규격·길이·검은 화면·무음·라우드니스·자막·ASR·중복 장면), 출처/가상 표시/라이선스/합성 표시 → 사람 검토 목록 |
| 15 | Publishing | 구현: 제목·설명·챕터·태그·출처·합성 콘텐츠 표시 패키지. **업로드 기능 없음**(OAuth·사용자 승인 필요) |
| 16 | Analytics | 미연결: OAuth 필요. 상태 API만 |

작업 큐: Redis/Celery 대신 SQLite 큐(같은 계약). PostgreSQL은 `TIMELINES_DATABASE_URL`로 전환 가능(미시험).
Docker/GitHub Actions/Remotion/Playwright는 이 PC에 없거나 미도입.

## 알려진 제한
- 3D 품질: 현재 매싱 모델 수준 — 개선 세션 결과로 교체 예정.
- 476~500년 후계 왕국 국경: 상업용으로 쓸 수 있는 데이터가 없어 라벨만 표시(국경 미표시).
- 395년 동서 분할 폴리곤은 AWMC 200년 영역을 손으로 자른 근사치.
- 자동 QC·에이전트 검토는 사람의 시청·청취·승인을 대신하지 않는다. 승인 기록에는 actor(user/agent/mcp)가 남는다.
