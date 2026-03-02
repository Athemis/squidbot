# Design: Matrix Block Spoiler Plugin (`>!` Syntax)

**Date:** 2026-03-02
**Branch:** `feat/markdown-rendering`

## Problem

The existing `plugin_mx_spoiler` handles inline spoilers (`||text||`) only. Multi-line spoiler
content requires a block-level syntax. mistune's built-in spoiler plugin uses `>!` prefix syntax
but outputs `class="spoiler"` HTML — not suitable for Matrix. We need a custom block plugin that
maps `>!`-prefixed lines to `<span data-mx-spoiler>`.

## Syntax

Lines prefixed with `>! ` (or `>!` alone for blank lines within the block):

```
>! here is the spoiler content
>!
>! it will be hidden
```

Multiple consecutive `>!` lines form a single spoiler block. A `>!`-less line ends the block.

## Output

```html
<span data-mx-spoiler>here is the spoiler content

it will be hidden</span>
```

The inner content is rendered as **inline Markdown** (bold, italic, code, links etc.) — spec-
conformant because `<strong>`, `<em>`, `<code>` etc. are valid inline children of `<span>`.
Block-level tags (`<p>`, `<ul>` etc.) are neither produced nor valid inside `<span>`.

## Architecture

### New component: `plugin_mx_block_spoiler` in `matrix_markdown.py`

- **Block-parser pattern:** `^(?:>![ \t]?[^\n]*(?:\n|$))+`
  Matches one or more consecutive lines starting with `>!`.
- **Parse function:** strips the `>! ` prefix from each line, joins with `\n`, stores as
  `raw` in token `{"type": "mx_block_spoiler", "raw": text}`.
- **Render function:** passes `raw` through the inline renderer, wraps in
  `<span data-mx-spoiler>{rendered}</span>`.
- **Registration:** `before="block_quote"` so `>!` is tested before `>` (blockquote).

### nh3 / sanitizer

No changes required. `span[data-mx-spoiler]` is already in `_MATRIX_ATTRIBUTES`.

### Interaction with existing plugins

- `||text||` inline plugin unchanged.
- Both plugins active on the same `Markdown` instance — they operate at different parse levels
  (block vs inline) and do not conflict.
- Email channel: neither plugin is registered → `>!` lines pass through as literal text.

## Testing

New tests in `TestMatrixSpoilerPlugin`:

1. Single `>!` line renders `<span data-mx-spoiler>`
2. Multi-line block with blank `>!` separator produces single span
3. Inline markdown inside block spoiler is rendered (`**bold**` → `<strong>`)
4. Block spoiler does not appear in email channel
5. Block and inline spoiler coexist in same message
6. Block spoiler registers before blockquote (plain `> quote` still works)

## Out of scope

- Spoiler reason (`>! reason | content`) — not supported by Element; deferred.
- Nested block spoilers.
- Image spoilers.
