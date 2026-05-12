---
name: feedback-store
description: Persist feedback data with full metadata, event history, and preference aggregation.
version: 0.1
owner: 陈嘉豪
---

## When to use
Called by feedback-capture and learn-from-feedback skills.

## Inputs
- item_id, reaction, item_meta dict, optional comment

## Preconditions
- data/ directory writable
- feedback.json exists or will be created

## Steps
1. Load and normalize feedback.json (handle old schema)
2. Create/update item snapshot in items[item_id]
3. Append event to events[] with feedback_id and timestamp
4. Update cumulative preferences (sources, domains)
5. Save atomically

## Outputs
- Updated data/feedback.json with structure: {items, events, preferences}

## Validation
- Old feedback.json formats are migrated without data loss
- feedback_count increments correctly
- preferences reflect cumulative like/dislike signals
