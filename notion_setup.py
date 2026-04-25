"""
Run once to set up Notion database columns.
Usage: py notion_setup.py
"""

from dotenv import load_dotenv
load_dotenv()

from notion_client import Client
from config import config

client = Client(auth=config.NOTION_TOKEN)

PROPERTIES = {
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
print("Response keys:", list(db.keys()))
print("Object type:", db.get("object"))
existing = set(db.get("properties", {}).keys())

to_add = {k: v for k, v in PROPERTIES.items() if k not in existing}

if to_add:
    client.databases.update(
        database_id=config.NOTION_DATABASE_ID,
        properties=to_add,
    )
    print(f"Added {len(to_add)} columns: {', '.join(to_add)}")
else:
    print("All columns already exist.")

print("Notion database is ready.")
