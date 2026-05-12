---
name: feedback-capture
description: Capture user reactions (like/dislike) and optional comments via HTTP or CLI.
version: 0.1
owner: 陈嘉豪
---

## When to use
When user clicks Feishu button or uses CLI to provide feedback on briefing items.

## Inputs
- item_id (stable hash)
- reaction: "like" or "dislike"
- comment (optional, max 1000 chars)

## Preconditions
- Feedback server running (port 9002)
- Recent briefing JSON exists in data/briefings/

## Steps
1. Receive reaction via GET /feedback?id=<item_id>&r=like|dislike
2. Look up item metadata from recent briefing JSONs
3. Record feedback with full metadata snapshot
4. Return HTML page with optional comment form
5. If comment submitted: POST /feedback/comment with feedback_id

## Outputs
- feedback.json updated with new event and item metadata
- HTML confirmation page shown to user

## Validation
- feedback.json items[item_id] has complete metadata
- feedback.json events[] has new entry with timestamp
- Comment length capped at 1000 chars
- HTML output is escaped against XSS
