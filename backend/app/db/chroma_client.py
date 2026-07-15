"""ChromaDB connectivity helpers."""

from __future__ import annotations

import chromadb

from app.core.config import get_settings

_chroma_client: chromadb.HttpClient | None = None


def get_chroma_client() -> chromadb.HttpClient:
    global _chroma_client
    if _chroma_client is None:
        settings = get_settings()
        _chroma_client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            ssl=settings.chroma_ssl,
        )
    return _chroma_client


async def check_chroma() -> tuple[bool, str]:
    try:
        client = get_chroma_client()
        client.heartbeat()
        return True, "ok"
    except Exception as exc:  # surfaced in readiness payload
        return False, str(exc)

