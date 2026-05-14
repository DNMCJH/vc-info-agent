"""Summarizer — uses LLM to generate structured summaries and daily briefing."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

from config import Config
from feedback import FeedbackStore, generate_item_id

logger = logging.getLogger(__name__)

ITEM_SUMMARY_PROMPT = """你是一位专业的 VC 行业分析师助手。请为以下内容生成精炼的中文摘要。

严格规则：
- 只能基于下方提供的原文内容进行摘要，严禁添加原文中没有的信息
- 如果原文信息不足，就简短概括已有内容，不要编造细节

用户历史偏好参考：
{preference_context}

要求：
1. 摘要（1-2 句话，不超过 60 字）：核心事实 + 关键数据
2. Why it matters（1 句话，不超过 40 字）：从风险投资视角分析意义

格式要求（严格遵守）：
摘要：<你的摘要>
Why it matters：<投资视角分析>

内容标题：{title}
来源：{channel}
内容描述：{description}
补充内容：{transcript}

请直接按格式输出，不要加其他前缀。"""

BRIEFING_PROMPT = """你是一位专业的 VC 行业分析师。请根据以下今日精选内容，生成一段简短的"趋势洞察"（1-2 句话），
指出今天信息中的共同主题或值得关注的趋势。

今日精选内容：
{items_summary}

请直接输出趋势洞察，不要加前缀。"""

TLDR_PROMPT = """根据以下今日精选标题，生成 3-5 个要点速览。每个要点不超过 20 字，用"• "开头。

标题：
{titles}

