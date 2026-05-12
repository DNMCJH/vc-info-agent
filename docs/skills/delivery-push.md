---
name: delivery-push
description: Push briefing to Feishu group chat as interactive card with feedback buttons.
version: 0.1
owner: 陈嘉豪
---

## When to use
After briefing generation, to deliver to end users.

## Inputs
- briefing_md: Markdown string
- briefing_data: structured JSON with items[].item_id

## Preconditions
- FEISHU_WEBHOOK configured
- FEEDBACK_BASE_URL points to reachable feedback server

## Steps
1. Parse Markdown into Feishu card elements
2. For each item block: attach feedback buttons using stable item_id from briefing_data
3. POST card payload to Feishu webhook
4. Log success/failure

## Outputs
- Feishu message delivered to group chat
- Each item has 👍/👎 buttons linking to /feedback?id=<item_id>&r=like|dislike

## Validation
- Button URLs contain stable item_id (not sequence number)
- Card renders correctly in Feishu mobile and desktop
- Webhook returns code=0
