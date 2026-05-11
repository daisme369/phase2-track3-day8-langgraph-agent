"""Checkpointer adapter."""

from __future__ import annotations

import sqlite3
from typing import Any


def build_checkpointer(kind: str = "memory", database_url: str | None = None) -> Any | None:
    """Return a LangGraph checkpointer.

    Defaults to in-memory for offline local runs.
    """
    if kind == "none":
        return None
    if kind == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    if kind == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise RuntimeError(
                "SQLite checkpointer requires: pip install langgraph-checkpoint-sqlite"
            ) from exc
        db_path = (database_url or "checkpoints.db").replace("sqlite:///", "")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return SqliteSaver(conn=conn)
    if kind == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise RuntimeError(
                "Postgres checkpointer requires: pip install langgraph-checkpoint-postgres"
            ) from exc
        return PostgresSaver.from_conn_string(database_url or "")
    raise ValueError(f"Unknown checkpointer kind: {kind}")
