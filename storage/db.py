"""
SQLite storage layer — data bank edition.

Tables
------
creators            — tracked Instagram creator profiles
reels               — raw reel submissions received via DM
trend_analyses      — Claude's structured analysis of each reel
creator_profiles    — per-creator rolling niche profile (one row per creator)
audio_bank          — deduplicated audio tracks with usage/trend data
keyword_bank        — deduplicated keywords with frequency and creator spread
processed_messages  — tracks which DM message IDs have been handled
"""

import json
import sqlite3
from datetime import datetime, timezone
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
            -- Tracked creators / clients
            CREATE TABLE IF NOT EXISTS creators (
                username        TEXT PRIMARY KEY,
                full_name       TEXT,
                bio             TEXT,
                follower_count  INTEGER,
                following_count INTEGER,
                media_count     INTEGER,
                profile_pic_url TEXT,
                first_seen_at   TEXT,
                last_seen_at    TEXT,
                total_reels     INTEGER DEFAULT 0
            );

            -- Raw reel submissions
            CREATE TABLE IF NOT EXISTS reels (
                id                  TEXT PRIMARY KEY,
                dm_thread_id        TEXT,
                reel_url            TEXT,
                creator_username    TEXT REFERENCES creators(username),
                submitted_by        TEXT,   -- who forwarded it to the bot
                caption             TEXT,
                audio_name          TEXT,
                audio_artist        TEXT,
                hashtags            TEXT,   -- JSON array
                view_count          INTEGER,
                like_count          INTEGER,
                play_count          INTEGER,
                duration            REAL,
                submitted_at        TEXT,
                raw_metadata        TEXT    -- JSON blob
            );

            -- Claude analyses
            CREATE TABLE IF NOT EXISTS trend_analyses (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                reel_id                 TEXT REFERENCES reels(id),
                creator_username        TEXT REFERENCES creators(username),
                niche                   TEXT,
                sub_niche               TEXT,
                trend_signals           TEXT,   -- JSON array
                content_style           TEXT,
                trending_audio_score    INTEGER,
                virality_indicators     TEXT,   -- JSON object
                keywords                TEXT,   -- JSON array
                niche_fit               TEXT,
                recommendation          TEXT,
                raw_response            TEXT,
                analyzed_at             TEXT
            );

            -- Per-creator rolling niche profiles
            CREATE TABLE IF NOT EXISTS creator_profiles (
                username            TEXT PRIMARY KEY REFERENCES creators(username),
                updated_at          TEXT,
                top_niches          TEXT,   -- JSON
                top_audio           TEXT,   -- JSON
                top_keywords        TEXT,   -- JSON
                content_patterns    TEXT,   -- JSON
                trend_momentum      TEXT,   -- JSON
                total_reels         INTEGER,
                profile_summary     TEXT
            );

            -- Global audio data bank
            CREATE TABLE IF NOT EXISTS audio_bank (
                audio_key           TEXT PRIMARY KEY,   -- "{name}||{artist}" normalised
                audio_name          TEXT,
                audio_artist        TEXT,
                usage_count         INTEGER DEFAULT 1,
                avg_trending_score  REAL DEFAULT 0,
                creator_count       INTEGER DEFAULT 1,  -- distinct creators using it
                first_seen_at       TEXT,
                last_seen_at        TEXT,
                creator_usernames   TEXT    -- JSON array of creators who used it
            );

            -- Global keyword data bank
            CREATE TABLE IF NOT EXISTS keyword_bank (
                keyword             TEXT PRIMARY KEY,
                usage_count         INTEGER DEFAULT 1,
                creator_count       INTEGER DEFAULT 1,
                niches              TEXT,   -- JSON array of niches it appears in
                first_seen_at       TEXT,
                last_seen_at        TEXT,
                creator_usernames   TEXT    -- JSON array
            );

            -- Processed DM messages (dedup)
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id      TEXT PRIMARY KEY,
                thread_id       TEXT,
                processed_at    TEXT
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Creators
    # ------------------------------------------------------------------

    def upsert_creator(self, creator: dict[str, Any]) -> None:
        username = creator["username"]
        existing = self._conn.execute(
            "SELECT total_reels FROM creators WHERE username = ?", (username,)
        ).fetchone()

        if existing:
            self._conn.execute(
                """
                UPDATE creators SET
                    full_name       = COALESCE(:full_name, full_name),
                    bio             = COALESCE(:bio, bio),
                    follower_count  = COALESCE(:follower_count, follower_count),
                    following_count = COALESCE(:following_count, following_count),
                    media_count     = COALESCE(:media_count, media_count),
                    profile_pic_url = COALESCE(:profile_pic_url, profile_pic_url),
                    last_seen_at    = :last_seen_at,
                    total_reels     = total_reels + 1
                WHERE username = :username
                """,
                {**creator, "last_seen_at": _now()},
            )
        else:
            self._conn.execute(
                """
                INSERT INTO creators
                    (username, full_name, bio, follower_count, following_count,
                     media_count, profile_pic_url, first_seen_at, last_seen_at, total_reels)
                VALUES
                    (:username, :full_name, :bio, :follower_count, :following_count,
                     :media_count, :profile_pic_url, :first_seen_at, :last_seen_at, 1)
                """,
                {
                    **creator,
                    "first_seen_at": _now(),
                    "last_seen_at": _now(),
                },
            )
        self._conn.commit()

    def get_all_creators(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM creators ORDER BY total_reels DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_creator(self, username: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM creators WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Reels
    # ------------------------------------------------------------------

    def save_reel(self, reel: dict[str, Any]) -> bool:
        try:
            self._conn.execute(
                """
                INSERT INTO reels
                    (id, dm_thread_id, reel_url, creator_username, submitted_by,
                     caption, audio_name, audio_artist, hashtags,
                     view_count, like_count, play_count, duration,
                     submitted_at, raw_metadata)
                VALUES
                    (:id, :dm_thread_id, :reel_url, :creator_username, :submitted_by,
                     :caption, :audio_name, :audio_artist, :hashtags,
                     :view_count, :like_count, :play_count, :duration,
                     :submitted_at, :raw_metadata)
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
            return False

    def get_sender_reel_count(self, submitted_by: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM reels WHERE submitted_by = ?", (submitted_by,)
        ).fetchone()
        return row[0] if row else 0

    def reel_exists(self, reel_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM reels WHERE id = ?", (reel_id,)
        ).fetchone()
        return row is not None

    def get_reels_for_creator(self, username: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT * FROM reels
            WHERE creator_username = ?
            ORDER BY submitted_at DESC
            LIMIT ?
            """,
            (username, limit),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("hashtags"):
                try:
                    d["hashtags"] = json.loads(d["hashtags"])
                except Exception:
                    pass
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Trend Analyses
    # ------------------------------------------------------------------

    def save_analysis(self, analysis: dict[str, Any]) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO trend_analyses
                (reel_id, creator_username, niche, sub_niche, trend_signals,
                 content_style, trending_audio_score, virality_indicators,
                 keywords, niche_fit, recommendation, raw_response, analyzed_at)
            VALUES
                (:reel_id, :creator_username, :niche, :sub_niche, :trend_signals,
                 :content_style, :trending_audio_score, :virality_indicators,
                 :keywords, :niche_fit, :recommendation, :raw_response, :analyzed_at)
            """,
            {
                **analysis,
                "trend_signals": json.dumps(analysis.get("trend_signals", [])),
                "virality_indicators": json.dumps(analysis.get("virality_indicators", {})),
                "keywords": json.dumps(analysis.get("keywords", [])),
                "analyzed_at": analysis.get("analyzed_at") or _now(),
            },
        )
        self._conn.commit()
        return cur.lastrowid

    def get_recent_analyses(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT ta.*, r.reel_url, r.submitted_by, r.audio_name, r.audio_artist
            FROM trend_analyses ta
            LEFT JOIN reels r ON ta.reel_id = r.id
            ORDER BY ta.analyzed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return _parse_analysis_rows(rows)

    def get_analyses_for_creator(self, username: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT ta.*, r.reel_url, r.audio_name, r.audio_artist
            FROM trend_analyses ta
            LEFT JOIN reels r ON ta.reel_id = r.id
            WHERE ta.creator_username = ?
            ORDER BY ta.analyzed_at DESC
            LIMIT ?
            """,
            (username, limit),
        ).fetchall()
        return _parse_analysis_rows(rows)

    def get_all_analyses(self, limit: int = 50) -> list[dict]:
        return self.get_recent_analyses(limit=limit)

    # ------------------------------------------------------------------
    # Creator Profiles
    # ------------------------------------------------------------------

    def save_creator_profile(self, username: str, profile: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO creator_profiles
                (username, updated_at, top_niches, top_audio, top_keywords,
                 content_patterns, trend_momentum, total_reels, profile_summary)
            VALUES (:username, :updated_at, :top_niches, :top_audio, :top_keywords,
                    :content_patterns, :trend_momentum, :total_reels, :profile_summary)
            ON CONFLICT(username) DO UPDATE SET
                updated_at       = excluded.updated_at,
                top_niches       = excluded.top_niches,
                top_audio        = excluded.top_audio,
                top_keywords     = excluded.top_keywords,
                content_patterns = excluded.content_patterns,
                trend_momentum   = excluded.trend_momentum,
                total_reels      = excluded.total_reels,
                profile_summary  = excluded.profile_summary
            """,
            {
                "username": username,
                "updated_at": _now(),
                "top_niches": json.dumps(profile.get("top_niches", [])),
                "top_audio": json.dumps(profile.get("top_audio", [])),
                "top_keywords": json.dumps(profile.get("top_keywords", [])),
                "content_patterns": json.dumps(profile.get("content_patterns", [])),
                "trend_momentum": json.dumps(profile.get("trend_momentum", {})),
                "total_reels": profile.get("total_reels", 0),
                "profile_summary": profile.get("profile_summary", ""),
            },
        )
        self._conn.commit()

    def get_creator_profile(self, username: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM creator_profiles WHERE username = ?", (username,)
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

    def get_all_creator_profiles(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM creator_profiles ORDER BY total_reels DESC"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for key in ("top_niches", "top_audio", "top_keywords", "content_patterns", "trend_momentum"):
                if d.get(key):
                    try:
                        d[key] = json.loads(d[key])
                    except Exception:
                        pass
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Audio Bank
    # ------------------------------------------------------------------

    def upsert_audio(self, audio_name: str, audio_artist: str, trending_score: int, creator_username: str) -> None:
        if not audio_name:
            return
        key = f"{audio_name.lower().strip()}||{(audio_artist or '').lower().strip()}"
        existing = self._conn.execute(
            "SELECT usage_count, avg_trending_score, creator_usernames FROM audio_bank WHERE audio_key = ?",
            (key,),
        ).fetchone()

        if existing:
            old_count = existing["usage_count"]
            old_avg = existing["avg_trending_score"] or 0
            new_avg = ((old_avg * old_count) + trending_score) / (old_count + 1)
            creators = json.loads(existing["creator_usernames"] or "[]")
            if creator_username not in creators:
                creators.append(creator_username)
            self._conn.execute(
                """
                UPDATE audio_bank SET
                    usage_count         = usage_count + 1,
                    avg_trending_score  = ?,
                    creator_count       = ?,
                    last_seen_at        = ?,
                    creator_usernames   = ?
                WHERE audio_key = ?
                """,
                (new_avg, len(creators), _now(), json.dumps(creators), key),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO audio_bank
                    (audio_key, audio_name, audio_artist, usage_count, avg_trending_score,
                     creator_count, first_seen_at, last_seen_at, creator_usernames)
                VALUES (?, ?, ?, 1, ?, 1, ?, ?, ?)
                """,
                (key, audio_name, audio_artist, trending_score, _now(), _now(),
                 json.dumps([creator_username])),
            )
        self._conn.commit()

    def get_trending_audio(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT * FROM audio_bank
            ORDER BY usage_count DESC, avg_trending_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("creator_usernames"):
                try:
                    d["creator_usernames"] = json.loads(d["creator_usernames"])
                except Exception:
                    pass
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Keyword Bank
    # ------------------------------------------------------------------

    def upsert_keywords(self, keywords: list[str], niche: str, creator_username: str) -> None:
        for kw in keywords:
            kw = kw.lower().strip()
            if not kw:
                continue
            existing = self._conn.execute(
                "SELECT usage_count, creator_usernames, niches FROM keyword_bank WHERE keyword = ?",
                (kw,),
            ).fetchone()
            if existing:
                creators = json.loads(existing["creator_usernames"] or "[]")
                niches = json.loads(existing["niches"] or "[]")
                if creator_username not in creators:
                    creators.append(creator_username)
                if niche and niche not in niches:
                    niches.append(niche)
                self._conn.execute(
                    """
                    UPDATE keyword_bank SET
                        usage_count         = usage_count + 1,
                        creator_count       = ?,
                        niches              = ?,
                        last_seen_at        = ?,
                        creator_usernames   = ?
                    WHERE keyword = ?
                    """,
                    (len(creators), json.dumps(niches), _now(), json.dumps(creators), kw),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO keyword_bank
                        (keyword, usage_count, creator_count, niches,
                         first_seen_at, last_seen_at, creator_usernames)
                    VALUES (?, 1, 1, ?, ?, ?, ?)
                    """,
                    (kw, json.dumps([niche] if niche else []), _now(), _now(),
                     json.dumps([creator_username])),
                )
        self._conn.commit()

    def get_trending_keywords(self, limit: int = 30) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT * FROM keyword_bank
            ORDER BY usage_count DESC, creator_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for key in ("creator_usernames", "niches"):
                if d.get(key):
                    try:
                        d[key] = json.loads(d[key])
                    except Exception:
                        pass
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Processed Messages (dedup)
    # ------------------------------------------------------------------

    def mark_message_processed(self, message_id: str, thread_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_messages (message_id, thread_id, processed_at) VALUES (?, ?, ?)",
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


# ------------------------------------------------------------------
# Shared helper
# ------------------------------------------------------------------

def _parse_analysis_rows(rows) -> list[dict]:
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
