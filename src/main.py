"""
VC Info Agent — main entry point.
Runs the full pipeline: collect → filter → summarize → output briefing.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from config import Config
from collector import YouTubeCollector
from filter import ContentFilter
from summarizer import Summarizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    config = Config()

    if not config.youtube_api_key:
        logger.error("YOUTUBE_API_KEY not set. Check your .env file.")
        sys.exit(1)
    if not config.llm_api_key:
        logger.error("LLM_API_KEY not set. Check your .env file.")
        sys.exit(1)

    logger.info("=== VC Info Agent starting ===")

    # Step 1: Collect
    logger.info("Step 1/3: Collecting from YouTube...")
    collector = YouTubeCollector(config)
    raw_items = collector.collect()
    total_collected = len(raw_items)
    logger.info(f"Collected {total_collected} items")

    if not raw_items:
        logger.warning("No items collected. Check API key and network.")
        sys.exit(0)

    # Step 2: Filter
    logger.info("Step 2/3: Filtering content...")
    content_filter = ContentFilter(config)
    filtered_items = content_filter.filter(raw_items)
    logger.info(f"Filtered to {len(filtered_items)} high-quality items")

    if not filtered_items:
        logger.warning("No items passed quality filter. Lowering threshold.")
        config.quality_threshold = 20
        content_filter = ContentFilter(config)
        filtered_items = content_filter.filter(raw_items)

    # Step 3: Summarize and generate briefing
    logger.info("Step 3/3: Generating briefing with LLM...")
    summarizer = Summarizer(config)
    try:
        briefing = summarizer.generate_briefing(filtered_items, total_collected)
    finally:
        summarizer.close()

    # Output
    output_dir = Path(__file__).parent.parent / "sample_output"
    output_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"briefing_{date_str}.md"
    output_path.write_text(briefing, encoding="utf-8")

    logger.info(f"Briefing saved to {output_path}")
    logger.info("=== VC Info Agent finished ===")

    print("\n" + "=" * 60)
    print(f"Briefing generated: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
