"""
Syncs logged reels to a Notion database.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
        self._db_id = config.NOTION_DATABASE_ID

    def sync_reel(self, metadata: dict[str, Any]) -> bool:
        if not config.NOTION_TOKEN or not config.NOTION_DATABASE_ID:
            return False
        try:
            r = httpx.post(
                "https://api.notion.com/v1/pages",
                headers=self._headers,
                json={
                    "parent": {"database_id": self._db_id},
                    "properties": _build_properties(metadata),
                },
                timeout=10,
            )
            if r.status_code == 200:
                success(f"Notion: synced reel {metadata.get('id')}")
                return True
            warning(f"Notion sync failed: {r.text[:200]}")
            return False
        except Exception as exc:
            warning(f"Notion sync error: {exc}")
            return False


def _build_properties(metadata: dict[str, Any]) -> dict:
    hashtags = ", ".join(f"#{h}" for h in (metadata.get("hashtags") or []))
    audio = metadata.get("audio_name") or ""
    if metadata.get("audio_artist"):
        audio += f" — {metadata['audio_artist']}"
    creator = metadata.get("creator_username") or "unknown"

    return {
        "Name":         {"title": [{"text": {"content": f"@{creator}"}}]},
        "Reel URL":     {"url": metadata.get("reel_url") or None},
        "Creator":      _rich_text(creator),
        "Caption":      _rich_text((metadata.get("caption") or "")[:2000]),
        "Hashtags":     _rich_text(hashtags[:2000]),
        "Audio":        _rich_text(audio),
        "Views":        {"number": metadata.get("view_count") or 0},
        "Likes":        {"number": metadata.get("like_count") or 0},
        "Plays":        {"number": metadata.get("play_count") or 0},
        "Duration (s)": {"number": metadata.get("duration") or 0},
        "Submitted By": _rich_text(metadata.get("submitted_by") or ""),
        "Logged At":    {"date": {"start": datetime.now(timezone.utc).isoformat()}},
    }


def _rich_text(value: str) -> dict:
    return {"rich_text": [{"text": {"content": value}}]}
