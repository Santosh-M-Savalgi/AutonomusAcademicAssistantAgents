"""Runtime resource assembly for the API process."""

from dataclasses import dataclass

from apps.api.config import Settings
from packages.persistence import Database, ObjectStorage, ObjectStorageSettings, RedisClient


@dataclass
class RuntimeResources:
    """Connections owned by one API process."""

    database: Database
    redis: RedisClient
    object_storage: ObjectStorage

    async def close(self) -> None:
        """Close resources in reverse ownership order."""

        await self.object_storage.close()
        await self.redis.close()
        await self.database.close()


def create_runtime_resources(settings: Settings) -> RuntimeResources:
    """Build clients without making network calls during application startup."""

    return RuntimeResources(
        database=Database(settings.database_url),
        redis=RedisClient(settings.redis_url),
        object_storage=ObjectStorage(
            ObjectStorageSettings(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key.get_secret_value(),
                bucket=settings.minio_bucket,
                secure=settings.minio_secure,
            )
        ),
    )
