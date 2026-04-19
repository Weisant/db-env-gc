"""模型层通用校验辅助函数。"""

from __future__ import annotations

from typing import Any


def _ensure_str(value: Any, field_name: str, default: str = "") -> str:
    """把任意值规范成字符串。"""
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value.strip()


def _ensure_dict_of_str(value: Any, field_name: str) -> dict[str, str]:
    """把任意字典规范成 `str -> str` 结构。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized[str(key).strip()] = str(item).strip()
    return normalized


def _ensure_list_of_str(value: Any, field_name: str) -> list[str]:
    """把任意列表规范成字符串列表。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return [str(item).strip() for item in value if str(item).strip()]


def _ensure_bool(value: Any, field_name: str, default: bool = False) -> bool:
    """把任意值规范成布尔值。"""
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean.")
    return value


def _ensure_list_of_dict(value: Any, field_name: str) -> list[dict[str, Any]]:
    """把任意列表规范成对象列表。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{field_name} items must be objects.")
        normalized.append(item)
    return normalized
