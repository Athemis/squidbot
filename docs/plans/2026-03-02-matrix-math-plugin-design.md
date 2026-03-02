# Matrix Math Plugin & HTML Passthrough — Design Document

**Status:** Draft

**Problem:** LLM-Antworten mit mathematischen Ausdrücken (`$$E=mc^2$$`, `$x^2$`) werden in Matrix nicht korrekt gerendert. Außerdem können LLMs kein Raw-HTML nutzen um Matrix-spezifische Tags wie `<details>`, `<u>` oder `<span data-mx-spoiler>` zu erzeugen, weil `escape=True` in mistune alles escaped.

**Solution:** Drei komplementäre Mechanismen:
1. **`plugin_mx_math`** — Mistune-Plugin für natürliche LaTeX-Syntax (`$$...$$`, `$...$`) → `<div data-mx-maths>` / `<span data-mx-maths>` (Matrix Spec v1.11+).
2. **`plugin_mx_spoiler`** — Mistune-Plugin für `||text||` → `<span data-mx-spoiler>text</span>` (Matrix-Spoiler-Format).
3. **HTML-Passthrough + nh3-Sanitizer** — `escape=False` in mistune erlaubt Raw-HTML vom LLM; nh3 saniert den Output mit der Matrix-Spec-v1.17-Allowlist vor dem Senden.

---

## Background

### Matrix Spec v1.17 — Erlaubte HTML-Tags

Clients müssen `formatted_body` gegen folgende Allowlist sanieren:

**Tags:**
```
del, h1, h2, h3, h4, h5, h6, blockquote, p, a, ul, ol, sup, sub, li,
b, i, u, strong, em, s, code, hr, br, div, table, thead, tbody, tr,
th, td, caption, pre, span, img, details, summary
```

**Attribute (pro Tag):**

| Tag     | Erlaubte Attribute                                               |
| ------- | ---------------------------------------------------------------- |
| `span`  | `data-mx-bg-color`, `data-mx-color`, `data-mx-spoiler`, `data-mx-maths` |
| `a`     | `href` (Schemes: https, http, ftp, mailto, magnet), `target`    |
| `img`   | `width`, `height`, `alt`, `title`, `src` (nur `mxc://`-URIs)   |
| `ol`    | `start`                                                          |
| `code`  | `class` (nur `language-*`)                                       |
| `div`   | `data-mx-maths`                                                  |

Alle anderen Tags: keine Attribute.

### Matrix Spec v1.11 — Mathematical Messages (MSC2191)

| Element | Tag      | Attribut                       | Kind-Content         |
| ------- | -------- | ------------------------------ | -------------------- |
| Block   | `<div>`  | `data-mx-maths="<LaTeX>"`      | Fallback (HTML/Text) |
| Inline  | `<span>` | `data-mx-maths="<LaTeX>"`      | Fallback (HTML/Text) |

Clients mit LaTeX-Rendering (Element, FluffyChat) lesen `data-mx-maths`. Clients ohne LaTeX zeigen den Kind-Content.

---

## Design

### Architektur

```
squidbot/adapters/channels/
├── matrix.py               # escape=False; nutzt plugin_mx_math + sanitize_for_matrix()
├── matrix_markdown.py      # NEU: plugin_mx_math + _MATRIX_SANITIZER (nh3.Cleaner)
└── email.py                # unverändert (escape=True, kein nh3)

squidbot/core/
└── markdown.py             # unverändert (shared plugin names)
```

**Abhängigkeitsrichtung:** `matrix.py` → `matrix_markdown.py`. `core/` importiert nichts aus `adapters/`. Hexagonale Architektur bleibt intakt.

### Rendering-Pipeline (Matrix)

