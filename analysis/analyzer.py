"""
Claude-powered trend analyzer.
Branches analysis prompt based on content type: reel, carousel, or photo.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import anthropic
import httpx

from config import config
from utils.logger import error, warning

_SYSTEM_PROMPT = """\
You are a social media content analyst. You analyze Instagram content metadata \
and extract structured intelligence about niches, trends, and creator style.

ALWAYS respond with valid JSON only. No markdown fences, no preamble.

JSON schema (all fields required):
{
  "niche": "string — primary niche",
  "sub_niche": "string — specific sub-category",
  "content_style": "string — format and style description",
  "trend_signals": ["array of strings"],
  "trending_audio_score": "integer 1-10 (reels only, else 0)",
  "virality_indicators": {
    "hook_strength": "string",
    "engagement_pattern": "string",
    "shareability": "string"
  },
  "keywords": ["5-10 keyword strings"],
  "niche_fit": "string",
  "recommendation": "string"
}
"""

_REEL_PROMPT_TEMPLATE = """\
Analyze this Instagram Reel:

Caption: {caption}
Hashtags: {hashtags}
Audio: {audio}
Views: {views}
Likes: {likes}
Duration: {duration}s
Creator: @{creator}

Focus on: niche, audio trend potential (score 1-10), content style, trend signals, keywords.
"""

_CAROUSEL_PROMPT_TEMPLATE = """\
Analyze this Instagram Carousel post:

Caption: {caption}
Hashtags: {hashtags}
Likes: {likes}
Creator: @{creator}

Focus on: niche, educational format preference, visual structure, caption style, keywords.
Set trending_audio_score to 0.
"""

_PHOTO_PROMPT_TEMPLATE = """\
Analyze this Instagram photo post:

Caption: {caption}
Hashtags: {hashtags}
Likes: {likes}
Creator: @{creator}

Focus on: niche, aesthetic style, visual taste, caption style the creator admires, keywords.
Set trending_audio_score to 0.
"""


_SUMMARY_PROMPT = (
    "Describe what is happening in this video in ONE sentence. "
    "Focus strictly on the visual content: people, actions, objects, setting, or concept shown. "
    "Be specific and visual. Under 20 words. Reply with the sentence only."
)


class TrendAnalyzer:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def generate_visual_summary(self, thumbnail_url: str, caption: str = "") -> str:
        if not thumbnail_url:
            return ""
        try:
            resp = httpx.get(thumbnail_url, timeout=10, follow_redirects=True)
            if resp.status_code != 200:
                return ""
            img_b64 = base64.standard_b64encode(resp.content).decode("utf-8")
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
            message = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=60,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": img_b64}},
                        {"type": "text", "text": _SUMMARY_PROMPT + (f"\nCaption hint: {caption[:100]}" if caption else "")},
                    ],
                }],
            )
            return message.content[0].text.strip()
        except Exception as exc:
            warning(f"Visual summary failed: {exc}")
            return ""

    def analyze(self, media: dict[str, Any]) -> dict[str, Any] | None:
        content_type = media.get("content_type", "reel")
        prompt = _build_prompt(media, content_type)
        raw = self._call_claude(prompt)
        if raw is None:
            return None
        return _parse_response(raw, media["id"])

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
                warning(f"Rate limited. Waiting {wait}s …")
                time.sleep(wait)
            except anthropic.APIError as exc:
                error(f"Claude API error (attempt {attempt + 1}): {exc}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_prompt(media: dict[str, Any], content_type: str) -> str:
    hashtags = " ".join(f"#{h}" for h in (media.get("hashtags") or []))
    caption = media.get("caption") or "(no caption)"
    likes = f"{media.get('like_count') or 0:,}"
    creator = media.get("creator_username") or "unknown"

    if content_type == "reel":
        audio = "(unknown / original audio)"
        if media.get("audio_name"):
            audio = f'"{media["audio_name"]}"'
            if media.get("audio_artist"):
                audio += f' by {media["audio_artist"]}'
        return _REEL_PROMPT_TEMPLATE.format(
            caption=caption,
            hashtags=hashtags or "(none)",
            audio=audio,
            views=f"{media.get('view_count') or 0:,}",
            likes=likes,
            duration=media.get("duration") or 0,
            creator=creator,
        )

    if content_type == "carousel":
        return _CAROUSEL_PROMPT_TEMPLATE.format(
            caption=caption,
            hashtags=hashtags or "(none)",
            likes=likes,
            creator=creator,
        )

    # photo
    return _PHOTO_PROMPT_TEMPLATE.format(
        caption=caption,
        hashtags=hashtags or "(none)",
        likes=likes,
        creator=creator,
    )


def _parse_response(raw: str, media_id: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        error(f"Failed to parse Claude response for {media_id}: {exc}")
        return None

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
