"""
FastAPI dashboard server.

Shares the same SQLite database as the bot — both can run simultaneously
thanks to WAL mode. Start with:  python main.py dashboard
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from storage.db import Database

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Noctura Trend Search", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# One shared DB connection per process (WAL mode handles concurrent bot writes)
_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    db = get_db()
    creators = db.get_all_creators()
    analyses = db.get_recent_analyses(limit=8)
    audio = db.get_trending_audio(limit=5)
    keywords = db.get_trending_keywords(limit=10)

    stats = {
        "total_creators": len(creators),
        "total_reels": sum(c.get("total_reels") or 0 for c in creators),
        "total_analyses": len(db.get_all_analyses(limit=9999)),
        "top_niche": _top_niche(analyses),
    }

    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "recent_analyses": analyses,
        "top_audio": audio,
        "top_keywords": keywords,
        "creators": creators[:5],
    })


@app.get("/creators", response_class=HTMLResponse)
async def creators_list(request: Request):
    db = get_db()
    creators = db.get_all_creators()
    profiles = {p["username"]: p for p in db.get_all_creator_profiles()}
    # Merge profile data into creator rows
    for c in creators:
        p = profiles.get(c["username"], {})
        top_niches = p.get("top_niches") or []
        top_kw = p.get("top_keywords") or []
        c["top_niche"] = top_niches[0]["value"] if top_niches else "—"
        c["top_keywords_str"] = ", ".join(k["value"] for k in top_kw[:4])
        c["profile_summary"] = p.get("profile_summary") or ""

    return templates.TemplateResponse("creators.html", {
        "request": request,
        "creators": creators,
    })


@app.get("/creators/{username}", response_class=HTMLResponse)
async def creator_detail(request: Request, username: str):
    db = get_db()
    creator = db.get_creator(username)
    if not creator:
        return HTMLResponse("<h2>Creator not found</h2>", status_code=404)

    profile = db.get_creator_profile(username) or {}
    analyses = db.get_analyses_for_creator(username, limit=20)

    # Build chart data
    niche_labels = [n["value"] for n in (profile.get("top_niches") or [])[:6]]
    niche_counts = [n["count"] for n in (profile.get("top_niches") or [])[:6]]
    kw_labels = [k["value"] for k in (profile.get("top_keywords") or [])[:10]]
    kw_counts = [k["count"] for k in (profile.get("top_keywords") or [])[:10]]

    return templates.TemplateResponse("creator.html", {
        "request": request,
        "creator": creator,
        "profile": profile,
        "analyses": analyses,
        "niche_labels": niche_labels,
        "niche_counts": niche_counts,
        "kw_labels": kw_labels,
        "kw_counts": kw_counts,
    })


@app.get("/bank", response_class=HTMLResponse)
async def data_bank(request: Request):
    db = get_db()
    audio = db.get_trending_audio(limit=30)
    keywords = db.get_trending_keywords(limit=40)

    # Chart: top 10 audio by usage
    audio_labels = [a.get("audio_name") or "unknown" for a in audio[:10]]
    audio_counts = [a.get("usage_count") or 0 for a in audio[:10]]
    audio_scores = [round(a.get("avg_trending_score") or 0, 1) for a in audio[:10]]

    return templates.TemplateResponse("bank.html", {
        "request": request,
        "audio": audio,
        "keywords": keywords,
        "audio_labels": audio_labels,
        "audio_counts": audio_counts,
        "audio_scores": audio_scores,
    })


@app.get("/analyses", response_class=HTMLResponse)
async def analyses_feed(request: Request, creator: str | None = None):
    db = get_db()
    if creator:
        analyses = db.get_analyses_for_creator(creator.lstrip("@"), limit=50)
        filter_label = f"@{creator.lstrip('@')}"
    else:
        analyses = db.get_recent_analyses(limit=50)
        filter_label = "All Creators"

    creators = db.get_all_creators()

    return templates.TemplateResponse("analyses.html", {
        "request": request,
        "analyses": analyses,
        "filter_label": filter_label,
        "creators": creators,
        "active_creator": creator,
    })


# ------------------------------------------------------------------
# API endpoints (JSON) — for future use / external integrations
# ------------------------------------------------------------------

@app.get("/api/creators")
async def api_creators():
    return get_db().get_all_creators()


@app.get("/api/creators/{username}")
async def api_creator(username: str):
    db = get_db()
    return {
        "creator": db.get_creator(username),
        "profile": db.get_creator_profile(username),
        "analyses": db.get_analyses_for_creator(username, limit=20),
    }


@app.get("/api/bank/audio")
async def api_audio():
    return get_db().get_trending_audio(limit=50)


@app.get("/api/bank/keywords")
async def api_keywords():
    return get_db().get_trending_keywords(limit=50)


@app.get("/api/analyses")
async def api_analyses():
    return get_db().get_recent_analyses(limit=50)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _top_niche(analyses: list[dict]) -> str:
    from collections import Counter
    niches = [a.get("niche") for a in analyses if a.get("niche")]
    if not niches:
        return "—"
    return Counter(niches).most_common(1)[0][0]
