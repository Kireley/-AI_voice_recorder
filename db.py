import os
import shutil
import sqlite3
from datetime import datetime

from config import DB_PATH, DATA_DIR, LEGACY_DB_PATH


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DB_PATH) and os.path.exists(LEGACY_DB_PATH):
        shutil.copy2(LEGACY_DB_PATH, DB_PATH)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)



def save_note(tag: str, content: str) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO notes (tag, content, created_at) VALUES (?, ?, ?)",
            (tag, content, now),
        )
        return cursor.lastrowid

def get_all_tags() -> list[tuple[str, int]]:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM notes GROUP BY tag ORDER BY cnt DESC, tag ASC"
        )
        return cursor.fetchall()


def get_notes_by_tag(tag: str, offset: int = 0, limit: int = 10) -> tuple[list[tuple], bool]:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT id, content, created_at FROM notes WHERE tag = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (tag, limit + 1, offset),
        )
        rows = cursor.fetchall()

    has_more = len(rows) > limit
    return rows[:limit], has_more

def delete_note(note_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return cursor.rowcount > 0