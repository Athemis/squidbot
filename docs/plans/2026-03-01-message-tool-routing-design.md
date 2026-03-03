# Message Tool Routing Design

## Context

`SendAttachmentTool` currently lives in filesystem tools. It solved immediate Matrix attachment
delivery, but it mixes delivery semantics with file IO and does not provide a clean API for
explicit routed sends such as "send me file X by email" from a Matrix conversation.

We want delivery to be modeled as messaging, not filesystem behavior.

Cutover strategy is direct: remove `send_attachment` in the same change set. No compatibility
layer and no staged migration path are planned.

## Goals

1. Introduce a dedicated `message` tool in `squidbot/adapters/tools/message.py`.
2. Remove `send_attachment` entirely (no alias/compat shim).
3. Keep normal AgentLoop final replies unchanged.
4. Support explicit owner-driven cross-channel sends (primary: Matrix -> Email).
5. Enforce policy: any target override requires owner + explicit request in current turn.
6. Use a native attachment list in domain model (no adapter-level multi-send workaround).

## Non-Goals

- Converting AgentLoop to tool-only message delivery.
- Adding new channel adapters.
- Adding sent-in-turn suppression in this phase.

## Architecture

Approach B remains: default replies continue through current AgentLoop path, while explicit
delivery/routing uses a dedicated tool.

Key shift: move attachment cardinality to the domain model.

- `OutboundMessage.attachment: Path | None` -> `OutboundMessage.attachments: list[Path]`
- channels iterate attachments natively
- `message` tool accepts `attachments: list[str]` and maps directly to domain list

This removes semantic mismatch between tool API and transport model.

## API Design (`message` tool)

Parameters:

- `content: str` (required)
- `attachments: list[str]` (optional) - local file paths
- `target_channel: str` (optional) - default current channel
- `target_sender_id: str` (optional) - default current sender/session target

Rules:

- Empty/whitespace attachment entries are ignored.
- Every attachment path is resolved and validated (workspace policy respected).
- Any target override (`target_channel` or `target_sender_id`) is treated as routed send.

## Policy Model

Routed sends are allowed only when all checks pass:

1. Sender is owner (same semantics as `MemoryManager._is_owner`):
   - scoped alias exact match `(sender_id, channel)`
   - unscoped alias exact match `sender_id`
   - case-sensitive
2. Request is explicit in current inbound text (deny-by-default).
3. Route is supported and target metadata/state is resolvable.

### Target Resolution Contract

For routed sends, target resolution is deterministic and deny-by-default:

1. If `target_sender_id` is provided, use it as recipient identifier.
2. If `target_channel == "email"` and no `target_sender_id` is provided:
   - build candidate set from owner aliases in this order:
     1) channel-scoped `channel == "email"` aliases with email-like addresses
     2) unscoped aliases with email-like addresses (only if step 1 is empty)
   - if exactly one candidate exists, use it
   - if zero or multiple aliases resolve, return unresolved-target error
3. For channels requiring runtime metadata (for example Matrix room id), if metadata cannot
   be resolved from current context, return unresolved-target error.

Error mapping is explicit:

- unknown/inactive channel: `Error: target channel unavailable`
- unsupported channel pair: `Error: target route is not supported`
- unresolved/ambiguous recipient metadata: `Error: target recipient could not be resolved`

### Explicitness Guard

The explicitness helper checks deterministic positive patterns plus negative guards.

- positive examples: "per email", "send to email", "schick ... per email"
- negative examples: "do not send", quoted/historical references

If explicitness cannot be proven for the current turn, routing is denied.

## Supported Route Matrix (v1)

| Source | Target | Status | Notes |
|---|---|---|---|
| matrix | matrix | Supported | Same session only; `target_sender_id` override denied in v1; requires `matrix_room_id` metadata |
| email | email | Supported | Same session only; `target_sender_id` override denied in v1 |
| matrix | email | Supported | Primary cross-channel flow; `target_sender_id` must resolve to recipient email |
| email | matrix | Not supported | No deterministic Matrix room resolver in email context |
| any | unknown/inactive | Not supported | deterministic routing error |

Unsupported route or unresolved target state returns value error:
`Error: target route is not supported` or `Error: target recipient could not be resolved`.

## Component Changes

### 1) Domain model migration

Update `squidbot/core/models.py`:

