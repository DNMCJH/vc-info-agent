"""TTS module — generate audio briefing from structured briefing data."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import edge_tts

logger = logging.getLogger(__name__)

AUDIO_DIR = Path(__file__).parent.parent / "data" / "audio"
VOICE = "zh-CN-YunyangNeural"
RATE = "+10%"


def generate_audio(briefing_data: dict, output_path: Path | None = None) -> Path:
    """Generate mp3 audio from briefing data. Returns path to the mp3 file."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    date_str = briefing_data.get("date", datetime.now().strftime("%Y-%m-%d"))
    if output_path is None:
        output_path = AUDIO_DIR / f"briefing_{date_str}.mp3"

    script = _build_script(briefing_data)
    asyncio.run(_synthesize(script, output_path))
    logger.info(f"Audio saved to {output_path} ({len(script)} chars)")
    return output_path


def _build_script(data: dict) -> str:
    """Convert briefing data into a spoken script."""
    parts = []

    date_str = data.get("date", "")
    weekday = ""
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            weekday = weekdays[dt.weekday()]
        except ValueError:
            pass

    item_count = data.get("selected_count", len(data.get("items", [])))
    parts.append(f"今日 VC 简报，{date_str}，{weekday}。共精选 {item_count} 条。")

    # TL;DR as opening hook
    tldr = data.get("tldr", "")
    if tldr:
        clean_tldr = tldr.replace("• ", "").replace("•", "")
        lines = [l.strip() for l in clean_tldr.split("\n") if l.strip()]
        parts.append("速览：" + "；".join(lines) + "。")

    parts.append("")

    # Items grouped by domain
    domain_items: dict[str, list[dict]] = {}
    for item in data.get("items", []):
        domain_items.setdefault(item.get("domain", "other"), []).append(item)

    idx = 1
    for domain in ["AI", "芯片", "机器人"]:
        items = domain_items.get(domain, [])
        if not items:
            continue
        parts.append(f"{domain}领域。")
        for item in items:
            title = item.get("title", "")
            summary = item.get("summary", "")
            why = item.get("why_it_matters", "")

            parts.append(f"第{idx}条，{title}。")
            if summary:
                parts.append(f"{summary}")
            if why:
                parts.append(f"投资视角：{why}")
            parts.append("")
            idx += 1

    # Trend insight as closing
    trend = data.get("trend_insight", "")
    if trend:
        parts.append(f"趋势洞察：{trend}")

    parts.append("以上是今日精选，完整内容请查看详情页。")

    return "\n".join(parts)


async def _synthesize(text: str, output_path: Path) -> None:
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicate.save(str(output_path))


# CLI entry point
if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python tts.py <briefing.json>")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    out = generate_audio(data)
    print(f"Generated: {out}")
