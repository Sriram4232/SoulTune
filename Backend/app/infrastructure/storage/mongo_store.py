"""MongoDB repository implementation."""
from __future__ import annotations

import time
from typing import Any

from .base import DuplicateUser


class MongoStore:
    kind = "mongodb"

    def __init__(self, uri: str, database: str):
        from pymongo import ASCENDING, MongoClient
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
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
        except Exception:
            self.client.close()
            raise RuntimeError("Configured MongoDB is unavailable. Check server configuration.") from None

    def _collection(self, kind: str):
        return self.db[{
            "user": "users", "session": "sessions", "playlist": "playlists",
            "otp": "otp_challenges", "deleted_playlist": "deleted_playlists",
            "saved_song": "saved_songs"
        }[kind]]

    def consume_otp(self, user_id: str, binding: str, submitted_hash: str) -> dict | None:
        from pymongo import ReturnDocument
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
