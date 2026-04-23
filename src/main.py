"""
VC Info Agent — main entry point.
Runs the full pipeline: collect → filter → summarize → deliver.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from config import Config
from collector import YouTubeCollector
from rss_collector import RSSCollector
from filter import ContentFilter
from summarizer import Summarizer
from delivery import FeishuDelivery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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

    total_collected = len(all_items)
    logger.info(f"Total collected: {total_collected} items")

    if not all_items:
        logger.warning("No items collected from any source.")
        sys.exit(0)

    # Step 2: Filter
    logger.info("Step 2/4: Filtering content...")
    content_filter = ContentFilter(config)
    filtered_items = content_filter.filter(all_items)
    logger.info(f"Filtered to {len(filtered_items)} high-quality items")

    if not filtered_items:
        logger.warning("No items passed quality filter. Lowering threshold.")
        config.quality_threshold = 20
        content_filter = ContentFilter(config)
        filtered_items = content_filter.filter(all_items)

    # Step 3: Summarize and generate briefing
    logger.info("Step 3/4: Generating briefing with LLM...")
    summarizer = Summarizer(config)
    try:
        briefing = summarizer.generate_briefing(filtered_items, total_collected)
    finally:
        summarizer.close()

    # Step 4: Output and deliver
    output_dir = Path(__file__).parent.parent / "sample_output"
    output_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"briefing_{date_str}.md"
    output_path.write_text(briefing, encoding="utf-8")
    logger.info(f"Briefing saved to {output_path}")

    # Push to Feishu if configured
    logger.info("Step 4/4: Delivering briefing...")
    delivery = FeishuDelivery(config)
    delivery.send(briefing)

    logger.info("=== VC Info Agent finished ===")
    print(f"\n{'=' * 60}")
    print(f"Briefing generated: {output_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
