"""
Niche profile builder — per-creator edition.

After each new analysis, rebuilds the rolling niche profile for that specific
creator. Also exposes a global data bank view across all creators.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

import anthropic
from rich.panel import Panel
from rich.table import Table

from config import config
from storage.db import Database
from utils.logger import console, error, info, success, warning

_PROFILE_SYSTEM = """\
You are a content strategist analyzing Instagram Reel trend data for a specific creator.
Based on the aggregated trend analyses provided, write a concise creator niche profile (3-5 sentences) that:
1. Identifies the creator's dominant content niche and its key characteristics.
2. Highlights the most important trend patterns in their content.
3. Recommends the top 2-3 content angles to pursue for this creator.

Be specific, actionable, and direct. No bullet points — flowing prose only.
"""


class NicheBuilder:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # ------------------------------------------------------------------
    # Rebuild the niche profile for a specific creator
    # ------------------------------------------------------------------

    def rebuild(self, creator_username: str) -> None:
        analyses = self.db.get_analyses_for_creator(
            creator_username, limit=config.NICHE_PROFILE_WINDOW
        )
        if not analyses:
            warning(f"No analyses for @{creator_username} yet.")
            return

        top_niches = _top_values([a.get("niche") for a in analyses], n=5)
        top_audio = _top_values(
            [a.get("audio_name") for a in analyses if a.get("audio_name")], n=5
        )
        top_keywords = _top_values(
            [kw for a in analyses for kw in (a.get("keywords") or [])], n=10
        )
        content_patterns = _top_values(
            [a.get("content_style") for a in analyses if a.get("content_style")], n=5
        )
        trend_momentum = _calc_momentum(analyses)
        summary = self._generate_summary(creator_username, analyses, top_niches, top_keywords)

        self.db.save_creator_profile(
            creator_username,
            {
                "top_niches": top_niches,
                "top_audio": top_audio,
                "top_keywords": top_keywords,
                "content_patterns": content_patterns,
                "trend_momentum": trend_momentum,
                "total_reels": len(analyses),
                "profile_summary": summary,
            },
        )
        success(f"Profile updated for @{creator_username}.")

    # ------------------------------------------------------------------
    # Claude prose summary
    # ------------------------------------------------------------------

    def _generate_summary(
        self,
        creator_username: str,
        analyses: list[dict],
        top_niches: list[dict],
        top_keywords: list[dict],
    ) -> str:
        snippet = json.dumps(
            {
                "creator": creator_username,
                "total_reels": len(analyses),
                "top_niches": top_niches[:3],
                "top_keywords": top_keywords[:8],
                "recent_recommendations": [
                    a.get("recommendation") for a in analyses[:5] if a.get("recommendation")
                ],
                "recent_niche_fits": [
                    a.get("niche_fit") for a in analyses[:5] if a.get("niche_fit")
                ],
            },
            indent=2,
        )
        try:
            resp = self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": _PROFILE_SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": f"Creator trend data:\n{snippet}\n\nWrite the niche profile summary.",
                    }
                ],
            )
            return resp.content[0].text.strip()
        except anthropic.APIError as exc:
            error(f"Claude API error generating summary: {exc}")
            return "(summary unavailable)"

    # ------------------------------------------------------------------
    # Print per-creator report
    # ------------------------------------------------------------------

    def print_creator_report(self, username: str) -> None:
        creator = self.db.get_creator(username)
        profile = self.db.get_creator_profile(username)

        if not profile:
            console.print(f"[yellow]No profile yet for @{username}.[/yellow]")
            return

        title = f"@{username}"
        if creator and creator.get("full_name"):
            title += f"  ·  {creator['full_name']}"
        if creator and creator.get("follower_count"):
            title += f"  ·  {creator['follower_count']:,} followers"

        console.print()
        console.print(
            Panel(
                profile.get("profile_summary") or "(no summary)",
                title=f"[bold magenta]{title}[/bold magenta]",
                border_style="magenta",
            )
        )

        _print_ranked_table("Top Niches", profile.get("top_niches") or [], col="Niche", color="cyan")
        _print_ranked_table("Top Keywords", profile.get("top_keywords") or [], col="Keyword", color="green")
        _print_ranked_table("Trending Audio", profile.get("top_audio") or [], col="Track", color="yellow")

        momentum = profile.get("trend_momentum") or {}
        if momentum:
            console.print()
            console.print("[bold]Trend Momentum[/bold]")
            for niche, direction in momentum.items():
                arrow = "↑" if direction == "rising" else ("↓" if direction == "falling" else "→")
                color = "green" if direction == "rising" else ("red" if direction == "falling" else "white")
                console.print(f"  [{color}]{arrow}[/{color}] {niche}")

        console.print()
        console.print(
            f"[dim]Based on {profile.get('total_reels', 0)} reels | "
            f"Updated {profile.get('updated_at', 'n/a')}[/dim]"
        )

    # ------------------------------------------------------------------
    # Print all creators overview
    # ------------------------------------------------------------------

    def print_creators_overview(self) -> None:
        creators = self.db.get_all_creators()
        profiles = {p["username"]: p for p in self.db.get_all_creator_profiles()}

        if not creators:
            console.print("[yellow]No creators tracked yet. Start the bot and submit some reels.[/yellow]")
            return

        table = Table(
            title="Tracked Creators",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Username", style="cyan")
        table.add_column("Full Name")
        table.add_column("Followers", justify="right")
        table.add_column("Reels", justify="right")
        table.add_column("Top Niche", style="magenta")
        table.add_column("Top Keywords", max_width=35)
        table.add_column("Last Seen", style="dim", max_width=12)

        for c in creators:
            username = c["username"]
            profile = profiles.get(username, {})
            top_niches = profile.get("top_niches") or []
            top_niche = top_niches[0]["value"] if top_niches else "—"
            top_keywords = profile.get("top_keywords") or []
            kw_str = ", ".join(k["value"] for k in top_keywords[:3])
            followers = c.get("follower_count")
            followers_str = f"{followers:,}" if followers else "—"
            last_seen = str(c.get("last_seen_at") or "")[:10]

            table.add_row(
                f"@{username}",
                c.get("full_name") or "—",
                followers_str,
                str(c.get("total_reels") or 0),
                top_niche,
                kw_str or "—",
                last_seen,
            )

        console.print()
        console.print(table)

    # ------------------------------------------------------------------
    # Print global data bank
    # ------------------------------------------------------------------

    def print_data_bank(self) -> None:
        console.print()
        console.print(Panel(
            "Cross-creator trend intelligence — audio tracks, keywords, and niches "
            "ranked by usage across all tracked creators.",
            title="[bold cyan]Global Trend Data Bank[/bold cyan]",
            border_style="cyan",
        ))

        # Trending audio
        audio = self.db.get_trending_audio(limit=15)
        if audio:
            table = Table(title="Trending Audio", show_header=True, header_style="bold yellow")
            table.add_column("#", style="dim", width=4)
            table.add_column("Track", style="yellow")
            table.add_column("Artist")
            table.add_column("Uses", justify="right")
            table.add_column("Avg Score", justify="right")
            table.add_column("Creators", justify="right")
            for i, a in enumerate(audio, 1):
                table.add_row(
                    str(i),
                    a.get("audio_name") or "—",
                    a.get("audio_artist") or "—",
                    str(a.get("usage_count") or 0),
                    f"{a.get('avg_trending_score') or 0:.1f}",
                    str(a.get("creator_count") or 0),
                )
            console.print()
            console.print(table)

        # Trending keywords
        keywords = self.db.get_trending_keywords(limit=20)
        if keywords:
            table = Table(title="Trending Keywords", show_header=True, header_style="bold green")
            table.add_column("#", style="dim", width=4)
            table.add_column("Keyword", style="green")
            table.add_column("Uses", justify="right")
            table.add_column("Creators", justify="right")
            table.add_column("Niches", max_width=40)
            for i, k in enumerate(keywords, 1):
                niches = k.get("niches") or []
                niches_str = ", ".join(niches[:3])
                table.add_row(
                    str(i),
                    k.get("keyword") or "—",
                    str(k.get("usage_count") or 0),
                    str(k.get("creator_count") or 0),
                    niches_str or "—",
                )
            console.print()
            console.print(table)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _top_values(values: list[Any], n: int = 5) -> list[dict]:
    cleaned = [str(v).strip() for v in values if v]
    counts = Counter(cleaned)
    return [{"value": v, "count": c} for v, c in counts.most_common(n)]


def _calc_momentum(analyses: list[dict]) -> dict[str, str]:
    if len(analyses) < 10:
        return {}
    recent = [a.get("niche") for a in analyses[:10] if a.get("niche")]
    prior = [a.get("niche") for a in analyses[10:20] if a.get("niche")]
    recent_counts = Counter(recent)
    prior_counts = Counter(prior)
    momentum: dict[str, str] = {}
    for niche in set(recent_counts) | set(prior_counts):
        r = recent_counts.get(niche, 0)
        p = prior_counts.get(niche, 0)
        momentum[niche] = "rising" if r > p else ("falling" if r < p else "stable")
    return momentum


def _print_ranked_table(title: str, items: list[dict], col: str, color: str) -> None:
    if not items:
        return
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column(col, style=color)
    table.add_column("Count", justify="right")
    for i, item in enumerate(items, 1):
        table.add_row(str(i), item.get("value", ""), str(item.get("count", "")))
    console.print()
    console.print(table)
