"""User feedback system — stores preferences and adjusts filter weights."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
FEEDBACK_FILE = DATA_DIR / "feedback.json"


class FeedbackStore:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        if FEEDBACK_FILE.exists():
            return json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        return {"items": {}, "preferences": {"sources": {}, "keywords": {}, "domains": {}}}

    def _save(self):
        FEEDBACK_FILE.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def record(self, item_id: str, reaction: str, item_meta: dict):
        """Record a like/dislike reaction for an item."""
        self.data["items"][item_id] = {
            "reaction": reaction,
            "title": item_meta.get("title", ""),
            "source": item_meta.get("channel", ""),
            "domain": item_meta.get("domain", ""),
            "timestamp": datetime.now().isoformat(),
        }
        self._update_preferences(reaction, item_meta)
        self._save()

    def _update_preferences(self, reaction: str, meta: dict):
        """Update preference weights based on feedback."""
        delta = 1.0 if reaction == "like" else -2.0
        prefs = self.data["preferences"]

        source = meta.get("channel", "")
        if source:
            prefs["sources"][source] = prefs["sources"].get(source, 0) + delta

        domain = meta.get("domain", "")
        if domain:
            prefs["domains"][domain] = prefs["domains"].get(domain, 0) + delta

    def get_source_weight(self, source: str) -> float:
        """Get preference weight for a source. Positive = liked, negative = disliked."""
        return self.data["preferences"]["sources"].get(source, 0)

    def get_domain_weight(self, domain: str) -> float:
        return self.data["preferences"]["domains"].get(domain, 0)

    def get_stats(self) -> dict:
        items = self.data["items"]
        likes = sum(1 for v in items.values() if v["reaction"] == "like")
        dislikes = sum(1 for v in items.values() if v["reaction"] == "dislike")
        return {"total": len(items), "likes": likes, "dislikes": dislikes}


def review_cli():
    """CLI tool to review the latest briefing and provide feedback."""
    output_dir = Path(__file__).parent.parent / "sample_output"
    briefings = sorted(output_dir.glob("briefing_*.md"), reverse=True)

    if not briefings:
        print("No briefings found in sample_output/")
        return

    latest = briefings[0]
    print(f"\n📋 Reviewing: {latest.name}\n")
    print(latest.read_text(encoding="utf-8"))

    store = FeedbackStore()
    print("\n" + "=" * 50)
    print("Feedback mode: enter item number + reaction")
    print("  Example: '1 like' or '3 dislike'")
    print("  Type 'quit' to exit, 'stats' to see feedback stats\n")

    # Parse item titles from briefing for metadata
    items = _parse_briefing_items(latest.read_text(encoding="utf-8"))

    while True:
        try:
            cmd = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd == "quit":
            break
        if cmd == "stats":
            stats = store.get_stats()
            print(f"Total: {stats['total']} | 👍 {stats['likes']} | 👎 {stats['dislikes']}")
            continue

        parts = cmd.split()
        if len(parts) != 2 or parts[1] not in ("like", "dislike"):
            print("Format: <number> like/dislike")
            continue

        idx = int(parts[0]) - 1
        if idx < 0 or idx >= len(items):
            print(f"Item number must be 1-{len(items)}")
            continue

        item = items[idx]
        store.record(
            item_id=item.get("title", f"item_{idx}"),
            reaction=parts[1],
            item_meta=item,
        )
        emoji = "👍" if parts[1] == "like" else "👎"
        print(f"{emoji} Recorded for: {item['title'][:50]}...")


def _parse_briefing_items(md: str) -> list[dict]:
    """Extract item metadata from a briefing markdown."""
    items = []
    current_domain = ""
    lines = md.split("\n")

    for i, line in enumerate(lines):
        if line.startswith("## ") and "领域" in line:
            for d in ["AI", "芯片", "机器人"]:
                if d in line:
                    current_domain = d
                    break
        elif line.startswith("### "):
            title = line.lstrip("# ").strip()
            # Remove leading number
            if ". " in title:
                title = title.split(". ", 1)[1]
            channel = ""
            if i + 1 < len(lines):
                src_line = lines[i + 1]
                if "·" in src_line:
                    parts = src_line.split("·")
                    channel = parts[1].strip() if len(parts) > 1 else ""
            items.append({"title": title, "channel": channel, "domain": current_domain})

    return items


if __name__ == "__main__":
    review_cli()
