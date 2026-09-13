"""LLM-scored editor's picks over a date range (half-month / month).

The daily pipeline already filters hard, so this is a second pass over items
that survived it: score each on several dimensions, keep only what clears a
threshold, and write a picks file the H5 site reads.

Deliberately biased toward selecting nothing over selecting filler — an empty
pick list is a valid answer for a quiet fortnight.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
BRIEFINGS_DIR = BASE_DIR / "data" / "briefings"
PICKS_DIR = BASE_DIR / "data" / "picks"
FEEDBACK_FILE = BASE_DIR / "data" / "feedback.json"

# Weighted 0-10 dimensions. Durability is weighted highest: a pick is meant to
# still be worth reading weeks later, which is what separates it from a daily.
DIMENSIONS = {
    "impact": ("影响力", 0.25),
    "scarcity": ("稀缺性", 0.20),
    "actionability": ("决策参考价值", 0.25),
    "durability": ("时效穿透力", 0.30),
}
assert abs(sum(w for _, w in DIMENSIONS.values()) - 1.0) < 1e-9, (
    "dimension weights must sum to 1.0, otherwise every score is skewed "
    "and the threshold no longer means what it says"
)

# Reader feedback is a light nudge, not a dimension: with only a handful of
# ratings so far it must not dominate. Scales with evidence.
FEEDBACK_MAX_BONUS = 1.0

# Calibrated against 2026-08: 60 candidates scored mean 6.08 / max 8.32.
# 7.0 let 20 through (not a "pick" anymore), 7.5 gave 11, 8.0 only 4.
# 7.8 yields ~6 per month — roughly 1-2 a week, which matches the brief.
SCORE_THRESHOLD = float(os.getenv("CURATOR_THRESHOLD", "7.8"))
MAX_PICKS = int(os.getenv("CURATOR_MAX_PICKS", "12"))
# Cap LLM spend: only the best daily-scored candidates get judged.
MAX_CANDIDATES = int(os.getenv("CURATOR_MAX_CANDIDATES", "60"))

SCORING_PROMPT = """你是一位面向投资人的内容编辑，正在从过去一段时间的 AI/芯片/机器人日报里挑选"精选"。
精选的标准是：过一个月再看仍然值得读。宁缺毋滥，不要为了凑数而选。

请对下面这条内容按 4 个维度打分（0-10 分，可用小数）：

- impact 影响力：对行业格局、技术路线或资本流向的实际影响有多大
- scarcity 稀缺性：这个信息是否独特、少见，还是到处都能看到的常规报道
- actionability 决策参考价值：对投资判断是否有具体可用的参考，而非泛泛而谈
- durability 时效穿透力：一个月后回看是否仍有价值，还是纯粹的当日噪音

同时给一句 reason（不超过 40 字，中文），说明这条内容值得或不值得入选的关键理由。

内容：
标题：{title}
领域：{domain}
来源：{channel}
日期：{date}
摘要：{summary}
为何重要：{why_it_matters}

