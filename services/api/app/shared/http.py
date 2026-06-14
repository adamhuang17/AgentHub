from __future__ import annotations

from typing import Any

from services.api.app.shared.errors import ValidationError


def path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def single(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() in {"1", "true", "yes"}


def string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list.")
    result = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValidationError(f"{field_name} must contain non-empty strings.")
        result.append(item)
    return result


def object_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list.")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValidationError(f"{field_name} must contain objects.")
        result.append(item)
    return result


def optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{field_name} must be a non-empty string when provided.")
    return value
