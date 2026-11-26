"""Provider-agnostic agent layer.

Two kinds of backends share one interface (`run(AgentRequest) -> AgentResult`):
  * session backends drive the locally logged-in CLIs - Claude Code (`claude -p`, resumable by
    session id) and Codex (`codex exec`, resumable by thread id). They use the user's own
    subscriptions; API keys are stripped from their environment so they never bill an API key.
  * API backends call the Anthropic, OpenAI and Gemini APIs with keys from the environment.

Every call is written to the cost ledger. API calls are refused once the project's budget is spent.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from . import config, db

# USD per million tokens (input, output). Anthropic: claude-api skill table cached 2026-11-03.
# OpenAI/Gemini prices are not bundled: set them in settings["prices"] or the ledger records the
# conservative FALLBACK price and marks the entry as estimated.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50), "claude-fable-5-2": (8.0, 40.0),
}
FALLBACK_PRICE = (15.0, 75.0)


class BudgetExceeded(RuntimeError):
    pass


class BackendUnavailable(RuntimeError):
    pass


@dataclass
class AgentRequest:
    prompt: str
    task: str = "free"
    project_id: str | None = None
    model: str | None = None
    session_id: str | None = None
    json_schema: dict | None = None
    system: str | None = None
    cwd: str | None = None
    write_access: bool = False
    timeout_s: int = 1800


@dataclass
class AgentResult:
    text: str
    backend: str
    model: str = ""
    session_id: str | None = None
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    estimated: bool = False
    structured: Any = None
    raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"text": self.text, "backend": self.backend, "model": self.model, "session_id": self.session_id,
                "cost_usd": round(self.cost_usd, 5), "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "estimated": self.estimated, "structured": self.structured}


SESSION_BACKENDS = ("claude_code", "codex")


def project_spent(project_id: str | None, *, billed_only: bool = True) -> float:
    """API spend counted against the budget. Session backends run on subscriptions (notional cost)."""
    with db.session() as s:
        q = select(func.coalesce(func.sum(db.CostEntry.cost_usd), 0.0))
        if billed_only:
            q = q.where(db.CostEntry.backend.not_in(SESSION_BACKENDS))
        if project_id:
            q = q.where(db.CostEntry.project_id == project_id)
        return float(s.scalar(q) or 0.0)


def project_budget(project_id: str | None) -> float:
    if project_id == "dev":                      # development work billed to the API key
        return float(db.get_setting("dev_budget_usd"))
    if project_id:
        with db.session() as s:
            p = s.get(db.Project, project_id)
            if p:
                return p.budget_usd
    return float(db.get_setting("budget_usd"))


def _price(model: str) -> tuple[tuple[float, float], bool]:
    custom = db.get_setting("prices") or {}
    if model in custom:
        return tuple(custom[model]), False  # type: ignore[return-value]
    for key, price in PRICES.items():
        if model.startswith(key):
            return price, False
    return FALLBACK_PRICE, True


def _record(req: AgentRequest, res: AgentResult) -> None:
    with db.session() as s:
        s.add(db.CostEntry(project_id=req.project_id, backend=res.backend, model=res.model, task=req.task,
                           cost_usd=res.cost_usd, tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                           estimated=res.estimated))
        if res.session_id:
            row = s.scalars(select(db.AgentSession).where(db.AgentSession.backend == res.backend,
                                                          db.AgentSession.session_id == res.session_id)).first()
            if row:
                row.turns += 1
                row.updated_at = db.now()
            else:
                s.add(db.AgentSession(backend=res.backend, session_id=res.session_id, project_id=req.project_id,
                                      title=req.prompt.strip().splitlines()[0][:120] if req.prompt.strip() else ""))
        s.commit()


def _clean_env(*drop: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in drop:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _schema_instruction(schema: dict | None) -> str:
    if not schema:
        return ""
    return ("\n\nReturn ONLY one JSON object that validates against this JSON Schema (no prose, no code fence):\n"
            + json.dumps(schema, ensure_ascii=False))


def _parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in agent output")
    return json.loads(text[start:end + 1])


# ------------------------------------------------------------------ session backends
class ClaudeCodeBackend:
    id, label, kind = "claude_code", "Claude Code session", "session"
    models = ["sonnet", "opus", "haiku", "fable"]

    def available(self) -> tuple[bool, str]:
        exe = config.cli_exe("claude")
        return (True, config.tool_report()["claude_cli"]["version"] or exe) if exe else (False, "claude CLI not found")

    def run(self, req: AgentRequest, _remaining: float | None = None, _api: bool = False) -> AgentResult:
        exe = config.cli_exe("claude")
        if not exe:
            raise BackendUnavailable("claude CLI not found on PATH")
        model = req.model or (db.get_setting("default_model") or {}).get(self.id) or "sonnet"
        cmd = [exe, "-p", "--output-format", "json", "--model", model]
        if req.session_id:
            cmd += ["--resume", req.session_id]
        if req.json_schema:
            cmd += ["--json-schema", json.dumps(req.json_schema)]
        if req.system:
            cmd += ["--append-system-prompt", req.system]
        # Per-call ceiling on Claude Code's cost meter: real money in API mode, notional on a subscription.
        ceiling = _remaining if _remaining is not None else max(0.5, project_budget(req.project_id))
        cmd += ["--max-budget-usd", f"{max(0.05, ceiling):.2f}"]
        if req.write_access and req.task.startswith("dev_shell"):
            # development session: edits + shell (Blender, ffmpeg, pytest) inside timelines_studio
            cmd += ["--permission-mode", "acceptEdits", "--add-dir", str(config.ROOT), "--allowedTools",
                    "Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebSearch", "WebFetch"]
        elif req.write_access:
            cmd += ["--permission-mode", "acceptEdits", "--add-dir", str(config.ROOT),
                    "--allowedTools", "Bash(.venv/Scripts/python.exe -m pytest:*)",
                    "Bash(.venv\Scripts\python.exe -m pytest:*)"]
        else:
            cmd += ["--allowedTools", "Read", "Glob", "Grep", "WebSearch", "WebFetch"]
        proc = subprocess.run(cmd, input=req.prompt, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=req.cwd or str(config.ROOT), timeout=req.timeout_s,
                              env=_clean_env("ANTHROPIC_AUTH_TOKEN") if _api
                              else _clean_env("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
        try:
            data = json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[-1500:]}") from None
        if data.get("is_error"):
            raise RuntimeError(f"claude error: {data.get('result') or data.get('subtype')}")
        usage = data.get("usage") or {}
        text = data.get("result") or ""
        structured = data.get("structured_output")
        if req.json_schema and structured is None and text:
            structured = _parse_json(text)
        # total_cost_usd is Claude Code's notional cost; on a subscription it is not billed.
        return AgentResult(text=text, backend=self.id, model=model, session_id=data.get("session_id"),
                           cost_usd=float(data.get("total_cost_usd") or 0), estimated=True,
                           tokens_in=int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0),
                           tokens_out=int(usage.get("output_tokens") or 0), structured=structured,
                           raw={"duration_ms": data.get("duration_ms"), "num_turns": data.get("num_turns")})


class ClaudeCodeAPIBackend(ClaudeCodeBackend):
    """Claude Code harness (tools: Read/Glob/Grep/WebSearch/WebFetch, optional edits) billed to
    ANTHROPIC_API_KEY instead of the subscription. Counted against the project budget."""
    id, label, kind = "claude_code_api", "Claude Code (API key billing)", "session"

    def available(self) -> tuple[bool, str]:
        ok, detail = super().available()
        if not ok:
            return ok, detail
        return (True, f"{detail}; billed to ANTHROPIC_API_KEY") if os.environ.get("ANTHROPIC_API_KEY")             else (False, "ANTHROPIC_API_KEY not set")

    def run(self, req: AgentRequest) -> AgentResult:
        spent, budget = project_spent(req.project_id), project_budget(req.project_id)
        if spent >= budget:
            raise BudgetExceeded(f"budget ${budget:.2f} spent (${spent:.2f}); raise it in Settings to continue")
        res = super().run(req, _remaining=budget - spent, _api=True)
        res.backend, res.estimated = self.id, False
        return res


class CodexBackend:
    id, label, kind = "codex", "Codex session", "session"
    models = ["(config default)"]

    def available(self) -> tuple[bool, str]:
        exe = config.cli_exe("codex")
        return (True, config.tool_report()["codex_cli"]["version"] or exe) if exe else (False, "codex CLI not found")

    def run(self, req: AgentRequest) -> AgentResult:
        exe = config.cli_exe("codex")
        if not exe:
            raise BackendUnavailable("codex CLI not found on PATH")
        with tempfile.TemporaryDirectory(prefix="tl_codex_") as tmp:
            last = Path(tmp) / "last.txt"
            base = ["--json", "--skip-git-repo-check", "-o", str(last)]
            if req.model and not req.model.startswith("("):
                base += ["-m", req.model]
            if req.json_schema and not req.session_id:
                schema_file = Path(tmp) / "schema.json"
                schema_file.write_text(json.dumps(req.json_schema), "utf-8")
                base += ["--output-schema", str(schema_file)]
            if req.session_id:
                cmd = [exe, "exec", "resume", req.session_id, *base, "-"]
            else:
                sandbox = "workspace-write" if req.write_access else "read-only"
                cmd = [exe, "exec", "-s", sandbox, "-C", req.cwd or str(config.ROOT), *base, "-"]
            prompt = (req.system + "\n\n" if req.system else "") + req.prompt
            if req.json_schema and req.session_id:
                prompt += _schema_instruction(req.json_schema)
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=req.timeout_s,
                                  env=_clean_env("OPENAI_API_KEY"), cwd=req.cwd or str(config.ROOT))
            thread, tin, tout, messages = req.session_id, 0, 0, []
            for line in proc.stdout.splitlines():
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "thread.started":
                    thread = ev.get("thread_id") or thread
                elif ev.get("type") == "turn.completed":
                    u = ev.get("usage") or {}
                    tin += int(u.get("input_tokens") or 0)
                    tout += int(u.get("output_tokens") or 0)
                elif ev.get("type") == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                    messages.append(ev["item"].get("text", ""))
                elif ev.get("type") in ("error", "turn.failed"):
                    raise RuntimeError(f"codex: {json.dumps(ev)[:1500]}")
            # stdout JSONL is UTF-8; the -o file may be written in the console code page on Windows.
            text = messages[-1] if messages else (last.read_text("utf-8", errors="replace") if last.exists() else "")
            if proc.returncode != 0 and not text:
                raise RuntimeError(f"codex exited {proc.returncode}: {proc.stderr[-1500:]}")
        structured = _parse_json(text) if req.json_schema and text else None
        # Codex reports tokens but no price; subscription usage is not billed per call.
        return AgentResult(text=text, backend=self.id, model=req.model or "codex-default", session_id=thread,
                           tokens_in=tin, tokens_out=tout, cost_usd=0.0, estimated=True, structured=structured)


# ------------------------------------------------------------------ API backends
class _APIBase:
    kind = "api"
    key_env = ""

    def available(self) -> tuple[bool, str]:
        return (True, f"{self.key_env} set") if os.environ.get(self.key_env) else (False, f"{self.key_env} not set")

    def _guard(self, req: AgentRequest) -> None:
        ok, why = self.available()
        if not ok:
            raise BackendUnavailable(why)
        if req.session_id:
            raise ValueError("API backends are stateless; resume is only for session backends")
        spent, budget = project_spent(req.project_id), project_budget(req.project_id)
        if spent >= budget:
            raise BudgetExceeded(f"budget ${budget:.2f} spent (${spent:.2f}); raise it in Settings to continue")

    def _cost(self, model: str, tin: int, tout: int) -> tuple[float, bool]:
        (pi, po), estimated = _price(model)
        return tin / 1e6 * pi + tout / 1e6 * po, estimated


class AnthropicAPIBackend(_APIBase):
    id, label, key_env = "anthropic_api", "Anthropic API", "ANTHROPIC_API_KEY"
    models = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]

    def run(self, req: AgentRequest) -> AgentResult:
        self._guard(req)
        import anthropic
        model = req.model or (db.get_setting("default_model") or {}).get(self.id) or "claude-opus-5-5"
        client = anthropic.Anthropic()
        kwargs: dict[str, Any] = dict(model=model, max_tokens=16000,
                                      messages=[{"role": "user", "content": req.prompt}],
                                      output_config={"effort": "high"})
        if req.system:
            kwargs["system"] = req.system
        if req.json_schema:
            kwargs["output_config"]["format"] = {"type": "json_schema", "schema": req.json_schema}
        # Server-side refusal fallback (opt-in default for current models).
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"refused: {getattr(resp.stop_details, 'category', None)}")
        text = "".join(b.text for b in resp.content if b.type == "text")
        tin = resp.usage.input_tokens + (resp.usage.cache_read_input_tokens or 0)
        cost, est = self._cost(resp.model or model, tin, resp.usage.output_tokens)
        return AgentResult(text=text, backend=self.id, model=resp.model or model, cost_usd=cost, estimated=est,
                           tokens_in=tin, tokens_out=resp.usage.output_tokens,
                           structured=_parse_json(text) if req.json_schema else None)


class OpenAIAPIBackend(_APIBase):
    id, label, key_env = "openai_api", "OpenAI API", "OPENAI_API_KEY"
    models = ["gpt-5", "gpt-5-mini"]

    def run(self, req: AgentRequest) -> AgentResult:
        self._guard(req)
        from openai import OpenAI
        model = req.model or (db.get_setting("default_model") or {}).get(self.id) or "gpt-5"
        client = OpenAI()
        messages = ([{"role": "system", "content": req.system}] if req.system else []) + \
                   [{"role": "user", "content": req.prompt + _schema_instruction(req.json_schema)}]
        kwargs: dict[str, Any] = {}
        if req.json_schema:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(model=model, messages=messages, **kwargs)
        text = resp.choices[0].message.content or ""
        tin, tout = resp.usage.prompt_tokens, resp.usage.completion_tokens
        cost, est = self._cost(model, tin, tout)
        return AgentResult(text=text, backend=self.id, model=model, cost_usd=cost, estimated=est, tokens_in=tin,
                           tokens_out=tout, structured=_parse_json(text) if req.json_schema else None)


class GeminiAPIBackend(_APIBase):
    id, label, key_env = "gemini_api", "Gemini API", "GEMINI_API_KEY"
    models = ["gemini-2.5-pro", "gemini-2.5-flash"]

    def run(self, req: AgentRequest) -> AgentResult:
        self._guard(req)
        import httpx
        model = req.model or (db.get_setting("default_model") or {}).get(self.id) or "gemini-2.5-pro"
        body: dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": req.prompt + _schema_instruction(req.json_schema)}]}]}
        if req.system:
            body["systemInstruction"] = {"parts": [{"text": req.system}]}
        if req.json_schema:
            body["generationConfig"] = {"responseMimeType": "application/json"}
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                       headers={"x-goog-api-key": os.environ[self.key_env]}, json=body, timeout=req.timeout_s)
        r.raise_for_status()
        data = r.json()
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        u = data.get("usageMetadata", {})
        tin, tout = int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0))
        cost, est = self._cost(model, tin, tout)
        return AgentResult(text=text, backend=self.id, model=model, cost_usd=cost, estimated=est, tokens_in=tin,
                           tokens_out=tout, structured=_parse_json(text) if req.json_schema else None)


BACKENDS = {b.id: b for b in (ClaudeCodeBackend(), ClaudeCodeAPIBackend(), CodexBackend(), AnthropicAPIBackend(), OpenAIAPIBackend(),
                              GeminiAPIBackend())}


def list_backends() -> list[dict]:
    out = []
    for b in BACKENDS.values():
        ok, detail = b.available()
        out.append({"id": b.id, "label": b.label, "kind": b.kind, "available": ok, "detail": detail,
                    "models": b.models})
    return out


def run(req: AgentRequest, backend: str | None = None) -> AgentResult:
    name = backend or db.get_setting("default_backend")
    if name not in BACKENDS:
        raise KeyError(f"unknown backend {name}")
    t0 = time.monotonic()
    res = BACKENDS[name].run(req)
    res.raw["wall_s"] = round(time.monotonic() - t0, 1)
    _record(req, res)
    return res
