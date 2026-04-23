"""
Instagram client wrapper.

Handles login, session persistence, and re-authentication on expiry.
Uses instagrapi's private API under the hood.
"""

import json
import time
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    BadPassword,
    LoginRequired,
    ReloginAttemptExceeded,
    TwoFactorRequired,
)

from config import config
from utils.logger import error, info, success, warning


class InstagramClient:
    def __init__(self) -> None:
        self._cl = Client()
        self._cl.delay_range = [1, 3]  # polite request pacing
        self._session_path = Path(config.SESSION_FILE)
        self._logged_in = False
        if config.PROXY_URL:
            self._cl.set_proxy(config.PROXY_URL)
            info(f"Proxy configured: {config.PROXY_HOST}:{config.PROXY_PORT}")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self) -> None:
        """Login, reusing saved session when possible."""
        if self._session_path.exists():
            info(f"Loading session from {self._session_path}")
            try:
                self._cl.load_settings(self._session_path)
                self._cl.login(config.INSTAGRAM_USERNAME, config.INSTAGRAM_PASSWORD)
                self._logged_in = True
                success("Session restored from file.")
                return
            except Exception as exc:
                warning(f"Saved session invalid ({exc}), doing fresh login.")
                self._session_path.unlink(missing_ok=True)

        self._fresh_login()

    def _fresh_login(self) -> None:
        info(f"Logging in as @{config.INSTAGRAM_USERNAME} …")
        try:
            self._cl.login(config.INSTAGRAM_USERNAME, config.INSTAGRAM_PASSWORD)
        except TwoFactorRequired:
            code = input("Enter 2FA code: ").strip()
            self._cl.login(
                config.INSTAGRAM_USERNAME,
                config.INSTAGRAM_PASSWORD,
                verification_code=code,
            )
        except BadPassword:
            raise RuntimeError("Instagram password is incorrect.")
        except ReloginAttemptExceeded:
            raise RuntimeError(
                "Too many re-login attempts. Wait before trying again."
            )

        self._cl.dump_settings(self._session_path)
        self._logged_in = True
        success("Logged in and session saved.")

    def ensure_logged_in(self) -> None:
        """Re-login if session has expired."""
        if not self._logged_in:
            self.login()
            return
        try:
            # Lightweight ping to check session validity
            self._cl.get_timeline_feed()
        except LoginRequired:
            warning("Session expired. Re-authenticating …")
            self._session_path.unlink(missing_ok=True)
            self._fresh_login()

    # ------------------------------------------------------------------
    # Delegation
    # ------------------------------------------------------------------

    @property
    def raw(self) -> Client:
        """Direct access to the underlying instagrapi Client."""
        return self._cl
