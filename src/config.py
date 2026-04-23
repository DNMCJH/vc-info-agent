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

    # --- YouTube: keyword search ---
    youtube_keywords: dict[str, list[str]] = field(default_factory=lambda: {
        "AI": [
            "AI agent 2026", "artificial intelligence startup",
            "LLM breakthrough", "AI投资",
        ],
        "芯片": [
            "semiconductor 2026", "chip design",
            "NVIDIA GPU", "芯片",
        ],
        "机器人": [
            "humanoid robot 2026", "robotics startup",
            "Figure robot", "人形机器人",
        ],
    })

    # --- YouTube: channel subscription mode ---
    # channel_id -> domain mapping
    youtube_channels: dict[str, str] = field(default_factory=lambda: {
        "UCbmNph6atAoGfqLoCL_duAg": "AI",       # AI Explained
        "UCbfYPyITQ-7l4upoX8nvctg": "AI",       # Two Minute Papers
        "UCsBjURrPoezykLs9EqgamOA": "AI",       # Fireship
        "UCVHFbqXqoYvEWM1Ddxl0QDg": "AI",       # a16z
        "UCcefcZRL2oaA_uBNeo5UOWg": "AI",       # Y Combinator
        "UC-8QAzbLcRglXeN_MY9blyw": "芯片",     # Bloomberg Technology
        "UCXZCJLvIRZ1CCST61YoGemw": "机器人",   # Figure
    })

    # --- RSS feeds ---
    rss_feeds: dict[str, dict] = field(default_factory=lambda: {
        # English sources
        "https://techcrunch.com/feed/": {
            "name": "TechCrunch", "lang": "en", "domains": ["AI", "芯片", "机器人"],
        },
        "https://feeds.arstechnica.com/arstechnica/technology-lab": {
            "name": "Ars Technica", "lang": "en", "domains": ["AI", "芯片"],
        },
        "https://www.technologyreview.com/feed/": {
            "name": "MIT Tech Review", "lang": "en", "domains": ["AI", "芯片", "机器人"],
        },
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml": {
            "name": "The Verge AI", "lang": "en", "domains": ["AI"],
        },
        # Chinese sources
        "https://36kr.com/feed": {
            "name": "36氪", "lang": "zh", "domains": ["AI", "芯片", "机器人"],
        },
        "https://www.jiqizhixin.com/rss": {
            "name": "机器之心", "lang": "zh", "domains": ["AI", "机器人"],
        },
        "https://www.qbitai.com/rss": {
            "name": "量子位", "lang": "zh", "domains": ["AI"],
        },
    })

    quality_threshold: int = 40
    max_items_per_domain: int = 4
    max_total_items: int = 12

    kol_whitelist: list[str] = field(default_factory=lambda: [
        "AI Explained", "Two Minute Papers", "Fireship",
        "Bloomberg Technology", "Figure",
        "Y Combinator", "a16z", "Sequoia Capital",
        "TechCrunch", "MIT Tech Review", "Ars Technica", "The Verge AI",
        "量子位", "机器之心", "36氪",
    ])

    spam_keywords: list[str] = field(default_factory=lambda: [
        "限时优惠", "免费领取", "点击关注", "抽奖",
        "giveaway", "subscribe and win", "use code",
        "affiliate link", "sponsored",
        # Gaming/consumer hardware noise
        "FPS", "benchmark", "gaming setup", "unboxing",
        "graphics card review", "overclock",
    ])

    # Domain keyword list for relevance scoring (shared by filter)
    domain_keywords: dict[str, list[str]] = field(default_factory=lambda: {
        "AI": ["AI", "LLM", "GPT", "agent", "大模型", "人工智能", "机器学习",
               "deep learning", "transformer", "neural", "OpenAI", "Anthropic",
               "DeepSeek", "Claude", "Gemini"],
        "芯片": ["chip", "semiconductor", "GPU", "NVIDIA", "TSMC", "台积电",
                 "芯片", "半导体", "晶圆", "制程", "HBM", "CoWoS", "AMD", "Intel"],
        "机器人": ["robot", "humanoid", "机器人", "人形", "Boston Dynamics",
                  "Figure", "Tesla Optimus", "宇树", "具身智能", "manipulation"],
    })