直接输出要点列表，不要加前缀或编号。"""

BRIEFINGS_DIR = Path(__file__).parent.parent / "data" / "briefings"


class Summarizer:
    """Generates structured summaries and daily briefings using LLM."""

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(
            base_url=config.llm_base_url,
            headers={"Authorization": f"Bearer {config.llm_api_key}"},
            timeout=60,
        )
        self.feedback = FeedbackStore()

    def summarize_items(self, items: list[dict]) -> list[dict]:
        preference_context = self.feedback.get_preference_context()
        for item in items:
            try:
                raw = self._call_llm(
                    ITEM_SUMMARY_PROMPT.format(
                        preference_context=preference_context,
                        title=item["title"],
                        channel=item.get("channel", ""),
                        description=item.get("description", "")[:1000],
                        transcript=item.get("transcript", "")[:1500],
                    )
                )
                summary, why = self._parse_summary(raw)
                item["summary"] = summary
                item["why_it_matters"] = why
            except Exception as e:
                logger.warning(f"LLM summary failed for '{item['title']}': {e}")
                item["summary"] = item.get("description", "")[:200]
                item["why_it_matters"] = ""
        return items

    @staticmethod
    def _parse_summary(raw: str) -> tuple[str, str]:
        summary, why = raw, ""
        if "Why it matters" in raw:
            parts = raw.split("Why it matters")
            summary = parts[0].replace("摘要：", "").replace("摘要:", "").strip()
            why = parts[1].lstrip("：:").strip()
        elif "摘要：" in raw or "摘要:" in raw:
            summary = raw.replace("摘要：", "").replace("摘要:", "").strip()
        return summary, why

    def generate_trend_insight(self, items: list[dict]) -> str:
        summaries = "\n".join(
            f"- [{item['domain']}] {item['title']}: {item.get('summary', '')}"
            for item in items
        )
        try:
            return self._call_llm(BRIEFING_PROMPT.format(items_summary=summaries))
        except Exception as e:
            logger.warning(f"Trend insight generation failed: {e}")
            return "暂无趋势洞察。"

    def generate_briefing(self, items: list[dict], total_collected: int) -> tuple[str, dict]:
        """Generate Markdown briefing and structured JSON data."""
        items = self.summarize_items(items)
        trend = self.generate_trend_insight(items)
        tldr = self._generate_tldr(items)

        today = datetime.now().strftime("%Y.%m.%d")
        date_str = datetime.now().strftime("%Y-%m-%d")
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
            datetime.now().weekday()
        ]

        lines = [
            f"# 📋 VC 每日简报 — {today}（{weekday}）\n",
            f"> 采集 {total_collected} 条，精选 {len(items)} 条\n",
        ]

        # TL;DR section
        if tldr:
            lines.append("## ⚡ 速览\n")
            lines.append(tldr)
            lines.append("")

        lines.append("---\n")

        domain_items: dict[str, list[dict]] = {}
        for item in items:
            domain_items.setdefault(item["domain"], []).append(item)

        domain_emoji = {"AI": "🤖", "芯片": "🔬", "机器人": "🦾"}
        idx = 1

        for domain in self.config.domains:
            d_items = domain_items.get(domain, [])
            if not d_items:
                continue
            emoji = domain_emoji.get(domain, "📌")
            lines.append(f"## {emoji} {domain}（{len(d_items)}）\n")

            for item in d_items:
                lines.append(f"**{idx}. {item['title']}**")
                lines.append(self._format_source_line(item))
                lines.append(item.get("summary", ""))
                if item.get("why_it_matters"):
                    lines.append(f"💡 {item['why_it_matters']}")
                lines.append(f"[🔗 {self._link_text(item)}]({item['url']})\n")
                idx += 1

            lines.append("---\n")

        filtered_count = len(items)
        lines.append(f"📊 采集 {total_collected} → 精选 {filtered_count}")
        lines.append(f"💡 {trend}\n")
        lines.append("> 📬 点击 👍👎 帮助系统学习偏好")

        briefing_md = "\n".join(lines)

        # Build structured briefing data
        briefing_data = {
            "briefing_id": f"briefing_{date_str}",
            "date": date_str,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_collected": total_collected,
            "selected_count": filtered_count,
            "trend_insight": trend,
            "tldr": tldr,
            "items": [self._item_to_json(item) for item in items],
        }

        return briefing_md, briefing_data

    @staticmethod
    def _item_to_json(item: dict) -> dict:
        return {
            "item_id": item.get("item_id") or generate_item_id(item),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source": item.get("source", ""),
            "channel": item.get("channel", ""),
            "domain": item.get("domain", ""),
            "summary": item.get("summary", ""),
            "why_it_matters": item.get("why_it_matters", ""),
            "quality_score": item.get("quality_score", 0),
            "published_at": item.get("published_at", ""),
            "video_id": item.get("video_id", ""),
            "article_id": item.get("article_id", ""),
            "description": item.get("description", "")[:500],
        }

    def _format_source_line(self, item: dict) -> str:
        source = item.get("source", "")
        channel = item.get("channel", "")
        if source == "YouTube":
            return f"📺 {channel}"
        else:
            return f"📝 {channel}"

    @staticmethod
    def _link_text(item: dict) -> str:
        return "观看原视频" if item.get("source") == "YouTube" else "阅读原文"

    def _generate_tldr(self, items: list[dict]) -> str:
        """Generate TL;DR bullet points from item titles."""
        titles = "\n".join(f"- {item['title']}" for item in items)
        try:
            return self._call_llm(TLDR_PROMPT.format(titles=titles))
        except Exception as e:
            logger.warning(f"TL;DR generation failed: {e}")
            return ""

    def _call_llm(self, prompt: str) -> str:
        resp = self.client.post(
            "/v1/chat/completions",
            json={
                "model": self.config.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 500,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError):
            logger.warning(f"Unexpected LLM response format: {str(data)[:200]}")
            return ""

    @staticmethod
    def _format_duration(iso_duration: str) -> str:
        if not iso_duration:
            return ""
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
        if not match:
            return ""
        h = int(match.group(1) or 0)
        m = int(match.group(2) or 0)
        if h > 0:
            return f"{h}小时{m}分钟"
        return f"{m} 分钟"

    def close(self):
        self.client.close()
