"""Generate briefing card image from structured JSON data."""

import json
import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "cards"

DOMAIN_EMOJI = {"AI": "🤖", "芯片": "🔬", "机器人": "🦾"}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def generate_card_image(briefing_data: dict, output_path: Path | None = None) -> Path:
    """Render briefing data to HTML then screenshot as PNG."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    date_str = briefing_data.get("date", datetime.now().strftime("%Y-%m-%d"))
    if output_path is None:
        output_path = OUTPUT_DIR / f"card_{date_str}.png"

    html = _render_html(briefing_data)
    _screenshot(html, output_path)
    logger.info(f"Card image saved to {output_path}")
    return output_path


def _render_html(data: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("card.html")

    date_str = data.get("date", "")
    weekday = ""
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            weekday = WEEKDAYS[dt.weekday()]
        except ValueError:
            pass

    tldr = data.get("tldr", "")
    tldr_lines = [line.strip() for line in tldr.split("\n") if line.strip()] if tldr else []

    # Group items by domain, preserving order
    grouped = {}
    for item in data.get("items", []):
        domain = item.get("domain", "other")
        grouped.setdefault(domain, []).append(item)

    domain_order = ["AI", "芯片", "机器人"]
    grouped_items = [(d, grouped[d]) for d in domain_order if d in grouped]
    for d, items in grouped.items():
        if d not in domain_order:
            grouped_items.append((d, items))

    return template.render(
        date_display=date_str,
        weekday=weekday,
        item_count=data.get("selected_count", len(data.get("items", []))),
        total_collected=data.get("total_collected", 0),
        tldr=tldr,
        tldr_lines=tldr_lines,
        grouped_items=grouped_items,
        domain_emoji=DOMAIN_EMOJI,
        trend_insight=data.get("trend_insight", ""),
    )


def _screenshot(html: str, output_path: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 420, "height": 800})
        page.set_content(html, wait_until="networkidle")
        page.wait_for_timeout(300)
        # Auto-height: screenshot full page
        page.screenshot(path=str(output_path), full_page=True)
        browser.close()


# CLI entry point for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python card_image.py <briefing.json>")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    out = generate_card_image(data)
    print(f"Generated: {out}")
