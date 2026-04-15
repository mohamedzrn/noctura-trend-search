#!/usr/bin/env python3
"""
Noctura Trend Search
--------------------
Instagram Reel trend bot — send a reel to your bot's DM inbox
and get back per-creator niche intelligence powered by Claude.

Commands
--------
  start               Start polling your DM inbox for new reels
  dashboard           Launch the web dashboard (localhost:8080)
  creators            List all tracked creators and their profiles
  profile <username>  Show the niche profile for a specific creator
  bank                Show the global trend data bank (audio, keywords)
  trends              List recent trend analyses
  analyze <url>       Manually analyze a reel by URL (no DM required)
"""

import argparse
import re
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

BANNER = """[bold magenta]
  Noctura Trend Search
  Instagram → Claude → Per-Creator Niche Intelligence
[/bold magenta]"""


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------

def cmd_start(args) -> None:
    from config import config
    try:
        config.validate()
    except EnvironmentError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(1)
    from instagram.monitor import Monitor
    Monitor().run()


def cmd_dashboard(args) -> None:
    import uvicorn
    from config import config
    host = args.host
    port = args.port
    console.print(f"[cyan]Dashboard running at http://{host}:{port}[/cyan]  (Ctrl+C to stop)")
    uvicorn.run(
        "web.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="warning",
    )


def cmd_creators(args) -> None:
    from storage.db import Database
    from analysis.niche_builder import NicheBuilder
    db = Database()
    NicheBuilder(db).print_creators_overview()


def cmd_profile(args) -> None:
    from storage.db import Database
    from analysis.niche_builder import NicheBuilder
    db = Database()
    username = args.username.lstrip("@")
    NicheBuilder(db).print_creator_report(username)


def cmd_bank(args) -> None:
    from storage.db import Database
    from analysis.niche_builder import NicheBuilder
    db = Database()
    NicheBuilder(db).print_data_bank()


def cmd_trends(args) -> None:
    from storage.db import Database
    db = Database()
    username = args.creator.lstrip("@") if args.creator else None
    if username:
        analyses = db.get_analyses_for_creator(username, limit=args.limit)
        title = f"Trend Analyses for @{username} (last {len(analyses)})"
    else:
        analyses = db.get_recent_analyses(limit=args.limit)
        title = f"Recent Trend Analyses (last {len(analyses)})"

    if not analyses:
        console.print("[yellow]No trend analyses yet. Start the bot and submit some reels.[/yellow]")
        return

    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Creator", style="cyan")
    table.add_column("Niche", style="magenta")
    table.add_column("Sub-Niche")
    table.add_column("Audio", justify="center", max_width=12)
    table.add_column("Keywords", max_width=38)
    table.add_column("Analyzed At", style="dim", max_width=19)

    for a in analyses:
        keywords = a.get("keywords") or []
        kw_str = ", ".join(keywords[:4])
        if len(keywords) > 4:
            kw_str += " …"
        table.add_row(
            f"@{a.get('creator_username') or '—'}",
            a.get("niche") or "—",
            a.get("sub_niche") or "—",
            _audio_score_bar(a.get("trending_audio_score") or 0),
            kw_str,
            str(a.get("analyzed_at") or "")[:19],
        )

    console.print()
    console.print(table)


