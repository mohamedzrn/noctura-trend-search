"""
One-off script: updates all Notion databases to use select-type properties
for Creator, Submitted By, and Content Type.
"""

import httpx
from config import config

_HEADERS = {
    "Authorization": f"Bearer {config.NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

_PATCH = {
    "properties": {
        "Creator":      {"select": {}},
        "Submitted By": {"select": {}},
        "Content Type": {"select": {}},
        "Summary":      {"rich_text": {}},
    }
}

databases = {
    "Fallback (Noctura Reels)": config.NOTION_DATABASE_ID,
    **{f"Creator: {k}": v for k, v in config.NOTION_CREATOR_DBS.items()},
}

for label, db_id in databases.items():
    if not db_id:
        print(f"SKIP {label} — no ID")
        continue
    r = httpx.patch(
        f"https://api.notion.com/v1/databases/{db_id}",
        headers=_HEADERS,
        json=_PATCH,
        timeout=10,
    )
    if r.status_code == 200:
        print(f"OK   {label}")
    else:
        print(f"FAIL {label} ({r.status_code}): {r.text[:200]}")
