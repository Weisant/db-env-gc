"""Prompt 文件读取工具。"""

from __future__ import annotations

from agent.config import PROMPTS_DIR


def load_prompt(name: str) -> str:
    """从 prompts 目录读取指定提示词文件。"""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")
