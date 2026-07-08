"""Runtime adapters for the multi-platform source pool."""

from pathlib import Path

import yaml

SOURCE_POOL_PATH = Path(__file__).parent / "source_pool.yaml"


def load_source_pool() -> list[dict]:
    """Load source_pool.yaml entries."""
    if not SOURCE_POOL_PATH.exists():
        return []
    try:
        data = yaml.safe_load(SOURCE_POOL_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return data.get("source_pool", []) if isinstance(data, dict) else []


def merge_active_sources(base_sources: dict, source_pool: list[dict]) -> dict:
    """Merge active source_pool entries into collector-compatible config.

    RSS entries can be used directly. YouTube entries require channel_id because
    the existing collector works with uploads playlists, not @handles.
    """
    merged = dict(base_sources)
    merged["rss_feeds"] = _merge_rss_feeds(base_sources.get("rss_feeds", []), source_pool)
    merged["youtube_channels"] = _merge_youtube_channels(
        base_sources.get("youtube_channels", {}), source_pool
    )
    merged["source_pool_stats"] = _source_pool_stats(source_pool)
    return merged


def _merge_rss_feeds(base_feeds: list[dict], source_pool: list[dict]) -> list[dict]:
    feeds = [dict(feed) for feed in base_feeds]
    seen_urls = {feed.get("url") for feed in feeds}

    for source in source_pool:
        if source.get("status") != "active":
            continue
        if source.get("access_method") != "rss":
            continue
        if source.get("platform") not in {"rss", "website"}:
            continue

        url = source.get("rss_url") or source.get("url")
        if not url or url in seen_urls:
            continue

        feeds.append(
            {
                "url": url,
                "name": source.get("name", source.get("source_id", url)),
                "lang": source.get("language", "en"),
                "domains": source.get("domains", ["AI"]),
                "authority": _authority_for_priority(source.get("priority")),
                "source_id": source.get("source_id", ""),
                "source_category": source.get("category", ""),
                "source_priority": source.get("priority", ""),
            }
        )
        seen_urls.add(url)

    return feeds


def _merge_youtube_channels(base_channels: dict, source_pool: list[dict]) -> dict:
    channels: dict = dict(base_channels)

    for source in source_pool:
        if source.get("status") != "active" or source.get("platform") != "youtube":
            continue
        channel_id = source.get("channel_id")
        if not channel_id or channel_id in channels:
            continue
        channels[channel_id] = {
            "domain": source.get("domains", ["AI"])[0],
            "source_id": source.get("source_id", ""),
            "source_category": source.get("category", ""),
            "source_priority": source.get("priority", ""),
            "name": source.get("name", ""),
        }

    return channels


def _source_pool_stats(source_pool: list[dict]) -> dict:
    active = [s for s in source_pool if s.get("status") == "active"]
    runnable_youtube = [
        s for s in active if s.get("platform") == "youtube" and s.get("channel_id")
    ]
    blocked_youtube = [
        s.get("source_id", s.get("name", ""))
        for s in active
        if s.get("platform") == "youtube" and not s.get("channel_id")
    ]
    return {
        "active_total": len(active),
        "active_rss": sum(
            1
            for s in active
            if s.get("access_method") == "rss" and s.get("platform") in {"rss", "website"}
        ),
        "active_youtube_runnable": len(runnable_youtube),
        "active_youtube_missing_channel_id": blocked_youtube,
    }


def _authority_for_priority(priority: str | None) -> str:
    return {"P0": "high", "P1": "medium", "P2": "low"}.get(priority or "", "medium")
