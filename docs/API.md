# TIMELINES Studio — HTTP API contract (v0.1)

Backend: FastAPI at `http://127.0.0.1:8790`. All JSON. The built frontend (`frontend/out`) is served at `/`.
Errors: `{"detail": ...}` with 4xx/5xx. Schema validation errors return 422 with `detail` = list of
`{loc, msg}`. Times are ISO-8601 UTC strings. Money is USD floats.

## System
| Method | Path | Response |
|---|---|---|
| GET | `/api/health` | `{ok: true, version}` |
| GET | `/api/system` | `{tools: {blender, ffmpeg, node, claude_cli, codex_cli}: {ok, path, version}, gpu: str|null, data_root, video_root, disk_free_gb: {C: n, ...}, queue: {workers, gpu_busy}}` |
| GET | `/api/settings` | `{budget_usd, default_backend, default_model: {backend: model}, tts_provider, tts_voice, keys: {ANTHROPIC_API_KEY: bool, OPENAI_API_KEY: bool, GEMINI_API_KEY: bool, YOUTUBE_API_KEY: bool, ELEVENLABS_API_KEY: bool}}` (keys are presence booleans only, never values) |
| PUT | `/api/settings` | same body subset → updated settings |

## Projects
Project object:
```
{id, title, topic, format, state, language, target_duration_s, created_at, updated_at,
 video_dir, final_mp4: str|null, final_url: str|null,
 stages: [{stage, status: "missing"|"ready"|"stale"|"running"|"failed", updated_at, artifact}],
 budget_usd, spent_usd}
```
`state` ∈ IDEA, RESEARCHING, RESEARCH_REVIEW, SCRIPTING, SCRIPT_REVIEW, STORYBOARD, ASSET_PRODUCTION,
RENDERING, EDITING, LOCALIZATION, FINAL_REVIEW, READY, PUBLISHED, FAILED.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/projects` | list of project objects (without heavy fields) |
| POST | `/api/projects` | body `{title, topic, format: "alt_history"|"history_explainer"|"documentary", target_duration_s, language: "en"}` → project |
| GET | `/api/projects/{id}` | project object |
| POST | `/api/projects/{id}/state` | body `{state}` → project (manual transition, recorded) |
| GET | `/api/projects/{id}/artifacts/{name}` | name ∈ `research_dossier, scenario, script, storyboard, timeline, qc_report, publish_package` → JSON or 404 |
| PUT | `/api/projects/{id}/artifacts/{name}` | body = artifact JSON; validated against schema; marks downstream stages `stale` |
| POST | `/api/projects/{id}/run` | body `{stage, options?}`; stage ∈ `research, scenario, script, storyboard, tts, previews, finals, compose, qa, publish_prep, finalize` → job |
| GET | `/api/projects/{id}/scenes` | `[{scene_id, scene_type, renderer, classification, start_s, end_s, narration, render_status, preview_url, final_url, thumb_url, spec}]` |
| POST | `/api/projects/{id}/scenes/{scene_id}/render` | body `{quality: "preview"|"final"}` → job. `final` returns 409 unless preview approved |
| POST | `/api/projects/{id}/scenes/{scene_id}/approve` | body `{approved: bool, note}` → scene |
| GET | `/api/projects/{id}/audio` | `[{scene_id, file_url, duration_s, text}]` narration clips |
| GET | `/api/projects/{id}/history` | `[{at, actor, action, detail}]` audit log |

## Jobs (local queue; GPU jobs run one at a time)
Job object:
```
{id, project_id, kind, stage, status: "queued"|"running"|"done"|"failed"|"cancelled",
 progress: 0..1, message, created_at, started_at, finished_at, attempts,
 metrics: {exec_s, cpu_s, gpu: bool, api_cost_usd, render_s, output_bytes, cache_hit},
 result: any, error: str|null}
```
| GET | `/api/jobs?project_id=&status=` | list, newest first |
| GET | `/api/jobs/{id}` | job |
| POST | `/api/jobs/{id}/cancel` | job |
| POST | `/api/jobs/{id}/retry` | new job |

## Agents (API providers + Claude Code / Codex sessions)
| GET | `/api/agents` | `[{id: "claude_code"|"codex"|"anthropic_api"|"openai_api"|"gemini_api", label, kind: "session"|"api", available: bool, detail, models: [str]}]` |
| POST | `/api/agents/run` | body `{backend, prompt, project_id?, task: "free"|"research"|"scenario"|"script"|"review", session_id?, model?, write_access?: bool}` → job; `job.result = {text, session_id, cost_usd, structured}` |
| GET | `/api/agents/sessions?project_id=` | `[{backend, session_id, project_id, title, updated_at, turns}]` (resume by passing `session_id`) |

## Costs
| GET | `/api/costs?project_id=` | `{budget_usd, spent_usd, entries: [{at, backend, model, task, cost_usd, tokens_in, tokens_out, estimated: bool}]}` |

## Assets
| GET | `/api/assets?q=&period=&region=&category=` | `[{asset_id, name, period, region, category, polygon_count, materials, license, source, accuracy_notes, preview_url, file_path}]` |

## Trends / Analytics
| GET | `/api/trends/status` | `{configured: bool, reason}` |
| GET | `/api/trends/channels` | `[{channel_id, title, handle, subscribers, video_count, collected_at}]` |
| POST | `/api/trends/channels` | `{handle_or_id}` |
| POST | `/api/trends/collect` | → job (needs YOUTUBE_API_KEY) |
| GET | `/api/trends/videos` | `[{video_id, channel_title, title, published_at, duration_s, views, views_per_day, views_per_subscriber, age_days, growth_per_day: number|null}]` growth only when ≥2 snapshots |
| GET | `/api/analytics/status` | `{connected: false, reason}` until OAuth is set up |

## Files
`GET /files/{project_id}/{relative_path}` serves files from the project's video folder with HTTP Range support
(MP4/WAV/JPG/PNG/JSON/SRT). Asset previews: `GET /assets-files/{asset_id}/{file}`.
