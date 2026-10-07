"""Shared immutable JSON artifact storage using the existing MinIO conventions."""

import hashlib
from io import BytesIO

from minio.error import S3Error

from packages.persistence.object_storage import ObjectStorage


def persist_json(storage: ObjectStorage, key: str, content: bytes, max_bytes: int) -> str:
    if len(content) > max_bytes:
        raise ValueError("Artifact size limit exceeded")
    digest = hashlib.sha256(content).hexdigest()
    try:
        existing = BytesIO()
        storage.download_into(key, existing, max_bytes=max_bytes,
                              expected_size=len(content), expected_sha256=digest)
    except S3Error as error:
        if error.code != "NoSuchKey":
            raise
        storage.client.put_object(storage.bucket, key, BytesIO(content), len(content),
                                  content_type="application/json", metadata={"sha256": digest})
    return f"minio://{storage.bucket}/{key}"
