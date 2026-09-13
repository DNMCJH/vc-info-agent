"""H5 briefing server — serves detail pages, public JSON APIs, and feedback API."""

import html
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from search_index import BriefingIndex

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
# systemd starts this without the project env loaded, and the radar proxy needs
# RADAR_API_KEY from .env.
load_dotenv(BASE_DIR / ".env")

TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"
BRIEFINGS_DIR = DATA_DIR / "briefings"
PICKS_DIR = DATA_DIR / "picks"
AUDIO_DIR = DATA_DIR / "audio"
FEEDBACK_FILE = DATA_DIR / "feedback.json"

DOMAIN_EMOJI = {"AI": "🤖", "芯片": "🔬", "机器人": "🦾"}

# AI Radar runs as a separate service (gh-tool-radar) behind an API key.
# Proxying server-side keeps the key out of the browser.
RADAR_API_BASE = os.getenv("RADAR_API_BASE", "http://127.0.0.1:9005").rstrip("/")
RADAR_API_KEY = os.getenv("RADAR_API_KEY", "")
RADAR_TIMEOUT = 15
# Only these paths may be proxied, so a crafted path can't reach other routes.
RADAR_ALLOWED_ORIGINS = {
    "https://vcbrief.site",
    "http://127.0.0.1:9003",
    "http://127.0.0.1:9013",  # local preview
}
RADAR_ALLOWED_PATHS = {
    "/api/kb",
    "/api/kb/facets",
    "/api/kb/trending",
    "/api/kb/leaderboard",
    "/api/news",
    "/api/news/topics",
}
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
# RSS feeds deliver titles with HTML entities (&#8217; etc.) already encoded.
# Jinja2 escapes the ampersand again, so decode before rendering.
env.filters["unescape"] = lambda value: html.unescape(value) if value else value

index = BriefingIndex(BRIEFINGS_DIR)


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


@app.get("/archive", response_class=HTMLResponse)
async def archive_frontend():
    """History page; fetches /api/briefings client-side like the index does."""
    template = env.get_template("archive.html")
    return HTMLResponse(template.render())


@app.get("/api/briefings")
async def list_briefings(limit: int = 30):
    """List available daily briefings for a thin external frontend."""
    limit = max(1, min(limit, 500))
    summaries = []
    for path in _briefing_files()[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Skipping invalid briefing %s: %s", path, exc)
            continue
        summaries.append(_briefing_summary(data))
    return JSONResponse({"count": len(summaries), "items": summaries})


@app.get("/search", response_class=HTMLResponse)
async def search_frontend():
    """Item-level search page across all briefings."""
    template = env.get_template("search.html")
    return HTMLResponse(template.render())


@app.get("/radar", response_class=HTMLResponse)
async def radar_frontend():
    """AI Radar tools + news, served through the server-side proxy below."""
    template = env.get_template("radar.html")
    return HTMLResponse(template.render())


@app.get("/picks", response_class=HTMLResponse)
async def picks_frontend():
    """Editor's picks across half-month / month windows."""
    template = env.get_template("picks.html")
    return HTMLResponse(template.render())


def _picks_files() -> list[Path]:
    """Pick files, newest window first."""
    if not PICKS_DIR.exists():
        return []
    return sorted(PICKS_DIR.glob("picks_*.json"), key=lambda p: p.stem, reverse=True)


@app.get("/api/picks")
async def list_picks():
    """Available pick periods, newest first, with their items inlined."""
    periods = []
    for path in _picks_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            logger.warning("Skipping picks file %s: %s", path, exc)
            continue
        periods.append(data)
    return JSONResponse({"count": len(periods), "periods": periods})


@app.get("/api/facets")
async def search_facets():
    """Filter options (calendar, domains, sources, channels) from real data."""
    return JSONResponse(index.facets())


@app.get("/api/search")
async def search_items(
    q: str = "",
    domain: str = "",
    source: str = "",
    channel: str = "",
    year: str = "",
    month: str = "",
    date: str = "",
    date_from: str = "",
    date_to: str = "",
    min_score: int = 0,
    sort: str = "date",
    offset: int = 0,
    limit: int = 20,
):
    """Item-level search across every briefing, with facets and paging."""
    result = index.search(
        keyword=q,
        domain=domain,
        source=source,
        channel=channel,
        year=year,
        month=month,
        date=date,
        date_from=date_from,
        date_to=date_to,
        min_score=min_score,
        sort=sort,
        offset=offset,
        limit=limit,
    )
    return JSONResponse(result)


@app.get("/api/radar/{path:path}")
async def radar_proxy(path: str, request: Request):
    """Forward whitelisted AI Radar reads, injecting the key server-side."""
    target = f"/api/{path}"
    if target not in RADAR_ALLOWED_PATHS:
        return JSONResponse({"error": "unsupported radar path"}, status_code=404)

    # Briefing JSON is deliberately open (CORS *), but this route spends
    # someone else's API key, so cross-origin browser reads are refused.
    # Same-origin fetches send no Origin header, or send ours.
    origin = request.headers.get("origin")
    if origin and origin not in RADAR_ALLOWED_ORIGINS:
        logger.warning("Radar proxy blocked cross-origin request from %s", origin)
        return JSONResponse({"error": "cross-origin not allowed"}, status_code=403)

    if not RADAR_API_KEY:
        return JSONResponse(
            {"error": "radar not configured", "hint": "set RADAR_API_KEY in .env"},
            status_code=503,
        )

    params = dict(request.query_params)
    # Never let a caller override the key we attach ourselves.
    params.pop("key", None)
    # `cap` is our own trimming hint, not part of the radar API.
    params.pop("cap", None)
    headers = {"Accept": "application/json"}
    if RADAR_API_KEY:
        headers["X-API-Key"] = RADAR_API_KEY

    try:
        async with httpx.AsyncClient(timeout=RADAR_TIMEOUT) as client:
            response = await client.get(
                f"{RADAR_API_BASE}{target}", params=params, headers=headers
            )
    except httpx.RequestError as exc:
        logger.warning("Radar proxy %s failed: %s", target, exc)
        return JSONResponse({"error": "radar unreachable"}, status_code=502)

    if response.status_code >= 400:
        logger.warning("Radar proxy %s -> HTTP %s", target, response.status_code)
        return JSONResponse(
            {"error": f"radar returned {response.status_code}"},
            status_code=response.status_code,
        )

    try:
        payload = response.json()
    except ValueError:
        return JSONResponse({"error": "radar returned non-JSON"}, status_code=502)

    # Radar's /api/kb has no limit param and returns ~630KB for 565 tools.
    # Trim server-side so mobile clients don't download the whole corpus.
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        try:
            cap = int(request.query_params.get("cap", "0"))
        except ValueError:
            cap = 0
        if cap > 0:
            payload["returned"] = min(cap, len(payload["items"]))
            payload["items"] = payload["items"][:cap]

    return JSONResponse(payload)


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
