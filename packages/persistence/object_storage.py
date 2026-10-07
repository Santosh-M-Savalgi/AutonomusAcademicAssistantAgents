"""MinIO/S3-compatible object-storage client infrastructure."""

import asyncio
import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import BinaryIO

from minio import Minio
from urllib3 import PoolManager, Timeout


class ObjectLimitError(ValueError):
    """Downloaded object exceeded its configured bound."""


class ObjectIntegrityError(ValueError):
    """Downloaded object does not match trusted database metadata."""


@dataclass(frozen=True)
class ObjectStorageSettings:
    """Connection values needed by the MinIO client."""

    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool
    io_timeout_seconds: float | None = None


class ObjectStorage:
    """Owns a synchronous MinIO SDK client behind async health checks."""

    def __init__(self, settings: ObjectStorageSettings) -> None:
        self.bucket = settings.bucket
        self._http = (PoolManager(timeout=Timeout(connect=settings.io_timeout_seconds,
                                                  read=settings.io_timeout_seconds), retries=0)
                      if settings.io_timeout_seconds is not None else None)
        self.client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
            http_client=self._http,
        )

    def download_into(
        self, object_name: str, destination: BinaryIO, *, max_bytes: int,
        expected_size: int, expected_sha256: str,
    ) -> None:
        """Bounded synchronous stream for an isolated worker process; closes the response."""

        if expected_size > max_bytes:
            raise ObjectLimitError("Object exceeds configured limit")
        response = self.client.get_object(self.bucket, object_name)
        try:
            total, digest = 0, hashlib.sha256()
            deadline = time.monotonic() + 10
            while chunk := response.read(min(64 * 1024, max_bytes - total + 1)):
                if self._http is not None and time.monotonic() > deadline:
                    raise TimeoutError("Object download deadline")
                total += len(chunk)
                if total > max_bytes:
                    raise ObjectLimitError("Object exceeds configured limit")
                digest.update(chunk)
                destination.write(chunk)
            if total != expected_size or digest.hexdigest() != expected_sha256:
                raise ObjectIntegrityError("Source integrity mismatch")
            destination.seek(0)
        finally:
            response.close()
            response.release_conn()

    def read_artifact(self, key: str, *, max_bytes: int, sha256: str) -> bytes:
        """Read only bounded, checksum-addressed JSON; caller validates the namespace/schema."""
        response = self.client.get_object(self.bucket, key)
        try:
            chunks: list[bytes] = []
            total, deadline = 0, time.monotonic() + 10
            while chunk := response.read(min(65536, max_bytes - total + 1)):
                total += len(chunk)
                if total > max_bytes:
                    raise ObjectLimitError("Artifact exceeds configured limit")
                if time.monotonic() > deadline:
                    raise TimeoutError("Artifact read deadline")
                chunks.append(chunk)
            content = b"".join(chunks)
            if hashlib.sha256(content).hexdigest() != sha256:
                raise ObjectIntegrityError("Artifact checksum mismatch")
            return content
        finally:
            response.close()
            response.release_conn()

    async def check(self) -> None:
        """Verify authenticated MinIO connectivity without creating application data."""

        await asyncio.to_thread(self.client.list_buckets)

    async def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not already exist."""

        exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self.bucket)

    async def put_object(
        self,
        object_name: str,
        data: BinaryIO,
        size: int,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        """Upload a stream without reading the document into application memory."""

        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            object_name,
            data,
            size,
            content_type=content_type,
            metadata=dict(metadata or {}),
        )

    async def delete_object(self, object_name: str) -> None:
        """Delete a compensating object after a failed database transaction."""

        await asyncio.to_thread(self.client.remove_object, self.bucket, object_name)

    async def close(self) -> None:
        """Close the owned HTTP pool after in-flight operations have completed."""

        self.close_sync()

    def close_sync(self) -> None:
        if self._http is not None:
            self._http.clear()
