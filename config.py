"""Application configuration loaded from the environment."""
import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    DATABASE = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "studymate.db"))
    AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")
    AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
    AI_BASE_URL = os.getenv("AI_BASE_URL", "")
    AI_API_KEY = os.getenv("AI_API_KEY", "")
    AI_DEMO_MODE = os.getenv("AI_DEMO_MODE", "false").lower() == "true"
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    MAIL_FROM = os.getenv("MAIL_FROM", "")
    SESSION_COOKIE_SECURE = os.getenv(
        "SESSION_COOKIE_SECURE", "true" if os.getenv("RENDER") else "false"
    ).lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    MAX_CONTENT_LENGTH = 1_000_000
    MAX_NOTES_CHARS = 20_000
