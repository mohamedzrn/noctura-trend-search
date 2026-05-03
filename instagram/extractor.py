"""
Media extractor — handles reels, carousels, and static posts forwarded via DM.
"""

from __future__ import annotations

import re
from typing import Any

from instagrapi.types import DirectMessage, Media

from utils.logger import warning


_REEL_TYPES   = {"clip", "reel_share", "xma_reel_share", "xma_clip"}
_SHARE_TYPES  = {"media_share", "xma_media_share"}
_STORY_TYPES  = {"story_share", "xma_story_share"}
_IGNORE_TYPES = {"like", "action_log", "raven_media", "felix_share", "text"}


def get_content_type(msg: DirectMessage) -> str | None:
    """
    Returns 'reel', 'carousel', 'photo', 'story', or None.
    None means unsupported / should be ignored or flagged.
    """
    item_type = getattr(msg, "item_type", "") or ""

    if item_type in _REEL_TYPES:
        return "reel"

    if item_type in _STORY_TYPES:
        return "story"

    if item_type == "xma_media_share":
        return "carousel"  # best guess; _enrich_metadata will correct

    if item_type in _SHARE_TYPES:
        media = _resolve_media(msg)
        if media is None:
            return None
        media_type = getattr(media, "media_type", None)
        if media_type == 8:
            return "carousel"
        if media_type == 1:
            return "photo"
        if media_type == 2:
            return "reel"

    return None


def is_supported_message(msg: DirectMessage) -> bool:
    return get_content_type(msg) is not None


def is_reel_message(msg: DirectMessage) -> bool:
    """Legacy alias — kept for compatibility."""
    return is_supported_message(msg)


def is_wrong_type_message(msg: DirectMessage) -> bool:
    """True when the sender clearly sent something but it's not a supported type."""
    item_type = getattr(msg, "item_type", "") or ""
    return item_type not in _IGNORE_TYPES and item_type != "" and get_content_type(msg) is None


def extract_story_metadata(
    msg: DirectMessage,
    thread_id: str,
    submitted_by: str,
) -> dict[str, Any] | None:
    """Extract metadata from a story_share or xma_story_share DM message."""
    item_type = getattr(msg, "item_type", "") or ""
    story = getattr(msg, "story_share", None)

    # xma_story_share has no accessible story object — return a stub
    if story is None and item_type == "xma_story_share":
        return {
            "id": str(msg.id),
            "content_type": "story",
            "dm_thread_id": thread_id,
            "reel_url": None,
            "creator_username": "unknown",
            "submitted_by": submitted_by,
            "caption": "",
            "audio_name": "",
            "audio_artist": "",
            "hashtags": [],
            "view_count": 0,
            "like_count": 0,
            "play_count": 0,
            "duration": 0,
            "thumbnail_url": "",
            "submitted_at": None,
            "raw_metadata": {},
            "creator": {"username": "unknown"},
        }

    if story is None:
        warning(f"story_share message {msg.id} has no story_share attribute")
        return None

    story_id = str(getattr(story, "pk", "") or getattr(story, "id", "") or msg.id)
    creator_user = getattr(story, "user", None)
    creator_username = getattr(creator_user, "username", "unknown") if creator_user else "unknown"

    thumbnail_url = ""
    iv = getattr(story, "image_versions2", None)
    if iv:
        candidates = getattr(iv, "candidates", None) or []
        if candidates:
            thumbnail_url = str(getattr(candidates[0], "url", "") or "")

    return {
        "id": story_id,
        "content_type": "story",
        "dm_thread_id": thread_id,
        "reel_url": None,
        "creator_username": creator_username,
        "submitted_by": submitted_by,
        "caption": (getattr(story, "caption_text", None) or "").strip(),
        "audio_name": "",
        "audio_artist": "",
        "hashtags": [],
        "view_count": 0,
        "like_count": 0,
        "play_count": 0,
        "duration": getattr(story, "video_duration", None) or 0,
        "thumbnail_url": thumbnail_url,
        "submitted_at": None,
        "raw_metadata": {},
        "creator": {
            "username": creator_username,
            "full_name": getattr(creator_user, "full_name", None) if creator_user else None,
            "bio": None,
            "follower_count": None,
            "following_count": None,
            "media_count": None,
            "profile_pic_url": str(getattr(creator_user, "profile_pic_url", None) or "") if creator_user else "",
        },
    }


