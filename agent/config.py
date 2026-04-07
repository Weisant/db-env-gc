"""LLM 配置读取工具。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / ".env"
PROMPTS_DIR = BASE_DIR / "prompts"


def load_env_file(path: Path) -> dict[str, str]:
    """读取简单的 KEY=VALUE 配置文件。"""
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
    """优先从本地配置读取，不存在时再读环境变量。"""
    value = values.get(key) or os.environ.get(key)
    if not value:
        raise ValueError(f"Missing required setting: {key}")
    return value


@dataclass(frozen=True)
class AgentSettings:
    """所有 agent 共用的 LLM 配置集合。

    支持一套默认模型加四个阶段级覆盖：
    - 如果某阶段没有显式配置，就回退到 DEFAULT_MODEL
    - 为兼容旧配置，DEFAULT_MODEL 缺失时仍尝试读取 MODEL_NAME
    """

    api_key: str
    base_url: str
    default_model: str
    parser_model: str
    planner_model: str
    generator_model: str
    validator_model: str


def load_settings() -> AgentSettings:
    """加载运行 LLM 客户端所需配置。"""
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
        planner_model=values.get("PLANNER_MODEL")
        or os.environ.get("PLANNER_MODEL")
        or default_model,
        generator_model=values.get("GENERATOR_MODEL")
        or os.environ.get("GENERATOR_MODEL")
        or default_model,
        validator_model=values.get("VALIDATOR_MODEL")
        or os.environ.get("VALIDATOR_MODEL")
        or default_model,
    )
