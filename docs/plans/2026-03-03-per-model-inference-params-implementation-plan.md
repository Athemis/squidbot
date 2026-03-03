# Per-Model Inference Parameters — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`,
`reasoning_effort`, and `extra_body` to be set per model in `squidbot.yaml` and
forwarded to the OpenAI-compatible API; also fix the existing bug where
`max_tokens` is configured but never passed to the API.

**Architecture:** Three-layer change: config schema → adapter → wiring. A new
`_build_kwargs()` helper in `OpenAIAdapter` eliminates the duplicated `kwargs`
assembly between `_stream()` and `_complete()`. All new fields are `None`/empty
by default so existing configs require no changes.

**Tech Stack:** Python 3.14, Pydantic v2, openai SDK, pytest, mypy --strict, ruff.

**Design doc:** `docs/plans/2026-03-03-per-model-inference-params-design.md`

---

## Task 1: Extend `LLMModelConfig` in the config schema

**Files:**
- Modify: `squidbot/config/schema.py:28–34`
- Test: `tests/core/test_config.py` (new file)

### Step 1: Write the failing tests

```python
# tests/core/test_config.py
"""Tests for LLMModelConfig inference parameter fields."""

from __future__ import annotations

import json

import pytest

from squidbot.config.schema import LLMModelConfig, Settings


def test_llm_model_config_defaults() -> None:
    cfg = LLMModelConfig(provider="openai", model="gpt-4o")
    assert cfg.temperature is None
    assert cfg.top_p is None
    assert cfg.presence_penalty is None
    assert cfg.frequency_penalty is None
    assert cfg.reasoning_effort is None
    assert cfg.extra_body == {}
    assert cfg.max_tokens == 8192


def test_llm_model_config_full_params() -> None:
    cfg = LLMModelConfig(
        provider="openai",
        model="o3",
        temperature=0.6,
        top_p=0.95,
        presence_penalty=0.1,
        frequency_penalty=0.2,
        reasoning_effort="high",
        extra_body={"min_p": 0.01},
    )
    assert cfg.temperature == 0.6
    assert cfg.top_p == 0.95
    assert cfg.presence_penalty == 0.1
    assert cfg.frequency_penalty == 0.2
    assert cfg.reasoning_effort == "high"
    assert cfg.extra_body == {"min_p": 0.01}


def test_llm_model_config_reasoning_effort_invalid() -> None:
    with pytest.raises(Exception):
        LLMModelConfig(provider="openai", model="o3", reasoning_effort="ultra")


def test_llm_model_config_json_round_trip() -> None:
    cfg = LLMModelConfig(
        provider="moonshot",
        model="kimi-k2.5",
        temperature=1.0,
        extra_body={"thinking": {"type": "enabled"}},
    )
    data = json.loads(cfg.model_dump_json())
    restored = LLMModelConfig.model_validate(data)
    assert restored.temperature == 1.0
    assert restored.extra_body == {"thinking": {"type": "enabled"}}


def test_settings_with_inference_params_loads_from_json(tmp_path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({
            "llm": {
                "providers": {"local": {"api_base": "http://localhost:8001/v1"}},
                "models": {
                    "kimi": {
                        "provider": "local",
                        "model": "kimi-k2.5",
                        "temperature": 0.6,
                        "top_p": 0.95,
                        "extra_body": {"thinking": {"type": "disabled"}},
                    }
                },
                "pools": {"default": [{"model": "kimi"}]},
            }
        })
    )
    settings = Settings.load(config_file)
    model_cfg = settings.llm.models["kimi"]
    assert model_cfg.temperature == 0.6
    assert model_cfg.top_p == 0.95
    assert model_cfg.extra_body == {"thinking": {"type": "disabled"}}
```

### Step 2: Run to verify they fail

```bash
uv run pytest tests/core/test_config.py -v
```

Expected: `FAILED` — `LLMModelConfig` has no `temperature` attribute.

### Step 3: Implement the changes in `squidbot/config/schema.py`

Replace the `LLMModelConfig` class (lines 28–34):

