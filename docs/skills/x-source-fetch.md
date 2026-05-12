---
name: x-source-fetch
description: Collect posts from X/Twitter accounts (pending implementation).
version: 0.1
owner: 陈嘉豪
---

## When to use
When X API access is confirmed and budget allows.

## Inputs
- X API bearer token
- List of handles from source_pool.yaml where platform=x and status=active

## Preconditions
- X API v2 access (Basic or Pro tier)
- Rate limit budget allocated

## Steps
1. For each active X source: fetch recent tweets (past 24h)
2. Filter out replies and retweets (keep original posts and quote tweets)
3. Extract: text, media URLs, engagement metrics, timestamp
4. Normalize to unified item schema
5. Classify domain based on content keywords

## Outputs
- List of item dicts with: item_id, platform="x", source_id, title (first 100 chars), content, url, published_at, domain

## Validation
- Status: PENDING — not yet implemented
- Requires X API cost/access confirmation from Vivian
