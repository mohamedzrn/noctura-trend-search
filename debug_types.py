"""
Prints item_type and available attributes for recent DM messages.
Run once to identify what types carousels and stories actually come through as.
"""
from instagram.client import InstagramClient

cl = InstagramClient()
cl.login()
raw = cl.raw

threads = list(raw.direct_threads(amount=5) or [])
for thread in threads:
    print(f"\n--- Thread {thread.id} ---")
    for msg in (thread.messages or [])[:5]:
        item_type = getattr(msg, "item_type", "?")
        user_id   = getattr(msg, "user_id", "?")
        media_attrs = []
        for attr in ("clip", "media_share", "reel_share", "story_share", "xma_share"):
            val = getattr(msg, attr, None)
            if val is not None:
                media_attrs.append(f"{attr}={type(val).__name__}")
        media_type = None
        for attr in ("clip", "media_share", "reel_share"):
            val = getattr(msg, attr, None)
            if val is not None:
                media_type = getattr(val, "media_type", None)
                break
        print(f"  msg {msg.id} | type={item_type} | user={user_id} | media_type={media_type} | {', '.join(media_attrs) or 'no media attrs'}")
