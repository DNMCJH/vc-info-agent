"""Twitter/X collector — fetches recent tweets from KOL accounts via TikHub API.

The official X API v2 plan returned 402 (paid tier required), so collection now
goes through TikHub's Twitter-Web endpoints:
  1. fetch_user_profile?screen_name=<handle>  -> data.rest_id
  2. fetch_user_post_tweet?screen_name=<handle> -> data.timeline[] (+ next_cursor)
Auth is a Bearer token from TIKHUB_API_KEY (.env).
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from config import Config

logger = logging.getLogger(__name__)

TIKHUB_API_BASE = "https://api.tikhub.io/api/v1/twitter/web"
TIKHUB_API_KEY = os.getenv("TIKHUB_API_KEY", "")

# Minimum tweets to gather per account; paginate via next_cursor until reached.
MIN_TWEETS_PER_KOL = 20
MAX_PAGES = 3

# Top AI KOLs: handle -> (display_name, domain)
TWITTER_KOLS = {
    "sama": ("Sam Altman", "AI"),
    "DarioAmodei": ("Dario Amodei", "AI"),
    "ilyasut": ("Ilya Sutskever", "AI"),
    "karpathy": ("Andrej Karpathy", "AI"),
    "DrJimFan": ("Jim Fan", "机器人"),
    "demishassabis": ("Demis Hassabis", "AI"),
    "hwchase17": ("Harrison Chase", "AI"),
    "AravSrinivas": ("Aravind Srinivas", "AI"),
    "alexandr_wang": ("Alexandr Wang", "AI"),
    "AndrewYNg": ("Andrew Ng", "AI"),
    "rowancheung": ("Rowan Cheung", "AI"),
    "lilianweng": ("Lilian Weng", "AI"),
    "LisaSu": ("Lisa Su", "芯片"),
    "elonmusk": ("Elon Musk", "AI"),
    "satyanadella": ("Satya Nadella", "AI"),
}


class TwitterAccessError(RuntimeError):
    """Raised when the TikHub plan cannot read requested resources (402/403)."""


class TwitterCollector:
    """Collects recent tweets from configured KOL accounts via TikHub."""

    def __init__(self, config: Config):
        self.config = config
        self.headers = {"Authorization": f"Bearer {TIKHUB_API_KEY}"}

    def collect(self) -> list[dict]:
        if not TIKHUB_API_KEY:
            logger.warning("TIKHUB_API_KEY not set, skipping Twitter")
            return []

        all_items = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)

        with httpx.Client(
            base_url=TIKHUB_API_BASE,
            headers=self.headers,
            timeout=20,
            follow_redirects=True,
        ) as client:
            for handle, (name, domain) in TWITTER_KOLS.items():
                try:
                    items = self._fetch_user_tweets(client, handle, name, domain, cutoff)
                    all_items.extend(items)
                except TwitterAccessError as e:
                    logger.warning(f"Twitter disabled for this run: {e}")
                    break
                except Exception as e:
                    logger.warning(f"Twitter @{handle} failed: {e}")

        logger.info(f"Collected {len(all_items)} items from Twitter")
        return all_items

    def _fetch_user_tweets(
        self,
        client: httpx.Client,
        handle: str,
        name: str,
        domain: str,
        cutoff: datetime,
    ) -> list[dict]:
        """Page through a user's timeline, keeping only original recent tweets."""
        results = []
        cursor = None
        collected = 0

        for _ in range(MAX_PAGES):
            timeline, cursor = self._fetch_timeline_page(client, handle, cursor)
            if not timeline:
                break

            stop = False
            for tweet in timeline:
                collected += 1
                item = self._build_item(tweet, handle, name, domain, cutoff)
                if item == "too_old":
                    # Timeline is reverse-chronological; older tweets follow.
                    stop = True
                    break
                if item:
                    results.append(item)

            if stop or collected >= MIN_TWEETS_PER_KOL or not cursor:
                break

        if results:
            logger.info(f"Twitter @{handle}: {len(results)} tweets")
        return results

    def _fetch_timeline_page(
        self, client: httpx.Client, handle: str, cursor: str | None
    ) -> tuple[list[dict], str | None]:
        params = {"screen_name": handle, "count": MIN_TWEETS_PER_KOL}
        if cursor:
            params["cursor"] = cursor

        resp = client.get("/fetch_user_post_tweet", params=params)
        if resp.status_code in (402, 403):
            raise TwitterAccessError(
                f"TikHub returned {resp.status_code} (plan/access limit)"
            )
        if resp.status_code == 429:
            logger.warning(f"TikHub rate limited on @{handle}, skipping rest")
            return [], None
        resp.raise_for_status()

        data = resp.json().get("data", {}) or {}
        return data.get("timeline", []) or [], data.get("next_cursor")

    def _build_item(
        self, tweet: dict, handle: str, name: str, domain: str, cutoff: datetime
    ) -> dict | str | None:
        """Convert a raw TikHub tweet into a pipeline item.

        Returns "too_old" to signal the caller to stop paging, None to skip a
        single tweet, or the item dict.
        """
        # Skip retweets — the KOL didn't author these.
        if tweet.get("retweeted") or tweet.get("text", "").startswith("RT @"):
            return None

        pub_time = self._parse_time(tweet.get("created_at", ""))
        if pub_time and pub_time < cutoff:
            return "too_old"

        text = tweet.get("text", "")
        if len(text) < 30:
            return None

        tweet_id = tweet.get("tweet_id", "")
        return {
            "article_id": tweet_id,
            "title": f"@{handle}: {text[:80]}",
            "channel": name,
            "description": text,
            "published_at": pub_time.isoformat() if pub_time else "",
            "url": f"https://x.com/{handle}/status/{tweet_id}",
            "domain": domain,
            "source": "Twitter",
            "source_authority": "high",
            "source_id": f"x_{handle}",
            "source_category": "kol",
            "source_priority": "high",
            "views": self._to_int(tweet.get("views")),
            "likes": self._to_int(tweet.get("favorites")),
            "comments": self._to_int(tweet.get("replies")),
            "duration": "",
            "transcript": "",
        }

    @staticmethod
    def _to_int(value) -> int:
        """TikHub returns views as a string and metrics as ints; normalize."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_time(created_at: str) -> datetime | None:
        """Parse TikHub's 'Sat Jul 04 19:59:34 +0000 2026' timestamp."""
        if not created_at:
            return None
        try:
            return parsedate_to_datetime(created_at)
        except (TypeError, ValueError):
            return None
