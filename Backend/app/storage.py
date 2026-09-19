"""Small persistence layer with durable SQLite and an optional MongoDB adapter.

An explicitly configured MongoDB connection fails closed. It never silently writes
users into a second database when the requested database is unavailable.
"""
from __future__ import annotations

import json
import hmac
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import Settings


class DuplicateUser(Exception):
    pass


def _merge_profile(data: dict, fields: dict) -> dict:
    for field, value in fields.items():
        if field == "preferences":
            data.setdefault("preferences", {}).update(value)
        else:
            data[field] = value
    return data


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
            data = _merge_profile(json.loads(row["data"]), fields)
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
            # A transaction serializes increments across concurrent requests/workers.
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


class MongoStore:
    kind = "mongodb"

    def __init__(self, uri: str, database: str):
        from pymongo import ASCENDING, MongoClient
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        uri = "[redacted]"
        try:
            self.client.admin.command("ping")
            self.db = self.client[database]
            self.db.users.create_index("email", unique=True, partialFilterExpression={"email": {"$type": "string"}})
            self.db.sessions.create_index([("owner", ASCENDING)])
            self.db.playlists.create_index([("owner", ASCENDING)])
            self.db.saved_songs.create_index([("owner", ASCENDING)])
            self.db.deleted_playlists.create_index([("owner", ASCENDING)])
            self.db.otp_challenges.create_index([("owner", ASCENDING)])
            self.db.otp_challenges.create_index("expires_at")
            self.db.rates.create_index("expires_at")
            self.cleanup()
        except Exception as exc:
            self.client.close()
            raise RuntimeError("Configured MongoDB is unavailable. Check server configuration.") from None

    def _collection(self, kind: str):
        return self.db[{"user": "users", "session": "sessions", "playlist": "playlists", "otp": "otp_challenges", "deleted_playlist": "deleted_playlists", "saved_song": "saved_songs"}[kind]]

    def consume_otp(self, user_id: str, binding: str, submitted_hash: str) -> dict | None:
        from pymongo import ReturnDocument
        # A single atomic operation counts wrong guesses and makes success single-use.
        document = self.db.otp_challenges.find_one_and_update({
            "_id": user_id, "expires_at": {"$gt": time.time()},
            "data.binding": binding, "data.consumed": False, "data.attempts": {"$lt": 5},
        }, [{"$set": {
            "data.attempts": {"$add": ["$data.attempts", 1]},
            "data.consumed": {"$eq": ["$data.code_hash", submitted_hash]},
        }}], return_document=ReturnDocument.AFTER)
        return document["data"] if document and document["data"]["consumed"] else None

    def get(self, kind: str, key: str) -> dict | None:
        document = self._collection(kind).find_one({"_id": key})
        if not document or (document.get("expires_at") is not None and document["expires_at"] <= time.time()):
            return None
        return document["data"]

    def user_by_email(self, email: str) -> dict | None:
        document = self.db.users.find_one({"email": email})
        return document["data"] if document else None

    def put(self, kind: str, key: str, data: dict, *, owner: str | None = None, expires_at: float | None = None) -> None:
        document: dict[str, Any] = {"_id": key, "data": data, "owner": owner, "expires_at": expires_at}
        if kind == "user" and data.get("email"):
            document["email"] = data["email"]
        self._collection(kind).replace_one({"_id": key}, document, upsert=True)

    def create_user(self, data: dict) -> None:
        from pymongo.errors import DuplicateKeyError
        document = {"_id": data["id"], "data": data, "expires_at": data.get("expires_at")}
        if data.get("email"):
            document["email"] = data["email"]
        try:
            self.db.users.insert_one(document)
        except DuplicateKeyError as exc:
            raise DuplicateUser() from exc

    def update_profile(self, user_id: str, fields: dict) -> dict | None:
        from pymongo import ReturnDocument
        updates = {}
        for field, value in fields.items():
            if field == "preferences":
                updates.update({f"data.preferences.{key}": item for key, item in value.items()})
            else:
                updates[f"data.{field}"] = value
        if not updates:
            return self.get("user", user_id)
        document = self.db.users.find_one_and_update(
            {"_id": user_id, "$or": [{"expires_at": None}, {"expires_at": {"$gt": time.time()}}]},
            {"$set": updates}, return_document=ReturnDocument.AFTER,
        )
        return document["data"] if document else None

    def rotate_password(self, user_id: str, password_hash: str, expected_version: int) -> dict | None:
        from pymongo import ReturnDocument
        query: dict[str, Any] = {"_id": user_id, "data.auth_version": expected_version}
        if expected_version == 0:
            query = {"_id": user_id, "$or": [{"data.auth_version": 0}, {"data.auth_version": {"$exists": False}}]}
        document = self.db.users.find_one_and_update(query, {
            "$set": {"data.password_hash": password_hash}, "$inc": {"data.auth_version": 1},
        }, return_document=ReturnDocument.AFTER)
        if not document:
            return None
        # auth_version invalidates old sessions immediately, including a login that
        # verified an old password concurrently but saves its session after this delete.
        self.delete_owned("session", user_id)
        return document["data"]

    def save_playlist(self, data: dict, expected_revision: int) -> bool:
        from pymongo.errors import DuplicateKeyError
        if not self.get("user", data["owner_id"]) or self.get("deleted_playlist", data["id"]):
            return False
        document = {"_id": data["id"], "owner": data["owner_id"], "data": data, "expires_at": None}
        query: dict[str, Any] = {"_id": data["id"], "owner": data["owner_id"], "data._revision": expected_revision}
        if expected_revision == 0:
            query = {"_id": data["id"], "owner": data["owner_id"], "$or": [
                {"data._revision": 0}, {"data._revision": {"$exists": False}},
            ]}
        try:
            result = self.db.playlists.replace_one(query, document, upsert=expected_revision == 0)
        except DuplicateKeyError:
            return False
        saved = bool(result.matched_count or result.upserted_id)
        # Close the cross-collection deletion race without requiring replica-set transactions.
        if saved and (not self.get("user", data["owner_id"]) or self.get("deleted_playlist", data["id"])):
            self.delete("playlist", data["id"])
            return False
        return saved

    def list_owned(self, kind: str, owner: str) -> list[dict]:
        return [document["data"] for document in self._collection(kind).find({
            "owner": owner, "$or": [{"expires_at": None}, {"expires_at": {"$gt": time.time()}}],
        })]

    def delete(self, kind: str, key: str) -> None:
        self._collection(kind).delete_one({"_id": key})

    def delete_owned(self, kind: str, owner: str) -> None:
        self._collection(kind).delete_many({"owner": owner})

    def delete_user(self, user_id: str) -> None:
        self.delete("user", user_id)
        self.delete_owned("session", user_id)
        self.delete_owned("playlist", user_id)
        self.delete_owned("otp", user_id)
        self.delete_owned("deleted_playlist", user_id)
        self.delete_owned("saved_song", user_id)

    def rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        from pymongo import ReturnDocument
        now = time.time()
        # Pipeline update resets an expired window and increments atomically.
        expired = {"$lte": [{"$ifNull": ["$expires_at", 0]}, now]}
        document = self.db.rates.find_one_and_update(
            {"_id": key}, [{"$set": {
                "count": {"$cond": [expired, 1, {"$add": ["$count", 1]}]},
                "expires_at": {"$cond": [expired, now + window_seconds, "$expires_at"]},
            }}], upsert=True, return_document=ReturnDocument.AFTER,
        )
        return document["count"] <= limit, max(1, int(document["expires_at"] - now) + 1)

    def cleanup(self) -> None:
        now = time.time()
        for user in self.db.users.find({"expires_at": {"$ne": None, "$lte": now}}, {"_id": 1}):
            self.delete_user(user["_id"])
        self.db.sessions.delete_many({"expires_at": {"$lte": now}})
        self.db.otp_challenges.delete_many({"expires_at": {"$lte": now}})
        self.db.rates.delete_many({"expires_at": {"$lte": now}})

    def ping(self) -> bool:
        return bool(self.client.admin.command("ping").get("ok"))

    def close(self) -> None:
        self.client.close()


def create_store(settings: Settings) -> SQLiteStore | MongoStore:
    if settings.mongodb_uri:
        return MongoStore(settings.mongodb_uri, settings.mongodb_database)
    return SQLiteStore(settings.database_path)
