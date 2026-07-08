"""
VC Info Agent — main entry point.
Runs the full pipeline: collect → filter → summarize → deliver.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import Config
from collector import YouTubeCollector
from rss_collector import RSSCollector
from twitter_collector import TwitterCollector
from wechat_collector import WechatCollector
from filter import ContentFilter
from feedback import generate_item_id

# Heavy modules (LLM, jinja2, TTS) are imported lazily inside main() so that
# `--dry-run` (collect + dedup only) works without those dependencies.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BRIEFINGS_DIR = Path(__file__).parent.parent / "data" / "briefings"
PIPELINE_DEBUG_DIR = Path(__file__).parent.parent / "data" / "pipeline_debug"
SEEN_DB = Path(__file__).parent.parent / "data" / "seen_articles.json"
# Retain seen IDs for 30 days; collectors use shorter windows (e.g. WeChat 3-day),
# so anything older than 30 days won't appear again anyway.
SEEN_RETENTION_DAYS = 30


def _load_seen(db: Path) -> dict[str, str]:
    if not db.exists():
        return {}
    try:
        return json.loads(db.read_text(encoding="utf-8"))
    except Exception:
        logger.warning(f"Could not parse {db}, starting fresh")
        return {}


def _save_seen(db: Path, seen: dict[str, str]) -> None:
    cutoff = (datetime.now() - timedelta(days=SEEN_RETENTION_DAYS)).date().isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_text(json.dumps(pruned, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    config = Config()
    date_str = datetime.now().strftime("%Y-%m-%d")

    if not config.llm_api_key:
        logger.error("LLM_API_KEY not set. Check your .env file.")
        sys.exit(1)

    logger.info("=== VC Info Agent starting ===")

    # Lazy imports — heavy deps (LLM, jinja2, TTS) not needed for --dry-run.
    from classifier import classify_items
    from summarizer import Summarizer
    from delivery import FeishuDelivery
    from card_image import generate_card_image, generate_cover_image
    from tts import generate_audio
    from wecom_broadcast import write_broadcast_file

    # Step 1: Collect from all sources
    all_items = _collect_sources(config)

    total_collected = len(all_items)
    logger.info(f"Total collected: {total_collected} items")
    _save_pipeline_debug(date_str, "collected", all_items, {
        "total_collected": total_collected,
        "source_pool_stats": config.source_pool_stats,
    })

    if not all_items:
        logger.warning("No items collected from any source.")
        sys.exit(0)

    # Step 1e: Cross-run dedup against previously-delivered article_ids
    seen = _load_seen(SEEN_DB)
    if seen:
        before = len(all_items)
        all_items = [i for i in all_items if i.get("article_id") not in seen]
        skipped = before - len(all_items)
        if skipped:
            logger.info(f"Dedup: skipped {skipped} previously-delivered items ({before} → {len(all_items)})")
        _save_pipeline_debug(date_str, "after_seen_dedup", all_items, {
            "before": before,
            "after": len(all_items),
            "skipped": skipped,
        })

    if not all_items:
        logger.warning("All collected items were already delivered before.")
        sys.exit(0)

    # Step 2: Classify domains using LLM
    logger.info("Step 2/5: Classifying content domains...")
    all_items = classify_items(all_items, config)
    irrelevant_count = sum(1 for i in all_items if i.get("domain") == "irrelevant")
    if irrelevant_count:
        logger.info(f"Marked {irrelevant_count} items as irrelevant")
    _save_pipeline_debug(date_str, "classified", all_items, {
        "irrelevant_count": irrelevant_count,
    })
    all_items = [i for i in all_items if i.get("domain") != "irrelevant"]

    # Step 3: Filter
    logger.info("Step 3/5: Filtering content...")
    from llm_dedup import LLMDeduplicator
    content_filter = ContentFilter(config)
    llm_dedup = LLMDeduplicator(config)
    try:
        filtered_items = content_filter.filter(all_items, llm_dedup=llm_dedup)
    finally:
        llm_dedup.close()
    logger.info(f"Filtered to {len(filtered_items)} high-quality items")
    filter_debug = content_filter.last_debug

    if not filtered_items:
        logger.warning("No items passed quality filter. Lowering threshold.")
        config.quality_threshold = 20
        content_filter = ContentFilter(config)
        llm_dedup = LLMDeduplicator(config)
        try:
            filtered_items = content_filter.filter(all_items, llm_dedup=llm_dedup)
        finally:
            llm_dedup.close()
        filter_debug = content_filter.last_debug

    _save_pipeline_debug(date_str, "scored", filter_debug.get("scored", []), {
        "threshold": config.quality_threshold,
        "above_threshold": len(filter_debug.get("above_threshold", [])),
        "deduped": len(filter_debug.get("deduped", [])),
        "selected": len(filtered_items),
    })
    _save_pipeline_debug(date_str, "rejected", filter_debug.get("rejected", []), {
        "threshold": config.quality_threshold,
    })

    # Assign stable item_id to each selected item
    for item in filtered_items:
        if not item.get("item_id"):
            item["item_id"] = generate_item_id(item)

    # Step 4: Summarize and generate briefing
    logger.info("Step 4/5: Generating briefing with LLM...")
    summarizer = Summarizer(config)
    try:
        briefing_md, briefing_data = summarizer.generate_briefing(
            filtered_items, total_collected
        )
    finally:
        summarizer.close()

    # Step 5: Output
    output_dir = Path(__file__).parent.parent / "sample_output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"briefing_{date_str}.md"
    output_path.write_text(briefing_md, encoding="utf-8")
    logger.info(f"Markdown briefing saved to {output_path}")

    # Save structured JSON briefing
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = BRIEFINGS_DIR / f"briefing_{date_str}.json"
    json_path.write_text(
        json.dumps(briefing_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"JSON briefing saved to {json_path}")

    # Prepare WeCom/WeChat customer-group broadcast copy.
    # This is useful for Group Broadcast Assistant, API-created tasks, or SCRM SOP tools.
    h5_base_for_broadcast = os.getenv("H5_BASE_URL", "https://vcbrief.site").rstrip("/")
    broadcast_path = write_broadcast_file(briefing_data, output_dir, h5_base_url=h5_base_for_broadcast)
    logger.info(f"WeCom broadcast text saved to {broadcast_path}")

    # Save full Markdown to data/briefings/ as well
    md_archive_path = BRIEFINGS_DIR / f"briefing_{date_str}.md"
    md_archive_path.write_text(briefing_md, encoding="utf-8")

    # Append to report log
    _append_report_log(date_str, total_collected, filtered_items, irrelevant_count)

    # Step 6: Generate card image, cover image, and audio
    logger.info("Step 6/7: Generating card image and audio...")
    try:
        card_path = generate_card_image(briefing_data)
        logger.info(f"Card image: {card_path}")
    except Exception as e:
        logger.warning(f"Card image generation failed: {e}")
        card_path = None

    try:
        cover_path = generate_cover_image(briefing_data)
        logger.info(f"Cover image: {cover_path}")
    except Exception as e:
        logger.warning(f"Cover image generation failed: {e}")
        cover_path = None

    try:
        audio_path = generate_audio(briefing_data)
        logger.info(f"Audio: {audio_path}")
    except Exception as e:
        logger.warning(f"Audio generation failed: {e}")
        audio_path = None

    # Step 7: Deliver
    logger.info("Step 7/7: Delivering briefing...")
    delivery = FeishuDelivery(config)
    delivery.send(briefing_md, briefing_data)

    # Build public URLs once — shared by WeChat (wxauto) and WeCom (webhook) paths.
    h5_base = os.getenv("H5_BASE_URL", "").rstrip("/")
    detail_url = f"{h5_base}/briefing/{date_str}" if h5_base else None
    audio_url = f"{h5_base}/audio/briefing_{date_str}.mp3" if (h5_base and audio_path) else None
    cover_url = f"{h5_base}/cards/cover_{date_str}.png" if (h5_base and cover_path) else None

    # Optional: push to WeChat via wxauto (requires Windows GUI + WECHAT_CHAT_NAME).
    # Skipped silently when env var is unset, so Linux/cloud scheduler runs are unaffected.
    wechat_chat = os.getenv("WECHAT_CHAT_NAME", "").strip()
    if wechat_chat and card_path:
        try:
            from wechat_delivery import WechatDelivery
            WechatDelivery(wechat_chat).send(
                card_image_path=card_path,
                audio_url=audio_url,
                detail_url=detail_url,
            )
        except Exception as e:
            logger.warning(f"WeChat delivery skipped: {e}")

    # Optional: push to WeCom (企业微信) group bot — cloud-native, works on VPS.
    # Skipped when WECOM_WEBHOOK_URL is unset.
    wecom_url = os.getenv("WECOM_WEBHOOK_URL", "").strip()
    if wecom_url:
        try:
            from wecom_delivery import WecomDelivery
            WecomDelivery(wecom_url).send(
                date_str=date_str,
                item_count=len(filtered_items),
                detail_url=detail_url,
                audio_url=audio_url,
                card_image_url=cover_url,
                tldr=briefing_data.get("tldr", ""),
            )
        except Exception as e:
            logger.warning(f"WeCom delivery skipped: {e}")

    # Record delivered article_ids so they won't be re-shown in future runs
    today = datetime.now().date().isoformat()
    for item in filtered_items:
        aid = item.get("article_id")
        if aid:
            seen[aid] = today
    _save_seen(SEEN_DB, seen)
    logger.info(f"Updated {SEEN_DB.name}: {len(seen)} entries (kept last {SEEN_RETENTION_DAYS} days)")

    logger.info("=== VC Info Agent finished ===")
    print(f"\n{'=' * 60}")
    print(f"Briefing generated: {output_path}")
    print(f"JSON data: {json_path}")
    print(f"{'=' * 60}")


def _append_report_log(
    date_str: str, total_collected: int, items: list[dict], irrelevant_count: int
):
    """Append one-line metadata to report_log.jsonl."""
    log_path = BRIEFINGS_DIR / "report_log.jsonl"
    domain_counts: dict[str, int] = {}
    sources_hit: set[str] = set()
    for item in items:
        domain_counts[item.get("domain", "other")] = (
            domain_counts.get(item.get("domain", "other"), 0) + 1
        )
        sources_hit.add(item.get("channel", ""))

    entry = {
        "date": date_str,
        "total_collected": total_collected,
        "selected": len(items),
        "irrelevant_filtered": irrelevant_count,
        "domains": domain_counts,
        "sources_hit": sorted(sources_hit),
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _collect_sources(config: Config) -> list[dict]:
    """Collect from every configured source type."""
    all_items = []

    if config.youtube_api_key:
        logger.info("Step 1a: Collecting from YouTube...")
        yt_collector = YouTubeCollector(config)
        yt_items = yt_collector.collect()
        all_items.extend(yt_items)
        logger.info(f"YouTube: {len(yt_items)} items")
    else:
        logger.warning("YOUTUBE_API_KEY not set, skipping YouTube")

    logger.info("Step 1b: Collecting from RSS feeds...")
    rss_collector = RSSCollector(config)
    rss_items = rss_collector.collect()
    all_items.extend(rss_items)

    logger.info("Step 1c: Collecting from Twitter...")
    twitter_collector = TwitterCollector(config)
    twitter_items = twitter_collector.collect()
    all_items.extend(twitter_items)

    logger.info("Step 1d: Collecting from WeChat...")
    wechat_collector = WechatCollector(config)
    wechat_items = wechat_collector.collect()
    all_items.extend(wechat_items)

    return all_items


def _save_pipeline_debug(date_str: str, stage: str, items: list[dict], meta: dict | None = None) -> Path:
    """Persist compact pipeline diagnostics for missed-item investigations."""
    PIPELINE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = PIPELINE_DEBUG_DIR / f"{date_str}_{stage}.json"
    payload = {
        "date": date_str,
        "stage": stage,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": meta or {},
        "count": len(items),
        "items": [_compact_debug_item(item) for item in items],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Pipeline debug saved: {path}")
    return path


def _compact_debug_item(item: dict) -> dict:
    fields = [
        "item_id",
        "article_id",
        "video_id",
        "title",
        "url",
        "source",
        "channel",
        "domain",
        "secondary_domains",
        "source_authority",
        "source_id",
        "source_category",
        "source_priority",
        "quality_score",
        "published_at",
        "rejection_stage",
        "rejection_reason",
    ]
    result = {field: item.get(field) for field in fields if item.get(field) not in (None, "")}
    desc = item.get("description", "")
    if desc:
        result["description"] = desc[:300]
    merged = item.get("merged_from", [])
    if merged:
        result["merged_from"] = merged[:5]
    return result


def dry_run(use_llm: bool = False):
    """Collect + dedup only — no summary, no delivery.

    use_llm=False: pure entity-overlap dedup (free, fast).
    use_llm=True:  entity coarse-cluster + LLM refinement (small DeepSeek
        spend, validates the production path before scheduling a real run).

    Prints each cluster so the kept item and its merged_from duplicates
    can be inspected for false merges (different events lumped together)
    or misses (real dupes left in).
    """
    # Windows consoles default to GBK, which chokes on emoji and some
    # CJK punctuation. Force UTF-8 for the validation report.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    config = Config()
    mode = "LLM-refined" if use_llm else "entity-only"
    logger.info(f"=== VC Info Agent DRY RUN ({mode} dedup) ===")

    all_items = []
    if config.youtube_api_key:
        all_items.extend(YouTubeCollector(config).collect())
    all_items.extend(RSSCollector(config).collect())
    all_items.extend(TwitterCollector(config).collect())
    all_items.extend(WechatCollector(config).collect())
    logger.info(f"Total collected: {len(all_items)} items")

    if not all_items:
        logger.warning("No items collected.")
        return

    # Score (domain may be absent — _score tolerates missing fields).
    content_filter = ContentFilter(config)
    scored = []
    for item in all_items:
        item["quality_score"] = content_filter._score(item)
        scored.append(item)
    scored.sort(key=lambda x: x["quality_score"], reverse=True)

    if use_llm:
        from llm_dedup import LLMDeduplicator
        llm_dedup = LLMDeduplicator(config)
        try:
            deduped = llm_dedup.refine(scored)
        finally:
            llm_dedup.close()
    else:
        deduped = content_filter._deduplicate(scored)

    print(f"\n{'='*70}")
    print(f"DEDUP ({mode}): {len(scored)} items -> {len(deduped)} clusters")
    print(f"{'='*70}")
    for item in deduped:
        merged = item.get("merged_from", [])
        marker = f"  [+{len(merged)} merged]" if merged else ""
        print(f"\n[{item.get('quality_score')}] {item.get('title', '')[:65]}{marker}")
        print(f"    source: {item.get('channel') or item.get('source', '')}")
        for m in merged:
            print(f"    └─ MERGED: {m['title'][:60]}  ({m.get('channel', '')})")
    print(f"\n{'='*70}")
    multi = [i for i in deduped if i.get("merged_from")]
    print(f"{len(multi)} clusters merged duplicates. Review above for false merges.")
    print(f"{'='*70}\n")


def breaking_check(send: bool = True):
    """Check high-authority sources for material updates between daily briefings."""
    config = Config()
    date_str = datetime.now().strftime("%Y-%m-%d")

    if not config.llm_api_key:
        logger.error("LLM_API_KEY not set. Check your .env file.")
        sys.exit(1)

    from classifier import classify_items
    from delivery import FeishuDelivery

    logger.info("=== VC Info Agent breaking check starting ===")
    all_items = _collect_sources(config)
    total_collected = len(all_items)
    _save_pipeline_debug(date_str, "breaking_collected", all_items, {
        "total_collected": total_collected,
        "source_pool_stats": config.source_pool_stats,
    })
    if not all_items:
        logger.warning("No items collected.")
        return

    seen = _load_seen(SEEN_DB)
    if seen:
        all_items = [i for i in all_items if i.get("article_id") not in seen]
    if not all_items:
        logger.info("No unseen items for breaking check.")
        return

    all_items = classify_items(all_items, config)
    all_items = [i for i in all_items if i.get("domain") != "irrelevant"]

    content_filter = ContentFilter(config)
    candidates = []
    for item in all_items:
        item["quality_score"] = content_filter._score(item)
        if _is_breaking_candidate(item, config):
            item["item_id"] = item.get("item_id") or generate_item_id(item)
            item["summary"] = item.get("description", "")[:120]
            item["why_it_matters"] = "重大信号，建议及时关注原文。"
            candidates.append(item)

    candidates.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    candidates = candidates[:5]
    _save_pipeline_debug(date_str, "breaking_candidates", candidates, {
        "threshold": config.breaking_threshold,
        "total_collected": total_collected,
    })

    if not candidates:
        logger.info("No breaking candidates found.")
        return

    briefing_md, briefing_data = _build_breaking_briefing(candidates, total_collected, date_str)
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = BRIEFINGS_DIR / f"breaking_{date_str}.json"
    md_path = BRIEFINGS_DIR / f"breaking_{date_str}.md"
    json_path.write_text(json.dumps(briefing_data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(briefing_md, encoding="utf-8")
    logger.info(f"Breaking briefing saved: {md_path}")

    if send:
        FeishuDelivery(config).send(briefing_md, briefing_data)
        today = datetime.now().date().isoformat()
        for item in candidates:
            aid = item.get("article_id")
            if aid:
                seen[aid] = today
        _save_seen(SEEN_DB, seen)


def _is_breaking_candidate(item: dict, config: Config) -> bool:
    score = item.get("quality_score", 0)
    if score < config.breaking_threshold:
        return False

    text = f"{item.get('title', '')} {item.get('description', '')}".lower()
    has_major_keyword = any(kw.lower() in text for kw in config.major_keywords)
    is_major_source = (
        item.get("channel", "") in config.major_sources
        or item.get("source_category") == "power_center"
        or item.get("source_priority") == "P0"
    )
    return is_major_source and has_major_keyword


def _build_breaking_briefing(items: list[dict], total_collected: int, date_str: str) -> tuple[str, dict]:
    lines = [f"# 🚨 VC 快讯 — {date_str}\n", f"> 本轮采集 {total_collected} 条，命中重大候选 {len(items)} 条\n"]
    for idx, item in enumerate(items, 1):
        lines.append(f"**{idx}. {item.get('title', '')}**")
        lines.append(f"{item.get('source', '')} · {item.get('channel', '')} · score={item.get('quality_score', 0)}")
        if item.get("description"):
            lines.append(item["description"][:180])
        lines.append(f"[🔗 查看原文]({item.get('url', '')})\n")

    data = {
        "briefing_id": f"breaking_{date_str}",
        "date": date_str,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_collected": total_collected,
        "selected_count": len(items),
        "trend_insight": "重大候选快讯，供当日补充关注。",
        "tldr": "\n".join(f"• {item.get('title', '')[:40]}" for item in items),
        "items": [
            {
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
                "article_id": item.get("article_id", ""),
                "description": item.get("description", "")[:500],
            }
            for item in items
        ],
    }
    return "\n".join(lines), data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VC Info Agent")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Collect + entity-only dedup; no LLM, no delivery",
    )
    parser.add_argument(
        "--dry-run-llm", action="store_true",
        help="Collect + entity coarse-cluster + LLM refinement; no delivery",
    )
    parser.add_argument(
        "--breaking-check", action="store_true",
        help="Run a lightweight material-news check between daily briefings",
    )
    parser.add_argument(
        "--no-send", action="store_true",
        help="With --breaking-check, archive candidates without sending to Feishu",
    )
    args = parser.parse_args()
    if args.breaking_check:
        breaking_check(send=not args.no_send)
    elif args.dry_run_llm:
        dry_run(use_llm=True)
    elif args.dry_run:
        dry_run(use_llm=False)
    else:
        main()
