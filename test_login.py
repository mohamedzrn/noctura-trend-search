import sys
from dotenv import load_dotenv
load_dotenv()

from instagrapi import Client
from config import config

print(f"Logging in as @{config.INSTAGRAM_USERNAME} ...")
if config.PROXY_URL:
    print(f"Using proxy: {config.PROXY_HOST}:{config.PROXY_PORT}")

cl = Client()
cl.delay_range = [1, 3]
if config.PROXY_URL:
    cl.set_proxy(config.PROXY_URL)

def challenge_handler(username, choice):
    print(f"\nInstagram sent a verification code to: {choice}")
    code = input("Enter the 6-digit code: ").strip()
    return code

cl.challenge_code_handler = challenge_handler

try:
    cl.login(config.INSTAGRAM_USERNAME, config.INSTAGRAM_PASSWORD)
    cl.dump_settings("session.json")
    print("\nLOGIN SUCCESSFUL - session.json saved")
    print(f"Logged in as: {cl.account_info().username}")
except Exception as e:
    print(f"\nLOGIN FAILED: {e}")
    sys.exit(1)
