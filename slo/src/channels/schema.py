"""Channel queue schema v1 (108.1; overview §3.1).

Migrations are additive: each slice adds a new ``user_version`` and never edits
past ones. This module owns only the v1 DDL and the migration entry point.
"""

from __future__ import annotations

import sqlite3

__all__ = ["SCHEMA_V1", "SCHEMA_VERSION", "migrate"]

SCHEMA_VERSION: int = 1
"""Current ``PRAGMA user_version`` this build migrates to."""

SCHEMA_V1: str = """
CREATE TABLE channels(
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    name         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE participants(
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL CHECK(kind IN ('user','agent','system')),
    name         TEXT NOT NULL,
    channel_id   TEXT REFERENCES channels(id),
    external_ref TEXT,
    status       TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
    last_seen_at TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE(channel_id, external_ref)
);

CREATE TABLE messages(
    id               TEXT PRIMARY KEY,
    agent_session_id TEXT NOT NULL,
    sender_id        TEXT NOT NULL REFERENCES participants(id),
    sender_name      TEXT NOT NULL,
    recipient_id     TEXT NOT NULL REFERENCES participants(id),
    recipient_name   TEXT NOT NULL,
    sent_at          TEXT NOT NULL,
    accepted_at      TEXT,
    message_contents TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    message_index    INTEGER NOT NULL,
    forced_at        TEXT,
    message_type     TEXT NOT NULL DEFAULT 'prompt'
                     CHECK(message_type IN ('prompt','note','notice','reply')),
    in_reply_to_id   TEXT REFERENCES messages(id),
    channel_id       TEXT REFERENCES channels(id),
    cancelled_at     TEXT,
    cancel_reason    TEXT,
    UNIQUE(agent_session_id, message_index)
);

CREATE INDEX inbound_pending  ON messages(recipient_id, accepted_at, cancelled_at, message_index);
CREATE INDEX outbound_pending ON messages(channel_id, recipient_id, accepted_at);
CREATE INDEX conversation     ON messages(agent_session_id, message_index);
"""
"""DDL for schema version 1: channels, participants, messages (overview §3.1)."""


def migrate(*, connection: sqlite3.Connection) -> None:
    """Bring the database up to the current schema version.

    Applies pending migrations in order and stamps ``PRAGMA user_version``.
    Version 0 → 1 creates all three tables and their indexes.

    Args:
        connection (sqlite3.Connection): Open database connection to migrate.
    """
    current: int = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current < 1:
        connection.executescript(SCHEMA_V1)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
