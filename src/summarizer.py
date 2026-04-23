"""Summarizer — uses LLM to generate structured summaries and daily briefing."""

import json
import logging
from datetime import datetime

import httpx

from config import Config

logger = logging.getLogger(__name__)

ITEM_SUMMARY_PROMPT = """你是一位专业的 VC 行业分析师助手。请为以下内容生成简洁的中文摘要。

要求：
- 2-3 句话，第一句是核心事实，第二句是关键数据或引用，第三句是影响分析
- 语言精炼，适合投资人快速阅读
- 保留关键数字和人名

内容标题：{title}
来源频道：{channel}
视频描述：{description}
字幕摘录：{transcript}

请直接输出摘要，不要加任何前缀。"""

BRIEFING_PROMPT = """你是一位专业的 VC 行业分析师。请根据以下今日精选内容，生成一段简短的"趋势洞察"（2-3 句话），
指出今天信息中的共同主题或值得关注的趋势。

今日精选内容：
{items_summary}

请直接输出趋势洞察，不要加前缀。"""


class Summarizer:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(
            base_url=config.llm_base_url,
            headers={"Authorization": f"Bearer {config.llm_api_key}"},
            timeout=60,
        )

    def summarize_items(self, items: list[dict]) -> list[dict]:
        for item in items:
            try:
                item["summary"] = self._call_llm(
                    ITEM_SUMMARY_PROMPT.format(
                        title=item["title"],
                        channel=item.get("channel", ""),
                        description=item.get("description", "")[:1000],
                        transcript=item.get("transcript", "")[:1500],
                    )
                )
            except Exception as e:
                logger.warning(f"LLM summary failed for '{item['title']}': {e}")
                item["summary"] = item.get("description", "")[:200]
        return items

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

    def generate_briefing(self, items: list[dict], total_collected: int) -> str:
        items = self.summarize_items(items)
        trend = self.generate_trend_insight(items)

        today = datetime.now().strftime("%Y.%m.%d")
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
            datetime.now().weekday()
        ]

        lines = [
            f"# 📋 VC 每日简报 — {today}（{weekday}）\n",
            f"> 今日共采集 {total_collected} 条内容，精选 {len(items)} 条高质量信息。\n",
            "---\n",
        ]

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
            lines.append(f"## {emoji} {domain}领域（{len(d_items)} 条）\n")

            for item in d_items:
                minutes = self._format_duration(item.get("duration", "PT0S"))
                lines.append(f"### {idx}. {item['title']}")
                lines.append(f"📺 YouTube · {item['channel']} · {minutes}")
                lines.append(item.get("summary", ""))
                lines.append(f"🔗 [观看原视频]({item['url']})\n")
                idx += 1

            lines.append("---\n")

        filtered_count = len(items)
        rate = (
            f"{filtered_count / total_collected * 100:.1f}"
            if total_collected > 0
            else "0"
        )
        lines.append(
            f"📊 **今日数据**：采集 {total_collected} 条 → 精选 {filtered_count} 条（入选率 {rate}%）"
        )
        lines.append(f"💡 **趋势洞察**：{trend}\n")
        lines.append("---")
        lines.append("> 📬 反馈：点击每条旁的 👍👎 帮助我学习你的偏好")
        lines.append("> 🕐 下期简报将于明日 08:00 推送")

        return "\n".join(lines)

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
        return resp.json()["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _format_duration(iso_duration: str) -> str:
        import re

        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
        if not match:
            return "未知时长"
        h = int(match.group(1) or 0)
        m = int(match.group(2) or 0)
        if h > 0:
            return f"{h}小时{m}分钟"
        return f"{m} 分钟"

    def close(self):
        self.client.close()
