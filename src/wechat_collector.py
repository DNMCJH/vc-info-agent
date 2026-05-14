"""WeChat public account collector — fetches articles via TikHub API."""

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from config import Config

logger = logging.getLogger(__name__)

TIKHUB_API_BASE = "https://api.tikhub.io/api/v1/wechat_mp/web"
TIKHUB_TOKEN = os.getenv("TIKHUB_API_KEY", "")

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
    "SerendipperShine": ("SerendipperShine", "AI"),
    "liuxiaopai-ai": ("刘小排", "AI"),
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
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)

        for ghid, (name, domain) in WECHAT_ACCOUNTS.items():
            try:
                items = self._fetch_articles(ghid, name, domain, cutoff)
                all_items.extend(items)
            except Exception as e:
                logger.warning(f"WeChat '{name}' failed: {e}")

        logger.info(f"Collected {len(all_items)} items from WeChat")
        return all_items

    def _fetch_articles(
        self, ghid: str, name: str, domain: str, cutoff: datetime
    ) -> list[dict]:
        url = f"{TIKHUB_API_BASE}/fetch_mp_article_list"
        params = {"ghid": ghid}

        resp = httpx.get(url, headers=self.headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 200 or not data.get("data"):
            logger.warning(f"WeChat '{name}': API returned {data.get('data')}")
            return []

        articles_data = data["data"]
        if isinstance(articles_data, str):
            logger.warning(f"WeChat '{name}': {articles_data}")
            return []

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

            title = article.get("title", "")
            digest = article.get("digest", article.get("abstract", ""))
            link = article.get("link", article.get("content_url", ""))

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
