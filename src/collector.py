"""YouTube data collector using YouTube Data API v3."""

import logging
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi

from config import Config

logger = logging.getLogger(__name__)


class YouTubeCollector:
    def __init__(self, config: Config):
        self.config = config
        self.youtube = build("youtube", "v3", developerKey=config.youtube_api_key)

    def collect(self) -> list[dict]:
        """Collect videos from YouTube for all configured domains."""
        all_items = []
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

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

    def _search(self, keyword: str, since: str, domain: str) -> list[dict]:
        resp = self.youtube.search().list(
            q=keyword,
            type="video",
            part="snippet",
            publishedAfter=since,
            maxResults=5,
            order="relevance",
            relevanceLanguage="en",
        ).execute()

        video_ids = [item["id"]["videoId"] for item in resp.get("items", [])]
        if not video_ids:
            return []

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
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "description": snippet.get("description", "")[:2000],
                "published_at": snippet["publishedAt"],
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "duration": video["contentDetails"]["duration"],
                "url": f"https://youtube.com/watch?v={video['id']}",
                "domain": domain,
                "source": "YouTube",
                "transcript": self._get_transcript(video["id"]),
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
