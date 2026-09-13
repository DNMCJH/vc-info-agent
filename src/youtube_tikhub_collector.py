"""YouTube collector backed by TikHub instead of YouTube Data API v3.

The official API key expired and renewing it needs a Google Cloud project with
billing attached. TikHub is already used for Twitter here, so reusing that key
avoids introducing another credential.

Two-step fetch mirrors the old v3 flow:
  1. get_channel_videos / get_general_search -> candidate video IDs
  2. get_video_info -> absolute publish_date, description, engagement counts

Step 1 only reports relative times ("2天前"), too coarse for a daily window,
so recency is decided from the ISO publish_date returned by step 2. Emitted
items keep exactly the field names the old collector produced.
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from opencc import OpenCC
from youtube_transcript_api import YouTubeTranscriptApi

from config import Config

_t2s = OpenCC("t2s")
logger = logging.getLogger(__name__)

TIKHUB_BASE = "https://api.tikhub.io/api/v1/youtube"
TIKHUB_API_KEY = os.getenv("TIKHUB_API_KEY", "")

# Step 1 returns 30 videos per channel; only the newest few can be inside a
# 1-day window, so detail lookups are capped to keep request counts sane.
MAX_DETAIL_PER_CHANNEL = 5
MAX_DETAIL_PER_KEYWORD = 5
REQUEST_TIMEOUT = 30

# "2天前" / "3 weeks ago" -> timedelta, used to pre-filter before paying for a
# detail call on a video that is obviously months old.
_REL_UNITS = {
    "分钟": "minutes", "小时": "hours", "天": "days",
    "周": "weeks", "个月": "months", "年": "years",
    "minute": "minutes", "hour": "hours", "day": "days",
    "week": "weeks", "month": "months", "year": "years",
}


def _relative_age_days(text: str) -> float | None:
    """Approximate age in days from a relative time string, None if unparsable."""
    if not text:
        return None
    match = re.search(r"(\d+)\s*(个月|分钟|小时|天|周|年|minute|hour|day|week|month|year)", text)
    if not match:
        return None
    value = int(match.group(1))
    unit = _REL_UNITS.get(match.group(2))
    per_day = {
        "minutes": 1 / 1440, "hours": 1 / 24, "days": 1,
        "weeks": 7, "months": 30, "years": 365,
    }
    return value * per_day.get(unit, 1)


def _to_int(value) -> int:
    """TikHub returns counts as ints or as text like '34万次观看'."""
    if isinstance(value, int):
        return value
    if not value:
        return 0
    text = str(value).replace(",", "")
    match = re.search(r"([\d.]+)\s*(万|亿|K|M|B)?", text, re.IGNORECASE)
    if not match:
        return 0
    try:
        number = float(match.group(1))
    except ValueError:
        return 0
    scale = {"万": 1e4, "亿": 1e8, "k": 1e3, "m": 1e6, "b": 1e9}
    suffix = (match.group(2) or "").lower()
    return int(number * scale.get(suffix, 1))


class YouTubeTikHubCollector:
    """Drop-in replacement for YouTubeCollector using TikHub endpoints."""

    def __init__(self, config: Config, window_days: int = 1):
        self.config = config
        self.window_days = window_days
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {TIKHUB_API_KEY}",
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict) -> dict | None:
        """One GET with a single retry; returns the `data` payload or None."""
        url = f"{TIKHUB_BASE}{path}"
        for attempt in (1, 2):
            try:
                response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                if response.status_code == 429:
                    time.sleep(2 * attempt)
                    continue
                if response.status_code >= 400:
                    logger.warning(
                        "TikHub %s -> HTTP %s: %s",
                        path, response.status_code, response.text[:160],
                    )
                    return None
                payload = response.json()
                if payload.get("code") not in (0, 200, None):
                    logger.warning("TikHub %s -> code %s", path, payload.get("code"))
                    return None
                return payload.get("data") or {}
            except (requests.RequestException, ValueError) as exc:
                logger.warning("TikHub %s attempt %d failed: %s", path, attempt, exc)
                time.sleep(1)
        return None

    def collect(self) -> list[dict]:
        """Collect recent videos from configured channels and keywords."""
        if not TIKHUB_API_KEY:
            logger.warning("TIKHUB_API_KEY not set, skipping YouTube")
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.window_days)
        all_items: list[dict] = []

        for channel_id, channel_cfg in self.config.youtube_channels.items():
            try:
                domain, source_meta = self._channel_runtime_config(channel_id, channel_cfg)
                all_items.extend(
                    self._collect_from_channel(channel_id, domain, cutoff, source_meta)
                )
            except Exception as exc:
                logger.warning("Failed channel %s: %s", channel_id, exc)

        for domain, keywords in self.config.youtube_keywords.items():
            for keyword in keywords:
                try:
                    all_items.extend(self._search(keyword, domain, cutoff))
                except Exception as exc:
                    logger.warning("Failed to search '%s': %s", keyword, exc)

        seen: set[str] = set()
        unique = []
        for item in all_items:
            if item["video_id"] not in seen:
                seen.add(item["video_id"])
                unique.append(item)

        logger.info("Collected %d unique videos from YouTube (TikHub)", len(unique))
        return unique

    def _candidate_ids(self, videos: list[dict], limit: int) -> list[str]:
        """Newest-first video IDs, dropping ones clearly outside the window."""
        # Allow 1 extra day of slack: "2天前" is rounded, and a video published
        # 25 hours ago may still belong in today's briefing.
        max_age = self.window_days + 1
        ids = []
        for video in videos:
            if video.get("is_live"):
                continue
            video_id = video.get("video_id") or ""
            if not video_id:
                continue
            age = _relative_age_days(video.get("published_time", ""))
            if age is not None and age > max_age:
                continue
            ids.append(video_id)
            if len(ids) >= limit:
                break
        return ids

    def _collect_from_channel(
        self, channel_id: str, domain: str, cutoff: datetime, source_meta: dict | None = None
    ) -> list[dict]:
        data = self._get("/web_v2/get_channel_videos", {"channel_id": channel_id})
        if not data:
            return []
        channel_name = (data.get("channel") or {}).get("name", "")
        video_ids = self._candidate_ids(data.get("videos") or [], MAX_DETAIL_PER_CHANNEL)
        return self._fetch_video_details(
            video_ids, domain, cutoff, source_meta, channel_name
        )

    def _search(self, keyword: str, domain: str, cutoff: datetime) -> list[dict]:
        # This endpoint rejects every upload_time value we tried (HTTP 400),
        # so results come back unfiltered and recency is enforced locally.
        data = self._get("/web_v2/get_general_search", {"search_query": keyword})
        if not data:
            return []
        videos = self._extract_search_videos(data)
        video_ids = self._candidate_ids(videos, MAX_DETAIL_PER_KEYWORD)
        return self._fetch_video_details(video_ids, domain, cutoff)

    @staticmethod
    def _extract_search_videos(data: dict) -> list[dict]:
        """Pull videoRenderer nodes out of YouTube's raw InnerTube payload.

        Search returns the untransformed response (unlike get_channel_videos),
        so walk it and normalise each hit to the same shape _candidate_ids
        expects.
        """
        results: list[dict] = []

        def walk(node):
            if isinstance(node, dict):
                renderer = node.get("videoRenderer")
                if isinstance(renderer, dict) and renderer.get("videoId"):
                    published = (renderer.get("publishedTimeText") or {}).get("simpleText", "")
                    results.append({
                        "video_id": renderer["videoId"],
                        "published_time": published,
                        "is_live": bool(renderer.get("badges") and any(
                            "LIVE" in str(b).upper() for b in renderer["badges"]
                        )),
                    })
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(data)
        return results

    def _fetch_video_details(
        self,
        video_ids: list[str],
        domain: str,
        cutoff: datetime,
        source_meta: dict | None = None,
        channel_name: str = "",
    ) -> list[dict]:
        """Resolve each ID to a full item, keeping only ones inside the window."""
        results = []
        for video_id in video_ids:
            data = self._get("/web_v2/get_video_info", {"video_id": video_id})
            if not data:
                continue

            published_at = data.get("publish_date") or data.get("upload_date") or ""
            published_dt = self._parse_iso(published_at)
            if published_dt is None:
                # Detail lookups occasionally come back without publish_date or
                # author. Without a trustworthy timestamp the item could be
                # months old, so drop it rather than pollute the daily window.
                logger.warning(
                    "Skipping %s: no usable publish_date in detail response", video_id
                )
                continue
            if published_dt < cutoff:
                continue

            title = data.get("title") or ""
            # Fall back to the channel name from step 1 when the detail payload
            # omits author, so downstream output never shows a blank source.
            channel = data.get("author") or channel_name or ""
            description = (data.get("description") or "")[:2000]

            item = {
                "video_id": video_id,
                "title": _t2s.convert(title),
                "channel": _t2s.convert(channel),
                "description": _t2s.convert(description),
                "published_at": published_at,
                "views": _to_int(data.get("view_count") or data.get("view_count_text")),
                "likes": _to_int(data.get("like_count") or data.get("like_count_text")),
                "comments": _to_int(data.get("comment_count")),
                "duration": self._duration(data.get("length_seconds")),
                "url": f"https://youtube.com/watch?v={video_id}",
                "domain": domain,
                "source": "YouTube",
                "transcript": _t2s.convert(self._get_transcript(video_id)),
            }
            if source_meta:
                item.update(source_meta)
            results.append(item)
        return results

    @staticmethod
    def _parse_iso(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _duration(length_seconds) -> str:
        """Emit ISO-8601 duration to match the old collector's field format."""
        try:
            total = int(length_seconds)
        except (TypeError, ValueError):
            return ""
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        out = "PT"
        if hours:
            out += f"{hours}H"
        if minutes:
            out += f"{minutes}M"
        if seconds or out == "PT":
            out += f"{seconds}S"
        return out

    @staticmethod
    def _channel_runtime_config(channel_id: str, channel_cfg) -> tuple[str, dict]:
        if isinstance(channel_cfg, dict):
            return channel_cfg.get("domain", "AI"), {
                "source_id": channel_cfg.get("source_id", ""),
                "source_category": channel_cfg.get("source_category", ""),
                "source_priority": channel_cfg.get("source_priority", ""),
                "source_pool_name": channel_cfg.get("name", ""),
            }
        return channel_cfg, {"source_id": channel_id}

    def _get_transcript(self, video_id: str) -> str:
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id, languages=["en", "zh-Hans", "zh"])
            return " ".join(s.text for s in transcript.snippets[:200])[:3000]
        except Exception:
            return ""
