"""Bounded SDK I/O shared by worker and draft-read API; cancellation leaves no live owner."""

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from packages.persistence.object_storage import ObjectStorage, ObjectStorageSettings

P = ParamSpec("P")
T = TypeVar("T")


def bounded_storage(endpoint: str, access_key: str, secret_key: str,
                    bucket: str, secure: bool) -> ObjectStorage:
    return ObjectStorage(ObjectStorageSettings(endpoint, access_key, secret_key, bucket, secure,
                                              io_timeout_seconds=2))


async def storage_call[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # SDK calls have socket/deadline bounds. Reap before the owner closes its HTTP pool.
        await asyncio.gather(task, return_exceptions=True)
        raise
