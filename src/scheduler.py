"""
Scheduler — runs the briefing pipeline on a daily cron schedule.
Usage: python scheduler.py
Keeps running 24/7, triggers main pipeline at configured time.
"""

import logging
import subprocess
import sys
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

    # Run once immediately on startup
    run_pipeline()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
