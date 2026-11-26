# TIMELINES Studio — architecture

```
 Next.js dashboard (frontend/out, static)            Claude Code / Codex session
          │  HTTP /api (docs/API.md)                     │  MCP stdio (timelines.mcp_server)
          ▼                                              ▼
   FastAPI  timelines.api  ───────────────►  timelines.pipeline (stage handlers)
          │                                       │
          ├─ timelines.jobs   SQLite job queue: 2 CPU workers + 1 GPU lane
          │                   (GPU lane + Blender also take ultradedit gpu_lock)
          ├─ timelines.agents API backends (Anthropic / OpenAI / Gemini, budget-capped)
          │                   session backends (claude -p --resume, codex exec resume)
          ├─ timelines.db     projects, jobs, costs, agent sessions, history, settings, trend snapshots
          └─ timelines.storage  per-video folder + validated JSON artifacts (+ stale tracking)
                                  │
                ultradedit research/timelines_videos/<video_id>/
                sources/ edit/{artifacts,scenes,audio,premiere} work/previews final/ retention_records/ evidence/qc_tmp
```

## Stage graph (each stage = one job; artifacts are schema-validated JSON)

| Stage | Module | Input → Output | State after |
|---|---|---|---|
| research | agents (session/API) or import | topic → `research_dossier` (sources, FACT/INTERPRETATION/SPECULATION claims, conflicts) | RESEARCH_REVIEW |
| scenario | agents or import | dossier → `scenario` (divergence, causal event graph, map changes; unsourced numbers rejected) | — |
| script | agents or import | dossier + scenario → `script` (segments with claim ids, scene type, camera/animation notes) | SCRIPT_REVIEW |
| storyboard | agents or import | script → `storyboard` (per-scene MapSpec / Scene3DSpec / GraphicSpec, transitions) | STORYBOARD |
| tts | modules.audio | script → narration WAV + word timings; retimes every scene from real narration length | — |
| previews | maps / graphics (process pool) / blender3d | storyboard → `work/previews/*_preview.mp4` (half res) | ASSET_PRODUCTION |
| review_previews (optional) | agents | preview frames → approve/reject recorded as an agent decision | — |
| approve (UI / CLI / MCP) | pipeline.approve_scene | gate: final renders need an approved preview | — |
| finals | same renderers | approved scenes → `edit/scenes/*_final.mp4` (+ .blend) | RENDERING |
| compose | modules.editor + audio | scenes + narration → final MP4, SRT, mix WAV, timeline JSON, FCP7 XML | EDITING |
| qa | modules.qa | final MP4 (measured) → `qc_report`; qc_tmp frames cleaned on pass | FINAL_REVIEW |
| publish_prep | modules.publishing | → `publish_package` (titles, description, chapters, sources, disclosure). No upload. | — |
| finalize | ultradedit video_retention | seal(final, QC, sources, edit, premiere) → maybe_finish | READY |

Caching: scene renders carry a `.key` (hash of spec + renderer version + quality); unchanged scenes are
skipped. TTS takes are keyed by provider/voice/rate/text. Editing an artifact marks downstream artifacts `stale`.

## Integration with the ultradedit editing workflow
- Storage: every project is created with `video_retention.init` under `research/timelines_videos/`, sealed with
  `seal` (sources, `edit/`, `edit/premiere`) and cleaned with `maybe_finish` only after the matching QC passed.
- Inspection frames: `evidence/qc_tmp/qc_frame_*.png`, removed by `qc_cleanup.cleanup_after_qc` after a pass.
- GPU: Blender renders hold `research/portfolio_flagship_20261029/gpu_lock.py` (one GPU job at a time,
  honours `E:/Flagship_work/GPU_PAUSE`).
- Premiere: `edit/premiere/<video>_vNN.xml` (xmeml v4; cuts only).
- Agent rules kept from the workspace: automatic QC ≠ human viewing; approvals record the actor (user / agent / mcp).
