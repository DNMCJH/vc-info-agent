"""WeChat public account collector — fetches articles via TikHub API."""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

from config import Config

logger = logging.getLogger(__name__)

TIKHUB_API_BASE = "https://api.tikhub.io/api/v1/wechat_mp/web"
TIKHUB_TOKEN = os.getenv("TIKHUB_API_KEY", "")

# TikHub returns "gzid错误" or times out under load even for valid ghids.
# Retry 3 times with exponential backoff before giving up.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.6  # seconds; doubles each attempt
INTER_REQUEST_DELAY = 0.4  # seconds between accounts to avoid rate-limit

# WeChat public accounts: ghid -> (display_name, domain)
WECHAT_ACCOUNTS = {
    "gh_94dba26f8ca0": ("数字生命卡兹克", "AI"),
    "gh_61591937120a": ("暗涌Waves", "AI"),
    "postlate": ("晚点LatePost", "AI"),
    "jazzyear": ("甲子光年", "AI"),
    "icbank": ("半导体行业观察", "芯片"),
    "jiweinet": ("集微网", "芯片"),
    "gaogongrobot": ("高工机器人", "机器人"),
    "geekpark": ("极客公园", "AI"),
    "gh_3e15792d80e2": ("ZoomZoe", "AI"),
    "gh_d56f73c13a02": ("刘小排r", "AI"),
    "gh_9a1919baf888": ("归藏的AI工具箱", "AI"),
}


class WechatCollector:
    """Collects recent articles from WeChat public accounts via TikHub."""

    def __init__(self, config: Config):
        self.config = config
        self.headers = {"Authorization": f"Bearer {TIKHUB_TOKEN}"}

    def collect(self) -> list[dict]:
        if not TIKHUB_TOKEN:
            logger.warning("TIKHUB_API_KEY not set, skipping WeChat")
            return []

        all_items = []
        # 3-day window: most monitored accounts don't publish daily.
        # Upstream dedup (by article_id) is expected to prevent duplicate reporting.
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)

        for i, (ghid, (name, domain)) in enumerate(WECHAT_ACCOUNTS.items()):
            if i > 0:
                time.sleep(INTER_REQUEST_DELAY)
            try:
                items = self._fetch_articles(ghid, name, domain, cutoff)
                all_items.extend(items)
            except Exception as e:
                logger.warning(f"WeChat '{name}' failed: {e}")

        logger.info(f"Collected {len(all_items)} items from WeChat")
        return all_items

    def _call_tikhub(self, ghid: str, name: str) -> dict | list | None:
        """Call TikHub with retries. Returns parsed articles_data on success, None on persistent failure."""
        url = f"{TIKHUB_API_BASE}/fetch_mp_article_list"
        params = {"ghid": ghid}
        last_err: str | None = None

        for attempt in range(RETRY_ATTEMPTS):
            if attempt > 0:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.info(f"WeChat '{name}': retry {attempt + 1}/{RETRY_ATTEMPTS} after {delay:.1f}s ({last_err})")
                time.sleep(delay)
            try:
                resp = httpx.get(url, headers=self.headers, params=params, timeout=20)
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 200 or not data.get("data"):
                    last_err = f"code={data.get('code')} data={str(data.get('data'))[:60]}"
                    continue
                articles_data = data["data"]
                if isinstance(articles_data, str):
                    last_err = articles_data  # "gzid错误" etc.
                    continue
                return articles_data
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                last_err = f"{type(e).__name__}: {e}"
                continue

        logger.warning(f"WeChat '{name}': all {RETRY_ATTEMPTS} attempts failed ({last_err})")
        return None

    def _fetch_articles(
        self, ghid: str, name: str, domain: str, cutoff: datetime
    ) -> list[dict]:
        articles_data = self._call_tikhub(ghid, name)
        if articles_data is None:
            return []

        logger.debug(f"WeChat '{name}' raw keys: {list(articles_data.keys()) if isinstance(articles_data, dict) else type(articles_data)}")

        results = []
        articles = articles_data.get("article_list", articles_data) if isinstance(articles_data, dict) else articles_data

        if isinstance(articles, dict):
            articles = articles.get("list", [])

        if not isinstance(articles, list):
            logger.warning(f"WeChat '{name}': unexpected data format")
            return []

        for article in articles[:10]:
            pub_ts = article.get("send_time") or article.get("create_time", 0)
            if pub_ts:
                pub_time = datetime.fromtimestamp(pub_ts, tz=timezone.utc)
                if pub_time < cutoff:
                    continue
                pub_str = pub_time.isoformat()
            else:
                pub_str = ""

            title = article.get("Title") or article.get("title", "")
            digest = article.get("Digest") or article.get("digest", article.get("abstract", ""))
            link = article.get("ContentUrl") or article.get("content_url") or article.get("link", "")

            if not title:
                continue

            results.append({
                "article_id": link or title,
                "title": title,
                "channel": name,
                "description": digest,
                "published_at": pub_str,
                "url": link,
                "domain": domain,
                "source": "WeChat",
                "source_authority": "high",
                "views": 0,
                "likes": 0,
                "comments": 0,
                "duration": "",
                "transcript": "",
            })

        if results:
            logger.info(f"WeChat '{name}': {len(results)} articles")
        return results
