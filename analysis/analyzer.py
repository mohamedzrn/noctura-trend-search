"""
Claude-powered trend analyzer.

Takes raw reel metadata and returns structured trend intelligence.
Uses prompt caching for the system prompt to reduce token cost.
"""

from __future__ import annotations

import json
import time
from typing import Any

import anthropic

from config import config
from utils.logger import error, warning

_SYSTEM_PROMPT = """\
You are a social media trend analyst specializing in Instagram Reels and short-form video content.
Your job is to analyze reel metadata and extract actionable trend intelligence.

Given metadata about an Instagram Reel (caption, audio, hashtags, engagement counts), you will:
1. Identify the primary content niche and sub-niche.
2. Extract specific trend signals — what makes this reel timely or viral-ready.
3. Score the audio's trending potential (1-10, where 10 = viral audio everyone is using).
4. Identify virality indicators: hook strength, shareability, engagement pattern.
5. Extract 5-10 content keywords that define this reel's niche.
6. Explain how this reel fits or shapes a content niche strategy.
7. Give one actionable recommendation for someone building content in this niche.

ALWAYS respond with valid JSON only. No markdown fences, no preamble, no explanation outside the JSON.

JSON schema:
{
  "niche": "string — primary niche (e.g. 'fitness', 'personal finance', 'aesthetic lifestyle')",
  "sub_niche": "string — more specific category",
  "trend_signals": ["array of strings — specific trend signals observed"],
  "content_style": "string — describe the content style/format",
  "trending_audio_score": "integer 1-10",
  "virality_indicators": {
    "hook_strength": "string — weak / moderate / strong + brief reason",
    "engagement_pattern": "string — what type of engagement this likely drives",
    "shareability": "string — low / medium / high + brief reason"
  },
  "keywords": ["array of 5-10 keyword strings"],
  "niche_fit": "string — how this reel defines or reinforces a niche",
  "recommendation": "string — one concrete content creation tip based on this reel"
}
"""


class TrendAnalyzer:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def analyze(self, reel: dict[str, Any]) -> dict[str, Any] | None:
        """
        Analyze a reel's metadata with Claude.
        Returns parsed analysis dict, or None on failure.
        """
        prompt = _build_user_prompt(reel)
        raw_response = self._call_claude(prompt)
        if raw_response is None:
            return None
        return _parse_response(raw_response, reel["id"])

    # ------------------------------------------------------------------
    # Claude API call with prompt caching
    # ------------------------------------------------------------------

    def _call_claude(self, user_prompt: str, retries: int = 3) -> str | None:
        for attempt in range(retries):
            try:
                response = self._client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=1024,
                    system=[
                        {
                            "type": "text",
                            "text": _SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return response.content[0].text
            except anthropic.RateLimitError:
                wait = 2 ** attempt * 5
                warning(f"Rate limited by Claude API. Waiting {wait}s …")
                time.sleep(wait)
            except anthropic.APIError as exc:
                error(f"Claude API error (attempt {attempt + 1}): {exc}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_user_prompt(reel: dict[str, Any]) -> str:
    hashtags_str = " ".join(f"#{h}" for h in (reel.get("hashtags") or []))
    audio_line = ""
    if reel.get("audio_name"):
        audio_line = f"Audio: \"{reel['audio_name']}\""
        if reel.get("audio_artist"):
            audio_line += f" by {reel['audio_artist']}"
    else:
        audio_line = "Audio: (unknown / original audio)"

    lines = [
        "Analyze this Instagram Reel:",
        "",
        f"Caption: {reel.get('caption') or '(no caption)'}",
        f"Hashtags: {hashtags_str or '(none)'}",
        audio_line,
        f"View count: {reel.get('view_count') or 0:,}",
        f"Like count: {reel.get('like_count') or 0:,}",
        f"Play count: {reel.get('play_count') or 0:,}",
        f"Duration: {reel.get('duration') or 0}s",
        f"Posted by: @{reel.get('sender_username') or 'unknown'}",
    ]
    return "\n".join(lines)


def _parse_response(raw: str, reel_id: str) -> dict[str, Any] | None:
    raw = raw.strip()
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        error(f"Failed to parse Claude response as JSON for reel {reel_id}: {exc}")
        error(f"Raw response: {raw[:200]}")
        return None

    # Normalise types
    try:
        data["trending_audio_score"] = int(data.get("trending_audio_score") or 0)
    except (ValueError, TypeError):
        data["trending_audio_score"] = 0

    if not isinstance(data.get("trend_signals"), list):
        data["trend_signals"] = []
    if not isinstance(data.get("keywords"), list):
        data["keywords"] = []
    if not isinstance(data.get("virality_indicators"), dict):
        data["virality_indicators"] = {}

    data["raw_response"] = raw
    return data
