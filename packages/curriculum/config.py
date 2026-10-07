"""Shared bounded draft processing configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DraftSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRAFT_", env_file=".env", extra="ignore")
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    artifact_max_bytes: int = Field(default=4 * 1024 * 1024, ge=1024, le=32 * 1024 * 1024)
    max_sections: int = Field(default=128, ge=1, le=256)
    unit_output_max_bytes: int = Field(default=65536, ge=1024, le=262144)