```
LLM-Text (Markdown + optional Raw-HTML)
        │
        ▼
mistune (escape=False, plugins=[...MARKDOWN_PLUGINS, plugin_mx_math, plugin_mx_spoiler])
        │  • $$...$$ → <div data-mx-maths="..."><code>...</code></div>
        │  • $...$ → <span data-mx-maths="..."><code>...</code></span>
        │  • ||text|| → <span data-mx-spoiler>text</span>
        │  • Raw HTML passiert unverändert
        ▼
nh3.Cleaner (Matrix Spec v1.17 Allowlist)
        │  • Unbekannte Tags: Content bleibt, Tag wird entfernt
        │  • Verbotene Attribute: entfernt
        │  • Ungültige URL-Schemes in href: entfernt
        │  • img src ohne mxc://: entfernt
        │  • code class ohne language-*: entfernt
        ▼
formatted_body (sicheres, spec-konformes HTML)
```

### `plugin_mx_math`

Reuses die Regex-Pattern des eingebauten `math`-Plugins, rendert aber Matrix-konform:

- Block `$$...\n...\n$$` → `<div data-mx-maths="ESCAPED_LATEX"><code>ESCAPED_LATEX</code></div>`
- Inline `$...$` → `<span data-mx-maths="ESCAPED_LATEX"><code>ESCAPED_LATEX</code></span>`

LaTeX-Content wird mit `html.escape()` für das Attribut und den Kind-Content escaped.

### `plugin_mx_spoiler`

Inline-Plugin für Matrix-Spoiler-Format:

- Syntax: `||spoiler text||`
- Output: `<span data-mx-spoiler>spoiler text</span>`

Der innere Text wird rekursiv als Inline-Markdown gerendert (z.B. `||**fetter Spoiler**||` → `<span data-mx-spoiler><strong>fetter Spoiler</strong></span>`). Kein Block-Spoiler — die Matrix-Spec kennt `data-mx-spoiler` nur auf `<span>`.

Pattern: `\|\|(?P<spoiler_text>.+?)\|\|` — kein Newline im Match, damit die Abgrenzung klar bleibt.

### nh3-Sanitizer-Konfiguration

```python
_MATRIX_TAGS: frozenset[str] = frozenset({
    "del", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "p", "a", "ul", "ol", "sup", "sub", "li",
    "b", "i", "u", "strong", "em", "s", "code", "hr", "br",
    "div", "table", "thead", "tbody", "tr", "th", "td", "caption",
    "pre", "span", "img", "details", "summary",
})

_MATRIX_ATTRIBUTES: dict[str, set[str]] = {
    "span": {"data-mx-bg-color", "data-mx-color", "data-mx-spoiler", "data-mx-maths"},
    "a":    {"href", "target"},
    "img":  {"width", "height", "alt", "title", "src"},
    "ol":   {"start"},
    "code": {"class"},
    "div":  {"data-mx-maths"},
}

# mxc hinzugefügt damit nh3 img[src=mxc://...] nicht vorzeitig blockt;
# attribute_filter beschränkt img src dann auf mxc:// explizit.
_MATRIX_URL_SCHEMES: frozenset[str] = frozenset({
    "https", "http", "ftp", "mailto", "magnet", "mxc",
})

def _matrix_attr_filter(tag: str, attr: str, value: str) -> str | None:
    if tag == "code" and attr == "class":
        return value if value.startswith("language-") else None
    if tag == "img" and attr == "src":
        return value if value.startswith("mxc://") else None
    return value

_MATRIX_SANITIZER = nh3.Cleaner(
    tags=_MATRIX_TAGS,
    attributes=_MATRIX_ATTRIBUTES,
    url_schemes=_MATRIX_URL_SCHEMES,
    attribute_filter=_matrix_attr_filter,
    # link_rel default "noopener noreferrer" bleibt — korrekt für ausgehende Links
)
```

Die `Cleaner`-Instanz wird einmal beim Modulimport erstellt und wiederverwendet.

### `matrix.py` — `_render_markdown`

```python
_md = mistune.create_markdown(escape=False, plugins=[*MARKDOWN_PLUGINS, plugin_mx_math])

def _render_markdown(text: str) -> str:
    raw = cast(str, _md(text)).strip()
    return sanitize_for_matrix(raw)
```

`escape=False`: Raw-HTML vom LLM passiert mistune unverändert. nh3 übernimmt die Sanierung.

### Was das LLM jetzt direkt schreiben kann

```html
<details><summary>Mehr Details</summary>Hier der Inhalt...</details>
<u>unterstrichen</u>
<span data-mx-spoiler>Spoiler-Text</span>
```

