"""SQLite connection management and schema initialization."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS student_profile (
    student_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    current_topic_index INTEGER NOT NULL DEFAULT 0 CHECK (current_topic_index >= 0),
    session_count INTEGER NOT NULL DEFAULT 0 CHECK (session_count >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topic_record (
    topic_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    topic_name TEXT NOT NULL,
    subtopics_json TEXT NOT NULL DEFAULT '[]',
    difficulty TEXT NOT NULL CHECK (
        difficulty IN ('beginner', 'intermediate', 'advanced')
    ),
    prerequisite TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'in_progress', 'taught', 'weak', 'strong', 'critical')
    ),
    quiz_score REAL NOT NULL DEFAULT 0 CHECK (quiz_score BETWEEN 0 AND 100),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    inferred_gap TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES student_profile(student_id) ON DELETE CASCADE,
    UNIQUE (student_id, position)
);

CREATE INDEX IF NOT EXISTS idx_topic_record_student
    ON topic_record(student_id, position);
CREATE INDEX IF NOT EXISTS idx_topic_record_status
    ON topic_record(student_id, status);
"""


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a configured SQLite connection with safe application defaults."""
    path = Path(db_path) if db_path is not None else settings.sqlite_db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


@contextmanager
def get_connection(
    db_path: str | Path | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a transaction-scoped connection and close it after use."""
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(db_path: str | Path | None = None) -> None:
    """Create the structured persistence schema if it does not exist."""
    with get_connection(db_path) as connection:
        connection.executescript(SCHEMA)
