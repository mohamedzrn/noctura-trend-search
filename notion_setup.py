"""
Run once to set up the Noctura Reels database.
Usage: py notion_setup.py
"""

from dotenv import load_dotenv
load_dotenv()

from notion_client import Client
from config import config

PARENT_PAGE_ID = "34dd7f3d741f8004bcd0ddf32cf1ad3c"

PROPERTIES = {
    "Reel URL":      {"url": {}},
    "Creator":       {"rich_text": {}},
    "Caption":       {"rich_text": {}},
    "Hashtags":      {"rich_text": {}},
    "Audio":         {"rich_text": {}},
    "Views":         {"number": {"format": "number"}},
    "Likes":         {"number": {"format": "number"}},
    "Plays":         {"number": {"format": "number"}},
    "Duration (s)":  {"number": {"format": "number"}},
    "Submitted By":  {"rich_text": {}},
    "Logged At":     {"date": {}},
}

import httpx

db_id = config.NOTION_DATABASE_ID
token = config.NOTION_TOKEN
headers = {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

print(f"Adding properties to database {db_id}...")
r = httpx.patch(
    f"https://api.notion.com/v1/databases/{db_id}",
    headers=headers,
    json={"properties": PROPERTIES},
)
print(f"Update status: {r.status_code}")
if r.status_code != 200:
    print(f"Error: {r.text}")
else:
    props = list((r.json().get("properties") or {}).keys())
    print(f"Properties in DB: {props}")

print("\nVerifying with test page...")
r2 = httpx.post(
    "https://api.notion.com/v1/pages",
    headers=headers,
    json={
        "parent": {"database_id": db_id},
        "properties": {
            "Name":    {"title": [{"text": {"content": "setup-test"}}]},
            "Creator": {"rich_text": [{"text": {"content": "test"}}]},
        },
    },
)
if r2.status_code == 200:
    page_id = r2.json().get("id")
    httpx.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=headers, json={"archived": True})
    print("Verification passed — database is ready.")
else:
    print(f"Verification failed: {r2.text[:300]}")
