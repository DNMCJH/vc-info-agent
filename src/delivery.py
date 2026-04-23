"""Feishu webhook delivery — push briefing as interactive card with feedback buttons."""

import logging
import os
import re
from urllib.parse import quote

import httpx

from config import Config

logger = logging.getLogger(__name__)

FEEDBACK_BASE = os.getenv("FEEDBACK_BASE_URL", "http://localhost:9002")


class FeishuDelivery:
    """Pushes briefing to Feishu group chat as interactive card with feedback buttons."""

    def __init__(self, config: Config):
        self.webhook_url = config.feishu_webhook

    def send(self, briefing_md: str) -> bool:
        """Send briefing to Feishu via interactive card message."""
        if not self.webhook_url:
            logger.info("Feishu webhook not configured, skipping push")
            return False

        card = self._build_card(briefing_md)
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

    def _build_card(self, md: str) -> dict:
        elements = []
        lines = md.split("\n")
        i = 0
        item_idx = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line or line.startswith("# "):
                i += 1
                continue

            if line == "---":
                elements.append({"tag": "hr"})
                i += 1
                continue

            if line.startswith("> "):
                text = line.lstrip("> ").strip()
                elements.append({
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": text}],
                })
                i += 1
                continue

            if line.startswith("## "):
                heading = line.lstrip("# ").strip()
                elements.append({"tag": "markdown", "content": f"**{heading}**"})
                i += 1
                continue

            if line.startswith("### "):
                title = line.lstrip("# ").strip()
                block_lines = [f"**{title}**"]
                i += 1

                while i < len(lines):
                    next_line = lines[i].strip()
                    if not next_line or next_line.startswith("##") or next_line == "---":
                        break
                    next_line = re.sub(r"\*\*([^*]+)\*\*", r"**\1**", next_line)
                    block_lines.append(next_line)
                    i += 1

                elements.append({
                    "tag": "markdown",
                    "content": "\n".join(block_lines),
                })

                # Add feedback buttons
                item_idx += 1
                clean_title = re.sub(r"^\d+\.\s*", "", title)
                encoded_title = quote(clean_title[:50])
                like_url = f"{FEEDBACK_BASE}/feedback?id={item_idx}&r=like&t={encoded_title}"
                dislike_url = f"{FEEDBACK_BASE}/feedback?id={item_idx}&r=dislike&t={encoded_title}"
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
                continue

            text = re.sub(r"\*\*([^*]+)\*\*", r"**\1**", line)
            elements.append({"tag": "markdown", "content": text})
            i += 1

        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": "📬 点击按钮反馈，帮助系统学习你的偏好"}],
        })

        title = "📋 VC 每日简报"
        for line in lines:
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break

        return {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": elements,
        }
