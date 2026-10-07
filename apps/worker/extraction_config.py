"""Extraction-specific limits; upload size/pages are supplied by shared Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExtractionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EXTRACTION_", env_file=".env", extra="ignore")

    timeout_seconds: float = Field(default=60, gt=0, le=600)
    max_output_bytes: int = Field(default=4 * 1024 * 1024, ge=1024, le=32 * 1024 * 1024)
    memory_mb: int = Field(default=512, ge=128, le=2048)
    minimum_useful_characters: int = Field(default=40, ge=0, le=10000)
