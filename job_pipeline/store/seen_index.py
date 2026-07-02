"""SQLite-backed dedup index. A job is marked seen only on terminal reject or publish."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class SeenIndex:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            " url_hash TEXT PRIMARY KEY,"
            " fuzzy_key TEXT NOT NULL DEFAULT '',"
            " added_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        self._conn.commit()

    def has_url(self, url_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen WHERE url_hash = ?", (url_hash,)
        ).fetchone()
        return row is not None

    def has_fuzzy(self, fuzzy_key: str) -> bool:
        if not fuzzy_key:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM seen WHERE fuzzy_key = ?", (fuzzy_key,)
        ).fetchone()
        return row is not None

    def mark(self, url_hash: str, fuzzy_key: str = "") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen (url_hash, fuzzy_key) VALUES (?, ?)",
            (url_hash, fuzzy_key),
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
