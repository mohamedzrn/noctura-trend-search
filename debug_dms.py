from dotenv import load_dotenv
load_dotenv()

from instagram.client import InstagramClient

client = InstagramClient()
client.login()

cl = client.raw
threads = cl.direct_threads(amount=10)

for thread in threads:
    for msg in (thread.messages or []):
        if getattr(msg, 'item_type', '') == 'xma_clip':
            print("xma_clip message found — dumping all non-None attributes:")
            for attr in dir(msg):
                if attr.startswith('_'):
                    continue
                try:
                    val = getattr(msg, attr)
                    if val is not None and not callable(val):
                        print(f"  {attr}: {type(val).__name__} = {str(val)[:120]}")
                except Exception:
                    pass
