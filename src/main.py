"""
VC Info Agent — main entry point.
Runs the full pipeline: collect → filter → summarize → deliver.
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import Config
from collector import YouTubeCollector
from rss_collector import RSSCollector
from twitter_collector import TwitterCollector
from wechat_collector import WechatCollector
from classifier import classify_items
from filter import ContentFilter
from summarizer import Summarizer
from delivery import FeishuDelivery
from feedback import generate_item_id
from card_image import generate_card_image
from tts import generate_audio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BRIEFINGS_DIR = Path(__file__).parent.parent / "data" / "briefings"
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

    if not config.llm_api_key:
        logger.error("LLM_API_KEY not set. Check your .env file.")
        sys.exit(1)

    logger.info("=== VC Info Agent starting ===")

    # Step 1: Collect from all sources
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

    total_collected = len(all_items)
    logger.info(f"Total collected: {total_collected} items")

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

    if not all_items:
        logger.warning("All collected items were already delivered before.")
        sys.exit(0)

    # Step 2: Classify domains using LLM
    logger.info("Step 2/5: Classifying content domains...")
    all_items = classify_items(all_items, config)
    irrelevant_count = sum(1 for i in all_items if i.get("domain") == "irrelevant")
    if irrelevant_count:
        logger.info(f"Marked {irrelevant_count} items as irrelevant")
    all_items = [i for i in all_items if i.get("domain") != "irrelevant"]

    # Step 3: Filter
    logger.info("Step 3/5: Filtering content...")
    content_filter = ContentFilter(config)
    filtered_items = content_filter.filter(all_items)
    logger.info(f"Filtered to {len(filtered_items)} high-quality items")

    if not filtered_items:
        logger.warning("No items passed quality filter. Lowering threshold.")
        config.quality_threshold = 20
        content_filter = ContentFilter(config)
        filtered_items = content_filter.filter(all_items)

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
    date_str = datetime.now().strftime("%Y-%m-%d")
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

    # Save full Markdown to data/briefings/ as well
    md_archive_path = BRIEFINGS_DIR / f"briefing_{date_str}.md"
    md_archive_path.write_text(briefing_md, encoding="utf-8")

    # Append to report log
    _append_report_log(date_str, total_collected, filtered_items, irrelevant_count)

    # Step 6: Generate card image and audio
    logger.info("Step 6/7: Generating card image and audio...")
    try:
        card_path = generate_card_image(briefing_data)
        logger.info(f"Card image: {card_path}")
    except Exception as e:
        logger.warning(f"Card image generation failed: {e}")
        card_path = None

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


if __name__ == "__main__":
    main()
