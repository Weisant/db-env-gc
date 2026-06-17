"""LLM configuration loader."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / ".env"
PROMPTS_DIR = BASE_DIR / "prompts"


def load_env_file(path: Path) -> dict[str, str]:
    """Read a simple KEY=VALUE configuration file."""
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def read_required_setting(values: dict[str, str], key: str) -> str:
    """Read from local config first, then from environment variables."""
    value = values.get(key) or os.environ.get(key)
    if not value:
        raise ValueError(f"Missing required setting: {key}")
    return value


@dataclass(frozen=True)
class AgentSettings:
    """Shared LLM configuration set for all agents.

    Supports one default model plus per-stage overrides:
    - If a stage is not configured explicitly, fall back to DEFAULT_MODEL.
    """

    api_key: str
    base_url: str
    default_model: str
    parser_model: str
    profiler_model: str
    planner_model: str
    generator_model: str


def load_settings() -> AgentSettings:
    """Load settings required to run the LLM client."""
    values = load_env_file(CONFIG_FILE)
    default_model = (
        values.get("DEFAULT_MODEL")
        or os.environ.get("DEFAULT_MODEL")
    )
    if not default_model:
        raise ValueError("Missing required setting: DEFAULT_MODEL")

    return AgentSettings(
        api_key=read_required_setting(values, "API_KEY"),
        base_url=read_required_setting(values, "BASE_URL"),
        default_model=default_model,
        parser_model=values.get("PARSER_MODEL")
        or os.environ.get("PARSER_MODEL")
        or default_model,
        profiler_model=values.get("PROFILER_MODEL")
        or os.environ.get("PROFILER_MODEL")
        or default_model,
        planner_model=values.get("PLANNER_MODEL")
        or os.environ.get("PLANNER_MODEL")
        or default_model,
        generator_model=values.get("GENERATOR_MODEL")
        or os.environ.get("GENERATOR_MODEL")
        or default_model,
    )
