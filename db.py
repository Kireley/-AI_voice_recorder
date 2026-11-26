import logging
import os
import shutil
import sqlite3
from datetime import datetime

from config import DB_PATH, DATA_DIR, LEGACY_DB_PATH

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    """Единая точка настроек соединения: WAL и таймаут против 'database is locked'."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DB_PATH) and os.path.exists(LEGACY_DB_PATH):
        logger.info("Переношу старую базу %s -> %s", LEGACY_DB_PATH, DB_PATH)
        shutil.copy2(LEGACY_DB_PATH, DB_PATH)

    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        # Без индекса каждый /tag делает полный проход по таблице
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_tag_id ON notes (tag, id DESC)")


def save_note(tag: str, content: str) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO notes (tag, content, created_at) VALUES (?, ?, ?)",
            (tag, content, now),
        )
        return cursor.lastrowid


def get_all_tags() -> list[tuple[str, int]]:
    with _connect() as conn:
        cursor = conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM notes GROUP BY tag ORDER BY cnt DESC, tag ASC"
        )
        return cursor.fetchall()


def get_notes_by_tag(tag: str, offset: int = 0, limit: int = 10) -> tuple[list[tuple], bool]:
    with _connect() as conn:
        cursor = conn.execute(
            "SELECT id, content, created_at FROM notes WHERE tag = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (tag, limit + 1, offset),
        )
        rows = cursor.fetchall()

    has_more = len(rows) > limit
    return rows[:limit], has_more


def delete_note(note_id: int) -> bool:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return cursor.rowcount > 0