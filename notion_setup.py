"""
Run once to set up Notion database columns.
Usage: py notion_setup.py
"""

from dotenv import load_dotenv
load_dotenv()

from notion_client import Client
from notion_client.errors import APIResponseError
from config import config

client = Client(auth=config.NOTION_TOKEN)

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

db = client.databases.retrieve(database_id=config.NOTION_DATABASE_ID)
existing = set((db.get("properties") or {}).keys())
print(f"Existing columns: {existing or '(none)'}")

to_add = {k: v for k, v in PROPERTIES.items() if k not in existing}

if to_add:
    try:
        result = client.databases.update(
            database_id=config.NOTION_DATABASE_ID,
            properties=to_add,
        )
        created = set((result.get("properties") or {}).keys()) - existing
        print(f"Added columns: {', '.join(to_add)}")
        print(f"Confirmed in DB: {created or '(check manually)'}")
    except APIResponseError as e:
        print(f"Error: {e}")
else:
    print("All columns already exist.")

print("Done.")
