# Noctura Trend Search

An Instagram Reel trend intelligence bot. Send a reel to your bot's DM inbox — Claude analyzes it for trend signals and builds a running niche profile over time.

## How it works

```
You send a reel via DM
        ↓
Bot polls inbox (every 60s)
        ↓
Extracts: audio, hashtags, engagement, caption
        ↓
Claude analyzes trend signals
        ↓
Stored in SQLite + niche profile rebuilt
```

## Setup

```bash
# 1. Clone and install
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env with your Instagram bot account + Anthropic API key
```

## Commands

| Command | Description |
|---------|-------------|
| `python main.py start` | Start the DM polling loop |
| `python main.py creators` | List all tracked creators and their top niche |
| `python main.py profile <username>` | Full niche profile for a specific creator |
| `python main.py bank` | Global trend data bank (audio + keywords across all creators) |
| `python main.py trends` | List recent trend analyses |
| `python main.py trends --creator <username>` | Filter analyses by creator |
| `python main.py analyze <url>` | Manually analyze a reel by URL (no DM required) |

## Configuration

Copy `.env.example` to `.env` and fill in your values.

### Required

| Variable | Description |
|----------|-------------|
| `INSTAGRAM_USERNAME` | Username of the bot Instagram account (the one that receives DMs) |
| `INSTAGRAM_PASSWORD` | Password for the bot account |
| `ANTHROPIC_API_KEY` | Your Claude API key — get it from console.anthropic.com |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `ALLOWED_SENDERS` | Comma-separated Instagram usernames allowed to DM reels to the bot (blank = accept from anyone). Example: `user1,user2` | blank |
| `POLL_INTERVAL_SECONDS` | How often to check DMs (seconds) | `60` |
| `SESSION_FILE` | Path to save the Instagram session (avoids re-login on restart) | `session.json` |
| `DB_PATH` | SQLite database file | `trends.db` |

### Proxy (optional)

Required if Instagram blocks direct connections from your server. Tested with [DataImpulse](https://dataimpulse.com) residential proxies.

| Variable | Description | Default |
|----------|-------------|---------|
| `PROXY_HOST` | Proxy hostname | blank |
| `PROXY_PORT` | Proxy port | `823` |
| `PROXY_USERNAME` | Proxy username | blank |
| `PROXY_PASSWORD` | Proxy password | blank |

## What Claude extracts per reel

- **Niche + sub-niche** — primary content category
- **Trend signals** — what makes this reel timely
- **Audio score** — trending potential of the audio (1–10)
- **Virality indicators** — hook strength, shareability, engagement pattern
- **Keywords** — 5–10 niche-defining keywords
- **Recommendation** — one actionable content tip

## Per-creator profiles

Every creator whose reel is submitted gets their own niche profile, rebuilt after each new reel:

- Top niches by frequency
- Trending audio tracks used by that creator
- Top keywords
- Content style patterns
- Trend momentum (rising / stable / falling per niche)
- Claude-written prose strategy summary

## Global trend data bank

Aggregates intelligence across all creators:

- **Audio bank** — every unique audio track ranked by usage count, average trend score, and how many distinct creators used it
- **Keyword bank** — every keyword ranked by frequency, cross-referenced with which creators and niches it appears in

## Project structure

```
main.py                    ← CLI
config.py                  ← Settings (reads from .env)
instagram/
  client.py                ← instagrapi auth + session persistence
  extractor.py             ← extract reel + creator identity from DM messages
  monitor.py               ← polling loop with message deduplication
analysis/
  analyzer.py              ← Claude trend analysis (prompt caching)
  niche_builder.py         ← per-creator profiles + global data bank
storage/
  db.py                    ← SQLite (creators, reels, analyses, audio_bank, keyword_bank)
utils/
  logger.py                ← Rich-based console output
```

## Notes

- Uses [instagrapi](https://github.com/subzeroid/instagrapi) (unofficial Instagram private API)
- Instagram session is saved to `session.json` to avoid re-login on restart
- Claude API calls use prompt caching to reduce token costs
- All data stored locally in SQLite — nothing leaves your machine except API calls
