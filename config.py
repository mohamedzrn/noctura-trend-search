import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Instagram
    INSTAGRAM_USERNAME: str = os.getenv("INSTAGRAM_USERNAME", "")
    INSTAGRAM_PASSWORD: str = os.getenv("INSTAGRAM_PASSWORD", "")
    SESSION_FILE: str = os.getenv("SESSION_FILE", "session.json")
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    ALLOWED_SENDER: str = os.getenv("ALLOWED_SENDER", "")  # legacy single-user

    @property
    def ALLOWED_SENDERS(self) -> set[str]:
        """Returns the full set of whitelisted Instagram usernames."""
        raw = os.getenv("ALLOWED_SENDERS", self.ALLOWED_SENDER)
        if not raw:
            return set()
        return {u.strip().lstrip("@").lower() for u in raw.split(",") if u.strip()}

    # Proxy
    PROXY_HOST: str = os.getenv("PROXY_HOST", "")
    PROXY_PORT: str = os.getenv("PROXY_PORT", "823")
    PROXY_USERNAME: str = os.getenv("PROXY_USERNAME", "")
    PROXY_PASSWORD: str = os.getenv("PROXY_PASSWORD", "")

    @property
    def PROXY_URL(self) -> str | None:
        if self.PROXY_HOST and self.PROXY_USERNAME:
            return f"http://{self.PROXY_USERNAME}:{self.PROXY_PASSWORD}@{self.PROXY_HOST}:{self.PROXY_PORT}"
        return None

    # Claude
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = "claude-opus-4-6"

    # Storage
    DB_PATH: str = os.getenv("DB_PATH", "trends.db")

    # How many recent analyses to include when building the niche profile
    NICHE_PROFILE_WINDOW: int = 50

    def validate(self) -> None:
        missing = []
        if not self.INSTAGRAM_USERNAME:
            missing.append("INSTAGRAM_USERNAME")
        if not self.INSTAGRAM_PASSWORD:
            missing.append("INSTAGRAM_PASSWORD")
        if not self.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Copy .env.example to .env and fill in your credentials."
            )


config = Config()
