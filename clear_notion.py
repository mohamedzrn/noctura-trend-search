from dotenv import load_dotenv
load_dotenv()
import httpx
from config import config

headers = {
    "Authorization": f"Bearer {config.NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

r = httpx.post(
    f"https://api.notion.com/v1/databases/{config.NOTION_DATABASE_ID}/query",
    headers=headers,
    json={},
)
pages = r.json().get("results", [])
for page in pages:
    httpx.patch(
        f"https://api.notion.com/v1/pages/{page['id']}",
        headers=headers,
        json={"archived": True},
    )
print(f"Cleared {len(pages)} rows from Notion.")
