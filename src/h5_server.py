"""H5 briefing server — serves detail pages, audio, and feedback API."""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
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

# Serve audio files
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

# Serve card images
CARDS_DIR = DATA_DIR / "cards"
CARDS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/cards", StaticFiles(directory=str(CARDS_DIR)), name="cards")

env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


@app.get("/briefing/{date_str}", response_class=HTMLResponse)
async def briefing_page(date_str: str):
    json_path = BRIEFINGS_DIR / f"briefing_{date_str}.json"
    if not json_path.exists():
        return HTMLResponse("<h1>Briefing not found</h1>", status_code=404)

    data = json.loads(json_path.read_text(encoding="utf-8"))
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