- replace `attachment: Path | None` with `attachments: list[Path] = field(default_factory=list)`

### 2) New messaging tool module

Add `squidbot/adapters/tools/message.py`:

- `MessageTool` implementing `ToolPort`
- owner resolver helper
- explicitness helper
- route capability resolver
- attachment path validation
- routed send callback invocation
- structured audit logging for allow/deny route decisions

### 3) Remove old attachment tool from filesystem module

Update `squidbot/adapters/tools/files.py`:

- delete `SendAttachmentTool`
- keep file tools scoped to file IO

### 4) Channel updates for native attachment list

Update channel adapters to consume `OutboundMessage.attachments`:

- Matrix: upload/send each attachment before text (preserve current behavior ordering)
- Email: attach each file in list to MIME message
- CLI/RichCLI: ignore attachment list as today

### 5) Gateway wiring

Update `squidbot/cli/gateway.py`:

- inject `MessageTool` per inbound message in `_channel_loop` and `_channel_loop_with_state`
- pass owner aliases, inbound text, session, metadata, workspace restriction context
- pass route callback bound to active channel registry

### 6) Prompt guidance

Update guidance in gateway/system prompt and workspace agent instructions:

- use `write_file` then `message` with `attachments`
- do not dump metadata JSON as attachment substitute

## Data Flow

1. User message arrives in Matrix.
2. Gateway injects `MessageTool` with turn context.
3. LLM creates file(s) with `write_file`.
4. LLM calls `message(content=..., attachments=[...], target_channel="email")`.
5. Tool validates content, policy, route, and all attachment paths.
6. Tool builds one `OutboundMessage` containing native attachment list.
7. Route callback dispatches to target channel adapter.
8. Channel adapter sends attachment list using channel-native behavior.
9. Tool returns success/error `ToolResult`; AgentLoop final reply path remains unchanged.

## Error Handling

All errors are value-based (`ToolResult(is_error=True)`) and never raised across tool boundary.

Error cases:

- invalid/missing `content`
- unknown/inactive `target_channel`
- owner/policy denial
- explicitness check failure
- unsupported route
- unresolved target metadata/state
- invalid attachment path(s)
- channel send failure

Each error case maps to a deterministic error string for stable tests.
Attachment list validation is atomic and pre-send: if any attachment path is invalid, the
tool returns an error and sends nothing.

## Testing Strategy

### Unit tests

`tests/adapters/tools/test_message.py`:

- current-context text send
- current-context multi-attachment send
- owner+explicit route allowed (matrix -> email)
- non-owner route denied
- non-explicit route denied
- negative phrase route denied
- same-channel `target_sender_id` override denied
- unsupported route denied (email -> matrix)
- unknown target channel denied
- attachment path restrictions and invalid path batch behavior
- unresolved `target_sender_id` denied with deterministic error
- ambiguous recipient resolution denied with deterministic error
- stale/unresolvable target state denied with deterministic error

### Domain/channel regression tests

- `tests/core/test_models.py`: new `OutboundMessage.attachments` default and serialization behavior
- `tests/adapters/channels/test_matrix.py`: list attachment send behavior
- `tests/adapters/channels/test_email.py`: attach all files in list

### Wiring tests

- `tests/adapters/test_channel_loops.py`: `message` injected, `send_attachment` absent
- `tests/adapters/test_gateway_status.py`: updated signatures as needed
- `tests/adapters/test_spawn_wiring.py`: guidance references `message` + `attachments`
- remove/replace `tests/adapters/tools/test_send_attachment.py`

### Verification commands

- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run mypy squidbot/`
- `uv run pytest`

## Risks and Mitigations

- Risk: larger scope due model migration.
  - Mitigation: explicit task ordering and focused tests per layer.

- Risk: routing edge cases around target overrides.
  - Mitigation: deny same-channel sender overrides in v1 and test explicitly.

- Risk: explicitness heuristic brittleness.
  - Mitigation: deterministic deny-by-default plus negative-pattern tests.

- Risk: weak auditability of routed sends.
  - Mitigation: structured logs for routed-send allow/deny with reason code and route metadata
    (without logging sensitive message body).

## Rollout

Single PR:

1. Model migration to native attachment list
2. New `message` tool + policy/routing
3. Filesystem tool cleanup
4. Channel + gateway + prompt updates
5. Test updates and full verification

No `send_attachment` alias in rollout.
