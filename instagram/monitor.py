"""
DM monitor — polls the bot's Instagram inbox for new reels.

Flow
----
1. Fetch the most recent DM threads.
2. For each thread, iterate messages newest-first.
3. Stop when we hit a message that's already been processed.
4. For every unseen reel message, run the full pipeline:
   extract → analyze → store → update niche profile.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from instagrapi.exceptions import ClientError, LoginRequired

from config import config
from instagram.client import InstagramClient
from instagram.extractor import extract_reel_metadata, is_reel_message
from storage.db import Database
from utils.logger import dim, error, info, success, warning

if TYPE_CHECKING:
    pass


class Monitor:
    def __init__(self) -> None:
        self.client = InstagramClient()
        self.db = Database()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the polling loop. Runs until interrupted."""
        self.client.login()
        info(
            f"Monitoring DMs for @{config.INSTAGRAM_USERNAME} "
            f"(polling every {config.POLL_INTERVAL_SECONDS}s) — Ctrl+C to stop"
        )
        while True:
            try:
                self._poll()
            except LoginRequired:
                warning("Session expired mid-poll. Re-logging in …")
                self.client.login()
            except KeyboardInterrupt:
                info("Shutting down.")
                break
            except Exception as exc:
                error(f"Unexpected error during poll: {exc}")
            dim(f"Sleeping {config.POLL_INTERVAL_SECONDS}s …")
            time.sleep(config.POLL_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Poll cycle
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        cl = self.client.raw
        threads = cl.direct_threads(amount=20)
        if not threads:
            dim("No DM threads found.")
            return

        for thread in threads:
            self._process_thread(thread)

    def _process_thread(self, thread) -> None:
        thread_id = str(thread.id)
        messages = thread.messages or []

        for msg in messages:
            msg_id = str(msg.id)

            if self.db.is_message_processed(msg_id):
                # Oldest processed message found — safe to stop
                break

            if not is_reel_message(msg):
                # Mark non-reel messages as seen so we skip them next cycle
                self.db.mark_message_processed(msg_id, thread_id)
                continue

            # Filter by whitelist if configured
            sender = _sender_username(msg, thread)
            allowed = config.ALLOWED_SENDERS
            if allowed and sender.lower() not in allowed:
                self.db.mark_message_processed(msg_id, thread_id)
                continue

            info(f"New reel from @{sender} in thread {thread_id}")
            self._handle_reel_message(msg, thread_id, sender)
            self.db.mark_message_processed(msg_id, thread_id)

    def _handle_reel_message(self, msg, thread_id: str, sender: str) -> None:
        from analysis.analyzer import TrendAnalyzer
        from analysis.niche_builder import NicheBuilder

        # 1. Extract metadata (includes creator identity)
        metadata = extract_reel_metadata(msg, thread_id, sender)
        if metadata is None:
            warning(f"Could not extract reel from message {msg.id}. Skipping.")
            return

        # 2. Enrich with full media info from the API
        metadata = self._enrich_metadata(metadata)

        creator = metadata.pop("creator", {})
        creator_username = metadata.get("creator_username") or "unknown"

        info(f"Reel from creator @{creator_username} (forwarded by @{sender})")

        # 3. Upsert creator into the data bank
        if creator.get("username") and creator["username"] != "unknown":
            self.db.upsert_creator(creator)

        # 4. Persist raw reel
        inserted = self.db.save_reel(metadata)
        if not inserted:
            dim(f"Reel {metadata['id']} already in DB. Skipping analysis.")
            return

        info(f"Reel {metadata['id']} saved. Running trend analysis …")

        # 5. Analyse with Claude
        analyzer = TrendAnalyzer()
        analysis = analyzer.analyze(metadata)
        if analysis is None:
            error("Analysis returned None. Skipping.")
            return

        self.db.save_analysis({
            **analysis,
            "reel_id": metadata["id"],
            "creator_username": creator_username,
        })

        # 6. Feed audio + keywords into the data banks
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

        success(
            f"Analysis complete — @{creator_username} | "
            f"Niche: {analysis.get('niche', 'unknown')} | "
            f"Keywords: {', '.join(keywords[:3])}"
        )

        # 7. Rebuild per-creator niche profile
        builder = NicheBuilder(self.db)
        builder.rebuild(creator_username)

        # 8. Send analysis results back to the sender via DM
        self._send_analysis_reply(thread_id, sender, creator_username, metadata, analysis)

    def _send_analysis_reply(
        self,
        thread_id: str,
        sender: str,
        creator_username: str,
        metadata: dict,
        analysis: dict,
    ) -> None:
        audio_score = analysis.get("trending_audio_score") or 0
        audio_bar = "█" * audio_score + "░" * (10 - audio_score)
        keywords = analysis.get("keywords") or []
        virality = analysis.get("virality_indicators") or {}
        audio_line = ""
        if metadata.get("audio_name"):
            audio_line = f"\n🎵 Audio: {metadata['audio_name']}"
            if metadata.get("audio_artist"):
                audio_line += f" — {metadata['audio_artist']}"

        msg = (
            f"✅ Reel Analysis — @{creator_username}\n"
            f"{'─' * 30}\n"
            f"📌 Niche: {analysis.get('niche', '—')}\n"
            f"   Sub-niche: {analysis.get('sub_niche', '—')}\n"
            f"🎨 Style: {analysis.get('content_style', '—')}\n"
            f"{audio_line}\n"
            f"🔥 Audio trend score: {audio_bar} {audio_score}/10\n"
            f"🏷️ Keywords: {', '.join(keywords[:6])}\n"
            f"{'─' * 30}\n"
            f"⚡ Hook: {virality.get('hook_strength', '—')}\n"
            f"📤 Shareability: {virality.get('shareability', '—')}\n"
            f"{'─' * 30}\n"
            f"💡 {analysis.get('recommendation', '—')}"
        )

        try:
            self.client.raw.direct_send(msg, thread_ids=[thread_id])
            success(f"Reply sent to @{sender} in thread {thread_id}")
        except Exception as exc:
            error(f"Failed to send DM reply to @{sender}: {exc}")

    def _enrich_metadata(self, metadata: dict) -> dict:
        """Attempt to pull richer data from media_info API call."""
        try:
            media = self.client.raw.media_info(metadata["id"])
            if media:
                from instagram.extractor import (
                    _get_audio, _get_caption, _extract_hashtags,
                    _build_url, _safe_media_dict, _extract_creator,
                )
                caption = _get_caption(media)
                audio_name, audio_artist = _get_audio(media)
                creator = _extract_creator(media)
                metadata.update(
                    {
                        "reel_url": _build_url(media),
                        "caption": caption or metadata["caption"],
                        "audio_name": audio_name or metadata["audio_name"],
                        "audio_artist": audio_artist or metadata["audio_artist"],
                        "hashtags": _extract_hashtags(caption) or metadata["hashtags"],
                        "view_count": getattr(media, "view_count", None) or metadata["view_count"],
                        "like_count": getattr(media, "like_count", None) or metadata["like_count"],
                        "play_count": getattr(media, "play_count", None) or metadata["play_count"],
                        "duration": getattr(media, "video_duration", None) or metadata["duration"],
                        "raw_metadata": _safe_media_dict(media),
                        "creator": creator,
                        "creator_username": creator["username"],
                    }
                )
        except Exception as exc:
            warning(f"Could not enrich metadata for reel {metadata['id']}: {exc}")
        return metadata


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
