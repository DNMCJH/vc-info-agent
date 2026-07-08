"""Generate copy-paste text for WeCom customer-group broadcast.

This does not bypass WeCom external-group restrictions. It prepares the exact
message that can be used in Group Broadcast Assistant, official customer-group
broadcast API task creation, or SCRM material/SOP tools.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


DEFAULT_H5_BASE_URL = "https://vcbrief.site"


def build_broadcast_text(
    briefing_data: dict,
    h5_base_url: str | None = None,
    max_points: int = 3,
) -> str:
    """Build a concise WeChat/WeCom-friendly daily broadcast text."""
    date_str = briefing_data.get("date") or datetime.now().strftime("%Y-%m-%d")
    base = (h5_base_url or DEFAULT_H5_BASE_URL).rstrip("/")
    detail_url = f"{base}/briefing/{date_str}"

    points = _extract_points(briefing_data, max_points=max_points)
    lines = [
        "今日 VC Info 简报已更新：",
        detail_url,
        "",
        "今日重点：",
    ]
    if points:
        lines.extend(f"{idx}. {point}" for idx, point in enumerate(points, 1))
    else:
        lines.append("1. 今日简报已生成，可点链接查看完整内容。")

    lines.extend([
        "",
        "适合快速浏览，也可以点链接看完整内容。",
    ])
    return "\n".join(lines)


def write_broadcast_file(
    briefing_data: dict,
    output_dir: Path,
    h5_base_url: str | None = None,
) -> Path:
    """Write broadcast text to sample_output/wecom_broadcast_YYYY-MM-DD.txt."""
    date_str = briefing_data.get("date") or datetime.now().strftime("%Y-%m-%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"wecom_broadcast_{date_str}.txt"
    output_path.write_text(
        build_broadcast_text(briefing_data, h5_base_url=h5_base_url),
        encoding="utf-8",
    )
    return output_path


def _extract_points(briefing_data: dict, max_points: int) -> list[str]:
    tldr = briefing_data.get("tldr") or ""
    points: list[str] = []
    for line in tldr.splitlines():
        cleaned = line.strip().lstrip("•-* ").strip()
        if cleaned:
            points.append(_trim(cleaned))
        if len(points) >= max_points:
            return points

    items = briefing_data.get("items") or []
    for item in items:
        title = (item.get("title") or "").strip()
        if title:
            points.append(_trim(title))
        if len(points) >= max_points:
            break
    return points


def _trim(text: str, limit: int = 42) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