Alles andere (z.B. `<script>`, `onclick=`) wird von nh3 entfernt.

---

## Scope

### In Scope

- `plugin_mx_math`: `$$...$$` → `<div data-mx-maths>`, `$...$` → `<span data-mx-maths>`
- `plugin_mx_spoiler`: `||text||` → `<span data-mx-spoiler>text</span>`
- nh3-Sanitizer mit Matrix-Spec-v1.17-Allowlist
- `escape=False` in Matrix-Adapter
- nh3 als neue Projektabhängigkeit
- Unit Tests für beide Plugins und Sanitizer

### Out of Scope

- Email-Adapter: bleibt unverändert (`escape=True`, kein nh3)
- Block-Spoiler — Matrix kennt `data-mx-spoiler` nur auf `<span>`
- Details-Plugin als Markdown-Syntax — LLM schreibt direkt `<details><summary>`
- `data-mx-color`-Wertvalidierung (`#rrggbb`) — Clients validieren selbst
- LaTeX → Unicode-Approximation im Fallback — `<code>` mit Roh-LaTeX reicht

---

## Testing Strategy

**Unit Tests** in `tests/adapters/channels/test_markdown_plugins.py`:

**`plugin_mx_math`:**
1. Block-Math erzeugt `<div data-mx-maths="...">`
2. Inline-Math erzeugt `<span data-mx-maths="...">`
3. LaTeX mit `"` korrekt escaped im Attribut
4. Multi-Line Block-Math erhalten
5. Koexistenz mit anderen Plugins

**`plugin_mx_spoiler`:**
6. `||text||` erzeugt `<span data-mx-spoiler>text</span>`
7. Nested Inline-Markdown funktioniert (`||**bold**||`)
8. Email-Channel rendert kein `data-mx-spoiler`

**`sanitize_for_matrix` (nh3):**
6. Unbekannte Tags werden entfernt (Content bleibt)
7. `<script>` und Content werden entfernt (`clean_content_tags`)
8. `<details>/<summary>` passieren
9. `<u>` passiert
10. `<span data-mx-spoiler>` passiert
11. `<span data-mx-maths>` passiert (kein Doppel-Escaping nach Plugin)
12. `code[class=language-python]` passiert, `code[class=foo]` wird entfernt
13. `img[src=mxc://...]` passiert, `img[src=https://...]` wird entfernt
14. `a[href=javascript:]` wird entfernt
15. Email-Channel rendert kein `data-mx-maths`

---

## Dependency

```toml
# pyproject.toml
"nh3>=0.2"
```

nh3 ist eine Rust-Extension (via PyO3/maturin). Binäre Wheels für alle gängigen Plattformen auf PyPI verfügbar — kein Compiler-Build nötig.

---

## Risks & Mitigations

| Risiko                                     | Wahrscheinlichkeit | Impact | Mitigation                                       |
| ------------------------------------------ | ------------------ | ------ | ------------------------------------------------ |
| nh3 entfernt `data-mx-*` Attribute         | Niedrig            | Hoch   | Explizit in `attributes` dict eintragen + Tests  |
| Double-Escaping: Plugin escaped, nh3 auch  | Mittel             | Mittel | nh3 parsed HTML korrekt, kein double-escape; Test |
| Pattern-Kollision `$...$` mit Superscript  | Niedrig            | Mittel | Inline-Math vor `link` registriert; Test         |
| nh3 binary wheel fehlt auf Zielplattform   | Sehr niedrig       | Mittel | nh3 0.3.3 hat Wheels für Linux/macOS/Windows     |

---

## References

- Matrix Spec v1.17 — Permitted HTML: <https://spec.matrix.org/v1.17/client-server-api/#permitted-html>
- Matrix Spec v1.17 — Mathematical Messages: <https://spec.matrix.org/v1.17/client-server-api/#mathematical-messages>
- MSC2191: Markup for mathematical messages
- nh3 Docs: <https://nh3.readthedocs.io/>
- mistune Plugin API: <https://mistune.lepture.com/en/latest/advanced.html#create-plugins>
