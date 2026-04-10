"""
Niche profile builder.

After each new analysis is stored, this module aggregates the last N analyses
into a rolling niche profile. It also asks Claude to write a prose summary
of the emerging niche.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

import anthropic
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import config
from storage.db import Database
from utils.logger import console, error, info, success, warning

_PROFILE_SYSTEM = """\
You are a content strategist analyzing a collection of Instagram Reel trend data.
Based on the aggregated trend analyses provided, write a concise niche profile (3-5 sentences) that:
1. Identifies the dominant content niche and its key characteristics.
2. Highlights the most important trend patterns.
3. Recommends the top 2-3 content angles to pursue.

Be specific, actionable, and direct. No bullet points — flowing prose only.
"""


class NicheBuilder:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # ------------------------------------------------------------------
    # Rebuild the niche profile from recent analyses
    # ------------------------------------------------------------------

    def rebuild(self) -> None:
        analyses = self.db.get_all_analyses(limit=config.NICHE_PROFILE_WINDOW)
        if not analyses:
            warning("No analyses yet — niche profile not built.")
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

        # Trend momentum: compare last 10 vs previous 10 by niche
        trend_momentum = _calc_momentum(analyses)

        # Ask Claude for the prose summary
        summary = self._generate_summary(analyses, top_niches, top_keywords)

        profile = {
            "top_niches": top_niches,
            "top_audio": top_audio,
            "top_keywords": top_keywords,
            "content_patterns": content_patterns,
            "trend_momentum": trend_momentum,
            "total_reels_analyzed": len(analyses),
            "profile_summary": summary,
        }
        self.db.save_niche_profile(profile)
        success("Niche profile updated.")

    # ------------------------------------------------------------------
    # Claude prose summary
    # ------------------------------------------------------------------

    def _generate_summary(
        self,
        analyses: list[dict],
        top_niches: list[dict],
        top_keywords: list[dict],
    ) -> str:
        snippet = json.dumps(
            {
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
                        "content": f"Trend data:\n{snippet}\n\nWrite the niche profile summary.",
                    }
                ],
            )
            return resp.content[0].text.strip()
        except anthropic.APIError as exc:
            error(f"Claude API error generating summary: {exc}")
            return "(summary unavailable)"

    # ------------------------------------------------------------------
    # Print report to terminal
    # ------------------------------------------------------------------

    def print_report(self) -> None:
        profile = self.db.get_niche_profile()
        if not profile:
            console.print("[yellow]No niche profile yet. Run the bot and submit some reels first.[/yellow]")
            return

        console.print()
        console.print(
            Panel(
                profile.get("profile_summary") or "(no summary)",
                title="[bold magenta]Niche Profile Summary[/bold magenta]",
                border_style="magenta",
            )
        )

        # Top niches
        _print_ranked_table(
            "Top Niches",
            profile.get("top_niches") or [],
            col="Niche",
            color="cyan",
        )

        # Top keywords
        _print_ranked_table(
            "Top Keywords",
            profile.get("top_keywords") or [],
            col="Keyword",
            color="green",
        )

        # Top audio
        _print_ranked_table(
            "Trending Audio",
            profile.get("top_audio") or [],
            col="Track",
            color="yellow",
        )

        # Momentum
        momentum = profile.get("trend_momentum") or {}
        if momentum:
            console.print()
            console.print("[bold]Trend Momentum (recent vs prior)[/bold]")
            for niche, direction in momentum.items():
                arrow = "↑" if direction == "rising" else ("↓" if direction == "falling" else "→")
                color = "green" if direction == "rising" else ("red" if direction == "falling" else "white")
                console.print(f"  [{color}]{arrow}[/{color}] {niche}")

        console.print()
        console.print(
            f"[dim]Based on {profile.get('total_reels_analyzed', 0)} reels | "
            f"Updated {profile.get('updated_at', 'n/a')}[/dim]"
        )


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
    all_niches = set(recent_counts) | set(prior_counts)
    momentum: dict[str, str] = {}
    for niche in all_niches:
        r = recent_counts.get(niche, 0)
        p = prior_counts.get(niche, 0)
        if r > p:
            momentum[niche] = "rising"
        elif r < p:
            momentum[niche] = "falling"
        else:
            momentum[niche] = "stable"
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
