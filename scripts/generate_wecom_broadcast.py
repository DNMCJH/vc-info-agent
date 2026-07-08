"""Generate WeCom/WeChat customer-group broadcast text from briefing JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from wecom_broadcast import build_broadcast_text, write_broadcast_file  # noqa: E402


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Generate customer-group broadcast text")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--json", dest="json_path", help="Path to briefing JSON")
    parser.add_argument("--h5-base-url", default=os.getenv("H5_BASE_URL", "https://vcbrief.site"))
    parser.add_argument("--print", dest="print_text", action="store_true", help="Print text to stdout")
    args = parser.parse_args()

    json_path = Path(args.json_path) if args.json_path else BASE_DIR / "data" / "briefings" / f"briefing_{args.date}.json"
    if not json_path.exists():
        print(f"Briefing JSON not found: {json_path}", file=sys.stderr)
        return 2

    briefing_data = json.loads(json_path.read_text(encoding="utf-8"))
    output_path = write_broadcast_file(
        briefing_data,
        BASE_DIR / "sample_output",
        h5_base_url=args.h5_base_url,
    )
    text = build_broadcast_text(briefing_data, h5_base_url=args.h5_base_url)
    if args.print_text:
        print(text)
    print(f"Broadcast text saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
