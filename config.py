"""Application configuration loaded from the environment."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "local-development-key-change-me")
    DATABASE = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "studymate.db"))
    AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")
    AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
    AI_BASE_URL = os.getenv("AI_BASE_URL", "")
    AI_API_KEY = os.getenv("AI_API_KEY", "")
    AI_DEMO_MODE = os.getenv("AI_DEMO_MODE", "false").lower() == "true"
    MAX_CONTENT_LENGTH = 1_000_000
    MAX_NOTES_CHARS = 20_000
