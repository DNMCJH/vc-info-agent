"""In-memory search index over all daily briefings.

Reading 120+ JSON files on every search request is wasteful, so the whole
corpus is flattened into a list of item records once and reused. The index
refreshes itself when files are added or modified, which keeps it correct
after the daily scheduler writes a new briefing without needing a restart.
"""

import html
import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class BriefingIndex:
    """Flattened, filterable view of every item across all briefings."""

    def __init__(self, briefings_dir: Path):
        self.dir = briefings_dir
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._dates: list[str] = []
        self._signature: tuple = ()

    def _current_signature(self) -> tuple:
        """Cheap fingerprint of the corpus: path + mtime + size per file."""
        entries = []
        for path in sorted(self.dir.glob("briefing_*.json")):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((path.name, stat.st_mtime_ns, stat.st_size))
        return tuple(entries)

    def _rebuild(self) -> None:
        items: list[dict] = []
        dates: set[str] = set()

        for path in sorted(self.dir.glob("briefing_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                logger.warning("Search index skipping %s: %s", path, exc)
                continue

            date_str = data.get("date") or path.stem.replace("briefing_", "")
            dates.add(date_str)

            for item in data.get("items", []):
                # Decode RSS entities so both display and keyword matching
                # work on real characters (&#8217; -> ').
                title = html.unescape(item.get("title", "") or "")
                summary = html.unescape(item.get("summary", "") or "")
                why = html.unescape(item.get("why_it_matters", "") or "")
                channel = item.get("channel", "") or ""
                items.append({
                    "date": date_str,
                    "item_id": item.get("item_id", ""),
                    "title": title,
                    "url": item.get("url", ""),
                    "summary": summary,
                    "why_it_matters": why,
                    "domain": item.get("domain", "") or "",
                    "source": item.get("source", "") or "",
                    "channel": channel,
                    "quality_score": item.get("quality_score", 0) or 0,
                    "published_at": item.get("published_at", "") or "",
                    # Precomputed lowercase haystack; keyword matching is the
                    # hot path and rebuilding this per request is pure waste.
                    "_haystack": " ".join(
                        (title, summary, why, channel, date_str)
                    ).lower(),
                })

        # Newest first so unfiltered browsing shows recent items.
        items.sort(key=lambda r: (r["date"], r["item_id"]), reverse=True)
        self._items = items
        self._dates = sorted(dates, reverse=True)

    def ensure_fresh(self) -> None:
        """Rebuild only when the underlying files changed."""
        signature = self._current_signature()
        with self._lock:
            if signature != self._signature:
                self._rebuild()
                self._signature = signature
                logger.info(
                    "Search index rebuilt: %d items across %d briefings",
                    len(self._items), len(self._dates),
                )

    @property
    def items(self) -> list[dict]:
        self.ensure_fresh()
        return self._items

    @property
    def dates(self) -> list[str]:
        self.ensure_fresh()
        return self._dates

    def facets(self) -> dict:
        """Filter options derived from real data, for populating the UI."""
        self.ensure_fresh()
        domains: dict[str, int] = {}
        sources: dict[str, int] = {}
        channels: dict[str, int] = {}
        # {"2026": {"05": 19, ...}} drives the year/month cascading selects.
        calendar: dict[str, dict[str, int]] = {}

        for date_str in self._dates:
            parts = date_str.split("-")
            if len(parts) >= 2:
                calendar.setdefault(parts[0], {}).setdefault(parts[1], 0)

        for item in self._items:
            if item["domain"]:
                domains[item["domain"]] = domains.get(item["domain"], 0) + 1
            if item["source"]:
                sources[item["source"]] = sources.get(item["source"], 0) + 1
            if item["channel"]:
                channels[item["channel"]] = channels.get(item["channel"], 0) + 1

        # Per-month briefing counts, not item counts: the month select shows
        # how many issues exist in that month.
        for date_str in self._dates:
            parts = date_str.split("-")
            if len(parts) >= 2:
                calendar[parts[0]][parts[1]] += 1

        def ranked(counts: dict[str, int]) -> list[dict]:
            return [
                {"value": k, "count": v}
                for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ]

        return {
            "total_items": len(self._items),
            "total_briefings": len(self._dates),
            "date_range": {
                "earliest": self._dates[-1] if self._dates else "",
                "latest": self._dates[0] if self._dates else "",
            },
            "calendar": {
                year: [
                    {"month": m, "count": c}
                    for m, c in sorted(months.items(), reverse=True)
                ]
                for year, months in sorted(calendar.items(), reverse=True)
            },
            "domains": ranked(domains),
            "sources": ranked(sources),
            "channels": ranked(channels),
        }

    def search(
        self,
        keyword: str = "",
        domain: str = "",
        source: str = "",
        channel: str = "",
        year: str = "",
        month: str = "",
        date: str = "",
        date_from: str = "",
        date_to: str = "",
        min_score: int = 0,
        sort: str = "date",
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """Filter items by any combination of keyword, facet, and date."""
        self.ensure_fresh()

        # All keyword terms must appear (AND), so extra words narrow results.
        terms = [t for t in keyword.lower().split() if t]
        rows = []

        for item in self._items:
            item_date = item["date"]
            if date and item_date != date:
                continue
            if year and item_date[:4] != year:
                continue
            if month and item_date[5:7] != month:
                continue
            if date_from and item_date < date_from:
                continue
            if date_to and item_date > date_to:
                continue
            if domain and item["domain"] != domain:
                continue
            if source and item["source"] != source:
                continue
            if channel and item["channel"] != channel:
                continue
            if min_score and item["quality_score"] < min_score:
                continue
            if terms and not all(t in item["_haystack"] for t in terms):
                continue
            rows.append(item)

        if sort == "score":
            rows.sort(key=lambda r: (r["quality_score"], r["date"]), reverse=True)

        total = len(rows)
        offset = max(0, offset)
        limit = max(1, min(limit, 100))
        page = rows[offset:offset + limit]

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
            "items": [
                {k: v for k, v in row.items() if not k.startswith("_")}
                for row in page
            ],
        }
