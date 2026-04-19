"""基于 OpenAI Python SDK 的最小 JSON 对话客户端。

这个模块只负责和 OpenAI 接口通信。
如果配置了 `base_url`，也允许通过官方 SDK 调用兼容 OpenAI 协议的网关。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from agent.config import AgentSettings


def _strip_json_fence(text: str) -> str:
    """移除模型偶尔返回的 Markdown 代码块包裹。"""
    stripped = text.strip()
    if stripped.startswith("```json"):
        stripped = stripped[len("```json") :].strip()
    elif stripped.startswith("```"):
        stripped = stripped[len("```") :].strip()

    if stripped.endswith("```"):
        stripped = stripped[:-3].strip()
    return stripped


@dataclass
class JsonChatClient:
    """通过 OpenAI Python SDK 请求 JSON 响应。"""

    settings: AgentSettings
    _client: OpenAI = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """根据配置初始化底层 OpenAI SDK 客户端。"""
        base_url = self.settings.base_url.strip()
        client_kwargs = {
            "api_key": self.settings.api_key,
            "max_retries": 0,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        model: str | None = None,
        timeout_seconds: int = 180,
    ) -> dict:
        """发送一次 JSON 对话请求，并在轻微网络抖动时自动重试。"""
        response = self._request_with_retry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            model=model or self.settings.default_model,
            timeout_seconds=timeout_seconds,
        )

        content = response.choices[0].message.content
        if not isinstance(content, str):
            raise RuntimeError("Model returned non-text content.")
        return json.loads(_strip_json_fence(content))

    def _request_with_retry(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        model: str,
        timeout_seconds: int,
        max_retries: int = 2,
    ):
        """执行 SDK 请求，并在网络层错误时做有限次重试。"""
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return self._client.with_options(
                    timeout=timeout_seconds,
                    max_retries=0,
                ).chat.completions.create(
                    model=model,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
            except APIStatusError as exc:
                detail = exc.response.text.strip() if exc.response is not None else str(exc)
                if exc.status_code >= 500 and attempt < max_retries:
                    last_error = exc
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"LLM request failed with {exc.status_code} for model {model}: {detail}"
                ) from exc
            except (APIConnectionError, APITimeoutError) as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                time.sleep(1.5 * (attempt + 1))

        raise RuntimeError(f"LLM request failed: {last_error}") from last_error
