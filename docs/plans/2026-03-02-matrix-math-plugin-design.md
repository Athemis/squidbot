# Matrix Math Plugin — Design Document

**Status:** Draft

**Problem:** LLM-Antworten mit mathematischen Ausdrücken (`$$E=mc^2$$`, `$x^2$`) werden aktuell nicht korrekt in Matrix gerendert. Das eingebaute mistune-math-Plugin erzeugt `<div class="math">`, aber Matrix-Clients (Element, FluffyChat) erwarten `<div data-mx-maths>` gemäß Spec v1.11+ (MSC2191).

**Solution:** Eigenes mistune-Plugin `plugin_mx_math`, das LaTeX-Syntax in Matrix-kompatibles HTML übersetzt. `escape=True` bleibt aktiv — kein HTML-Sanitizer nötig.

---

## Background

### Matrix Spec v1.11 — Mathematical Messages

Die Matrix-Spec definiert seit v1.11 ein spezielles HTML-Format für mathematische Inhalte:

| Element   | Tag     | Attribut                    | Kind-Content           |
| --------- | ------- | --------------------------- | ---------------------- |
| Block     | `<div>`   | `data-mx-maths="<LaTeX>"`     | Fallback (HTML/Text)   |
| Inline    | `<span>`  | `data-mx-maths="<LaTeX>"`     | Fallback (HTML/Text)   |

**Beispiel (inline):**

```html
<span data-mx-maths="\sin(x)=\frac{a}{b}">sin(<i>x</i>)=<sup><i>a</i></sup>/<sub><i>b</i></sub></span>
```

- Das `data-mx-maths`-Attribut enthält den rohen LaTeX-String (HTML-escaped).
- Der Kind-Content ist ein Fallback für Clients ohne LaTeX-Support.
- Clients mit LaTeX-Rendering (Element, FluffyChat) zeigen die gerenderte Formel an.

### mistune Built-in `math` Plugin

Das eingebaute Plugin nutzt dieselbe Syntax (`$$...$$` / `$...$`), erzeugt aber:

```html
<div class="math">$$\nE=mc^2\n$$</div>
<span class="math">\((E=mc^2)\)</span>
```

Das ist **nicht** Matrix-kompatibel. Ein CSS-basierter Ansatz (`class="math"`) wird von Element/FluffyChat nicht unterstützt.

---

## Design

### Architektur

```
squidbot/adapters/channels/
├── matrix.py               # importiert plugin_mx_math, fügt es zur Plugin-Liste
├── matrix_markdown.py      # NEU: plugin_mx_math implementation
└── email.py                # unverändert (nutzt nur core.markdown PLUGINS)

squidbot/core/
└── markdown.py             # unverändert (enthält nur shared plugin names)
```

**Abhängigkeitsrichtung:**

- `matrix.py` → `matrix_markdown.py` (Plugin-Import)
- `email.py` → `core/markdown.py` (shared Plugins)
- `core/` importiert nichts aus `adapters/` (Hexagonal Architecture bleibt intakt)

### Plugin-Signatur

```python
def plugin_mx_math(md: Markdown) -> None:
    """Mistune plugin that renders math to Matrix data-mx-maths format."""
```

Das Plugin folgt dem mistune-Plugin-Contract (callable, nimmt `Markdown`-Instanz, registriert Parser und Renderer).

### Syntax-Erkennung

Identisch zum eingebauten `math`-Plugin:

| Typ    | Pattern                                  | Beispiel          |
| ------ | ---------------------------------------- | ----------------- |
| Block  | `^ {0,3}\$\$[ \t]*\n[\s\S]+?\n\$\$[ \t]*$` | `$$\nE=mc^2\n$$`    |
| Inline | `\$(?!\s)(.+?)(?!\s)\$`                    | `$x^2$`             |

Block-Math wird vor `list` registriert, Inline-Math vor `link`.

### HTML-Output

**Block:**

