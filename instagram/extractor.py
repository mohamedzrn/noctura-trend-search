"""
Reel metadata extractor.

Given a DirectMessage object that contains a reel, extracts everything
useful: audio, hashtags, engagement counts, caption, URL.
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
    sender_username: str,
) -> dict[str, Any] | None:
    """
    Extract structured metadata from a DM message that contains a reel.

    Returns None if the media cannot be resolved.
    """
    media: Media | None = _resolve_media(msg)
    if media is None:
        warning(f"Could not resolve media from message {msg.id}")
        return None

    caption = _get_caption(media)
    hashtags = _extract_hashtags(caption)
    audio_name, audio_artist = _get_audio(media)

    return {
        "id": str(media.pk),
        "dm_thread_id": thread_id,
        "reel_url": _build_url(media),
        "caption": caption,
        "audio_name": audio_name,
        "audio_artist": audio_artist,
        "hashtags": hashtags,
        "view_count": getattr(media, "view_count", None) or 0,
        "like_count": getattr(media, "like_count", None) or 0,
        "play_count": getattr(media, "play_count", None) or 0,
        "duration": getattr(media, "video_duration", None) or 0,
        "sender_username": sender_username,
        "submitted_at": None,  # filled by DB layer
        "raw_metadata": _safe_media_dict(media),
    }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _resolve_media(msg: DirectMessage) -> Media | None:
    """Try every attribute that may hold the Media object."""
    for attr in ("clip", "media_share", "reel_share"):
        media = getattr(msg, attr, None)
        if media is not None and isinstance(media, Media):
            return media
    # xma_reel_share is a dict with nested media
    xma = getattr(msg, "xma_reel_share", None)
    if isinstance(xma, dict):
        # instagrapi may or may not parse this; return None and let caller skip
        pass
    return None


def _get_caption(media: Media) -> str:
    cap = getattr(media, "caption_text", None) or ""
    return cap.strip()


def _extract_hashtags(caption: str) -> list[str]:
    return re.findall(r"#(\w+)", caption)


def _get_audio(media: Media) -> tuple[str, str]:
    music = getattr(media, "clips_metadata", None) or {}
    if isinstance(music, dict):
        audio = music.get("audio_type") or {}
        # clips_metadata.original_sound_info or music_info
        for key in ("music_info", "original_sound_info"):
            info_block = music.get(key) or {}
            if isinstance(info_block, dict):
                title = info_block.get("title") or ""
                artist = info_block.get("artist") or info_block.get("display_artist") or ""
                if title:
                    return title, artist
    # fallback: check audio_codec or ig_media_sharing_disabled
    soundtrack = getattr(media, "product_type", "") or ""
    return "", ""


def _build_url(media: Media) -> str:
    code = getattr(media, "code", None)
    if code:
        return f"https://www.instagram.com/reel/{code}/"
    return f"https://www.instagram.com/p/{media.pk}/"


def _safe_media_dict(media: Media) -> dict:
    """Convert Media to a JSON-serialisable dict, dropping non-serialisable values."""
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
