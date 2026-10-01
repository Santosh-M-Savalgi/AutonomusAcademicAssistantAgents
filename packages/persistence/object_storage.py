"""MinIO/S3-compatible object-storage client infrastructure."""

import asyncio
from dataclasses import dataclass

from minio import Minio


@dataclass(frozen=True)
class ObjectStorageSettings:
    """Connection values needed by the MinIO client."""

    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool


class ObjectStorage:
    """Owns a synchronous MinIO SDK client behind async health checks."""

    def __init__(self, settings: ObjectStorageSettings) -> None:
        self.bucket = settings.bucket
        self.client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )

    async def check(self) -> None:
        """Verify authenticated MinIO connectivity without creating application data."""

        await asyncio.to_thread(self.client.list_buckets)

    async def close(self) -> None:
        """Keep a stable async shutdown interface for the runtime owner."""

        return None
