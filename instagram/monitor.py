"""
DM monitor — polls the bot's Instagram inbox for reels, carousels, and photos.

Adaptive polling: fast when active, backs off to 1 hour when idle.
Wakes up within 15s if a new message arrives during a long sleep.
"""

from __future__ import annotations

import time
from collections import defaultdict

from instagrapi.exceptions import LoginRequired

from config import config
from instagram.client import InstagramClient
from instagram.extractor import (
    extract_reel_metadata,
    extract_story_metadata,
    get_content_type,
    is_supported_message,
    is_wrong_type_message,
)
from storage.db import Database
from utils.logger import dim, error, info, success, warning


class Monitor:
    _MIN_SLEEP     = 15
    _MAX_SLEEP     = 3600
    _BACKOFF_FACTOR = 2

    def __init__(self) -> None:
        self.client = InstagramClient()
        self.db = Database()
        # tracks how many items each sender has sent this session
        self._session_counts: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.client.login()
        info(f"Monitoring DMs for @{config.INSTAGRAM_USERNAME} — Ctrl+C to stop")

        sleep_secs = self._MIN_SLEEP
        while True:
            try:
                found = self._poll()
                sleep_secs = self._MIN_SLEEP if found else min(sleep_secs * self._BACKOFF_FACTOR, self._MAX_SLEEP)
            except LoginRequired:
                warning("Session expired. Re-logging in …")
                self.client.login()
                sleep_secs = self._MIN_SLEEP
            except KeyboardInterrupt:
                info("Shutting down.")
                break
            except Exception as exc:
                error(f"Unexpected error during poll: {exc}")

            dim(f"Sleeping {sleep_secs}s …")
            # Sleep in 15s chunks — wakes up early if new messages arrive
            elapsed = 0
            while elapsed < sleep_secs:
                chunk = min(15, sleep_secs - elapsed)
                time.sleep(chunk)
                elapsed += chunk
                try:
                    if self._has_new_messages():
                        dim("Activity detected — waking up early.")
                        break
                except Exception:
                    break

    # ------------------------------------------------------------------
    # Poll cycle
    # ------------------------------------------------------------------

    def _poll(self) -> bool:
        cl = self.client.raw
        threads = list(cl.direct_threads(amount=20) or [])

        try:
            pending = cl.direct_pending_inbox(amount=20) or []
            for thread in pending:
                try:
                    cl.direct_thread_approve(thread.id)
                except Exception:
                    pass
            threads += pending
        except Exception as exc:
            warning(f"Could not fetch pending inbox: {exc}")

        if not threads:
            dim("No DM threads found.")
            return False

        found = False
        for thread in threads:
            try:
                if self._process_thread(thread):
                    found = True
            except Exception as exc:
                error(f"Error processing thread {thread.id}: {exc}")
        return found

    def _process_thread(self, thread) -> bool:
        thread_id = str(thread.id)
        messages = thread.messages or []
        found = False

        for msg in messages:
            msg_id = str(msg.id)

            if self.db.is_message_processed(msg_id):
                break

            # Skip messages sent by the bot itself
            if getattr(msg, "is_sent_by_viewer", False):
                self.db.mark_message_processed(msg_id, thread_id)
                continue

            sender = _sender_username(msg, thread)

            # Fallback: skip if sender is the bot account
            if sender.lower() == config.INSTAGRAM_USERNAME.lower():
                self.db.mark_message_processed(msg_id, thread_id)
                continue

            allowed = config.ALLOWED_SENDERS

            # Not on whitelist
            if allowed and sender.lower() not in allowed:
                self._send(thread_id, "This account is private. If you think you should have access, speak to your team.")
                self.db.mark_message_processed(msg_id, thread_id)
                continue

            # Story share — handle separately (download before expiry)
            item_type = getattr(msg, "item_type", "") or ""
            if item_type in {"story_share", "xma_story_share"}:
                info(f"Story from @{sender} in thread {thread_id}")
                self._handle_story_message(msg, thread_id, sender)
                self.db.mark_message_processed(msg_id, thread_id)
                found = True
                continue

            # Unsupported user-initiated content — respond and skip
            if is_wrong_type_message(msg) or item_type in {"text", "felix_share", "voice_media"}:
                self._send(thread_id, "That's not supported yet — forward reels and/or photos only please.")
                self.db.mark_message_processed(msg_id, thread_id)
                continue

            # Truly silent system messages (likes, action_log) — skip without reply
            if not is_supported_message(msg):
                self.db.mark_message_processed(msg_id, thread_id)
                continue

            info(f"New content from @{sender} in thread {thread_id} (type: {get_content_type(msg)})")
            self._handle_media_message(msg, thread_id, sender)
            self.db.mark_message_processed(msg_id, thread_id)
            found = True

        return found

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def _handle_media_message(self, msg, thread_id: str, sender: str) -> None:
        from analysis.analyzer import TrendAnalyzer
        from analysis.niche_builder import NicheBuilder

        # 1. Extract
        metadata = extract_reel_metadata(msg, thread_id, sender)
        if metadata is None:
            warning(f"Could not extract media from message {msg.id} (type={getattr(msg, 'item_type', '?')})")
            return

        # 2. Enrich
        metadata = self._enrich_metadata(metadata)

        creator = metadata.pop("creator", {})
        creator_username = metadata.get("creator_username") or "unknown"
        content_type = metadata.get("content_type", "reel")

        info(f"{content_type} from @{creator_username} (sent by @{sender})")

        # 3. Upsert creator
        if creator.get("username") and creator["username"] != "unknown":
            self.db.upsert_creator(creator)

        # 4. Save
        is_new_creator = self.db.get_creator_reel_count(creator_username) == 0
        inserted = self.db.save_reel(metadata)
        if not inserted:
            dim(f"Media {metadata['id']} already in DB.")
            return

        # 4b. Sync to Notion
        from notion.sync import NotionSync
        NotionSync().sync_reel(metadata)

        # 5. Send context-aware acknowledgment
        prior_count = self.db.get_sender_reel_count(sender) - 1  # -1 since we just saved
        self._session_counts[sender] += 1
        session_count = self._session_counts[sender]
        ack = _build_ack(prior_count, session_count, creator_username, is_new_creator, content_type)
        self._send(thread_id, ack)

        # 6. Analyse
        analyzer = TrendAnalyzer()
        analysis = analyzer.analyze(metadata)
        if analysis is None:
            error("Analysis returned None.")
            return

        self.db.save_analysis({
            **analysis,
            "reel_id": metadata["id"],
            "creator_username": creator_username,
        })

        # 7. Update banks
        audio_name = metadata.get("audio_name") or ""
        if audio_name:
            self.db.upsert_audio(
                audio_name,
                metadata.get("audio_artist") or "",
                analysis.get("trending_audio_score") or 0,
                creator_username,
            )
        keywords = analysis.get("keywords") or []
        if keywords:
            self.db.upsert_keywords(keywords, analysis.get("niche") or "", creator_username)

        # 8. Notable signal follow-up
        audio_score = analysis.get("trending_audio_score") or 0
        niche = analysis.get("niche") or ""
        if audio_score >= 8 and audio_name and niche:
            self._send(
                thread_id,
                f"Strong trending signal on this one — the audio is moving fast across {niche} content right now."
            )

        success(f"Logged — @{sender} | @{creator_username} | {niche} | {', '.join(keywords[:3])}")

        # 9. Rebuild profile
        NicheBuilder(self.db).rebuild(creator_username)

    def _handle_story_message(self, msg, thread_id: str, sender: str) -> None:
        from notion.sync import NotionSync

        metadata = extract_story_metadata(msg, thread_id, sender)
        if metadata is None:
            warning(f"Could not extract story from message {msg.id}")
            return

        creator = metadata.pop("creator", {})
        creator_username = metadata.get("creator_username") or "unknown"

        if creator.get("username") and creator["username"] != "unknown":
            self.db.upsert_creator(creator)

        inserted = self.db.save_reel(metadata)
        if not inserted:
            dim(f"Story {metadata['id']} already in DB.")
            return

        NotionSync().sync_story(metadata)

        self._send(thread_id, "Story saved.")
        success(f"Story logged — @{sender} | @{creator_username}")

    def _enrich_metadata(self, metadata: dict) -> dict:
        try:
            media_id = metadata["id"]
            if not str(media_id).isdigit():
                media_id = str(self.client.raw.media_pk_from_code(media_id))
                metadata["id"] = media_id
            media = self.client.raw.media_info(media_id)
            if media:
                from instagram.extractor import (
                    _get_audio, _get_caption, _extract_hashtags,
                    _build_url, _safe_media_dict, _extract_creator,
                )
                caption = _get_caption(media)
                audio_name, audio_artist = _get_audio(media) if metadata.get("content_type") == "reel" else ("", "")
                creator = _extract_creator(media)
                media_type = getattr(media, "media_type", None)
                if media_type == 8:
                    content_type = "carousel"
                elif media_type == 1:
                    content_type = "photo"
                else:
                    content_type = metadata.get("content_type", "reel")
                from instagram.extractor import _get_thumbnail_url
                metadata.update({
                    "content_type": content_type,
                    "reel_url": _build_url(media),
                    "caption": caption or metadata["caption"],
                    "audio_name": audio_name or metadata["audio_name"],
                    "audio_artist": audio_artist or metadata["audio_artist"],
                    "hashtags": _extract_hashtags(caption) or metadata["hashtags"],
                    "view_count": getattr(media, "view_count", None) or metadata["view_count"],
                    "like_count": getattr(media, "like_count", None) or metadata["like_count"],
                    "play_count": getattr(media, "play_count", None) or metadata["play_count"],
                    "duration": getattr(media, "video_duration", None) or metadata["duration"],
                    "thumbnail_url": _get_thumbnail_url(media) or metadata.get("thumbnail_url", ""),
                    "raw_metadata": _safe_media_dict(media),
                    "creator": creator,
                    "creator_username": creator["username"],
                })
        except Exception as exc:
            warning(f"Could not enrich metadata for {metadata['id']}: {exc}")
        return metadata

    def _has_new_messages(self) -> bool:
        threads = list(self.client.raw.direct_threads(amount=10) or [])
        for thread in threads:
            for msg in (thread.messages or [])[:1]:
                if not self.db.is_message_processed(str(msg.id)):
                    return True
        return False

    def _send(self, thread_id: str, text: str) -> None:
        try:
            self.client.raw.direct_send(text, thread_ids=[thread_id])
        except Exception as exc:
            warning(f"Could not send message to thread {thread_id}: {exc}")


# ------------------------------------------------------------------
# Message builder
# ------------------------------------------------------------------

def _build_ack(prior_count: int, session_count: int, creator_username: str = "unknown", is_new_creator: bool = False, content_type: str = "reel") -> str:
    label = {"reel": "Reel", "carousel": "Carousel", "photo": "Photo"}.get(content_type, "Content")
    if prior_count == 0:
        return "Logged. I'll start building your content profile from here — keep sending reels as you come across them and I'll do the rest."
    if session_count > 0 and session_count % 5 == 0:
        return f"Logged {session_count} reels. Your profile is updating."
    if is_new_creator:
        return f"New creator logged — @{creator_username} added to your profile."
    return f"{label} from @{creator_username} has been stored."


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _sender_username(msg, thread) -> str:
    user_id = getattr(msg, "user_id", None)
    if user_id and hasattr(thread, "users"):
        for user in thread.users:
            if str(getattr(user, "pk", "")) == str(user_id):
                return getattr(user, "username", str(user_id))
    return str(user_id or "unknown")
