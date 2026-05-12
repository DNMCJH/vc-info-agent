---
name: youtube-source-fetch
description: Collect recent videos from YouTube channels via Data API v3.
version: 0.1
owner: 陈嘉豪
---

## When to use
Daily scheduled collection from subscribed YouTube channels and keyword searches.

## Inputs
- YouTube API key
- Channel IDs and domain mappings from config
- Search keywords per domain

## Preconditions
- Valid YOUTUBE_API_KEY in environment
- Channels configured in sources.yaml

## Steps
1. For each channel: fetch recent uploads via playlist API
2. For each domain keyword: search API with relevance ordering
3. Fetch video details (stats, duration, content details)
4. Attempt transcript fetch (en/zh)
5. Deduplicate by video_id
6. Return normalized item list

## Outputs
- List of item dicts with: video_id, title, channel, description, published_at, views, likes, comments, duration, url, domain, source, transcript

## Validation
- Items have non-empty title and url
- published_at is within collection window
- No duplicate video_ids in output
