# Markdown Plugin Support Design

**Goal:** Enable extended Markdown rendering to HTML in Matrix and Email channels.

**Problem:** Currently, Markdown tables, strikethrough, task lists, footnotes, and auto-links are not converted to proper HTML. The Matrix `formatted_body` and Email HTML parts render these as raw text.

**Root Cause:** Both `MatrixChannel` and `EmailChannel` use `mistune.create_markdown(escape=True)` which does not include any plugins by default.

**Solution:** Add a curated set of mistune plugins that are useful for LLM-generated content.

---

## Architecture

The fix is minimal and localized to two files:

```
squidbot/adapters/channels/
├── matrix.py    # _md = mistune.create_markdown(escape=True, plugins=[...])
└── email.py     # _md = mistune.create_markdown(escape=True, plugins=[...])
```

### Plugin Selection

| Plugin | Syntax | Use Case |
|--------|--------|----------|
| `table` | `| col | col |` | Structured data, comparisons |
| `strikethrough` | `~~text~~` | Corrections, deletions — frequently used by LLMs |
| `task_lists` | `- [ ] task` / `- [x] done` | To-do lists, checklists |
| `url` | Auto-link `https://...` | Clickable URLs without explicit markdown |
| `footnotes` | `[^1]` | Source citations without link clutter |
| `superscript` | `x^2` or `x^2^` | Exponents, ordinal indicators (1st, 2nd) |
| `subscript` | `H~2~O` | Chemical formulas, technical notation |

### Current State

```python
# matrix.py:65
_md = mistune.create_markdown(escape=True)

# email.py:44
_md = mistune.create_markdown(escape=True)
```

### Target State

```python
_PLUGINS = ["table", "strikethrough", "task_lists", "url", "footnotes", "superscript", "subscript"]

# matrix.py:65
_md = mistune.create_markdown(escape=True, plugins=_PLUGINS)

# email.py:44
_md = mistune.create_markdown(escape=True, plugins=_PLUGINS)
```

---

## Affected Components

| Component | File | Change |
|-----------|------|--------|
| Matrix `_render_markdown()` | `squidbot/adapters/channels/matrix.py:65` | Add plugins list |
| Email HTML body | `squidbot/adapters/channels/email.py:44` | Add plugins list |

---

## Testing Strategy

### Unit Tests

Create `tests/adapters/channels/test_markdown_plugins.py`:

1. **Test table rendering** — Input: Markdown table → Output: HTML `<table>`
2. **Test strikethrough** — Input: `~~text~~` → Output: `<del>text</del>`
3. **Test task lists** — Input: `- [ ] task` → Output: `<li class="task-list-item">`
4. **Test auto-url** — Input: `https://example.com` → Output: `<a href="...">`
5. **Test footnotes** — Input: `text[^1]` + `[^1]: note` → Output: footnote link

### Integration Test

Manual verification:
1. Send a message with all plugin syntaxes via Matrix
2. Verify the `formatted_body` contains proper HTML
3. Verify rendering in Matrix clients (Element, etc.)

---

## Risks

| Risk | Mitigation |
|------|------------|
| Plugin output format changes | Plugins are stable; verify with tests |
| HTML escaping conflicts | `escape=True` only escapes input, not generated HTML |
| Footnote rendering in clients | Test across Matrix clients; footnote CSS may vary |

---

## Dependencies

- `mistune>=3.0` — already in `pyproject.toml`
- No new dependencies required

---

## Out of Scope

- `math`, `ruby`, `spoiler` — too niche for chatbot use
- `abbr`, `mark`, `insert` — rarely used in chat
- `def_list` — definitions are uncommon in LLM responses
- Table plugins for blockquotes/lists (`table_in_quote`, `table_in_list`) — YAGNI
