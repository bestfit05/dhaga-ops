from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    model_mode: str
    gemini_api_key: str
    gemini_fast_model: str
    gemini_creative_model: str
    database_url: str
    sqlite_path: Path
    is_vercel: bool

    @property
    def live_models_enabled(self) -> bool:
        return self.model_mode.lower() == "live" and bool(self.gemini_api_key)

    @property
    def persistent_database_configured(self) -> bool:
        return bool(self.database_url)


def get_settings() -> Settings:
    sqlite_path = Path(os.getenv("SQLITE_PATH", "var/dhaga_os.db"))
    if not sqlite_path.is_absolute():
        sqlite_path = ROOT_DIR / sqlite_path
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://") :]
    elif database_url.startswith("postgresql://") and "+" not in database_url.split(":", 1)[0]:
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]

    return Settings(
        model_mode=os.getenv("MODEL_MODE", "demo").strip().lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_fast_model=os.getenv("GEMINI_FAST_MODEL", "gemini-3.5-flash-lite").strip(),
        gemini_creative_model=os.getenv("GEMINI_CREATIVE_MODEL", "gemini-3.8-flash").strip(),
        database_url=database_url,
        sqlite_path=sqlite_path,
        is_vercel=bool(os.getenv("VERCEL")),
    )
