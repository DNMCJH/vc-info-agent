"""
Scheduler — runs the briefing pipeline on a daily cron schedule.
Usage: python scheduler.py
Keeps running 24/7, triggers main pipeline at configured time.
"""

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MAIN_SCRIPT = str(Path(__file__).parent / "main.py")
SRC_DIR = str(Path(__file__).parent)
PYTHON = sys.executable
BRIEFINGS_DIR = Path(__file__).parent.parent / "data" / "briefings"


def _already_ran_today() -> bool:
    """Check if today's briefing JSON already exists (pipeline ran successfully)."""
    today = datetime.now().strftime("%Y-%m-%d")
    return (BRIEFINGS_DIR / f"briefing_{today}.json").exists()


def run_pipeline():
    logger.info("Scheduler triggered — running pipeline...")
    try:
        result = subprocess.run(
            [PYTHON, MAIN_SCRIPT],
            capture_output=True, text=True, timeout=600,
            cwd=SRC_DIR,
        )
        if result.returncode == 0:
            logger.info("Pipeline completed successfully")
        else:
            logger.error(f"Pipeline failed (exit {result.returncode}): {result.stderr[-500:]}")
    except subprocess.TimeoutExpired:
        logger.error("Pipeline timed out after 10 minutes")
    except Exception as e:
        logger.error(f"Pipeline error: {e}")


def main():
    scheduler = BlockingScheduler()

    # Daily at 08:00
    scheduler.add_job(
        run_pipeline,
        CronTrigger(hour=8, minute=0),
        id="daily_briefing",
        name="Daily VC Briefing",
    )

    logger.info("Scheduler started — briefing will run daily at 08:00")
    logger.info("Press Ctrl+C to stop")

    # Run on startup only if today's briefing hasn't been generated yet
    if _already_ran_today():
        logger.info("Today's briefing already exists, skipping startup run")
    else:
        run_pipeline()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