```python
class LLMModelConfig(BaseModel):
    """A named model definition referencing a provider."""

    provider: str
    model: str
    max_tokens: int = 8192
    max_context_tokens: int = 100_000
    # Inference parameters — all optional; provider must support them.
    # See README § "Model-specific inference parameters" for provider notes.
    temperature: float | None = None
    top_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
```

`Literal` and `Any` are already imported in the file (`from typing import Any, Literal`).

### Step 4: Run tests to verify they pass

```bash
uv run pytest tests/core/test_config.py -v
uv run mypy squidbot/config/schema.py
```

Expected: all `PASSED`, mypy clean.

### Step 5: Commit

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat(config): add inference params to LLMModelConfig"
```

---

## Task 2: Refactor `OpenAIAdapter` — add `_build_kwargs` + new constructor params

**Files:**
- Modify: `squidbot/adapters/llm/openai.py`
- Test: `tests/adapters/llm/test_openai_adapter.py` (new file)

### Step 1: Write the failing tests

```python
# tests/adapters/llm/test_openai_adapter.py
"""Tests for OpenAIAdapter._build_kwargs inference parameter forwarding."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squidbot.adapters.llm.openai import OpenAIAdapter


def _make_adapter(**kwargs: Any) -> OpenAIAdapter:
    """Build an adapter with a mocked AsyncOpenAI client."""
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI"):
        return OpenAIAdapter(
            api_base="http://localhost:8001/v1",
            api_key="test",
            model="kimi-k2.5",
            **kwargs,
        )


class TestBuildKwargs:
    def test_minimal_stream(self) -> None:
        adapter = _make_adapter()
        kwargs = adapter._build_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            stream=True,
        )
        assert kwargs["model"] == "kimi-k2.5"
        assert kwargs["stream"] is True
        assert "tools" not in kwargs
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs
        assert "max_tokens" not in kwargs
        assert "extra_body" not in kwargs

    def test_max_tokens_always_forwarded(self) -> None:
        adapter = _make_adapter(max_tokens=16384)
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert kwargs["max_tokens"] == 16384

    def test_temperature_forwarded_when_set(self) -> None:
        adapter = _make_adapter(temperature=0.6)
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert kwargs["temperature"] == 0.6

    def test_temperature_absent_when_none(self) -> None:
        adapter = _make_adapter(temperature=None)
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert "temperature" not in kwargs

    def test_top_p_forwarded(self) -> None:
        adapter = _make_adapter(top_p=0.95)
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert kwargs["top_p"] == 0.95

    def test_presence_penalty_forwarded(self) -> None:
        adapter = _make_adapter(presence_penalty=0.1)
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert kwargs["presence_penalty"] == 0.1

    def test_frequency_penalty_forwarded(self) -> None:
        adapter = _make_adapter(frequency_penalty=0.2)
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert kwargs["frequency_penalty"] == 0.2

    def test_reasoning_effort_forwarded(self) -> None:
        adapter = _make_adapter(reasoning_effort="high")
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert kwargs["reasoning_effort"] == "high"

    def test_extra_body_forwarded_when_non_empty(self) -> None:
        adapter = _make_adapter(extra_body={"thinking": {"type": "disabled"}})
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_extra_body_absent_when_empty(self) -> None:
        adapter = _make_adapter(extra_body={})
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=False)
        assert "extra_body" not in kwargs

    def test_tools_included_when_provided(self) -> None:
        tools = [{"type": "function", "function": {"name": "f"}}]
        adapter = _make_adapter()
        kwargs = adapter._build_kwargs(messages=[], tools=tools, stream=True)
        assert kwargs["tools"] == tools

    def test_all_params_set(self) -> None:
        adapter = _make_adapter(
            max_tokens=4096,
            temperature=1.0,
            top_p=0.95,
            presence_penalty=0.0,
            frequency_penalty=0.0,
            reasoning_effort="medium",
            extra_body={"min_p": 0.01},
        )
        kwargs = adapter._build_kwargs(messages=[], tools=None, stream=True)
        assert kwargs["max_tokens"] == 4096
        assert kwargs["temperature"] == 1.0
        assert kwargs["top_p"] == 0.95
        assert kwargs["presence_penalty"] == 0.0
        assert kwargs["frequency_penalty"] == 0.0
        assert kwargs["reasoning_effort"] == "medium"
        assert kwargs["extra_body"] == {"min_p": 0.01}
```

### Step 2: Run to verify they fail

```bash
uv run pytest tests/adapters/llm/test_openai_adapter.py -v
```

Expected: `FAILED` — `OpenAIAdapter` has no `_build_kwargs` or the new constructor params.

### Step 3: Implement in `squidbot/adapters/llm/openai.py`

Replace the `OpenAIAdapter` class body. Changes:

1. Add six parameters to `__init__` after `supports_reasoning_content`.
2. Add `_build_kwargs()` method.
3. Replace inline `kwargs` assembly in `_stream()` and `_complete()` with a call to `_build_kwargs()`.

```python
class OpenAIAdapter:
    """
    LLM adapter for OpenAI-compatible endpoints.

    Implements LLMPort via structural subtyping (no explicit inheritance).
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        supports_reasoning_content: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
        reasoning_effort: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        """
        Args:
            api_base: Base URL for the API (e.g., "https://openrouter.ai/api/v1").
            api_key: API key for authentication.
            model: Model identifier (e.g., "anthropic/claude-opus-4-5").
            supports_reasoning_content: Whether provider supports reasoning content fields.
            max_tokens: Maximum tokens in the response. Forwarded only when set.
            temperature: Sampling temperature. Forwarded only when set.
            top_p: Nucleus sampling probability. Forwarded only when set.
            presence_penalty: Presence penalty. Forwarded only when set.
            frequency_penalty: Frequency penalty. Forwarded only when set.
            reasoning_effort: Reasoning effort for o-series models ("low"/"medium"/"high").
                Forwarded only when set.
            extra_body: Provider-specific parameters passed via the OpenAI SDK
                extra_body mechanism (e.g. {"thinking": {"type": "disabled"}}).
                Forwarded only when non-empty.
        """
        self._client = AsyncOpenAI(base_url=api_base, api_key=api_key)
        self._model = model
        self._supports_reasoning_content = supports_reasoning_content
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p
        self._presence_penalty = presence_penalty
        self._frequency_penalty = frequency_penalty
        self._reasoning_effort = reasoning_effort
        self._extra_body: dict[str, Any] = extra_body or {}

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """
        Build kwargs for chat.completions.create.

        Only includes optional parameters that have been explicitly configured,
        preserving provider defaults for everything else.

        Args:
            messages: Formatted OpenAI message dicts.
            tools: Formatted OpenAI tool dicts, or None.
            stream: Whether to request a streaming response.

        Returns:
            kwargs dict ready for AsyncOpenAI.chat.completions.create(**kwargs).
        """
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if stream:
            kwargs["stream"] = True
        if tools:
            kwargs["tools"] = tools
        if self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._top_p is not None:
            kwargs["top_p"] = self._top_p
        if self._presence_penalty is not None:
            kwargs["presence_penalty"] = self._presence_penalty
        if self._frequency_penalty is not None:
            kwargs["frequency_penalty"] = self._frequency_penalty
        if self._reasoning_effort is not None:
            kwargs["reasoning_effort"] = self._reasoning_effort
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        return kwargs

    # In _stream(), replace the kwargs block (lines 109–111) with:
    #   kwargs = self._build_kwargs(messages, tools, stream=True)
    #
    # In _complete(), replace the kwargs block (lines 168–170) with:
    #   kwargs = self._build_kwargs(messages, tools, stream=False)
