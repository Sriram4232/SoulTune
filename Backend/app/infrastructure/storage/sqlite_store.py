"""SQLite repository implementation."""
from __future__ import annotations

import hmac
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .base import DuplicateUser, merge_profile


class SQLiteStore:
    kind = "sqlite"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL,
                    id TEXT NOT NULL,
                    owner TEXT,
                    email TEXT,
                    expires_at REAL,
                    data TEXT NOT NULL,
                    PRIMARY KEY (kind, id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS unique_user_email
                    ON records(email) WHERE kind = 'user' AND email IS NOT NULL;
                CREATE INDEX IF NOT EXISTS records_owner ON records(kind, owner);
                CREATE INDEX IF NOT EXISTS records_expiry ON records(expires_at);
                CREATE TABLE IF NOT EXISTS rate_limits (
                    id TEXT PRIMARY KEY,
                    count INTEGER NOT NULL,
                    expires_at REAL NOT NULL
                );
            """)
        self.cleanup()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, kind: str, key: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT data FROM records WHERE kind=? AND id=? AND (expires_at IS NULL OR expires_at>?)",
                (kind, key, time.time()),
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def user_by_email(self, email: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT data FROM records WHERE kind='user' AND email=?", (email,),
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def consume_otp(self, user_id: str, binding: str, submitted_hash: str) -> dict | None:
        """Check, count attempts and consume a code in one write transaction."""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT data FROM records WHERE kind='otp' AND id=? AND expires_at>?",
                                     (user_id, time.time())).fetchone()
            if not row:
                return None
            data = json.loads(row["data"])
            if data.get("consumed") or data["attempts"] >= 5 or not hmac.compare_digest(data["binding"], binding):
                return None
            data["attempts"] += 1
            valid = hmac.compare_digest(data["code_hash"], submitted_hash)
            data["consumed"] = valid
            connection.execute("UPDATE records SET data=? WHERE kind='otp' AND id=?", (json.dumps(data), user_id))
            return data if valid else None

    def put(self, kind: str, key: str, data: dict, *, owner: str | None = None, expires_at: float | None = None) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO records(kind,id,owner,email,expires_at,data) VALUES(?,?,?,?,?,?)
                ON CONFLICT(kind,id) DO UPDATE SET owner=excluded.owner,email=excluded.email,
                    expires_at=excluded.expires_at,data=excluded.data""",
                (kind, key, owner, data.get("email") if kind == "user" else None, expires_at, json.dumps(data)),
            )

    def create_user(self, data: dict) -> None:
        try:
            with self.connection() as connection:
                connection.execute(
                    "INSERT INTO records(kind,id,email,expires_at,data) VALUES('user',?,?,?,?)",
                    (data["id"], data.get("email"), data.get("expires_at"), json.dumps(data)),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateUser() from exc

    def update_profile(self, user_id: str, fields: dict) -> dict | None:
        """Update only profile fields against the current record, never credentials."""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT data FROM records WHERE kind='user' AND id=? AND (expires_at IS NULL OR expires_at>?)",
                (user_id, time.time()),
            ).fetchone()
            if not row:
                return None
            data = merge_profile(json.loads(row["data"]), fields)
            connection.execute("UPDATE records SET data=? WHERE kind='user' AND id=?", (json.dumps(data), user_id))
        return data

    def rotate_password(self, user_id: str, password_hash: str, expected_version: int) -> dict | None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT data FROM records WHERE kind='user' AND id=?", (user_id,)).fetchone()
            if not row:
                return None
            data = json.loads(row["data"])
            if data.get("auth_version", 0) != expected_version:
                return None
            data.update(password_hash=password_hash, auth_version=expected_version + 1)
            connection.execute("UPDATE records SET data=? WHERE kind='user' AND id=?", (json.dumps(data), user_id))
            connection.execute("DELETE FROM records WHERE kind='session' AND owner=?", (user_id,))
        return data

    def save_playlist(self, data: dict, expected_revision: int) -> bool:
        """Prevent a delayed refinement from resurrecting/deleting newer changes."""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            owner = connection.execute("SELECT id FROM records WHERE kind='user' AND id=?", (data["owner_id"],)).fetchone()
            if not owner:
                return False
            if connection.execute("SELECT 1 FROM records WHERE kind='deleted_playlist' AND id=?", (data["id"],)).fetchone():
                return False
            row = connection.execute("SELECT data FROM records WHERE kind='playlist' AND id=?", (data["id"],)).fetchone()
            if row:
                current = json.loads(row["data"])
                if current.get("_revision", 0) != expected_revision or current["owner_id"] != data["owner_id"]:
                    return False
            elif expected_revision != 0:
                return False
            connection.execute(
                """INSERT INTO records(kind,id,owner,data) VALUES('playlist',?,?,?)
                ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data""",
                (data["id"], data["owner_id"], json.dumps(data)),
            )
        return True

    def list_owned(self, kind: str, owner: str) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT data FROM records WHERE kind=? AND owner=? AND (expires_at IS NULL OR expires_at>?)",
                (kind, owner, time.time()),
            ).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def delete(self, kind: str, key: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, key))

    def delete_owned(self, kind: str, owner: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM records WHERE kind=? AND owner=?", (kind, owner))

    def delete_user(self, user_id: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM records WHERE owner=? OR (kind='user' AND id=?)", (user_id, user_id))

    def rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.time()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM rate_limits WHERE expires_at<=?", (now,))
            connection.execute(
                """INSERT INTO rate_limits(id,count,expires_at) VALUES(?,1,?)
                ON CONFLICT(id) DO UPDATE SET count=count+1""", (key, now + window_seconds),
            )
            row = connection.execute("SELECT count,expires_at FROM rate_limits WHERE id=?", (key,)).fetchone()
        return row["count"] <= limit, max(1, int(row["expires_at"] - now) + 1)

    def cleanup(self) -> None:
        with self.connection() as connection:
            now = time.time()
            connection.execute(
                "DELETE FROM records WHERE owner IN (SELECT id FROM records WHERE kind='user' AND expires_at<=?)",
                (now,),
            )
            connection.execute("DELETE FROM records WHERE expires_at<=?", (now,))
            connection.execute("DELETE FROM rate_limits WHERE expires_at<=?", (now,))

    def ping(self) -> bool:
        with self.connection() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

    def close(self) -> None:
        pass
