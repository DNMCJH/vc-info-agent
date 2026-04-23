"""
Configuration for VC Info Agent.
Copy .env.example to .env and fill in your API keys.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    youtube_api_key: str = os.getenv("YOUTUBE_API_KEY", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    feishu_webhook: str = os.getenv("FEISHU_WEBHOOK", "")

    domains: list[str] = field(default_factory=lambda: ["AI", "芯片", "机器人"])

    youtube_keywords: dict[str, list[str]] = field(default_factory=lambda: {
        "AI": [
            "AI agent 2026", "artificial intelligence startup",
            "LLM breakthrough", "AI投资", "大模型"
        ],
        "芯片": [
            "semiconductor 2026", "chip design",
            "NVIDIA GPU", "芯片", "半导体"
        ],
        "机器人": [
            "humanoid robot 2026", "robotics startup",
            "Figure robot", "人形机器人"
        ],
    })

    quality_threshold: int = 40
    max_items_per_domain: int = 4
    max_total_items: int = 12

    # KOL whitelist — channels/authors that get a credibility boost
    kol_whitelist: list[str] = field(default_factory=lambda: [
        "AI Explained", "Two Minute Papers", "Fireship",
        "Linus Tech Tips", "Bloomberg Technology",
        "Y Combinator", "a]6z", "Sequoia Capital",
        "量子位", "机器之心", "36氪",
    ])

    # Spam keywords that trigger ad/promo detection
    spam_keywords: list[str] = field(default_factory=lambda: [
        "限时优惠", "免费领取", "点击关注", "抽奖",
        "giveaway", "subscribe and win", "use code",
        "affiliate link", "sponsored",
    ])
