"""The one place LLM calls are made.

Determinism for the demo:
  * Every call is keyed by sha256(model, task, prompt version, system, user text, schema).
  * Results are written to LLM_CACHE_DIR/<task>/<key>.json and served from there on later runs.
  * With no ANTHROPIC_API_KEY the client serves the cache, and on a miss runs the deterministic stub for
    that task (sherlock/llm/stub.py). Stub output is never written to the cache, so a stub answer can
    never shadow a real one once a key is available.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sherlock.config import Settings, get_settings
from sherlock.llm.schemas import TASK_SCHEMAS
from sherlock.llm.stub import STUBS


class CacheMiss(RuntimeError):
    pass


@dataclass
class LLMResult:
    output: dict[str, Any]
    source: str  # api | cache | stub
    cache_key: str
    model: str


class LLMClient:
    def __init__(self, settings: Settings | None = None, allow_stub: bool = True):
        self.settings = settings or get_settings()
        self.cache_dir = Path(self.settings.llm_cache_dir)
        self.allow_stub = allow_stub
        self._client = None

    @property
    def has_key(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    def complete_json(self, task: str, prompt_version: str, system: str, user: str, stub_input: Any = None) -> LLMResult:
        schema_model = TASK_SCHEMAS[task]
        schema = schema_model.model_json_schema()
        model = self.settings.anthropic_model
        key = _cache_key(model, task, prompt_version, system, user, schema)
        path = self.cache_dir / task / f"{key}.json"

        cached = _read(path)
        if cached:
            return LLMResult(schema_model.model_validate(cached["output"]).model_dump(), "cache", key, cached["model"])

        if self.has_key:
            output = schema_model.model_validate(self._call_api(model, system, user, schema)).model_dump()
            _write(path, {"task": task, "prompt_version": prompt_version, "model": model, "source": "api",
                          "created_at": datetime.now(timezone.utc).isoformat(), "output": output})
            return LLMResult(output, "api", key, model)

        if self.allow_stub:
            output = schema_model.model_validate(STUBS[task](stub_input if stub_input is not None else user)).model_dump()
            return LLMResult(output, "stub", key, "stub")
        raise CacheMiss(f"no ANTHROPIC_API_KEY and no cached result for {task}/{key}")

    def _call_api(self, model: str, system: str, user: str, schema: dict) -> dict:
        import anthropic

        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        response = self._client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"LLM declined the request: {getattr(response.stop_details, 'explanation', '')}")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)


def _cache_key(model: str, task: str, version: str, system: str, user: str, schema: dict) -> str:
    payload = json.dumps({"model": model, "task": task, "version": version, "system": system, "user": user,
                          "schema": schema}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


_default: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient()
    return _default
