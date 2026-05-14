"""Feishu webhook delivery — push briefing as interactive card with feedback buttons."""

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import httpx

from config import Config

logger = logging.getLogger(__name__)

FEEDBACK_BASE = os.getenv("FEEDBACK_BASE_URL", "http://localhost:9002")
_BEIJING = timezone(timedelta(hours=8))


class FeishuDelivery:
    """Pushes briefing to Feishu group chat as interactive card with feedback buttons."""

    def __init__(self, config: Config):
        self.webhook_url = config.feishu_webhook

    def send(self, briefing_md: str, briefing_data: dict | None = None) -> bool:
        """Send briefing to Feishu via interactive card message."""
        if not self.webhook_url:
            logger.info("Feishu webhook not configured, skipping push")
            return False

        card = self._build_card(briefing_md, briefing_data)
        payload = {"msg_type": "interactive", "card": card}

        try:
            resp = httpx.post(self.webhook_url, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") == 0:
                logger.info("Briefing pushed to Feishu successfully")
                return True
            else:
                logger.warning(f"Feishu API error: {result}")
                return False
        except Exception as e:
            logger.warning(f"Feishu push failed: {e}")
            return False

    def _build_card(self, md: str, briefing_data: dict | None = None) -> dict:
        """Build Feishu interactive card from structured briefing data."""
        data = briefing_data or {}
        data_items = data.get("items", [])
        elements = []

        # Header stats
        total = data.get("total_collected", 0)
        selected = data.get("selected_count", 0)
        elements.append({
            "tag": "markdown",
            "content": f"采集 {total} 条，精选 {selected} 条",
        })

        # TL;DR section
        tldr = data.get("tldr", "")
        if tldr:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": f"**⚡ 速览**\n{tldr}",
            })

        # Group items by domain
        domain_items: dict[str, list[dict]] = {}
        for item in data_items:
            domain_items.setdefault(item.get("domain", "other"), []).append(item)

        domain_emoji = {"AI": "🤖", "芯片": "🔬", "机器人": "🦾"}
        domain_color = {"AI": "blue", "芯片": "turquoise", "机器人": "violet"}
        idx = 1

        for domain in ["AI", "芯片", "机器人"]:
            d_items = domain_items.get(domain, [])
            if not d_items:
                continue

            elements.append({"tag": "hr"})
            emoji = domain_emoji.get(domain, "📌")
            elements.append({
                "tag": "markdown",
                "content": f"**{emoji} {domain}（{len(d_items)}）**",
            })

            for item in d_items:
                # Item content block with background color
                source_icon = "📺" if item.get("source") == "YouTube" else "📝"
                channel = item.get("channel", "")
                summary = item.get("summary", "")
                why = item.get("why_it_matters", "")
                url = item.get("url", "")
                link_text = "观看原视频" if item.get("source") == "YouTube" else "阅读原文"

                content_lines = [f"**{idx}. {item.get('title', '')}**"]
                content_lines.append(f"{source_icon} {channel}")
                if summary:
                    content_lines.append(summary)
                if why:
                    content_lines.append(f"💡 {why}")
                if url:
                    content_lines.append(f"[🔗 {link_text}]({url})")

                # Publish time
                pub_at = item.get("published_at", "")
                if pub_at:
                    try:
                        dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                        dt_bj = dt.astimezone(_BEIJING)
                        content_lines.append(f"🕐 {dt_bj.strftime('%Y-%m-%d %H:%M')}")
                    except (ValueError, TypeError):
                        pass

                # Use column_set with background for visual grouping
                color = domain_color.get(domain, "grey")
                elements.append({
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": color,
                    "columns": [{
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [{
                            "tag": "markdown",
                            "content": "\n".join(content_lines),
                        }],
                    }],
                })

                # Feedback buttons
                stable_id = item.get("item_id", str(idx))
                like_url = f"{FEEDBACK_BASE}/feedback?id={stable_id}&r=like"
                dislike_url = f"{FEEDBACK_BASE}/feedback?id={stable_id}&r=dislike"

                elements.append({
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "👍 有用"},
                            "type": "primary",
                            "url": like_url,
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "👎 不想看"},
                            "type": "default",
                            "url": dislike_url,
                        },
                    ],
                })
                idx += 1

        # Trend insight
        trend = data.get("trend_insight", "")
        if trend:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": f"💡 **趋势洞察**\n{trend}",
            })

        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": "📬 点击按钮反馈，帮助系统学习你的偏好"}],
        })

        title = "📋 VC 每日简报"
        date_str = data.get("date", "")
        if date_str:
            title = f"📋 VC 每日简报 — {date_str}"

        return {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": elements,
        }