```html
<div data-mx-maths="a^2 + b^2 = c^2"><code>a^2 + b^2 = c^2</code></div>
```

**Inline:**

```html
<span data-mx-maths="x^2"><code>x^2</code></span>
```

- `data-mx-maths`-Attribut: LaTeX roh, HTML-escaped (`html.escape(..., quote=True)`)
- Kind-Content: `<code>` mit dem gleichen Text (Fallback für nicht-LaTeX-Clients)
- Keine Unicode-Konvertierung, keine LaTeX → HTML-Approximation — das überlassen wir dem Client

### Security

- `escape=True` bleibt in `matrix.py` aktiviert
- Das Plugin selbst escapet LaTeX-Content mit `html.escape()` bevor er ins Attribut geschrieben wird
- Kein Raw-HTML-Passthrough, kein Sanitizer (nh3) nötig
- Single-user Bot, Trusted Output — Risiko ist minimal

### Koexistenz mit anderen Plugins

`plugin_mx_math` wird **zusätzlich** zu den bestehenden Plugins geladen:

```python
_md = mistune.create_markdown(
    escape=True,
    plugins=[*MARKDOWN_PLUGINS, plugin_mx_graph],
)
```

Die Pattern von `plugin_mx_graph` und `superscript` (`^text^`) können kollidieren. Da Inline-Math vor `link` registriert wird und Superscript ein eigenes Pattern hat, gibt es keinen Konflikt in der Praxis — mistune priorisiert nach Registrierungsreihenfolge.

---

## Scope

### In Scope

- Block-Math (`$$...$$`) → `<div data-mx-maths>`
- Inline-Math (`$...$`) → `<span data-mx-maths>`
- HTML-Escaping von LaTeX-Content
- Fallback `<code>` für nicht-LaTeX-Clients
- Unit Tests

### Out of Scope

- Spoiler-Plugin (`data-mx-spoiler`) — separates Feature
- Details/Summary-Plugin — Raw-HTML-Passthrough oder separates Plugin
- Math in Email-Channel — nicht Matrix-spezifisch
- LaTeX → Unicode/HTML-Approximation — Client-seitiges Rendering

---

## Testing Strategy

**Unit Tests** in `tests/adapters/channels/test_markdown_plugins.py`:

1. Block-Math erzeugt `<div data-mx-maths="...">` mit korrektem Attribut
2. Inline-Math erzeugt `<span data-mx-maths="...">` mit korrektem Attribut
3. LaTeX mit Quotes wird korrekt escaped (`"` → `&quot;`)
4. Multi-Line Block-Math bleibt erhalten
5. Email-Channel rendert NICHT `data-mx-maths` (Plugin nicht aktiv)
6. Koexistenz mit anderen Plugins (strikethrough, table, etc.)

**Integration:**

- Manueller Test in echtem Matrix-Room mit Element/FluffyChat
- Verifikation dass Formeln korrekt gerendert werden

---

## Risks & Mitigations

| Risiko                              | Wahrscheinlichkeit | Impact | Mitigation                              |
| ----------------------------------- | ------------------ | ------ | --------------------------------------- |
| Pattern-Kollision mit `superscript` | Niedrig           | Mittel | Inline-Math vor `link`, Test Coverage   |
| LaTeX mit Sonderzeichen escaped falsch | Mittel           | Niedrig | `html.escape(..., quote=True)` + Tests  |
| Element unterstützt `data-mx-maths` nicht | Niedrig (Spec v1.11+) | Mittel | Fallback `<code>` wird angezeigt        |

---

## References

- Matrix Spec v1.17 — Mathematical Messages: <https://spec.matrix.org/v1.17/client-server-api/#mathematical-messages>
- MSC2191: Markup for mathematical messages
- mistune Plugin API: <https://mistune.lepture.com/en/latest/advanced.html#create-plugins>
- mistune `math` plugin source: `mistune/plugins/math.py`
