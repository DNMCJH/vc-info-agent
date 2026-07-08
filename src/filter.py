"""Content filter — scores and filters collected items by quality."""

import logging
import re
from datetime import datetime, timezone

from config import Config
from feedback import FeedbackStore

logger = logging.getLogger(__name__)


class ContentFilter:
    """Scores, deduplicates, and selects top content items by quality."""

    def __init__(self, config: Config):
        self.config = config
        self.feedback = FeedbackStore()
        self.last_debug: dict = {}

    def filter(self, items: list[dict], llm_dedup=None) -> list[dict]:
        """Score → threshold → dedup → top-N selection.

        If llm_dedup is provided (an LLMDeduplicator instance), event-level
        dedup uses LLM refinement on coarse entity clusters; otherwise it
        falls back to entity-only matching (cheaper, more false merges).
        """
        scored = []
        below_threshold = []
        for item in items:
            score = self._score(item)
            item["quality_score"] = score
            if score >= self.config.quality_threshold:
                scored.append(item)
            else:
                item["rejection_stage"] = "quality_threshold"
                item["rejection_reason"] = f"score {score} < threshold {self.config.quality_threshold}"
                below_threshold.append(item)

        scored.sort(key=lambda x: x["quality_score"], reverse=True)
        if llm_dedup is not None:
            deduped = llm_dedup.refine(scored)
        else:
            deduped = self._deduplicate(scored)

        # Post-dedup: boost items that absorbed duplicates (multi-source
        # coverage signals industry-wide attention). Capped at +5 to stay
        # within the Engagement dimension's 20-point budget.
        for item in deduped:
            n_merged = len(item.get("merged_from", []))
            if n_merged > 0:
                item["quality_score"] += min(n_merged * 2, 5)
        deduped.sort(key=lambda x: x["quality_score"], reverse=True)

        result = self._select_top(deduped)
        selected_keys = {self._item_key(item) for item in result}
        dropped_after_dedup = []
        for item in deduped:
            if self._item_key(item) in selected_keys:
                continue
            item["rejection_stage"] = "selection_limit"
            item["rejection_reason"] = "per-domain, per-source, or total item limit"
            dropped_after_dedup.append(item)

        self.last_debug = {
            "scored": scored + below_threshold,
            "above_threshold": scored,
            "deduped": deduped,
            "selected": result,
            "rejected": below_threshold + dropped_after_dedup,
        }
        logger.info(
            f"Filtered {len(items)} → {len(scored)} above threshold → {len(deduped)} after dedup → {len(result)} selected"
        )
        return result

    def _score(self, item: dict) -> int:
        """Calculate quality score (0-100) across 6 dimensions + feedback adjustment."""
        score = 0
        text = f"{item.get('title', '')} {item.get('description', '')}".lower()

        # Source credibility (25%)
        if item.get("channel", "") in self.config.kol_whitelist:
            score += 25
        elif item.get("views", 0) > 10000:
            score += 15
        else:
            score += 5

        # Content length (15%)
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

        # Engagement (20%)
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

        # Keyword relevance (20%)
        all_keywords = []
        for kws in self.config.domain_keywords.values():
            all_keywords.extend(kws)
        hits = sum(1 for kw in all_keywords if kw.lower() in text)
        major_signal = self._major_signal_score(item, text)
        if hits == 0 and major_signal == 0:
            return 0
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

        # Major first-party sources and material event terms should not be
        # crowded out by broad YouTube keyword-search noise.
        score += major_signal
        score -= self._noise_source_penalty(item, text)

        # Historical feedback adjustment (replaces old shallow source/domain weight)
        score += self.feedback.get_item_adjustment(item)

        return max(score, 0)

    def _major_signal_score(self, item: dict, text: str) -> int:
        score = 0
        channel = item.get("channel", "")
        category = item.get("source_category", "")
        priority = item.get("source_priority", "")

        if channel in self.config.major_sources:
            score += 10
        if category == "power_center":
            score += 10
        elif category in {"builder_practitioner", "educator_curator", "vc_startup"}:
            score += 5

        score += {"P0": 8, "P1": 4}.get(priority, 0)
        keyword_hits = sum(1 for kw in self.config.major_keywords if kw.lower() in text)
        score += min(keyword_hits * 3, 12)
        return min(score, 30)

    def _noise_source_penalty(self, item: dict, text: str) -> int:
        channel = item.get("channel", "").lower()
        configured_hits = sum(
            1 for noise in self.config.noise_channels if noise.lower() in channel
        )
        generic_noise = (
            "gaming",
            "benchmark",
            "unboxing",
            "stock",
            "股市",
            "投顾",
            "政经",
            "政治",
        )
        generic_hits = sum(1 for token in generic_noise if token in channel or token in text)
        return min((configured_hits + generic_hits) * 12, 36)

    @staticmethod
    def _item_key(item: dict) -> str:
        return item.get("item_id") or item.get("url") or item.get("article_id") or item.get("title", "")

    # Generic words that look like proper nouns but carry no event identity.
    # Lowercased on lookup, so list them lowercase here.
    _ENTITY_STOPWORDS = frozenset(w.lower() for w in {
        # Short acronyms / common words
        "AI", "IO", "API", "LLM", "GPT", "US", "USA", "CEO", "CTO", "CFO",
        "AGI", "ML", "VR", "AR", "I", "O", "THE", "AND", "FOR", "NEW",
        "HOW", "WHY", "WHAT", "DAY", "TOP", "BIG", "GPU", "CPU", "OS",
        # Long but non-distinctive words that wrongly read as proper nouns
        # (capitalized in clickbait titles). These must NOT be strong entities.
        "CHINA", "CHINESE", "AMERICA", "AMERICAN", "STRONG", "ROBOT",
        "ROBOTS", "BILLION", "MILLION", "TRILLION", "MODEL", "MODELS",
        "TECH", "DATA", "AGENT", "AGENTS", "STARTUP", "STARTUPS",
        "JUST", "BEAST", "MODE", "GAME", "CHANGER", "EVERYTHING",
        "COMPANIES", "COMPANY", "INDUSTRY", "FUTURE", "WORLD", "HUMAN",
        "HUMANOID", "POWER", "MARKET", "GROWTH", "OPENING", "REMARKS",
        "KEYNOTE", "RELEASED", "RELEASE", "UPGRADED", "DANGERS",
    })

    # Generic Chinese terms that recur across unrelated events — weak signal.
    _CN_STOPWORDS = frozenset({
        "人工智能", "机器人", "大模型", "产业大会", "办公室", "开发者",
        "知情人士", "互联网", "科技股", "全球史", "运营中心",
    })

    @classmethod
    def _extract_entities(cls, item: dict) -> tuple[set[str], set[str]]:
        """Extract named entities from title + summary, split by strength.

        Returns (strong, weak). Strong entities are distinctive product /
        company / proper names; weak ones are short or generic tokens. Two
        items count as the same event only if they share a STRONG entity
        (see _deduplicate) — this stops generic words like "AI" + a year
        from falsely merging unrelated stories.

        Title alone is unreliable (creators write clickbait variants of the
        same news), so the summary — which states the actual facts — is
        also folded in.
        """
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        strong: set[str] = set()
        weak: set[str] = set()

        # English proper-noun tokens: capitalized words / alphanumeric model
        # names. Tokenized word-by-word so a shared anchor ("Google", "I/O")
        # survives even when surrounding clickbait differs across creators.
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]*(?:/[A-Za-z0-9]+)*", text):
            norm = re.sub(r"[^a-z0-9]", "", word.lower())  # "I/O" -> "io"
            if not norm or norm in cls._ENTITY_STOPWORDS:
                continue
            if not word[0].isupper():
                continue
            # >=4 chars -> distinctive proper noun; shorter -> weak.
            (strong if len(norm) >= 4 else weak).add(norm)

        # Numeric tokens (years, versions) are weak on their own — only
        # meaningful glued to a product name, which the regex above already
        # captures (e.g. "Gemini3").
        for num in re.findall(r"\b\d[\d.]*\b", text):
            weak.add(num.replace(".", ""))

        # Chinese product/company terms. Generic ones go to weak.
        for token in re.findall(r"[一-鿿]{3,8}", text):
            (weak if token in cls._CN_STOPWORDS else strong).add(token)

        return strong, weak

    @classmethod
    def _deduplicate(cls, items: list[dict]) -> list[dict]:
        """Collapse items covering the same event via shared named entities.

        Items are pre-sorted by quality_score (desc), so the first item of
        each event cluster is the strongest one and is the one we keep.
        Weaker duplicates are recorded in `merged_from` for optional display.
        """
        result: list[dict] = []
        kept_entities: list[tuple[set[str], set[str]]] = []

        for item in items:
            strong, weak = cls._extract_entities(item)
            dup_of = None
            for kept, (k_strong, k_weak) in zip(result, kept_entities):
                # Same event requires:
                #  - at least one shared STRONG entity (distinctive name), AND
                #  - total overlap (strong + weak) >= 2.
                # The strong requirement blocks "AI" + year false merges;
                # the total>=2 requirement avoids merging on a single
                # incidentally-shared name.
                shared_strong = strong & k_strong
                shared_total = shared_strong | (weak & k_weak)
                if shared_strong and len(shared_total) >= 2:
                    dup_of = kept
                    break
            if dup_of is not None:
                dup_of.setdefault("merged_from", []).append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "channel": item.get("channel", ""),
                })
            else:
                result.append(item)
                kept_entities.append((strong, weak))
        return result

    def _select_top(self, scored: list[dict]) -> list[dict]:
        """Pick top items per domain and per source, respecting max limits."""
        result = []
        domain_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        max_per_source = 2

        for item in scored:
            domain = item.get("domain", "other")
            channel = item.get("channel", "")

            if domain_counts.get(domain, 0) >= self.config.max_items_per_domain:
                continue
            if source_counts.get(channel, 0) >= max_per_source:
                continue
            if len(result) >= self.config.max_total_items:
                break
            result.append(item)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            source_counts[channel] = source_counts.get(channel, 0) + 1

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
