"""Command line: serve the studio, run stages, approve previews, export schemas.

  python -m timelines.cli serve
  python -m timelines.cli new --title T --topic "..." --duration 90
  python -m timelines.cli run PROJECT STAGE [--params JSON]
  python -m timelines.cli approve PROJECT SCENE [--reject] --note "..." [--actor NAME]
  python -m timelines.cli sample-roman            # builds the Phase 1 sample end to end
  python -m timelines.cli export-schemas
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, jobs, pipeline
from .schemas import SCHEMAS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="timelines")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    n = sub.add_parser("new")
    n.add_argument("--title", required=True)
    n.add_argument("--topic", required=True)
    n.add_argument("--duration", type=float, default=90)
    r = sub.add_parser("run")
    r.add_argument("project")
    r.add_argument("stage")
    r.add_argument("--params", default="{}")
    a = sub.add_parser("approve")
    a.add_argument("project")
    a.add_argument("scene")
    a.add_argument("--reject", action="store_true")
    a.add_argument("--note", default="")
    a.add_argument("--actor", default="user")
    s = sub.add_parser("sample-roman")
    s.add_argument("--project", help="reuse an existing project id")
    s.add_argument("--until", default="previews")
    sub.add_parser("export-schemas")
    args = ap.parse_args(argv)

    from . import api  # noqa: F401 - registers agent/trends handlers
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("timelines.api:app", host="127.0.0.1", port=config.PORT, log_level="info")
    elif args.cmd == "new":
        p = pipeline.create_project(args.title, args.topic, target_duration_s=args.duration)
        print(json.dumps({"id": p.id, "video_dir": p.video_dir}))
    elif args.cmd == "run":
        res = jobs.run_inline(args.stage, args.project, json.loads(args.params))
        print(json.dumps({k: res[k] for k in ("status", "result", "error", "metrics")}, indent=2, default=str))
        return 0 if res["status"] == "done" else 1
    elif args.cmd == "approve":
        print(json.dumps(pipeline.approve_scene(args.project, args.scene, not args.reject, args.note, args.actor)))
    elif args.cmd == "sample-roman":
        sample = config.ROOT / "samples" / "roman_empire"
        pid = args.project
        if not pid:
            p = pipeline.create_project("What If the Roman Empire Never Fell?",
                                        "What if the Western Roman Empire never fell in 476 CE?",
                                        target_duration_s=80)
            pid = p.id
        params = {"research": {"dossier_file": str(sample / "research" / "research_dossier.json")},
                  "scenario": {"scenario_file": str(sample / "scenario.json")},
                  "script": {"script_file": str(sample / "script.json")},
                  "storyboard": {"storyboard_file": str(sample / "storyboard.json")}}
        out = pipeline.run_all(pid, params, stop_after=args.until)
        for res in out:
            print(res["stage"], res["status"], json.dumps(res["result"], default=str)[:300], res["error"] or "")
        print("project", pid)
    elif args.cmd == "export-schemas":
        d = config.ROOT / "docs" / "schemas"
        d.mkdir(parents=True, exist_ok=True)
        for name, model in SCHEMAS.items():
            (d / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2), "utf-8")
        print(f"wrote {len(SCHEMAS)} schemas to {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
