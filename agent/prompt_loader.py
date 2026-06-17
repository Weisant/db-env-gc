"""Prompt file loader."""

from __future__ import annotations

from agent.config import PROMPTS_DIR


def load_prompt(name: str) -> str:
    """Read a prompt file from the prompts directory."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")
