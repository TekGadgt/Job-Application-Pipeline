"""SQLite-backed dedup index. A job is marked seen only on terminal reject or publish."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class SeenIndex:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = None

    def _conn(self) -> sqlite3.Connection:
        """Lazily create and cache database connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path)
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS seen ("
                " url_hash TEXT PRIMARY KEY,"
                " fuzzy_key TEXT NOT NULL DEFAULT '',"
                " added_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            self._connection.commit()
        return self._connection

    def close(self) -> None:
        """Close the database connection if open."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def has_url(self, url_hash: str) -> bool:
        row = self._conn().execute(
            "SELECT 1 FROM seen WHERE url_hash = ?", (url_hash,)
        ).fetchone()
        return row is not None

    def has_fuzzy(self, fuzzy_key: str) -> bool:
        if not fuzzy_key:
            return False
        row = self._conn().execute(
            "SELECT 1 FROM seen WHERE fuzzy_key = ?", (fuzzy_key,)
        ).fetchone()
        return row is not None

    def mark(self, url_hash: str, fuzzy_key: str = "") -> None:
        self._conn().execute(
            "INSERT INTO seen (url_hash, fuzzy_key) VALUES (?, ?) "
            "ON CONFLICT(url_hash) DO UPDATE SET fuzzy_key = excluded.fuzzy_key "
            "WHERE excluded.fuzzy_key != ''",
            (url_hash, fuzzy_key),
        )
        self._conn().commit()

    def unmark(self, url_hash: str) -> bool:
        """Delete the row for url_hash; returns whether a row existed.

        Deliberate escape hatch (--reprocess): removing the row also clears
        its fuzzy_key, so the re-run redoes URL AND fuzzy dedup for this entry.
        """
        cur = self._conn().execute("DELETE FROM seen WHERE url_hash = ?", (url_hash,))
        self._conn().commit()
        return cur.rowcount > 0

    def count(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM seen").fetchone()[0]
