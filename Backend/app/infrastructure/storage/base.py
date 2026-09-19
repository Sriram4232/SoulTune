"""Base exceptions and helper utilities for storage stores."""
from __future__ import annotations


class DuplicateUser(Exception):
    pass


def merge_profile(data: dict, fields: dict) -> dict:
    for field, value in fields.items():
        if field == "preferences":
            data.setdefault("preferences", {}).update(value)
        else:
            data[field] = value
    return data
