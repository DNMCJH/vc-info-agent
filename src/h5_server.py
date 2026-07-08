"""H5 briefing server — serves detail pages, public JSON APIs, and feedback API."""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"
BRIEFINGS_DIR = DATA_DIR / "briefings"
AUDIO_DIR = DATA_DIR / "audio"
FEEDBACK_FILE = DATA_DIR / "feedback.json"

DOMAIN_EMOJI = {"AI": "🤖", "芯片": "🔬", "机器人": "🦾"}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

app = FastAPI(title="VC Briefing H5")

# Public read APIs are intended to be consumed by a thin frontend on another
# domain, such as vc.vivianai.cn. Keep feedback POST simple for the MVP too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Serve audio files
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

# Serve card images
CARDS_DIR = DATA_DIR / "cards"
CARDS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/cards", StaticFiles(directory=str(CARDS_DIR)), name="cards")

env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _briefing_files() -> list[Path]:
    """Return regular daily briefing JSON files, newest date first."""
    return sorted(BRIEFINGS_DIR.glob("briefing_*.json"), reverse=True)


def _load_briefing(date_str: str) -> dict | None:
    """Load one daily briefing by date, or None when missing/invalid."""
    json_path = BRIEFINGS_DIR / f"briefing_{date_str}.json"
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read briefing %s: %s", json_path, exc)
        return None


def _briefing_summary(data: dict) -> dict:
    """Build a compact list item for archives and index pages."""
    date_str = data.get("date", "")
    items = data.get("items", [])
    top_titles = [item.get("title", "") for item in items[:3] if item.get("title")]
    return {
        "briefing_id": data.get("briefing_id", f"briefing_{date_str}"),
        "date": date_str,
        "generated_at": data.get("generated_at", ""),
        "total_collected": data.get("total_collected", 0),
        "selected_count": data.get("selected_count", len(items)),
        "tldr": data.get("tldr", ""),
        "trend_insight": data.get("trend_insight", ""),
        "top_titles": top_titles,
        "html_url": f"/briefing/{date_str}" if date_str else "",
        "api_url": f"/api/briefing/{date_str}" if date_str else "",
    }


@app.get("/", response_class=HTMLResponse)
async def latest_frontend():
    """Minimal frontend that fetches the public JSON API client-side."""
    template = env.get_template("vc_latest.html")
    return HTMLResponse(template.render())


@app.get("/api/briefings")
async def list_briefings(limit: int = 30):
    """List available daily briefings for a thin external frontend."""
    limit = max(1, min(limit, 100))
    summaries = []
    for path in _briefing_files()[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Skipping invalid briefing %s: %s", path, exc)
            continue
        summaries.append(_briefing_summary(data))
    return JSONResponse({"count": len(summaries), "items": summaries})


@app.get("/api/latest")
async def latest_briefing():
    """Return the newest daily briefing JSON plus display links."""
    for path in _briefing_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Skipping invalid briefing %s: %s", path, exc)
            continue
        date_str = data.get("date", "")
        data.setdefault("html_url", f"/briefing/{date_str}" if date_str else "")
        data.setdefault("api_url", f"/api/briefing/{date_str}" if date_str else "")
        return JSONResponse(data)
    return JSONResponse({"error": "no briefing found"}, status_code=404)


@app.get("/api/briefing/{date_str}")
async def briefing_json(date_str: str):
    """Return one daily briefing JSON by date."""
    data = _load_briefing(date_str)
    if data is None:
        return JSONResponse({"error": "briefing not found"}, status_code=404)
    data.setdefault("html_url", f"/briefing/{date_str}")
    data.setdefault("api_url", f"/api/briefing/{date_str}")
    return JSONResponse(data)


@app.get("/briefing/{date_str}", response_class=HTMLResponse)
async def briefing_page(date_str: str):
    data = _load_briefing(date_str)
    if data is None:
        return HTMLResponse("<h1>Briefing not found</h1>", status_code=404)

    template = env.get_template("briefing.html")

    # Prepare template context
    weekday = ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = WEEKDAYS[dt.weekday()]
    except ValueError:
        pass

    tldr = data.get("tldr", "")
    tldr_lines = [l.strip() for l in tldr.split("\n") if l.strip()] if tldr else []

    grouped = {}
    for item in data.get("items", []):
        grouped.setdefault(item.get("domain", "other"), []).append(item)

    domain_order = ["AI", "芯片", "机器人"]
    grouped_items = [(d, grouped[d]) for d in domain_order if d in grouped]
    for d, items in grouped.items():
        if d not in domain_order:
            grouped_items.append((d, items))

    audio_path = AUDIO_DIR / f"briefing_{date_str}.mp3"
    audio_url = f"/audio/briefing_{date_str}.mp3" if audio_path.exists() else None

    html = template.render(
        date=date_str,
        weekday=weekday,
        total_collected=data.get("total_collected", 0),
        item_count=data.get("selected_count", len(data.get("items", []))),
        audio_url=audio_url,
        audio_duration="~5 min",
        tldr_lines=tldr_lines,
        grouped_items=grouped_items,
        domain_emoji=DOMAIN_EMOJI,
        trend_insight=data.get("trend_insight", ""),
    )
    return HTMLResponse(html)


@app.post("/api/feedback")
async def submit_feedback(request: Request):
    body = await request.json()
    item_id = body.get("item_id", "")
    rating = body.get("rating", "")

    if not item_id or not rating:
        return JSONResponse({"error": "missing fields"}, status_code=400)

    feedback = []
    if FEEDBACK_FILE.exists():
        try:
            feedback = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        except Exception:
            feedback = []

    feedback.append({
        "item_id": item_id,
        "rating": rating,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })

    FEEDBACK_FILE.write_text(
        json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9003)
