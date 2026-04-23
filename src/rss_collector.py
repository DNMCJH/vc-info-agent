"""RSS feed collector for tech media sources."""

import logging
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
from opencc import OpenCC

from config import Config

_t2s = OpenCC("t2s")
logger = logging.getLogger(__name__)


class RSSCollector:
    def __init__(self, config: Config):
        self.config = config

    def collect(self) -> list[dict]:
        """Collect articles from all configured RSS feeds."""
        all_items = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)

        for url, meta in self.config.rss_feeds.items():
            try:
                items = self._parse_feed(url, meta, cutoff)
                all_items.extend(items)
                logger.info(f"RSS '{meta['name']}': {len(items)} items")
            except Exception as e:
                logger.warning(f"RSS '{meta['name']}' failed: {e}")

        logger.info(f"Collected {len(all_items)} items from RSS feeds")
        return all_items

    def _parse_feed(self, url: str, meta: dict, cutoff: datetime) -> list[dict]:
        feed = feedparser.parse(url)
        results = []

        for entry in feed.entries[:20]:
            pub_time = self._parse_time(entry)
            if pub_time and pub_time < cutoff:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            # Strip HTML tags from summary
            import re
            summary = re.sub(r"<[^>]+>", "", summary)[:2000]

            if meta.get("lang") == "zh":
                title = _t2s.convert(title)
                summary = _t2s.convert(summary)

            domain = self._classify_domain(title + " " + summary, meta)

            results.append({
                "article_id": entry.get("id", entry.get("link", url + title)),
                "title": title,
                "channel": meta["name"],
                "description": summary,
                "published_at": pub_time.isoformat() if pub_time else "",
                "url": entry.get("link", ""),
                "domain": domain,
                "source": "RSS",
                "views": 0,
                "likes": 0,
                "comments": 0,
                "duration": "",
                "transcript": "",
            })

        return results

    def _classify_domain(self, text: str, meta: dict) -> str:
        """Assign domain based on keyword matching against domain_keywords."""
        text_lower = text.lower()
        best_domain = meta.get("domains", ["AI"])[0]
        best_score = 0

        for domain, keywords in self.config.domain_keywords.items():
            if domain not in meta.get("domains", []):
                continue
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain

    @staticmethod
    def _parse_time(entry) -> datetime | None:
        for field in ("published_parsed", "updated_parsed"):
            parsed = entry.get(field)
            if parsed:
                return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
        return None
