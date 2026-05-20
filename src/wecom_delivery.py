"""WeCom (企业微信) group bot delivery via webhook — cloud-native, no GUI needed.

Unlike wxauto, this targets WeCom group bots (qyapi.weixin.qq.com/cgi-bin/webhook/send)
and works from any host that can make HTTPS requests, including the VPS.

Two payload modes:
- news: image card linking to the H5 detail page (preferred when H5_BASE_URL is set)
- markdown: text fallback when no public detail URL is available

Reference: https://developer.work.weixin.qq.com/document/path/91770
"""

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class WecomDelivery:
    """Push briefing to a WeCom group via incoming webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(
        self,
        date_str: str,
        item_count: int,
        detail_url: str | None = None,
        audio_url: str | None = None,
        card_image_url: str | None = None,
        tldr: str = "",
    ) -> bool:
        if not self.webhook_url:
            logger.info("WeCom webhook not configured, skipping push")
            return False

        if detail_url and card_image_url:
            payload = self._build_news_payload(
                date_str, item_count, detail_url, card_image_url, audio_url
            )
        else:
            payload = self._build_markdown_payload(
                date_str, item_count, detail_url, audio_url, tldr
            )

        try:
            resp = httpx.post(self.webhook_url, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info(f"WeCom delivery succeeded (mode={payload['msgtype']})")
                return True
            logger.warning(f"WeCom API error: {result}")
            return False
        except Exception as e:
            logger.warning(f"WeCom push failed: {e}")
            return False

    def _build_news_payload(
        self,
        date_str: str,
        item_count: int,
        detail_url: str,
        card_image_url: str,
        audio_url: str | None,
    ) -> dict:
        # News articles render as a clickable image card with title + description.
        # WeCom requires picurl to be a publicly accessible HTTPS image.
        desc_parts = [f"精选 {item_count} 条 · AI / 芯片 / 机器人"]
        if audio_url:
            desc_parts.append("🎧 含音频版")
        return {
            "msgtype": "news",
            "news": {
                "articles": [
                    {
                        "title": f"📋 VC 每日简报 — {date_str}",
                        "description": "  ".join(desc_parts),
                        "url": detail_url,
                        "picurl": card_image_url,
                    }
                ]
            },
        }

    def _build_markdown_payload(
        self,
        date_str: str,
        item_count: int,
        detail_url: str | None,
        audio_url: str | None,
        tldr: str,
    ) -> dict:
        lines = [f"## 📋 VC 每日简报 — {date_str}", f"> 精选 **{item_count}** 条"]
        if tldr:
            tldr_block = "\n".join(f"> {line}" for line in tldr.split("\n") if line.strip())
            lines.append(tldr_block)
        if detail_url:
            lines.append(f"[📖 查看完整日报]({detail_url})")
        if audio_url:
            lines.append(f"[🎧 收听音频版]({audio_url})")
        return {
            "msgtype": "markdown",
            "markdown": {"content": "\n".join(lines)},
        }


if __name__ == "__main__":
    import os
    import sys
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
    url = os.getenv("WECOM_WEBHOOK_URL", "")
    if not url:
        print("Set WECOM_WEBHOOK_URL in .env to test")
        sys.exit(1)

    date_str = sys.argv[1] if len(sys.argv) > 1 else "2026-05-20"
    h5 = os.getenv("H5_BASE_URL", "").rstrip("/")
    detail = f"{h5}/briefing/{date_str}" if h5 else None
    audio = f"{h5}/audio/briefing_{date_str}.mp3" if h5 else None
    card = f"{h5}/cards/briefing_{date_str}.png" if h5 else None

    ok = WecomDelivery(url).send(
        date_str=date_str,
        item_count=8,
        detail_url=detail,
        audio_url=audio,
        card_image_url=card,
        tldr="测试推送",
    )
    print("OK" if ok else "FAILED")
