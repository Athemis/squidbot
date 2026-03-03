# GFM Math Syntax Extensions — Design

**Status:** Draft · 2026-03-02

---

## Problem Statement

After PR #56 the Matrix channel renders `$...$` (inline) and `$$...$$` (block) math
correctly, but three GFM math syntax variants remain unsupported:

| Syntax | GFM form | Status |
|---|---|---|
| Inline backtick | `` $`expr`$ `` | **missing** |
| Fenced block | ` ```math\n...\n``` ` | **missing** |
| Inline-open block | `$$expr\n...\n...expr$$` | **broken** |

The third variant (opening `$$` immediately followed by content on the same line, closing
`$$` at the end of the last content line) covers all multi-environment LaTeX blocks
(`\begin{align}`, `\begin{bmatrix}`, `\begin{cases}`, etc.) and was reported broken in
the original bug report that triggered this work.

Reference: <https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/writing-mathematical-expressions>

---

## Architecture

All changes are confined to **`squidbot/adapters/channels/matrix_markdown.py`** and
the corresponding test file **`tests/adapters/channels/test_markdown_plugins.py`**.
No new dependencies.  No changes to ports, core, CLI, or other adapters.

The existing `plugin_mx_math()` mistune plugin registers:
- One block rule `mx_block_math` (pattern `_BLOCK_MATH_PATTERN`)
- One inline rule `mx_inline_math` (pattern `_INLINE_MATH_PATTERN`)

We extend the plugin by:
1. Adding a **third regex alternative** to `_BLOCK_MATH_PATTERN` for the inline-open
   block case.
2. Extending `_INLINE_MATH_PATTERN` with a second alternative for the backtick inline
   form.
3. Registering a **new block rule** `mx_fenced_math` for ` ```math ` fences (before
   mistune's own `fenced_code` rule so we intercept the block first).

The two block token types (`mx_block_math` and `mx_fenced_math`) share the same
renderer function `_render_block_math`.  The nh3 sanitizer and `sanitize_for_matrix`
need no changes — `div[data-mx-maths]` is already in the allowlist.

---

## Detailed Design

### 1 · Fix: inline-open block math  `$$expr\nmore\n...\nexpr$$`

**Problem:** `_BLOCK_MATH_PATTERN` only matches:
- Form A — `$$` alone on opening line: `$$\ncontent\n$$`
- Form B — everything on one line: `$$content$$`

It does not match Form C — `$$` immediately followed by content on the opening line,
with the closing `$$` appended to the last content line:

```
$$\begin{align}
f(x) &= x^2 + 2x + 1 \\
&= (x+1)^2
\end{align}$$
```

**Fix:** Add a third named-group alternative `math_text_m` to `_BLOCK_MATH_PATTERN`.

```python
_BLOCK_MATH_PATTERN = (
    # Form A: $$ on its own line, content, $$ on its own line
    r"^ {0,3}\$\$[ \t]*\n(?P<math_text>[\s\S]+?)\n\$\$[ \t]*$"
    # Form B: single line  $$content$$
    r"|^ {0,3}\$\$[ \t]*(?P<math_text_s>[^\n$][^\n]*?)[ \t]*\$\$[ \t]*$"
    # Form C: $$ opens with content on same line, closes at end of last line
    r"|^ {0,3}\$\$(?P<math_text_m>[^\n$][^\n]*\n[\s\S]+?)\$\$[ \t]*$"
)
```

Pattern C breakdown:
- `[^\n$]` — first char after `$$` is not newline or `$` (prevents `$$$$` / `$$$x$$$`)
- `[^\n]*` — rest of opening line content
- `\n` — at least one newline (must be multiline)
- `[\s\S]+?` — lazy: remaining content through to the closing `$$`
- `\$\$[ \t]*$` — closing `$$` at end of line

The `_parse_block_math` function gains one `or` clause:
```python
math_text: str = (
    m.group("math_text") or m.group("math_text_s") or m.group("math_text_m") or ""
)
```

**Known limitation:** if the LaTeX content itself contains a bare `$$` on a line of its
own, the lazy quantifier stops early.  This matches the same trade-off already present
in Form A.  Pathological inputs are extremely rare in practice.

---

### 2 · New: backtick inline math  `` $`expr`$ ``

GFM documents `` $`expr`$ `` as an alternative inline delimiter designed for expressions
containing characters that conflict with Markdown syntax (e.g. `|`, `_`).

**Regex extension:** prepend a second alternative to `_INLINE_MATH_PATTERN`:

```python
_INLINE_MATH_PATTERN = (
    # GFM backtick form:  $`expr`$   (backtick content cannot contain backticks)
    r"\$`(?P<math_text_bt>[^`]+?)`\$"
    # Standard dollar form:  $expr$
    r"|\$(?!\s)(?P<math_text>.+?)(?!\s)\$"
)
```

The backtick alternative is placed **first** so the combined regex prefers it over the
standard form when the input starts with `` $` ``.  The `[^`]+?` content class prevents
ambiguous matching when expressions contain embedded backticks.

**Registration order:** currently `before="link"`.  To prevent mistune's `codespan`
rule from consuming the backtick before we see it, the registration must change to
`before="codespan"`.  This is safe: we only capture the strict `` $`...`$ `` shape;
a lone backtick span like `` `code` `` is unaffected.

The `_parse_inline_math` function gains one `or` clause:
```python
math_text: str = m.group("math_text_bt") or m.group("math_text") or ""
```

---

### 3 · New: fenced block math  ` ```math `

