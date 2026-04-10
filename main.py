#!/usr/bin/env python3
"""
Noctura Trend Search
--------------------
Instagram Reel trend bot — send a reel to your bot's DM inbox
and get back niche intelligence powered by Claude.

Commands
--------
  start     Start polling your DM inbox for new reels
  report    Print the current niche profile summary
  trends    List recent trend analyses
"""

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

BANNER = """[bold magenta]
  Noctura Trend Search
  Instagram → Claude → Niche Intelligence
[/bold magenta]"""


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------

def cmd_start(args) -> None:
    """Validate config then launch the DM monitor loop."""
    from config import config

    try:
        config.validate()
    except EnvironmentError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(1)

    from instagram.monitor import Monitor

    monitor = Monitor()
    monitor.run()


def cmd_report(args) -> None:
    """Print the current niche profile."""
    from config import config
    from storage.db import Database
    from analysis.niche_builder import NicheBuilder

    db = Database()
    builder = NicheBuilder(db)
    builder.print_report()


def cmd_trends(args) -> None:
    """List recent trend analyses in a table."""
    from storage.db import Database

    db = Database()
    analyses = db.get_recent_analyses(limit=args.limit)

    if not analyses:
        console.print("[yellow]No trend analyses yet. Start the bot and submit some reels.[/yellow]")
        return

    table = Table(title=f"Recent Trend Analyses (last {len(analyses)})", show_header=True, header_style="bold cyan")
    table.add_column("Reel ID", style="dim", max_width=16)
    table.add_column("Niche", style="magenta")
    table.add_column("Sub-Niche", style="cyan")
    table.add_column("Audio Score", justify="center")
    table.add_column("Keywords", max_width=40)
    table.add_column("Analyzed At", style="dim", max_width=20)

    for a in analyses:
        keywords = a.get("keywords") or []
        kw_str = ", ".join(keywords[:4])
        if len(keywords) > 4:
            kw_str += " …"
        score = a.get("trending_audio_score") or 0
        score_str = _audio_score_bar(score)
        table.add_row(
            str(a.get("reel_id") or "")[:16],
            a.get("niche") or "—",
            a.get("sub_niche") or "—",
            score_str,
            kw_str,
            str(a.get("analyzed_at") or "")[:19],
        )

    console.print()
    console.print(table)


def cmd_analyze_url(args) -> None:
    """
    Manually analyze a reel by its Instagram URL.
    Useful for testing without the DM loop.
    """
    from config import config

    try:
        config.validate()
    except EnvironmentError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(1)

    from instagram.client import InstagramClient
    from instagram.extractor import _build_url, _get_audio, _get_caption, _extract_hashtags, _safe_media_dict
    from analysis.analyzer import TrendAnalyzer
    from analysis.niche_builder import NicheBuilder
    from storage.db import Database

    url: str = args.url
    # Extract shortcode from URL
    import re
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

    metadata = {
        "id": str(media.pk),
        "dm_thread_id": None,
        "reel_url": url,
        "caption": caption,
        "audio_name": audio_name,
        "audio_artist": audio_artist,
        "hashtags": _extract_hashtags(caption),
        "view_count": getattr(media, "view_count", 0) or 0,
        "like_count": getattr(media, "like_count", 0) or 0,
        "play_count": getattr(media, "play_count", 0) or 0,
        "duration": getattr(media, "video_duration", 0) or 0,
        "sender_username": "manual",
        "submitted_at": None,
        "raw_metadata": _safe_media_dict(media),
    }

    db = Database()
    db.save_reel(metadata)

    console.print("Running trend analysis …")
    analyzer = TrendAnalyzer()
    analysis = analyzer.analyze(metadata)

    if analysis is None:
        console.print("[red]Analysis failed.[/red]")
        sys.exit(1)

    db.save_analysis({**analysis, "reel_id": metadata["id"]})

    # Pretty-print the analysis
    console.print()
    console.print(Panel(
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
    builder.rebuild()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _audio_score_bar(score: int) -> str:
    score = max(0, min(10, score or 0))
    filled = "█" * score
    empty = "░" * (10 - score)
    return f"{filled}{empty}"


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
    p_start = subparsers.add_parser("start", help="Start the DM monitor loop")
    p_start.set_defaults(func=cmd_start)

    # report
    p_report = subparsers.add_parser("report", help="Print the niche profile summary")
    p_report.set_defaults(func=cmd_report)

    # trends
    p_trends = subparsers.add_parser("trends", help="List recent trend analyses")
    p_trends.add_argument(
        "--limit", type=int, default=10, help="Number of analyses to show (default: 10)"
    )
    p_trends.set_defaults(func=cmd_trends)

    # analyze
    p_analyze = subparsers.add_parser(
        "analyze", help="Manually analyze a reel by URL (no DM required)"
    )
    p_analyze.add_argument("url", help="Instagram reel URL")
    p_analyze.set_defaults(func=cmd_analyze_url)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
