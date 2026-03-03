# Per-Model Inference Parameters — Design

## Problem

`LLMModelConfig` carries `max_tokens` and `max_context_tokens` but neither value
is forwarded to the API. `OpenAIAdapter._stream()` and `._complete()` only pass
`model`, `messages`, `stream`, and `tools` in `kwargs` — every other inference
parameter relies on the provider's built-in defaults.

This makes it impossible to follow provider- or model-specific recommendations
such as:

- Kimi K2.5 (Moonshot): `temperature=0.6` for instant mode, `temperature=1.0` for thinking mode
- GLM-5 (Z.AI): `temperature=1.0`, `max_tokens=131072`, preserved thinking via `extra_body`
- OpenAI o-series: `reasoning_effort="high"`

## Goals

1. Allow any sampling parameter supported by OpenAI-compatible APIs to be
   configured per model in `squidbot.yaml`.
2. Pass those parameters verbatim to `chat.completions.create()`.
3. Provide a generic escape hatch (`extra_body`) for non-standard, provider-specific
   parameters (e.g. `min_p`, `thinking`, `clear_thinking`).
4. Fix the existing bug where `max_tokens` is configured but never forwarded.
5. Document special-case parameters for Kimi K2.5, GLM-5, and OpenAI o-series
   in the README.

## Non-Goals

- Dynamic parameter overrides at call time (parameters are baked into the adapter
  at construction, not passed per-message).
- Per-pool parameter overrides (only per-model, on `LLMModelConfig`).
- Validation that a given provider actually supports the configured parameters
  (unknown parameters are silently ignored or cause a provider-level error).

## Architecture

### Layer 1 — Config Schema (`squidbot/config/schema.py`)

Add six optional fields to `LLMModelConfig`:

```python
class LLMModelConfig(BaseModel):
    provider: str
    model: str
    max_tokens: int = 8192
    max_context_tokens: int = 100_000
    # Inference parameters
    temperature: float | None = None
    top_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
```

All new fields default to `None` / empty dict, so existing configs require no
changes. `max_tokens` keeps its default of `8192` (existing behaviour preserved
at the config level; the fix is in the adapter).

**Why `extra_body` on the model, not the provider?**
Different models from the same provider have different requirements — e.g. a
provider might serve both a standard chat model and a reasoning model. Provider-level
`extra_body` would wrongly apply to all models.

**Why not `LLMPoolEntry`?**
Per-model is the right granularity. The same model object can appear in multiple
pools. Putting parameters on pool entries would require duplicating them.

### Layer 2 — Adapter (`squidbot/adapters/llm/openai.py`)

Add all six fields to `__init__`. Extract `_build_kwargs()` as a private helper
shared by `_stream()` and `_complete()`, eliminating the current duplication of
the `kwargs` assembly block.

```
_stream(messages, tools)  ─┐
                            ├─→ _build_kwargs(messages, tools, stream=True/False)
_complete(messages, tools) ─┘
```

`_build_kwargs` conditionally adds each parameter only when it is not `None`
(or not empty for `extra_body`). This preserves provider defaults for any
parameter not explicitly configured.

`reasoning_effort` is a standard top-level OpenAI parameter — it goes directly
in `kwargs`, not in `extra_body`.

### Layer 3 — Wiring (`squidbot/cli/gateway.py`)

`_resolve_llm()` already constructs `OpenAIAdapter` instances from config. Add
the six new keyword arguments to the `OpenAIAdapter(...)` call.

Note: `max_tokens` is always forwarded because `LLMModelConfig` always has a
concrete `int` value (default `8192`). The adapter therefore receives `int`, not
`int | None`, from the gateway. The `max_tokens: int | None = None` signature on
`OpenAIAdapter.__init__` is needed to allow direct construction in unit tests
without specifying a value; in production the gateway always supplies a concrete
value.

## Data Flow

```
squidbot.yaml
  └─ llm.models.<name>.temperature = 0.6
       │
       ▼
Settings.load() → LLMModelConfig(temperature=0.6, ...)
       │
       ▼
_resolve_llm() → OpenAIAdapter(..., temperature=0.6, ...)
       │  (stored as self._temperature)
       ▼
_build_kwargs() → kwargs["temperature"] = 0.6
       │
       ▼
AsyncOpenAI.chat.completions.create(**kwargs)
```

## Provider-Specific Notes

### Kimi K2.5 (Moonshot AI)

Thinking is **on by default**. Controlled via temperature and/or `extra_body`:

| Mode    | temperature | extra_body                             |
|---------|-------------|----------------------------------------|
| Instant | 0.6         | `{"thinking": {"type": "disabled"}}`  |
| Thinking| 1.0         | *(default, no extra_body needed)*      |

Recommended `top_p = 0.95` for both modes.

### GLM-5 (Z.AI)

Thinking is **on by default**. Three distinct modes via `extra_body`:

| Mode              | extra_body                                                   |
|-------------------|--------------------------------------------------------------|
| Thinking (default)| `{"thinking": {"type": "enabled"}}`                         |
| No thinking       | `{"thinking": {"type": "disabled"}}`                        |
| Preserved Thinking| `{"thinking": {"type": "enabled", "clear_thinking": false}}`|

Preserved Thinking keeps `reasoning_content` across assistant turns. Requires
that the full, unmodified `reasoning_content` is returned to the API on each
turn. squidbot already passes `reasoning_content` back when
`supports_reasoning_content = true` is set on the provider — so this works
out of the box.

Recommended: `temperature=1.0`, `max_tokens=131072` for general use;
`temperature=0.7`, `max_tokens=16384` for SWE/coding tasks.

### OpenAI o-series (o1, o3, o4-mini, …)

`reasoning_effort` is a standard top-level parameter:

```yaml
reasoning_effort: "high"   # low | medium | high
```

`temperature` and `top_p` are **not supported** on o-series models (the API
rejects them). Do not set them when using an o-series model.

## Error Handling

- Unknown or unsupported parameters passed to the API will result in a
  provider-level HTTP 400 error. This surfaces through the existing
  `AgentLoop` error handler as a user-visible message.
- No squidbot-level validation of parameter values beyond Pydantic's type
  checking (e.g. `float | None` for temperature).

## Testing Strategy

- **Unit tests** for `_build_kwargs` covering: all params set, none set, partial set,
  `extra_body` merging, `reasoning_effort` placement.
- **Unit tests** for `LLMModelConfig` serialisation round-trip (JSON ↔ model).
- **Unit tests** for `_resolve_llm` verifying parameters flow from config to adapter,
  including an assertion that `max_tokens=8192` is forwarded when no override is set
  (confirming the bug fix is tested at the wiring layer).
- All tests use `unittest.mock` — no real API calls.

## README Changes

A new subsection **"Model-specific inference parameters"** under the Configuration
section explains:
- The six new fields with type and default
- Kimi K2.5 instant/thinking mode examples
- GLM-5 preserved thinking example
- OpenAI o-series `reasoning_effort` example
- Warning about `temperature`/`top_p` incompatibility with o-series
