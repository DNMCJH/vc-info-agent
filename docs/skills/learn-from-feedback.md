---
name: learn-from-feedback
description: Use historical feedback to adjust filter scores and summarizer prompts.
version: 0.1
owner: 陈嘉豪
---

## When to use
Every pipeline run — filter and summarizer both read historical feedback.

## Inputs
- Current item being scored/summarized
- Historical feedback data from feedback.json

## Preconditions
- feedback.json exists (empty is fine — returns neutral adjustments)

## Steps
1. Filter: call get_item_adjustment(item) which checks:
   - Exact item_id match (strong signal)
   - Source/channel preference weight
   - Domain preference weight
   - Title keyword overlap with liked/disliked items
2. Summarizer: call get_preference_context() which returns:
   - Recent liked examples with title/domain/channel/summary/comment
   - Recent disliked examples
3. Inject preference context into LLM prompt with guardrails

## Outputs
- Filter: integer score adjustment (clamped to [-25, +20])
- Summarizer: preference context string for prompt injection

## Validation
- Adjustment is bounded and does not dominate base score
- Preference context explicitly states "only for attention angle, not facts"
- With zero feedback: returns neutral (0 adjustment, "暂无历史反馈")
