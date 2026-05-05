"""
Syncs logged content to per-creator Notion databases.

Routing: each submission goes to the database mapped to the submitter's
Instagram username in NOTION_CREATOR_DBS. Falls back to NOTION_DATABASE_ID.
"""

from __future__ import annotations

from typing import Any

import httpx

from config import config
from utils.logger import warning, success

_NOTION_VERSION = "2022-06-28"


class NotionSync:
    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {config.NOTION_TOKEN}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def sync_reel(self, metadata: dict[str, Any]) -> bool:
        if not config.NOTION_TOKEN:
            return False
        db_id = self._db_for(metadata.get("submitted_by", ""))
        if not db_id:
            warning("Notion: no database ID configured — skipping sync")
            return False
        try:
            thumbnail = metadata.get("thumbnail_url") or ""
            page: dict[str, Any] = {
                "parent": {"database_id": db_id},
                "properties": _build_properties(metadata),
            }
            if thumbnail:
                page["cover"] = {"type": "external", "external": {"url": thumbnail}}

            r = httpx.post(
                "https://api.notion.com/v1/pages",
                headers=self._headers,
                json=page,
                timeout=10,
            )
            if r.status_code == 200:
                success(f"Notion: synced {metadata.get('content_type', 'reel')} {metadata.get('id')}")
                return True
            warning(f"Notion sync failed ({r.status_code}): {r.text[:200]}")
            return False
        except Exception as exc:
            warning(f"Notion sync error: {exc}")
            return False

    def sync_story(self, metadata: dict[str, Any]) -> bool:
        if not config.NOTION_TOKEN:
            return False
        db_id = self._db_for(metadata.get("submitted_by", ""))
        if not db_id:
            warning("Notion: no database ID configured — skipping story sync")
            return False
        try:
            thumbnail = metadata.get("thumbnail_url") or ""
            creator = metadata.get("creator_username") or "unknown"
            submitted_by = metadata.get("submitted_by") or ""

            properties = {
                "Name": {"title": [{"text": {"content": f"Story by @{creator}"}}]},
                "Creator": {"select": {"name": creator}},
                "Submitted By": {"select": {"name": submitted_by}},
                "Content Type": {"select": {"name": "story"}},
                "Caption": _rich_text((metadata.get("caption") or "")[:2000]),
            }

            page: dict[str, Any] = {
                "parent": {"database_id": db_id},
                "properties": properties,
            }
            if thumbnail:
                page["cover"] = {"type": "external", "external": {"url": thumbnail}}

            r = httpx.post(
                "https://api.notion.com/v1/pages",
                headers=self._headers,
                json=page,
                timeout=10,
            )
            if r.status_code == 200:
                success(f"Notion: synced story {metadata.get('id')}")
                return True
            warning(f"Notion story sync failed ({r.status_code}): {r.text[:200]}")
            return False
        except Exception as exc:
            warning(f"Notion story sync error: {exc}")
            return False

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _db_for(self, submitted_by: str) -> str:
        username = (submitted_by or "").lower().lstrip("@")
        creator_dbs = config.NOTION_CREATOR_DBS
        return creator_dbs.get(username) or config.NOTION_DATABASE_ID


# ------------------------------------------------------------------
# Property builders
# ------------------------------------------------------------------

def _build_properties(metadata: dict[str, Any]) -> dict:
    hashtags = ", ".join(f"#{h}" for h in (metadata.get("hashtags") or []))
    audio = metadata.get("audio_name") or ""
    if metadata.get("audio_artist"):
        audio += f" — {metadata['audio_artist']}"
    creator = metadata.get("creator_username") or "unknown"
    submitted_by = metadata.get("submitted_by") or ""
    content_type = metadata.get("content_type") or "reel"

    return {
        "Name":           {"title": [{"text": {"content": f"@{creator}"}}]},
        "Reel URL":       {"url": metadata.get("reel_url") or None},
        "Creator":        {"select": {"name": creator}},
        "Submitted By":   {"select": {"name": submitted_by}} if submitted_by else _rich_text(""),
        "Content Type":   {"select": {"name": content_type}},
        "Summary":        _rich_text((metadata.get("visual_summary") or "")[:2000]),
        "Caption":        _rich_text((metadata.get("caption") or "")[:2000]),
        "Hashtags":       _rich_text(hashtags[:2000]),
        "Audio":          _rich_text(audio),
        "Views":          {"number": metadata.get("view_count") or 0},
        "Likes":          {"number": metadata.get("like_count") or 0},
        "Plays":          {"number": metadata.get("play_count") or 0},
        "Duration (s)":   {"number": metadata.get("duration") or 0},
    }


def _rich_text(value: str) -> dict:
    return {"rich_text": [{"text": {"content": value}}]}
