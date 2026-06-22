"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _parse_origins(value: str) -> tuple[str, ...]:
    """Return a normalized, immutable list of configured CORS origins."""
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    tavily_api_key: str | None
    sqlite_db_path: Path
    chroma_db_path: Path
    allowed_origins: tuple[str, ...]

    syllabus_model: str = "gemini-2.5-flash-lite"
    search_model: str = "gemini-2.5-flash-lite"
    tutor_model: str = "gemini-2.5-flash"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768


settings = Settings(
    gemini_api_key=os.getenv("GEMINI_API_KEY"),
    tavily_api_key=os.getenv("TAVILY_API_KEY"),
    sqlite_db_path=Path(os.getenv("SQLITE_DB_PATH", "./data/aaa.db")),
    chroma_db_path=Path(os.getenv("CHROMA_DB_PATH", "./chroma_store")),
    allowed_origins=_parse_origins(
        os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
    ),
)
