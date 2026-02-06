"""EL Persistent Memory - SQLite backed memory system."""

import sqlite3
import json
import time
from pathlib import Path
from typing import Optional
from el.config.settings import EL_DB_PATH, EL_HOME


class Memory:
    """Persistent memory for EL. Stores conversations, preferences, and context."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or EL_DB_PATH
        EL_HOME.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                importance INTEGER DEFAULT 5,
                created_at REAL NOT NULL,
                expires_at REAL DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                cron_expr TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                last_run REAL DEFAULT NULL,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);
            CREATE INDEX IF NOT EXISTS idx_conv_time ON conversations(timestamp);
            CREATE INDEX IF NOT EXISTS idx_context_topic ON context(topic);
        """)
        self.conn.commit()

    def add_message(self, user_id: str, role: str, content: str, metadata: dict = None):
        self.conn.execute(
            "INSERT INTO conversations (user_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, time.time(), json.dumps(metadata or {})),
        )
        self.conn.commit()

    def get_recent_messages(self, user_id: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content, timestamp, metadata FROM conversations WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["timestamp"],
                "metadata": json.loads(r["metadata"]),
            }
            for r in reversed(rows)
        ]

    def get_conversation_summary(self, user_id: str, last_n: int = 20) -> str:
        messages = self.get_recent_messages(user_id, last_n)
        if not messages:
            return "No previous conversations."
        lines = []
        for m in messages:
            prefix = "User" if m["role"] == "user" else "EL"
            lines.append(f"{prefix}: {m['content'][:200]}")
        return "\n".join(lines)

    def set_preference(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, time.time()),
        )
        self.conn.commit()

    def get_preference(self, key: str, default: str = None) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def get_all_preferences(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM preferences").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def add_context(self, topic: str, summary: str, importance: int = 5, expires_in: float = None):
        expires_at = time.time() + expires_in if expires_in else None
        self.conn.execute(
            "INSERT INTO context (topic, summary, importance, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (topic, summary, importance, time.time(), expires_at),
        )
        self.conn.commit()

    def get_relevant_context(self, topic: str = None, limit: int = 10) -> list[dict]:
        now = time.time()
        if topic:
            rows = self.conn.execute(
                "SELECT topic, summary, importance FROM context WHERE (expires_at IS NULL OR expires_at > ?) AND topic LIKE ? ORDER BY importance DESC, created_at DESC LIMIT ?",
                (now, f"%{topic}%", limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT topic, summary, importance FROM context WHERE expires_at IS NULL OR expires_at > ? ORDER BY importance DESC, created_at DESC LIMIT ?",
                (now, limit),
            ).fetchall()
        return [{"topic": r["topic"], "summary": r["summary"], "importance": r["importance"]} for r in rows]

    def add_scheduled_task(self, name: str, description: str, cron_expr: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO scheduled_tasks (name, description, cron_expr, created_at) VALUES (?, ?, ?, ?)",
            (name, description, cron_expr, time.time()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_scheduled_tasks(self, enabled_only: bool = True) -> list[dict]:
        query = "SELECT * FROM scheduled_tasks"
        if enabled_only:
            query += " WHERE enabled = 1"
        rows = self.conn.execute(query).fetchall()
        return [dict(r) for r in rows]

    def update_task_last_run(self, task_id: int):
        self.conn.execute(
            "UPDATE scheduled_tasks SET last_run = ? WHERE id = ?",
            (time.time(), task_id),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
