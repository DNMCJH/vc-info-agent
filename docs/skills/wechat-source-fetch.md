---
name: wechat-source-fetch
description: Collect articles from WeChat public accounts (pending implementation).
version: 0.1
owner: 陈嘉豪
---

## When to use
When a reliable WeChat MP article collection method is confirmed.

## Inputs
- List of public account names from source_pool.yaml where platform=wechat_mp

## Preconditions
- Access method confirmed (RSS bridge, manual curation, or third-party API)
- Compliance review passed

## Steps
1. Fetch recent articles from target accounts
2. Extract: title, author, publish_time, content, url
3. Convert Traditional Chinese to Simplified if needed
4. Normalize to unified item schema
5. Classify domain

## Outputs
- List of item dicts with: item_id, platform="wechat_mp", source_id, title, content, url, published_at, domain

## Validation
- Status: PENDING — no stable automated access method confirmed
- Options under research: WeChatFerry, RSS bridges, manual weekly batch
