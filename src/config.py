"""
Configuration for VC Info Agent.
System params from .env, info sources from sources.yaml.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv
from source_registry import load_source_pool, merge_active_sources

load_dotenv(Path(__file__).parent.parent / ".env")

_SOURCES_PATH = Path(__file__).parent / "sources.yaml"


def _load_sources() -> dict:
    """Load info source config from sources.yaml, return empty dict if missing."""
    if _SOURCES_PATH.exists():
        try:
            return yaml.safe_load(_SOURCES_PATH.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return {}
    return {}


_source_pool = load_source_pool()
_src = merge_active_sources(_load_sources(), _source_pool)


@dataclass
class Config:
    """Central configuration — API keys from .env, info sources from sources.yaml."""

    # API keys (from .env)
    youtube_api_key: str = os.getenv("YOUTUBE_API_KEY", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    feishu_webhook: str = os.getenv("FEISHU_WEBHOOK", "")

    # System params
    quality_threshold: int = 40
    max_items_per_domain: int = 3
    max_total_items: int = 8
    breaking_threshold: int = 72

    # Info sources (from sources.yaml)
    domains: list[str] = field(
        default_factory=lambda: _src.get("domains", ["AI", "芯片", "机器人"])
    )
    youtube_keywords: dict[str, list[str]] = field(
        default_factory=lambda: _src.get("youtube_keywords", {})
    )
    youtube_channels: dict[str, str] = field(
        default_factory=lambda: _src.get("youtube_channels", {})
    )
    rss_feeds: list[dict] = field(
        default_factory=lambda: _src.get("rss_feeds", [])
    )
    kol_whitelist: list[str] = field(
        default_factory=lambda: _src.get("kol_whitelist", [])
    )
    domain_keywords: dict[str, list[str]] = field(
        default_factory=lambda: _src.get("domain_keywords", {})
    )
    spam_keywords: list[str] = field(
        default_factory=lambda: _src.get("spam_keywords", [])
    )
    major_sources: list[str] = field(
        default_factory=lambda: _src.get(
            "major_sources",
            [
                "OpenAI",
                "Anthropic",
                "Google DeepMind",
                "NVIDIA Newsroom",
                "NVIDIA",
                "Microsoft",
                "Apple",
                "Meta",
                "Y Combinator",
                "a16z",
                "LangChain",
                "Hugging Face",
            ],
        )
    )
    major_keywords: list[str] = field(
        default_factory=lambda: _src.get(
            "major_keywords",
            [
                "launch",
                "release",
                "announces",
                "open source",
                "funding",
                "acquires",
                "partnership",
                "model",
                "API",
                "agent",
                "reasoning",
                "发布",
                "融资",
                "收购",
                "开源",
                "模型",
                "芯片",
                "机器人",
            ],
        )
    )
    noise_channels: list[str] = field(
        default_factory=lambda: _src.get("noise_channels", [])
    )
    source_pool_stats: dict = field(
        default_factory=lambda: _src.get("source_pool_stats", {})
    )
