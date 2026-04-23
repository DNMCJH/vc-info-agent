"""Content filter — scores and filters collected items by quality."""

import logging
import re
from datetime import datetime, timezone

from config import Config
from feedback import FeedbackStore

logger = logging.getLogger(__name__)


class ContentFilter:
    def __init__(self, config: Config):
        self.config = config
        self.feedback = FeedbackStore()

    def filter(self, items: list[dict]) -> list[dict]:
        scored = []
        for item in items:
            score = self._score(item)
            item["quality_score"] = score
            if score >= self.config.quality_threshold:
                scored.append(item)

        scored.sort(key=lambda x: x["quality_score"], reverse=True)
        deduped = self._deduplicate(scored)

        result = self._select_top(deduped)
        logger.info(
            f"Filtered {len(items)} → {len(scored)} above threshold → {len(deduped)} after dedup → {len(result)} selected"
        )
        return result

    def _score(self, item: dict) -> int:
        score = 0

        # Source credibility (25%)
        if item.get("channel", "") in self.config.kol_whitelist:
            score += 25
        elif item.get("views", 0) > 10000:
            score += 15
        else:
            score += 5

        # Content length (15%) — duration for YouTube, description length for RSS
        if item.get("source") == "YouTube":
            duration_str = item.get("duration", "PT0S")
            minutes = self._parse_duration_minutes(duration_str)
            if minutes >= 10:
                score += 15
            elif minutes >= 5:
                score += 10
            elif minutes >= 2:
                score += 5
        else:
            desc_len = len(item.get("description", ""))
            if desc_len >= 1000:
                score += 15
            elif desc_len >= 500:
                score += 10
            elif desc_len >= 200:
                score += 5

        # Engagement (20%) — RSS gets authority-based compensation
        likes = item.get("likes", 0)
        comments = item.get("comments", 0)
        engagement = likes + comments * 2
        if item.get("source") == "RSS":
            authority = item.get("source_authority", "medium")
            score += {"high": 15, "medium": 10, "low": 3}.get(authority, 3)
        elif engagement > 5000:
            score += 20
        elif engagement > 1000:
            score += 15
        elif engagement > 100:
            score += 10
        else:
            score += 3

        # Keyword relevance (20%) — use domain_keywords from config
        text = f"{item.get('title', '')} {item.get('description', '')}".lower()
        all_keywords = []
        for kws in self.config.domain_keywords.values():
            all_keywords.extend(kws)
        hits = sum(1 for kw in all_keywords if kw.lower() in text)
        score += min(hits * 5, 20)

        # Recency (10%)
        try:
            pub = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
            hours_ago = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
            if hours_ago < 6:
                score += 10
            elif hours_ago < 12:
                score += 7
            elif hours_ago < 24:
                score += 5
        except (KeyError, ValueError):
            score += 3

        # Spam penalty (10%)
        spam_hits = sum(
            1 for kw in self.config.spam_keywords if kw.lower() in text
        )
        if spam_hits > 0:
            score -= min(spam_hits * 15, 45)

        if re.search(r"bit\.ly|utm_|affiliate", text):
            score -= 15

        # Feedback preference adjustment
        source_weight = self.feedback.get_source_weight(item.get("channel", ""))
        domain_weight = self.feedback.get_domain_weight(item.get("domain", ""))
        score += int(source_weight * 3 + domain_weight * 2)

        return max(score, 0)

    @staticmethod
    def _deduplicate(items: list[dict]) -> list[dict]:
        """Remove items covering the same event using keyword overlap in titles."""
        result = []
        for item in items:
            title_words = set(re.findall(r"\w+", item.get("title", "").lower()))
            is_dup = False
            for existing in result:
                existing_words = set(re.findall(r"\w+", existing.get("title", "").lower()))
                if not title_words or not existing_words:
                    continue
                overlap = len(title_words & existing_words)
                similarity = overlap / min(len(title_words), len(existing_words))
                if similarity > 0.5:
                    is_dup = True
                    break
            if not is_dup:
                result.append(item)
        return result

    def _select_top(self, scored: list[dict]) -> list[dict]:
        """Pick top items per domain, respecting max limits."""
        result = []
        domain_counts: dict[str, int] = {}

        for item in scored:
            domain = item.get("domain", "other")
            count = domain_counts.get(domain, 0)
            if count >= self.config.max_items_per_domain:
                continue
            if len(result) >= self.config.max_total_items:
                break
            result.append(item)
            domain_counts[domain] = count + 1

        return result

    @staticmethod
    def _parse_duration_minutes(iso_duration: str) -> float:
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
        if not match:
            return 0
        h = int(match.group(1) or 0)
        m = int(match.group(2) or 0)
        s = int(match.group(3) or 0)
        return h * 60 + m + s / 60
