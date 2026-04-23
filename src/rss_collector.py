"""RSS feed collector for tech media sources."""

import logging
import re
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
from opencc import OpenCC

from config import Config

_t2s = OpenCC("t2s")
logger = logging.getLogger(__name__)


class RSSCollector:
    """Collects articles from configured RSS feeds with domain classification."""

    def __init__(self, config: Config):
        self.config = config

    def collect(self) -> list[dict]:
        """Collect articles from all configured RSS feeds."""
        all_items = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)

        for feed_cfg in self.config.rss_feeds:
            try:
                items = self._parse_feed(feed_cfg, cutoff)
                all_items.extend(items)
                logger.info(f"RSS '{feed_cfg['name']}': {len(items)} items")
            except Exception as e:
                logger.warning(f"RSS '{feed_cfg.get('name', '?')}' failed: {e}")

        logger.info(f"Collected {len(all_items)} items from RSS feeds")
        return all_items

    def _parse_feed(self, feed_cfg: dict, cutoff: datetime) -> list[dict]:
        feed = feedparser.parse(feed_cfg["url"])
        results = []

        for entry in feed.entries[:20]:
            pub_time = self._parse_time(entry)
            if pub_time and pub_time < cutoff:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            summary = re.sub(r"<[^>]+>", "", summary)[:2000]

            if feed_cfg.get("lang") == "zh":
                title = _t2s.convert(title)
                summary = _t2s.convert(summary)

            domain = self._classify_domain(title + " " + summary, feed_cfg)

            results.append({
                "article_id": entry.get("id", entry.get("link", title)),
                "title": title,
                "channel": feed_cfg["name"],
                "description": summary,
                "published_at": pub_time.isoformat() if pub_time else "",
                "url": entry.get("link", ""),
                "domain": domain,
                "source": "RSS",
                "source_authority": feed_cfg.get("authority", "medium"),
                "views": 0,
                "likes": 0,
                "comments": 0,
                "duration": "",
                "transcript": "",
            })

        return results

    def _classify_domain(self, text: str, feed_cfg: dict) -> str:
        """Assign domain based on keyword matching against domain_keywords."""
        text_lower = text.lower()
        best_domain = feed_cfg.get("domains", ["AI"])[0]
        best_score = 0

        for domain, keywords in self.config.domain_keywords.items():
            if domain not in feed_cfg.get("domains", []):
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
