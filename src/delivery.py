"""Feishu webhook delivery — push briefing as interactive card."""

import logging
import re

import httpx

from config import Config

logger = logging.getLogger(__name__)


class FeishuDelivery:
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
                text = re.sub(r"\*\*([^*]+)\*\*", r"**\1**", text)
                elements.append({
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": text}],
                })
                i += 1
                continue

            if line.startswith("## "):
                heading = line.lstrip("# ").strip()
                elements.append({
                    "tag": "markdown",
                    "content": f"**{heading}**",
                })
                i += 1
                continue

            if line.startswith("### "):
                # Collect the full item block: title + source + summary + why + link
                title = line.lstrip("# ").strip()
                block_lines = [f"**{title}**"]
                i += 1

                while i < len(lines):
                    next_line = lines[i].strip()
                    if not next_line or next_line.startswith("##") or next_line == "---":
                        break
                    # Convert markdown links
                    next_line = re.sub(r"\*\*([^*]+)\*\*", r"**\1**", next_line)
                    block_lines.append(next_line)
                    i += 1

                elements.append({
                    "tag": "markdown",
                    "content": "\n".join(block_lines),
                })
                continue

            # Stats / trend / other lines
            text = re.sub(r"\*\*([^*]+)\*\*", r"**\1**", line)
            elements.append({"tag": "markdown", "content": text})
            i += 1

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
