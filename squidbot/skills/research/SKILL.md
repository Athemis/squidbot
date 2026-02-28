---
name: research
description: "Performs structured research with source evaluation and citations using `web_search` and `fetch_url`. Use when the user asks for fact-finding, comparisons, or referenced summaries."
always: false
requires: {}
---

# Research Skill

Conduct structured research using the `web_search` and `fetch_url` tools.

## Workflow

### 1. Define Query

Clarify what information is needed. Break complex questions into sub-queries.

### 2. Search

Use `web_search` to find relevant sources:

```
web_search(query="topic", num_results=10)
```

### 3. Evaluate Sources

Before trusting a source:
- Check domain credibility (.edu, .gov, established publications)
- Look for publication date (is it current?)
- Cross-reference claims with other sources

Use `fetch_url` to read full content before citing.

### 4. Extract Information

- Pull key facts, not entire articles
- Note source URLs for citation
- Flag conflicting information

### 5. Synthesize

Present findings as:
1. **Summary** — 2-3 sentence overview
2. **Key Points** — bullet list of main findings
3. **Sources** — URLs with brief descriptions

## Best Practices

- **Triangulate**: Confirm facts across 2-3 independent sources
- **Cite**: Always include source URLs
- **Date check**: Note when information was published
- **Scope**: Stay focused on the original question

## Example Output

```
## Summary
[Topic] refers to...

## Key Points
- Point 1 (Source: url1.com)
- Point 2 (Source: url2.com)
- Point 3 (Source: url1.com, url3.com)

## Sources
- url1.com — Description
- url2.com — Description
```
