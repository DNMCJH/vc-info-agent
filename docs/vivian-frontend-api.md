# Vivian Website MVP API

This is the minimal handoff contract for embedding VC Agent data into an
external website such as `vc.vivianai.cn`.

## Goal

Keep the VC Agent collector, scheduler, API keys, and briefing generation on the
existing VC Agent server. Vivian's website only needs a thin frontend that reads
JSON and renders it.

## Public endpoints

Base URL is the deployed H5/API server, for example:

```text
https://<vc-agent-server>
```

### Latest briefing

```http
GET /api/latest
```

Returns the newest daily briefing JSON.

### Briefing archive

```http
GET /api/briefings?limit=30
```

Returns compact metadata for available daily briefings.

### One briefing by date

```http
GET /api/briefing/YYYY-MM-DD
```

Returns one full daily briefing JSON.

### Built-in minimal frontend

```http
GET /
```

Renders a minimal page that fetches `/api/latest` in the browser.

If this HTML is copied to another domain, pass the API base URL by query string:

```text
https://vc.vivianai.cn/?api=https://<vc-agent-server>
```

## First MVP scope

- Latest daily briefing page
- TL;DR
- Selected items
- Trend insight
- Links to original sources and full H5 detail page

## Later scope

- History page
- Search
- Category filters
- Real-time/latest item stream
- AIHOT-like selected feed
