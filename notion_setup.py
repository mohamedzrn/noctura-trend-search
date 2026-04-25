"""
Run once to create the Noctura Reels database inside the shared Notion page.
Usage: py notion_setup.py
"""

from dotenv import load_dotenv
load_dotenv()

from notion_client import Client
from config import config

PARENT_PAGE_ID = "34dd7f3d741f8004bcd0ddf32cf1ad3c"

client = Client(auth=config.NOTION_TOKEN)

print("Creating Noctura Reels database...")
db = client.databases.create(
    parent={"type": "page_id", "page_id": PARENT_PAGE_ID},
    title=[{"type": "text", "text": {"content": "Noctura Reels"}}],
    properties={
        "Name":          {"title": {}},
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
    },
)

db_id = db["id"]
print(f"Database created: {db_id}")
print(f"Add this to your .env: NOTION_DATABASE_ID={db_id.replace('-', '')}")
