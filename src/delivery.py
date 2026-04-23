"""Feishu webhook delivery — push briefing to Feishu group chat."""

import logging
import re

import httpx

from config import Config

logger = logging.getLogger(__name__)


class FeishuDelivery:
    def __init__(self, config: Config):
        self.webhook_url = config.feishu_webhook

    def send(self, briefing_md: str) -> bool:
        """Send briefing to Feishu via webhook. Returns True on success."""
        if not self.webhook_url:
            logger.info("Feishu webhook not configured, skipping push")
            return False

        content = self._md_to_feishu_post(briefing_md)
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": self._extract_title(briefing_md),
                        "content": content,
                    }
                }
            },
        }

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

    @staticmethod
    def _extract_title(md: str) -> str:
        for line in md.split("\n"):
            if line.startswith("# "):
                return line.lstrip("# ").strip()
        return "VC 每日简报"

    @staticmethod
    def _md_to_feishu_post(md: str) -> list[list[dict]]:
        """Convert markdown to Feishu post content (list of paragraphs)."""
        paragraphs = []
        current_para = []

        for line in md.split("\n"):
            line = line.strip()
            if not line:
                if current_para:
                    paragraphs.append(current_para)
                    current_para = []
                continue

            if line.startswith("# "):
                continue

            link_match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", line)
            if link_match:
                text_before = line[:link_match.start()].strip()
                if text_before:
                    current_para.append({"tag": "text", "text": text_before + " "})
                current_para.append({
                    "tag": "a",
                    "text": link_match.group(1),
                    "href": link_match.group(2),
                })
            elif line.startswith("## ") or line.startswith("### "):
                if current_para:
                    paragraphs.append(current_para)
                    current_para = []
                heading = line.lstrip("#").strip()
                current_para.append({"tag": "text", "text": f"【{heading}】\n"})
            elif line.startswith(">"):
                text = line.lstrip("> ").strip()
                current_para.append({"tag": "text", "text": text + "\n"})
            elif line == "---":
                if current_para:
                    paragraphs.append(current_para)
                    current_para = []
                paragraphs.append([{"tag": "text", "text": "─" * 20}])
            else:
                text = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
                current_para.append({"tag": "text", "text": text + "\n"})

        if current_para:
            paragraphs.append(current_para)

        return paragraphs
