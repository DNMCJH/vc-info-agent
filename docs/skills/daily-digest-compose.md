---
name: daily-digest-compose
description: Generate daily briefing with LLM summaries, trend insight, and structured output.
version: 0.1
owner: 陈嘉豪
---

## When to use
After filtering, to produce the daily briefing for delivery.

## Inputs
- Filtered items list (with item_id, quality_score)
- Total collected count
- Historical preference context from FeedbackStore

## Preconditions
- LLM API key configured
- At least 1 filtered item available

## Steps
1. Load preference context (once per run)
2. For each item: call LLM with ITEM_SUMMARY_PROMPT including preference context
3. Parse structured summary and why_it_matters
4. Generate trend insight across all items
5. Compose Markdown briefing
6. Build structured JSON briefing_data

## Outputs
- `sample_output/briefing_YYYY-MM-DD.md`
- `data/briefings/briefing_YYYY-MM-DD.json`
- Return tuple: (briefing_md, briefing_data)

## Validation
- Every item in JSON has: item_id, title, url, summary, why_it_matters, quality_score
- Markdown renders correctly
- Preference context injected but does not override factual content