```

Full diff for `_stream` (replace lines 106–112):
```python
    async def _stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[str | list[ToolCall] | tuple[list[ToolCall], str | None]]:
        """Stream response chunks and accumulate tool calls."""
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}
        accumulated_reasoning: list[str] = []

        kwargs = self._build_kwargs(messages, tools, stream=True)

        async with await self._client.chat.completions.create(**kwargs) as stream:
            # ... rest unchanged
```

Full diff for `_complete` (replace lines 162–171):
```python
    async def _complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[str | list[ToolCall] | tuple[list[ToolCall], str | None]]:
        """Non-streaming completion."""
        kwargs = self._build_kwargs(messages, tools, stream=False)

        response = await self._client.chat.completions.create(**kwargs)
        # ... rest unchanged
```

### Step 4: Run tests

```bash
uv run pytest tests/adapters/llm/test_openai_adapter.py -v
uv run mypy squidbot/adapters/llm/openai.py
```

Expected: all `PASSED`, mypy clean.

### Step 5: Commit

```bash
git add squidbot/adapters/llm/openai.py tests/adapters/llm/test_openai_adapter.py
git commit -m "feat(llm): add _build_kwargs, forward inference params to API"
```

---

## Task 3: Wire new params through `_resolve_llm()` in gateway

**Files:**
- Modify: `squidbot/cli/gateway.py:273–279`
- Test: `tests/cli/test_resolve_llm.py` (new file)

### Step 1: Write the failing tests

```python
# tests/cli/test_resolve_llm.py
"""Tests that _resolve_llm forwards inference params from config to OpenAIAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from squidbot.config.schema import (
    LLMConfig,
    LLMModelConfig,
    LLMPoolEntry,
    LLMProviderConfig,
    Settings,
)


def _make_settings(model_kwargs: dict) -> Settings:
    """Build a minimal Settings with one provider, model, and pool."""
    settings = Settings()
    settings.llm = LLMConfig(
        default_pool="default",
        providers={"p": LLMProviderConfig(api_base="http://localhost/v1", api_key="k")},
        models={"m": LLMModelConfig(provider="p", model="test-model", **model_kwargs)},
        pools={"default": [LLMPoolEntry(model="m")]},
    )
    return settings


class TestResolveLlmForwardsInferenceParams:
    def test_temperature_forwarded(self) -> None:
        settings = _make_settings({"temperature": 0.6})
        # Patch at the source module: _resolve_llm uses a lazy import so patching
        # squidbot.cli.gateway.OpenAIAdapter would not intercept the local binding.
        with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as MockAdapter:  # noqa: N806
            from squidbot.cli.gateway import _resolve_llm  # noqa: PLC0415
            _resolve_llm(settings, "default")
            call_kwargs = MockAdapter.call_args.kwargs
            assert call_kwargs["temperature"] == 0.6

    def test_top_p_forwarded(self) -> None:
        settings = _make_settings({"top_p": 0.95})
        with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as MockAdapter:  # noqa: N806
            from squidbot.cli.gateway import _resolve_llm  # noqa: PLC0415
            _resolve_llm(settings, "default")
            assert MockAdapter.call_args.kwargs["top_p"] == 0.95

    def test_reasoning_effort_forwarded(self) -> None:
        settings = _make_settings({"reasoning_effort": "high"})
        with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as MockAdapter:  # noqa: N806
            from squidbot.cli.gateway import _resolve_llm  # noqa: PLC0415
            _resolve_llm(settings, "default")
            assert MockAdapter.call_args.kwargs["reasoning_effort"] == "high"

    def test_extra_body_forwarded(self) -> None:
        settings = _make_settings({"extra_body": {"thinking": {"type": "disabled"}}})
        with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as MockAdapter:  # noqa: N806
            from squidbot.cli.gateway import _resolve_llm  # noqa: PLC0415
            _resolve_llm(settings, "default")
            assert MockAdapter.call_args.kwargs["extra_body"] == {
                "thinking": {"type": "disabled"}
            }

    def test_max_tokens_always_forwarded(self) -> None:
        settings = _make_settings({"max_tokens": 16384})
        with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as MockAdapter:  # noqa: N806
            from squidbot.cli.gateway import _resolve_llm  # noqa: PLC0415
            _resolve_llm(settings, "default")
            assert MockAdapter.call_args.kwargs["max_tokens"] == 16384

    def test_defaults_forwarded_when_no_params_set(self) -> None:
        settings = _make_settings({})
        with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as MockAdapter:  # noqa: N806
            from squidbot.cli.gateway import _resolve_llm  # noqa: PLC0415
            _resolve_llm(settings, "default")
            call_kwargs = MockAdapter.call_args.kwargs
            # Omitted max_tokens should keep provider/model defaults.
            assert call_kwargs["max_tokens"] is None
            assert call_kwargs["temperature"] is None
            assert call_kwargs["top_p"] is None
            assert call_kwargs["reasoning_effort"] is None
            assert call_kwargs["extra_body"] == {}
```

### Step 2: Run to verify they fail

```bash
uv run pytest tests/cli/test_resolve_llm.py -v
```

Expected: `FAILED` — `_resolve_llm` does not yet pass the new params to `OpenAIAdapter`.

### Step 3: Implement in `squidbot/cli/gateway.py`

Replace the `OpenAIAdapter(...)` call in `_resolve_llm()` (lines 273–279):

```python
        model_fields_set = getattr(model_cfg, "model_fields_set", set())
        max_tokens = model_cfg.max_tokens
        if "max_tokens" not in model_fields_set:
            max_tokens = None

        adapters.append(
            OpenAIAdapter(
                api_base=provider_cfg.api_base,
                api_key=provider_cfg.api_key,
                model=model_cfg.model,
                supports_reasoning_content=provider_cfg.supports_reasoning_content,
                max_tokens=max_tokens,
                temperature=model_cfg.temperature,
                top_p=model_cfg.top_p,
                presence_penalty=model_cfg.presence_penalty,
                frequency_penalty=model_cfg.frequency_penalty,
                reasoning_effort=model_cfg.reasoning_effort,
                extra_body=model_cfg.extra_body,
            )
        )
```

### Step 4: Run tests

```bash
uv run pytest tests/cli/test_resolve_llm.py -v
uv run mypy squidbot/cli/gateway.py
```

Expected: all `PASSED`, mypy clean.

### Step 5: Commit

```bash
git add squidbot/cli/gateway.py tests/cli/test_resolve_llm.py
git commit -m "feat(gateway): wire inference params from LLMModelConfig to OpenAIAdapter"
```

---

## Task 4: Update README with model-specific documentation

**Files:**
- Modify: `README.md` (after the existing `models:` block in the Configuration section)

### Step 1: Add documentation

After the existing `models:` YAML block (currently ending around line 88), add a new
subsection. The exact insertion point is after the closing line of the `models:`
section and before the `pools:` section, inside the overall YAML block.

Update the `models:` YAML example in the README to show the new fields, and add
a prose section below the YAML block. See exact text in Step 3.

### Step 2: No test needed

README changes are documentation only.

### Step 3: Insert the following content

**In the YAML config example** — extend the `models:` block to add a comment
annotation showing which new fields are available.

Find the block starting with `    llama:` and ending with
`      max_context_tokens: 8192` (the last model entry in the example YAML).
Insert the commented kimi example immediately after that block, before the
`  pools:` line. The result should look like:

```yaml
  models:
    opus:
      provider: openrouter
      model: "anthropic/claude-opus-4-5"
      max_tokens: 8192
      max_context_tokens: 200000
    haiku:
      provider: openrouter
      model: "anthropic/claude-haiku-4-5"
      max_tokens: 4096
      max_context_tokens: 200000
    llama:
      provider: local
      model: "llama3.2"
      max_tokens: 2048
      max_context_tokens: 8192
    # All inference parameters are optional. See "Model-specific inference
    # parameters" below for provider-specific notes.
    # kimi-instant:
    #   provider: moonshot
    #   model: "kimi-k2.5"
    #   max_tokens: 8192
    #   max_context_tokens: 98304
    #   temperature: 0.6
    #   top_p: 0.95
    #   extra_body:
    #     thinking:
    #       type: "disabled"
```

**After the closing ` ``` ` of the YAML block** (find the line that closes the
fenced block started by ` ```yaml ` in the Configuration section), add:

````markdown
### Model-specific inference parameters

All fields in `llm.models.<name>` are optional and default to the provider's own
defaults when unset:

| Field | Type | Default | Description |
|---|---|---|---|
| `temperature` | float | provider default | Sampling temperature |
| `top_p` | float | provider default | Nucleus sampling probability |
| `presence_penalty` | float | provider default | Penalise tokens by presence in context |
| `frequency_penalty` | float | provider default | Penalise tokens by frequency in context |
| `reasoning_effort` | `"low"` / `"medium"` / `"high"` | — | Reasoning depth for OpenAI o-series models |
| `extra_body` | dict | `{}` | Provider-specific parameters forwarded verbatim via the OpenAI SDK `extra_body` mechanism |
| `max_tokens` | int | `8192` | Maximum output tokens |

#### Kimi K2.5 (Moonshot AI)

Thinking mode is on by default. Two named model entries let you switch modes per pool:

```yaml
models:
  kimi-thinking:
    provider: moonshot
    model: "kimi-k2.5"
    temperature: 1.0    # thinking mode
    top_p: 0.95

  kimi-instant:
    provider: moonshot
    model: "kimi-k2.5"
    temperature: 0.6    # instant mode
    top_p: 0.95
    extra_body:
      thinking:
        type: "disabled"
```

#### GLM-5 (Z.AI)

Thinking is on by default. For agentic / coding workflows, enable **Preserved
Thinking** to retain reasoning across turns (requires `supports_reasoning_content:
true` on the provider so the adapter returns `reasoning_content` to the API):

```yaml
providers:
  zai:
    api_base: "https://api.z.ai/api/paas/v4"
    api_key: "sk-..."
    supports_reasoning_content: true

models:
  glm5:
    provider: zai
    model: "glm-5"
    temperature: 1.0
    max_tokens: 131072
    max_context_tokens: 200000

  glm5-coding:
    provider: zai
    model: "glm-5"
    temperature: 0.7
    max_tokens: 16384
    extra_body:
      thinking:
        type: "enabled"
        clear_thinking: false   # Preserved Thinking — keep reasoning across turns
```

#### OpenAI o-series (o1, o3, o4-mini, …)

Use `reasoning_effort` to control thinking depth. **Do not set `temperature` or
`top_p`** — the API rejects them for o-series models:

```yaml
models:
  o3-high:
    provider: openai
    model: "o3"
    max_tokens: 16384
    reasoning_effort: "high"

  o4-mini-fast:
    provider: openai
    model: "o4-mini"
    max_tokens: 8192
    reasoning_effort: "low"
```
````

### Step 4: Commit

```bash
git add README.md
git commit -m "docs: document per-model inference parameters and provider-specific notes"
```

---

## Task 5: Full quality gate

### Step 1: Run the complete test suite

```bash
uv run pytest -v
```

Expected: all tests pass (no regressions).

### Step 2: Run mypy

```bash
uv run mypy squidbot/
```

Expected: no errors.

### Step 3: Run ruff

```bash
uv run ruff check .
uv run ruff format . --check
```

Expected: no issues.

### Step 4: If any check fails, fix and re-run before proceeding

### Step 5: Final commit (if fixups were needed)

```bash
git add -A
git commit -m "fix: address linting and type errors from inference params feature"
```

---

## Summary of files changed

| File | Change |
|---|---|
| `squidbot/config/schema.py` | Add 6 fields to `LLMModelConfig` |
| `squidbot/adapters/llm/openai.py` | Add 6 constructor params, `_build_kwargs()`, update `_stream`/`_complete` |
| `squidbot/cli/gateway.py` | Pass new params in `_resolve_llm()` |
| `README.md` | Add "Model-specific inference parameters" section |
| `tests/core/test_config.py` | New — config schema tests |
| `tests/adapters/llm/test_openai_adapter.py` | New — `_build_kwargs` unit tests |
| `tests/cli/test_resolve_llm.py` | New — wiring tests |
