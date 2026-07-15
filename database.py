"""
database.py — SQLite storage for library chunks.
Replaces ChromaDB. No external dependencies, built into Python.
Data persists between bot restarts — no need to reindex after every deploy.
"""

import sqlite3
from config import DB_PATH


def init_db() -> None:
    """Create table on first run."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id          TEXT PRIMARY KEY,
                text        TEXT NOT NULL,
                thread_name TEXT NOT NULL,
                thread_url  TEXT NOT NULL,
                category    TEXT NOT NULL,
                channel     TEXT NOT NULL
            )
        """)


def clear_db() -> None:
    """Wipe all chunks before a reindex."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM chunks")


def save_chunks(chunks: list[dict]) -> None:
    """Bulk-insert chunks."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO chunks "
            "(id, text, thread_name, thread_url, category, channel) "
            "VALUES (?,?,?,?,?,?)",
            [
                (c["id"], c["text"], c["thread_name"],
                 c["thread_url"], c["category"], c["channel"])
                for c in chunks
            ],
        )


def load_all_chunks() -> list[dict]:
    """Load every chunk into memory for BM25 index building."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, text, thread_name, thread_url, category, channel FROM chunks"
        ).fetchall()
    return [
        {
            "id":          r[0],
            "text":        r[1],
            "thread_name": r[2],
            "thread_url":  r[3],
            "category":    r[4],
            "channel":     r[5],
        }
        for r in rows
    ]


def count_chunks() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]


def get_indexed_thread_ids() -> set[str]:
    """
    Return the set of Discord thread IDs already in the database.
    Chunk IDs are stored as "{thread_id}_{chunk_index}", so we strip
    the suffix to recover the thread ID.
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT id FROM chunks").fetchall()
    return {row[0].rsplit("_", 1)[0] for row in rows}


def save_chunks_append(chunks: list[dict]) -> None:
    """
    Insert new chunks without touching existing ones.
    Uses INSERT OR IGNORE so already-indexed chunks are silently skipped.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO chunks "
            "(id, text, thread_name, thread_url, category, channel) "
            "VALUES (?,?,?,?,?,?)",
            [
                (c["id"], c["text"], c["thread_name"],
                 c["thread_url"], c["category"], c["channel"])
                for c in chunks
            ],
        )

def delete_thread_chunks(thread_id: str) -> None:
    """Remove all chunks belonging to a single thread (for re-indexing)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM chunks WHERE id LIKE ?", (f"{thread_id}_%",))