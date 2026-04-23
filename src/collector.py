"""YouTube data collector using YouTube Data API v3."""

import logging
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from opencc import OpenCC

from config import Config

_t2s = OpenCC("t2s")
logger = logging.getLogger(__name__)


class YouTubeCollector:
    """Collects videos from YouTube via channel subscriptions and keyword search."""

    def __init__(self, config: Config):
        self.config = config
        self.youtube = build("youtube", "v3", developerKey=config.youtube_api_key)

    def collect(self) -> list[dict]:
        """Collect videos via channel subscriptions + keyword search."""
        all_items = []
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        # Mode 1: Channel subscriptions (low API cost, high precision)
        for channel_id, domain in self.config.youtube_channels.items():
            try:
                items = self._collect_from_channel(channel_id, domain, since)
                all_items.extend(items)
            except Exception as e:
                logger.warning(f"Failed channel {channel_id}: {e}")

        # Mode 2: Keyword search (broader coverage)
        for domain, keywords in self.config.youtube_keywords.items():
            for keyword in keywords:
                try:
                    items = self._search(keyword, since, domain)
                    all_items.extend(items)
                except Exception as e:
                    logger.warning(f"Failed to search '{keyword}': {e}")

        seen_ids = set()
        unique = []
        for item in all_items:
            if item["video_id"] not in seen_ids:
                seen_ids.add(item["video_id"])
                unique.append(item)

        logger.info(f"Collected {len(unique)} unique videos from YouTube")
        return unique

    def _collect_from_channel(self, channel_id: str, domain: str, since: str) -> list[dict]:
        """Fetch recent videos from a specific channel's uploads playlist."""
        ch_resp = self.youtube.channels().list(
            part="contentDetails", id=channel_id,
        ).execute()
        items = ch_resp.get("items", [])
        if not items:
            return []

        uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl_resp = self.youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=5,
        ).execute()

        video_ids = []
        for item in pl_resp.get("items", []):
            pub = item["snippet"].get("publishedAt", "")
            if pub >= since:
                video_ids.append(item["snippet"]["resourceId"]["videoId"])

        if not video_ids:
            return []

        return self._fetch_video_details(video_ids, domain)

    def _search(self, keyword: str, since: str, domain: str) -> list[dict]:
        resp = self.youtube.search().list(
            q=keyword, type="video", part="snippet",
            publishedAfter=since, maxResults=5,
            order="relevance", relevanceLanguage="en",
        ).execute()

        video_ids = [item["id"]["videoId"] for item in resp.get("items", [])]
        if not video_ids:
            return []

        return self._fetch_video_details(video_ids, domain)

    def _fetch_video_details(self, video_ids: list[str], domain: str) -> list[dict]:
        """Fetch full details for a list of video IDs."""
        details = self.youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(video_ids),
        ).execute()

        results = []
        for video in details.get("items", []):
            snippet = video["snippet"]
            stats = video.get("statistics", {})
            results.append({
                "video_id": video["id"],
                "title": _t2s.convert(snippet["title"]),
                "channel": _t2s.convert(snippet["channelTitle"]),
                "description": _t2s.convert(snippet.get("description", "")[:2000]),
                "published_at": snippet["publishedAt"],
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "duration": video["contentDetails"]["duration"],
                "url": f"https://youtube.com/watch?v={video['id']}",
                "domain": domain,
                "source": "YouTube",
                "transcript": _t2s.convert(self._get_transcript(video["id"])),
            })
        return results

    def _get_transcript(self, video_id: str) -> str:
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id, languages=["en", "zh-Hans", "zh"])
            text = " ".join(snippet.text for snippet in transcript.snippets[:200])
            return text[:3000]
        except Exception:
            return ""
