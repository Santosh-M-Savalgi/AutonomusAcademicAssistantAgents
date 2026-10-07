"""Worker-only environment configuration, independent of FastAPI."""

from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.domain.enums import JobLane


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=".env", extra="ignore")

    enabled: bool = True
    concurrency: int = Field(default=2, ge=1, le=32)
    poll_seconds: float = Field(default=2, gt=0, le=60)
    lease_seconds: float = Field(default=60, gt=0, le=3600)
    heartbeat_seconds: float = Field(default=15, gt=0, le=1200)
    reaper_seconds: float = Field(default=15, gt=0, le=3600)
    retry_base_seconds: float = Field(default=2, gt=0, le=3600)
    retry_max_seconds: float = Field(default=300, gt=0, le=86400)
    shutdown_grace_seconds: float = Field(default=30, ge=0, le=300)
    io_timeout_seconds: float = Field(default=5, gt=0, le=60)
    lanes: tuple[JobLane, ...] = (JobLane.INTERACTIVE, JobLane.PREFETCH, JobLane.BATCH)

    @model_validator(mode="after")
    def validate_timing(self) -> Self:
        if self.heartbeat_seconds * 3 > self.lease_seconds:
            raise ValueError("Heartbeat interval must be at most one third of the lease")
        if self.io_timeout_seconds > self.heartbeat_seconds:
            raise ValueError("I/O timeout must not exceed heartbeat interval")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("Maximum retry delay must be at least the base delay")
        if not self.lanes or len(set(self.lanes)) != len(self.lanes):
            raise ValueError("Worker lanes must be nonempty and unique")
        return self