GFM's fenced block form uses a standard code fence with `math` as the language
identifier.  Mistune would normally render this as
`<pre><code class="language-math">...</code></pre>` which the nh3 sanitizer preserves
(it passes `language-*` class names).  But Matrix clients do not treat that as LaTeX.

**Approach:** register a new block rule `mx_fenced_math` **before** mistune's
`fenced_code` rule so we intercept ` ```math ` blocks first.

```python
_BLOCK_MATH_FENCE_PATTERN = (
    # Opening fence: ``` or ~~~, followed by optional whitespace and "math"
    r"^ {0,3}(?:```|~~~)[ \t]*math[ \t]*\n"
    # Content (any chars including newlines, lazy)
    r"(?P<math_text_f>[\s\S]+?)"
    # Closing fence: ``` or ~~~ on its own line
    r"\n {0,3}(?:```|~~~)[ \t]*$"
)
```

New parse function:
```python
def _parse_fenced_math(block: BlockParser, m: Any, state: BlockState) -> int:
    math_text: str = m.group("math_text_f") or ""
    # Reuse mx_block_math token type so the same renderer is used automatically.
    state.append_token({"type": "mx_block_math", "raw": math_text})
    return int(m.end()) + 1
```

Registration:
```python
md.block.register(
    "mx_fenced_math", _BLOCK_MATH_FENCE_PATTERN, _parse_fenced_math, before="fenced_code"
)
```

By emitting `mx_block_math` tokens, `_parse_fenced_math` reuses the existing
`_render_block_math` renderer without any additional renderer registration.

**Note:** both ` ``` ` and `~~~` are accepted as the opening fence.  The closing fence
does not need to match the opening type — this keeps the regex simple and covers all
realistic inputs.

---

## Testing Strategy

All tests live in `tests/adapters/channels/test_markdown_plugins.py`,
class `TestMatrixMathPlugin`.

New test cases (all failing before implementation, passing after):

### Form C (inline-open block)
- `$$\begin{align}\nf(x) &= x + 1\n\end{align}$$` → `<div data-mx-maths="...">`
- `$$\begin{bmatrix}\n1 & 2\n\end{bmatrix}$$` → `<div data-mx-maths="...">`
- `$$\begin{cases}\nx & x \geq 0\n\end{cases}$$` → `<div data-mx-maths="...">`
- No stray `$$` characters in output for any Form C input

### Backtick inline
- `` $`E = mc^2`$ `` → `<span data-mx-maths="E = mc^2">`
- `` $`a | b`$ `` (pipe in expression) → `<span data-mx-maths="a | b">`
- `` `code` `` (plain code span) → unchanged `<code>code</code>` (no interference)

### Fenced block
- ` ```math\nE = mc^2\n``` ` → `<div data-mx-maths="E = mc^2">`
- ` ```math\nmulti\nline\n``` ` → `<div data-mx-maths="multi\nline">`
- ` ~~~math\nE = mc^2\n~~~ ` → `<div data-mx-maths="E = mc^2">` (tilde fence)
- ` ```python\ncode\n``` ` → `<pre><code class="language-python">...` (no interference)

### Regression
- All existing `TestMatrixMathPlugin` tests continue to pass.

---

## Files Touched

| File | Change |
|---|---|
| `squidbot/adapters/channels/matrix_markdown.py` | Extend patterns, add `_parse_fenced_math`, update registrations |
| `tests/adapters/channels/test_markdown_plugins.py` | Add ~12 new test cases to `TestMatrixMathPlugin` |

No other files require changes.
