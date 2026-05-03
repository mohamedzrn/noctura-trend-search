from dotenv import load_dotenv
load_dotenv()

from notion_client import Client
from config import config

client = Client(auth=config.NOTION_TOKEN)
db_id = config.NOTION_DATABASE_ID

print("=== Step 1: Retrieve database ===")
db = client.databases.retrieve(database_id=db_id)
props = db.get("properties") or {}
print(f"Properties found: {list(props.keys()) or '(none)'}")
print(f"data_sources: {db.get('data_sources')}")
print(f"parent: {db.get('parent')}")

print("\n=== Step 2: Add one test property ===")
try:
    result = client.databases.update(
        database_id=db_id,
        properties={"_test_col": {"rich_text": {}}},
    )
    props_after = result.get("properties") or {}
    print(f"Properties after update: {list(props_after.keys()) or '(none)'}")
except Exception as e:
    print(f"Update failed: {e}")

print("\n=== Step 3: Create test page ===")
try:
    page = client.pages.create(
        parent={"database_id": db_id},
        properties={"Name": {"title": [{"text": {"content": "test"}}]}},
    )
    print(f"Page created: {page.get('id')}")
except Exception as e:
    print(f"Page create failed: {e}")
