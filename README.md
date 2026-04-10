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
| `python main.py report` | Print the current niche profile |
| `python main.py trends` | List recent trend analyses |
| `python main.py analyze <url>` | Manually analyze a reel by URL |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `INSTAGRAM_USERNAME` | Bot account username | required |
| `INSTAGRAM_PASSWORD` | Bot account password | required |
| `ANTHROPIC_API_KEY` | Claude API key | required |
| `POLL_INTERVAL_SECONDS` | How often to check DMs | `60` |
| `ALLOWED_SENDER` | Only process reels from this username (blank = everyone) | blank |
| `SESSION_FILE` | Path to save Instagram session | `session.json` |
| `DB_PATH` | SQLite database file | `trends.db` |

## What Claude extracts per reel

- **Niche + sub-niche** — primary content category
- **Trend signals** — what makes this reel timely
- **Audio score** — trending potential of the audio (1–10)
- **Virality indicators** — hook strength, shareability, engagement pattern
- **Keywords** — 5–10 niche-defining keywords
- **Recommendation** — one actionable content tip

## Niche profile

After each new reel, the niche profile is rebuilt from the last 50 analyses:

- Top niches by frequency
- Trending audio tracks
- Top keywords
- Content style patterns
- Trend momentum (rising / stable / falling per niche)
- Claude-written prose strategy summary

## Project structure

```
main.py                    ← CLI
config.py                  ← Settings (reads from .env)
instagram/
  client.py                ← instagrapi auth + session persistence
  extractor.py             ← extract reel metadata from DM messages
  monitor.py               ← polling loop with message deduplication
analysis/
  analyzer.py              ← Claude trend analysis (prompt caching)
  niche_builder.py         ← aggregate analyses into niche profile
storage/
  db.py                    ← SQLite storage
utils/
  logger.py                ← Rich-based console output
```

## Notes

- Uses [instagrapi](https://github.com/subzeroid/instagrapi) (unofficial Instagram private API)
- Instagram session is saved to `session.json` to avoid re-login on restart
- Claude API calls use prompt caching to reduce token costs
- All data stored locally in SQLite — nothing leaves your machine except API calls