只输出 JSON，不要任何其他文字：
{{"impact": 数字, "scarcity": 数字, "actionability": 数字, "durability": 数字, "reason": "..."}}"""


@dataclass
class Candidate:
    """One briefing item plus the context needed to score it."""
    item_id: str
    date: str
    title: str
    url: str
    domain: str
    channel: str
    summary: str
    why_it_matters: str
    quality_score: int


def period_range(period: str, today: date | None = None) -> tuple[str, str, str]:
    """Resolve a period keyword to (start, end, label).

    half-month covers the 1st-15th or 16th-end of the *previous* completed
    half, so a run never judges a window that is still filling up.
    """
    today = today or date.today()

    if period == "month":
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
        return start.isoformat(), end.isoformat(), f"{start.year}年{start.month}月"

    if period == "half-month":
        if today.day > 15:
            start = today.replace(day=1)
            end = today.replace(day=15)
            label = f"{start.year}年{start.month}月上半月"
        else:
            last_month_end = today.replace(day=1) - timedelta(days=1)
            start = last_month_end.replace(day=16)
            end = last_month_end
            label = f"{start.year}年{start.month}月下半月"
        return start.isoformat(), end.isoformat(), label

    raise ValueError(f"unknown period: {period}")


def _load_feedback_signals() -> dict[str, dict]:
    """item_id -> reaction info, used as a small scoring nudge."""
    if not FEEDBACK_FILE.exists():
        return {}
    try:
        data = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning("Cannot read feedback: %s", exc)
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def collect_candidates(start: str, end: str) -> list[Candidate]:
    """Every briefing item inside the window, best daily score first."""
    candidates: list[Candidate] = []
    for path in sorted(BRIEFINGS_DIR.glob("briefing_*.json")):
        date_str = path.stem.replace("briefing_", "")
        if not (start <= date_str <= end):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            logger.warning("Skipping %s: %s", path, exc)
            continue
        for item in data.get("items", []):
            candidates.append(Candidate(
                item_id=item.get("item_id", ""),
                date=data.get("date", date_str),
                title=item.get("title", ""),
                url=item.get("url", ""),
                domain=item.get("domain", ""),
                channel=item.get("channel", ""),
                summary=item.get("summary", ""),
                why_it_matters=item.get("why_it_matters", ""),
                quality_score=item.get("quality_score", 0) or 0,
            ))

    candidates.sort(key=lambda c: c.quality_score, reverse=True)
    return candidates


class Curator:
    """Scores candidates with the LLM and keeps only those above threshold."""

    def __init__(self, config):
        self.config = config
        self.client = httpx.Client(
            base_url=config.llm_base_url,
            headers={"Authorization": f"Bearer {config.llm_api_key}"},
            timeout=60,
        )

    def close(self):
        self.client.close()

    def _score_one(self, candidate: Candidate) -> dict | None:
        """Ask the LLM for per-dimension scores; None when unusable."""
        prompt = SCORING_PROMPT.format(
            title=candidate.title,
            domain=candidate.domain or "未分类",
            channel=candidate.channel or "未知来源",
            date=candidate.date,
            summary=candidate.summary or "（无摘要）",
            why_it_matters=candidate.why_it_matters or "（无）",
        )
        try:
            response = self.client.post("/v1/chat/completions", json={
                "model": self.config.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 300,
                # Matches summarizer.py: v4-flash otherwise returns empty content.
                "thinking": {"type": "disabled"},
            })
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("Scoring failed for %s: %s", candidate.title[:40], exc)
            return None

        return self._parse_scores(raw, candidate)

    @staticmethod
    def _parse_scores(raw: str, candidate: Candidate) -> dict | None:
        """Extract the JSON object, tolerating code fences around it."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1] if "```" in text[3:] else text[3:]
            text = text.removeprefix("json").strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            logger.warning("No JSON in score response for %s", candidate.title[:40])
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            logger.warning("Bad score JSON for %s: %s", candidate.title[:40], exc)
            return None

        dims = {}
        for key in DIMENSIONS:
            try:
                dims[key] = max(0.0, min(10.0, float(parsed.get(key, 0))))
            except (TypeError, ValueError):
                dims[key] = 0.0
        return {"dims": dims, "reason": str(parsed.get("reason", ""))[:120]}

    @staticmethod
    def _feedback_bonus(item_id: str, signals: dict) -> tuple[float, str]:
        """Small ± nudge from reader reactions. Zero when no feedback exists.

        Feedback volume is tiny right now, so this can only move a score by up
        to FEEDBACK_MAX_BONUS and never decides a pick on its own. As ratings
        accumulate the same formula gets more influence without a code change.
        """
        entry = signals.get(item_id)
        if not entry:
            return 0.0, ""
        reaction = (entry.get("latest_reaction") or "").lower()
        count = max(1, int(entry.get("feedback_count") or 1))
        # More ratings = more confidence, capped so a single voice can't decide.
        confidence = min(1.0, count / 3)
        if reaction in ("like", "useful"):
            return FEEDBACK_MAX_BONUS * confidence, f"读者认可 ×{count}"
        if reaction in ("dislike", "already_known", "too_technical"):
            return -FEEDBACK_MAX_BONUS * confidence, f"读者负反馈({reaction}) ×{count}"
        return 0.0, ""

    def build_picks(self, period: str, today: date | None = None) -> dict:
        """Score the window's candidates and return the picks payload."""
        start, end, label = period_range(period, today)
        candidates = collect_candidates(start, end)
        signals = _load_feedback_signals()

        logger.info(
            "Curating %s (%s..%s): %d candidates, judging top %d",
            label, start, end, len(candidates), min(len(candidates), MAX_CANDIDATES),
        )

        scored = []
        for candidate in candidates[:MAX_CANDIDATES]:
            result = self._score_one(candidate)
            if result is None:
                continue

            dims = result["dims"]
            base = sum(dims[key] * weight for key, (_, weight) in DIMENSIONS.items())
            bonus, bonus_note = self._feedback_bonus(candidate.item_id, signals)
            total = round(min(10.0, max(0.0, base + bonus)), 2)

            scored.append({
                "item_id": candidate.item_id,
                "date": candidate.date,
                "title": candidate.title,
                "url": candidate.url,
                "domain": candidate.domain,
                "channel": candidate.channel,
                "summary": candidate.summary,
                "why_it_matters": candidate.why_it_matters,
                "quality_score": candidate.quality_score,
                "pick_score": total,
                "base_score": round(base, 2),
                "feedback_bonus": round(bonus, 2),
                "feedback_note": bonus_note,
                "dims": dims,
                "reason": result["reason"],
            })

        scored.sort(key=lambda row: row["pick_score"], reverse=True)
        picks = [row for row in scored if row["pick_score"] >= SCORE_THRESHOLD][:MAX_PICKS]

        logger.info(
            "Scored %d items, %d cleared threshold %.1f",
            len(scored), len(picks), SCORE_THRESHOLD,
        )

        return {
            "period": period,
            "label": label,
            "start": start,
            "end": end,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "threshold": SCORE_THRESHOLD,
            "candidates_total": len(candidates),
            "candidates_scored": len(scored),
            "pick_count": len(picks),
            "dimension_weights": {
                key: {"label": name, "weight": weight}
                for key, (name, weight) in DIMENSIONS.items()
            },
            "items": picks,
        }


def save_picks(payload: dict) -> Path:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    path = PICKS_DIR / f"picks_{payload['period']}_{payload['end']}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate editor's picks")
    parser.add_argument("--period", choices=["half-month", "month"], default="half-month")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="score and print without writing a picks file",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="override how many candidates get scored (cost control)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.limit:
        global MAX_CANDIDATES
        MAX_CANDIDATES = args.limit

    from config import Config

    curator = Curator(Config())
    try:
        payload = curator.build_picks(args.period)
    finally:
        curator.close()

    print(f"\n=== {payload['label']} ({payload['start']} .. {payload['end']}) ===")
    print(f"candidates {payload['candidates_total']}, scored {payload['candidates_scored']}, "
          f"picked {payload['pick_count']} (threshold {payload['threshold']})")
    for row in payload["items"]:
        dims = " ".join(f"{k}={v}" for k, v in row["dims"].items())
        print(f"\n[{row['pick_score']}] {row['date']} {row['domain']} | {row['title'][:56]}")
        print(f"    {dims}")
        if row["feedback_note"]:
            print(f"    feedback: {row['feedback_note']} ({row['feedback_bonus']:+})")
        print(f"    reason: {row['reason']}")

    if args.dry_run:
        print("\n(dry run, nothing written)")
    else:
        path = save_picks(payload)
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
