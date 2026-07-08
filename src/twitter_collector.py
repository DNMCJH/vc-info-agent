"""Twitter/X collector — fetches recent tweets from KOL accounts via API v2."""

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from config import Config

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"
BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

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
    """Raised when the configured X API plan cannot read requested resources."""


class TwitterCollector:
    """Collects recent tweets from configured KOL accounts."""

    def __init__(self, config: Config):
        self.config = config
        self.headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}

    def collect(self) -> list[dict]:
        if not BEARER_TOKEN:
            logger.warning("TWITTER_BEARER_TOKEN not set, skipping Twitter")
            return []

        all_items = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)

        for handle, (name, domain) in TWITTER_KOLS.items():
            try:
                items = self._fetch_user_tweets(handle, name, domain, cutoff)
                all_items.extend(items)
            except TwitterAccessError as e:
                logger.warning(f"Twitter disabled for this run: {e}")
                break
            except Exception as e:
                logger.warning(f"Twitter @{handle} failed: {e}")

        logger.info(f"Collected {len(all_items)} items from Twitter")
        return all_items

    def _fetch_user_tweets(
        self, handle: str, name: str, domain: str, cutoff: datetime
    ) -> list[dict]:
        user_id = self._get_user_id(handle)
        if not user_id:
            return []

        url = f"{TWITTER_API_BASE}/users/{user_id}/tweets"
        params = {
            "max_results": 10,
            "start_time": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tweet.fields": "created_at,public_metrics,text",
            "exclude": "retweets,replies",
        }

        resp = httpx.get(url, headers=self.headers, params=params, timeout=15)
        if resp.status_code == 429:
            logger.warning(f"Twitter rate limited on @{handle}, skipping rest")
            return []
        resp.raise_for_status()

        data = resp.json().get("data", [])
        results = []
        for tweet in data:
            text = tweet.get("text", "")
            if len(text) < 30:
                continue

            metrics = tweet.get("public_metrics", {})
            results.append({
                "article_id": tweet["id"],
                "title": f"@{handle}: {text[:80]}",
                "channel": name,
                "description": text,
                "published_at": tweet.get("created_at", ""),
                "url": f"https://x.com/{handle}/status/{tweet['id']}",
                "domain": domain,
                "source": "Twitter",
                "source_authority": "high",
                "views": metrics.get("impression_count", 0),
                "likes": metrics.get("like_count", 0),
                "comments": metrics.get("reply_count", 0),
                "duration": "",
                "transcript": "",
            })

        if results:
            logger.info(f"Twitter @{handle}: {len(results)} tweets")
        return results

    def _get_user_id(self, handle: str) -> str | None:
        url = f"{TWITTER_API_BASE}/users/by/username/{handle}"
        resp = httpx.get(url, headers=self.headers, timeout=10)
        if resp.status_code == 402:
            raise TwitterAccessError("X API returned 402 Payment Required")
        if resp.status_code != 200:
            logger.warning(f"Cannot resolve @{handle}: {resp.status_code}")
            return None
        return resp.json().get("data", {}).get("id")
