"""
Reel metadata extractor.

Given a DirectMessage object that contains a reel, extracts everything
useful: audio, hashtags, engagement counts, caption, URL — and importantly,
the original creator's Instagram username and profile info.
"""

from __future__ import annotations

import re
from typing import Any

from instagrapi.types import DirectMessage, Media

from utils.logger import warning


# Message item_type values that may carry a reel
_REEL_TYPES = {"clip", "reel_share", "xma_reel_share", "media_share"}


def is_reel_message(msg: DirectMessage) -> bool:
    return getattr(msg, "item_type", "") in _REEL_TYPES


def extract_reel_metadata(
    msg: DirectMessage,
    thread_id: str,
    submitted_by: str,  # username of whoever forwarded the reel to the bot
) -> dict[str, Any] | None:
    """
    Extract structured metadata from a DM message that contains a reel.

    Returns a dict with both reel data and creator info, or None on failure.
    """
    media: Media | None = _resolve_media(msg)
    if media is None:
        warning(f"Could not resolve media from message {msg.id}")
        return None

    caption = _get_caption(media)
    hashtags = _extract_hashtags(caption)
    audio_name, audio_artist = _get_audio(media)
    creator = _extract_creator(media)

    return {
        # Reel fields
        "id": str(media.pk),
        "dm_thread_id": thread_id,
        "reel_url": _build_url(media),
        "creator_username": creator["username"],
        "submitted_by": submitted_by,
        "caption": caption,
        "audio_name": audio_name,
        "audio_artist": audio_artist,
        "hashtags": hashtags,
        "view_count": getattr(media, "view_count", None) or 0,
        "like_count": getattr(media, "like_count", None) or 0,
        "play_count": getattr(media, "play_count", None) or 0,
        "duration": getattr(media, "video_duration", None) or 0,
        "submitted_at": None,  # filled by DB layer
        "raw_metadata": _safe_media_dict(media),
        # Creator fields (used to upsert into creators table)
        "creator": creator,
    }


def extract_creator_from_media(media: Media) -> dict[str, Any]:
    """Public helper — pull creator info from any Media object."""
    return _extract_creator(media)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _resolve_media(msg: DirectMessage) -> Media | None:
    for attr in ("clip", "media_share", "reel_share"):
        media = getattr(msg, attr, None)
        if media is not None and isinstance(media, Media):
            return media
    return None


def _extract_creator(media: Media) -> dict[str, Any]:
    """Extract the original poster's identity from the media object."""
    user = getattr(media, "user", None)
    if user is None:
        return {
            "username": "unknown",
            "full_name": None,
            "bio": None,
            "follower_count": None,
            "following_count": None,
            "media_count": None,
            "profile_pic_url": None,
        }
    return {
        "username": getattr(user, "username", "unknown") or "unknown",
        "full_name": getattr(user, "full_name", None),
        "bio": getattr(user, "biography", None),
        "follower_count": getattr(user, "follower_count", None),
        "following_count": getattr(user, "following_count", None),
        "media_count": getattr(user, "media_count", None),
        "profile_pic_url": str(getattr(user, "profile_pic_url", None) or ""),
    }


def _get_caption(media: Media) -> str:
    cap = getattr(media, "caption_text", None) or ""
    return cap.strip()


def _extract_hashtags(caption: str) -> list[str]:
    return re.findall(r"#(\w+)", caption)


def _get_audio(media: Media) -> tuple[str, str]:
    music = getattr(media, "clips_metadata", None) or {}
    if isinstance(music, dict):
        for key in ("music_info", "original_sound_info"):
            info_block = music.get(key) or {}
            if isinstance(info_block, dict):
                title = info_block.get("title") or ""
                artist = (
                    info_block.get("artist")
                    or info_block.get("display_artist")
                    or ""
                )
                if title:
                    return title, artist
    return "", ""


def _build_url(media: Media) -> str:
    code = getattr(media, "code", None)
    if code:
        return f"https://www.instagram.com/reel/{code}/"
    return f"https://www.instagram.com/p/{media.pk}/"


def _safe_media_dict(media: Media) -> dict:
    try:
        raw = media.dict() if hasattr(media, "dict") else media.__dict__
    except Exception:
        return {}
    clean: dict = {}
    for k, v in raw.items():
        try:
            import json
            json.dumps(v)
            clean[k] = v
        except (TypeError, ValueError):
            clean[k] = str(v)
    return clean
