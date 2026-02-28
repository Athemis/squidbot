---
name: summarize
description: "Summarize documents, conversations, or content into key points."
always: false
requires: {}
---

# Summarize Skill

Condense long-form content into structured, actionable summaries.

## When to Use

- Long documents, articles, reports
- Meeting transcripts, chat logs
- Email threads
- Any content needing distillation

## Output Structure

### 1. Key Points (Required)

Bullet list of the most important takeaways (3-7 items).

### 2. Details (Optional)

Supporting context for key points, if needed.

### 3. Action Items (If Applicable)

Next steps, decisions, or follow-ups.

## Guidelines

- **Length**: Target ~10% of original content
- **Format**: Bullet points, not prose
- **Language**: Match the input language
- **Focus**: What matters most to the reader

## Example

**Input:** 2000-word article about microservices

**Output:**

```
## Key Points
- Microservices improve scalability but add complexity
- Start with monolith, extract services when needed
- Each service should own its data
- Use API gateways for cross-cutting concerns

## Details
- Deployment: Each service deploys independently
- Communication: Prefer async messaging over sync HTTP
- Monitoring: Distributed tracing is essential

## Action Items
- Assess team DevOps readiness before migration
- Define data consistency strategy per service boundary
- Budget for latency/observability in service-to-service calls
```
