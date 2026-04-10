"""
SQLite storage layer.

Tables
------
reels               — raw reel submissions received via DM
trend_analyses      — Claude's structured analysis of each reel
niche_profile       — rolling niche summary (one row, updated in-place)
processed_messages  — tracks which DM message IDs have been handled
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or config.DB_PATH
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _migrate(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reels (
                id              TEXT PRIMARY KEY,
                dm_thread_id    TEXT,
                reel_url        TEXT,
                caption         TEXT,
                audio_name      TEXT,
                audio_artist    TEXT,
                hashtags        TEXT,   -- JSON array
                view_count      INTEGER,
                like_count      INTEGER,
                play_count      INTEGER,
                duration        REAL,
                sender_username TEXT,
                submitted_at    TEXT,
                raw_metadata    TEXT    -- JSON blob
            );

            CREATE TABLE IF NOT EXISTS trend_analyses (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                reel_id             TEXT REFERENCES reels(id),
                niche               TEXT,
                sub_niche           TEXT,
                trend_signals       TEXT,   -- JSON array
                content_style       TEXT,
                trending_audio_score INTEGER,
                virality_indicators TEXT,   -- JSON object
                keywords            TEXT,   -- JSON array
                niche_fit           TEXT,
                recommendation      TEXT,
                raw_response        TEXT,
                analyzed_at         TEXT
            );

            CREATE TABLE IF NOT EXISTS niche_profile (
                id                      INTEGER PRIMARY KEY CHECK (id = 1),
                updated_at              TEXT,
                top_niches              TEXT,   -- JSON
                top_audio               TEXT,   -- JSON
                top_keywords            TEXT,   -- JSON
                content_patterns        TEXT,   -- JSON
                trend_momentum          TEXT,   -- JSON
                total_reels_analyzed    INTEGER,
                profile_summary         TEXT
            );

            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id  TEXT PRIMARY KEY,
                thread_id   TEXT,
                processed_at TEXT
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reels
    # ------------------------------------------------------------------

    def save_reel(self, reel: dict[str, Any]) -> bool:
        """Insert reel. Returns True if inserted, False if already exists."""
        try:
            self._conn.execute(
                """
                INSERT INTO reels
                    (id, dm_thread_id, reel_url, caption, audio_name, audio_artist,
                     hashtags, view_count, like_count, play_count, duration,
                     sender_username, submitted_at, raw_metadata)
                VALUES
                    (:id, :dm_thread_id, :reel_url, :caption, :audio_name, :audio_artist,
                     :hashtags, :view_count, :like_count, :play_count, :duration,
                     :sender_username, :submitted_at, :raw_metadata)
                """,
                {
                    **reel,
                    "hashtags": json.dumps(reel.get("hashtags", [])),
                    "raw_metadata": json.dumps(reel.get("raw_metadata", {})),
                    "submitted_at": reel.get("submitted_at") or _now(),
                },
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # already processed

    def reel_exists(self, reel_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM reels WHERE id = ?", (reel_id,)
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Trend Analyses
    # ------------------------------------------------------------------

    def save_analysis(self, analysis: dict[str, Any]) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO trend_analyses
                (reel_id, niche, sub_niche, trend_signals, content_style,
                 trending_audio_score, virality_indicators, keywords,
                 niche_fit, recommendation, raw_response, analyzed_at)
            VALUES
                (:reel_id, :niche, :sub_niche, :trend_signals, :content_style,
                 :trending_audio_score, :virality_indicators, :keywords,
                 :niche_fit, :recommendation, :raw_response, :analyzed_at)
            """,
            {
                **analysis,
                "trend_signals": json.dumps(analysis.get("trend_signals", [])),
                "virality_indicators": json.dumps(
                    analysis.get("virality_indicators", {})
                ),
                "keywords": json.dumps(analysis.get("keywords", [])),
                "analyzed_at": analysis.get("analyzed_at") or _now(),
            },
        )
        self._conn.commit()
        return cur.lastrowid

    def get_recent_analyses(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT ta.*, r.reel_url, r.sender_username, r.audio_name, r.audio_artist
            FROM trend_analyses ta
            LEFT JOIN reels r ON ta.reel_id = r.id
            ORDER BY ta.analyzed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for key in ("trend_signals", "virality_indicators", "keywords"):
                if d.get(key):
                    try:
                        d[key] = json.loads(d[key])
                    except Exception:
                        pass
            result.append(d)
        return result

    def get_all_analyses(self, limit: int = 50) -> list[dict]:
        return self.get_recent_analyses(limit=limit)

    # ------------------------------------------------------------------
    # Niche Profile
    # ------------------------------------------------------------------

    def save_niche_profile(self, profile: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO niche_profile
                (id, updated_at, top_niches, top_audio, top_keywords,
                 content_patterns, trend_momentum, total_reels_analyzed, profile_summary)
            VALUES (1, :updated_at, :top_niches, :top_audio, :top_keywords,
                    :content_patterns, :trend_momentum, :total_reels_analyzed, :profile_summary)
            ON CONFLICT(id) DO UPDATE SET
                updated_at              = excluded.updated_at,
                top_niches              = excluded.top_niches,
                top_audio               = excluded.top_audio,
                top_keywords            = excluded.top_keywords,
                content_patterns        = excluded.content_patterns,
                trend_momentum          = excluded.trend_momentum,
                total_reels_analyzed    = excluded.total_reels_analyzed,
                profile_summary         = excluded.profile_summary
            """,
            {
                **profile,
                "top_niches": json.dumps(profile.get("top_niches", [])),
                "top_audio": json.dumps(profile.get("top_audio", [])),
                "top_keywords": json.dumps(profile.get("top_keywords", [])),
                "content_patterns": json.dumps(profile.get("content_patterns", [])),
                "trend_momentum": json.dumps(profile.get("trend_momentum", {})),
                "updated_at": _now(),
            },
        )
        self._conn.commit()

    def get_niche_profile(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM niche_profile WHERE id = 1"
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("top_niches", "top_audio", "top_keywords", "content_patterns", "trend_momentum"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        return d

    # ------------------------------------------------------------------
    # Processed Messages (dedup)
    # ------------------------------------------------------------------

    def mark_message_processed(self, message_id: str, thread_id: str) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO processed_messages (message_id, thread_id, processed_at)
            VALUES (?, ?, ?)
            """,
            (message_id, thread_id, _now()),
        )
        self._conn.commit()

    def is_message_processed(self, message_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM processed_messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._conn.close()