def cmd_analyze_url(args) -> None:
    """Manually analyze a reel by URL — no DM required."""
    from config import config
    try:
        config.validate()
    except EnvironmentError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(1)

    from instagram.client import InstagramClient
    from instagram.extractor import (
        _build_url, _get_audio, _get_caption,
        _extract_hashtags, _safe_media_dict, _extract_creator,
    )
    from analysis.analyzer import TrendAnalyzer
    from analysis.niche_builder import NicheBuilder
    from storage.db import Database

    url: str = args.url
    match = re.search(r"/(reel|p)/([A-Za-z0-9_-]+)", url)
    if not match:
        console.print(f"[red]Could not parse reel URL:[/red] {url}")
        sys.exit(1)

    shortcode = match.group(2)
    console.print(f"Fetching reel [cyan]{shortcode}[/cyan] …")

    client = InstagramClient()
    client.login()

    try:
        media = client.raw.media_info_by_code(shortcode)
    except Exception as exc:
        console.print(f"[red]Failed to fetch reel:[/red] {exc}")
        sys.exit(1)

    caption = _get_caption(media)
    audio_name, audio_artist = _get_audio(media)
    creator = _extract_creator(media)
    creator_username = creator["username"]

    console.print(f"Original creator: [cyan]@{creator_username}[/cyan]")

    metadata = {
        "id": str(media.pk),
        "dm_thread_id": None,
        "reel_url": url,
        "creator_username": creator_username,
        "submitted_by": "manual",
        "caption": caption,
        "audio_name": audio_name,
        "audio_artist": audio_artist,
        "hashtags": _extract_hashtags(caption),
        "view_count": getattr(media, "view_count", 0) or 0,
        "like_count": getattr(media, "like_count", 0) or 0,
        "play_count": getattr(media, "play_count", 0) or 0,
        "duration": getattr(media, "video_duration", 0) or 0,
        "submitted_at": None,
        "raw_metadata": _safe_media_dict(media),
    }

    db = Database()
    if creator_username != "unknown":
        db.upsert_creator(creator)
    db.save_reel(metadata)

    console.print("Running trend analysis …")
    analyzer = TrendAnalyzer()
    analysis = analyzer.analyze(metadata)

    if analysis is None:
        console.print("[red]Analysis failed.[/red]")
        sys.exit(1)

    db.save_analysis({**analysis, "reel_id": metadata["id"], "creator_username": creator_username})

    if audio_name:
        db.upsert_audio(audio_name, audio_artist, analysis.get("trending_audio_score") or 0, creator_username)
    if analysis.get("keywords"):
        db.upsert_keywords(analysis["keywords"], analysis.get("niche") or "", creator_username)

    console.print()
    console.print(Panel(
        f"[bold]Creator:[/bold] @{creator_username}\n"
        f"[bold]Niche:[/bold] {analysis.get('niche')}\n"
        f"[bold]Sub-niche:[/bold] {analysis.get('sub_niche')}\n"
        f"[bold]Content style:[/bold] {analysis.get('content_style')}\n"
        f"[bold]Audio score:[/bold] {_audio_score_bar(analysis.get('trending_audio_score', 0))} "
        f"({analysis.get('trending_audio_score')}/10)\n"
        f"[bold]Keywords:[/bold] {', '.join(analysis.get('keywords') or [])}\n\n"
        f"[bold]Niche fit:[/bold] {analysis.get('niche_fit')}\n\n"
        f"[bold]Recommendation:[/bold] {analysis.get('recommendation')}",
        title="[magenta]Trend Analysis[/magenta]",
        border_style="magenta",
    ))

    builder = NicheBuilder(db)
    builder.rebuild(creator_username)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _audio_score_bar(score: int) -> str:
    score = max(0, min(10, score or 0))
    return "█" * score + "░" * (10 - score)


# ------------------------------------------------------------------
# CLI wiring
# ------------------------------------------------------------------

def main() -> None:
    console.print(BANNER)

    parser = argparse.ArgumentParser(
        prog="noctura",
        description="Instagram Reel trend intelligence bot",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # start
    p = subparsers.add_parser("start", help="Start the DM monitor loop")
    p.set_defaults(func=cmd_start)

    # dashboard
    p = subparsers.add_parser("dashboard", help="Launch web dashboard (localhost:8080)")
    p.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    p.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    p.set_defaults(func=cmd_dashboard)

    # creators
    p = subparsers.add_parser("creators", help="List all tracked creators")
    p.set_defaults(func=cmd_creators)

    # profile
    p = subparsers.add_parser("profile", help="Show niche profile for a creator")
    p.add_argument("username", help="Instagram username (with or without @)")
    p.set_defaults(func=cmd_profile)

    # bank
    p = subparsers.add_parser("bank", help="Show the global trend data bank")
    p.set_defaults(func=cmd_bank)

    # trends
    p = subparsers.add_parser("trends", help="List recent trend analyses")
    p.add_argument("--limit", type=int, default=10, help="Number to show (default: 10)")
    p.add_argument("--creator", type=str, default=None, help="Filter by creator username")
    p.set_defaults(func=cmd_trends)

    # analyze
    p = subparsers.add_parser("analyze", help="Manually analyze a reel by URL")
    p.add_argument("url", help="Instagram reel URL")
    p.set_defaults(func=cmd_analyze_url)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