def extract_reel_metadata(
    msg: DirectMessage,
    thread_id: str,
    submitted_by: str,
) -> dict[str, Any] | None:
    """
    Extract metadata from any supported DM media message.
    Includes a 'content_type' key ('reel', 'carousel', 'photo') for the analyzer.
    """
    item_type = getattr(msg, "item_type", "") or ""

    if item_type == "xma_clip":
        return _extract_xma_clip_metadata(msg, thread_id, submitted_by)

    if item_type == "xma_media_share":
        return _extract_xma_media_share_metadata(msg, thread_id, submitted_by)

    content_type = get_content_type(msg)
    if content_type is None:
        return None

    media: Media | None = _resolve_media(msg)
    if media is None:
        warning(f"Could not resolve media from message {msg.id}")
        return None

    caption = _get_caption(media)
    hashtags = _extract_hashtags(caption)
    audio_name, audio_artist = _get_audio(media) if content_type == "reel" else ("", "")
    creator = _extract_creator(media)

    return {
        "id": str(media.pk),
        "content_type": content_type,
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
        "thumbnail_url": _get_thumbnail_url(media),
        "submitted_at": None,
        "raw_metadata": _safe_media_dict(media),
        "creator": creator,
    }


def extract_creator_from_media(media: Media) -> dict[str, Any]:
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
    return (getattr(media, "caption_text", None) or "").strip()


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


def _get_thumbnail_url(media: Media) -> str:
    # Reels/videos
    thumb = getattr(media, "thumbnail_url", None)
    if thumb:
        return str(thumb)
    # Photos and carousels
    iv = getattr(media, "image_versions2", None)
    if iv:
        candidates = getattr(iv, "candidates", None) or []
        if candidates:
            url = getattr(candidates[0], "url", None)
            if url:
                return str(url)
    # First carousel item
    resources = getattr(media, "resources", None) or []
    if resources:
        first = resources[0]
        iv = getattr(first, "image_versions2", None)
        if iv:
            candidates = getattr(iv, "candidates", None) or []
            if candidates:
                url = getattr(candidates[0], "url", None)
                if url:
                    return str(url)
    return ""


def _build_url(media: Media) -> str:
    code = getattr(media, "code", None)
    if code:
        return f"https://www.instagram.com/p/{code}/"
    return f"https://www.instagram.com/p/{media.pk}/"


def _extract_xma_clip_metadata(msg: DirectMessage, thread_id: str, submitted_by: str) -> dict[str, Any] | None:
    xma = getattr(msg, "xma_share", None)
    if xma is None:
        warning(f"xma_clip message {msg.id} has no xma_share")
        return None

    url = str(getattr(xma, "video_url", "") or "")
    id_match = re.search(r"[?&]id=(\d+)", url)
    if not id_match:
        warning(f"Could not extract media ID from xma_clip URL: {url[:120]}")
        return None
    media_id = id_match.group(1)

    code_match = re.search(r"/reel/([A-Za-z0-9_-]+)", url)
    reel_url = f"https://www.instagram.com/reel/{code_match.group(1)}/" if code_match else url

    return {
        "id": media_id,
        "content_type": "reel",
        "dm_thread_id": thread_id,
        "reel_url": reel_url,
        "creator_username": "unknown",
        "submitted_by": submitted_by,
        "caption": "",
        "audio_name": "",
        "audio_artist": "",
        "hashtags": [],
        "view_count": 0,
        "like_count": 0,
        "play_count": 0,
        "duration": 0,
        "thumbnail_url": "",
        "submitted_at": None,
        "raw_metadata": {},
        "creator": {"username": "unknown"},
    }


def _extract_xma_media_share_metadata(msg: DirectMessage, thread_id: str, submitted_by: str) -> dict[str, Any] | None:
    xma = getattr(msg, "xma_share", None)
    if xma is None:
        warning(f"xma_media_share message {msg.id} has no xma_share")
        return None

    video_url = str(getattr(xma, "video_url", "") or "")
    code_match = re.search(r"/p/([A-Za-z0-9_-]+)/", video_url)
    if not code_match:
        warning(f"xma_media_share {msg.id}: could not extract shortcode from url")
        return None

    shortcode = code_match.group(1)
    preview_url = str(getattr(xma, "preview_url", "") or "")

    return {
        "id": shortcode,  # non-numeric; _enrich_metadata resolves to pk via media_pk_from_code
        "content_type": "carousel",
        "dm_thread_id": thread_id,
        "reel_url": f"https://www.instagram.com/p/{shortcode}/",
        "creator_username": "unknown",
        "submitted_by": submitted_by,
        "caption": "",
        "audio_name": "",
        "audio_artist": "",
        "hashtags": [],
        "view_count": 0,
        "like_count": 0,
        "play_count": 0,
        "duration": 0,
        "thumbnail_url": preview_url,
        "submitted_at": None,
        "raw_metadata": {},
        "creator": {"username": "unknown"},
    }


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
