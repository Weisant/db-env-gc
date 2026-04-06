"""最小可用的 OpenAI 兼容 JSON 对话客户端。

这个模块只负责和兼容 OpenAI 协议的模型接口通信。
为了让整条流水线在网络偶发抖动时更稳，这里还做了简单的重试封装。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib import error, request

from agent.config import AgentSettings


def _strip_json_fence(text: str) -> str:
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
    """只负责向兼容接口请求 JSON 响应。"""

    settings: AgentSettings

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> dict:
        """发送一次 JSON 对话请求，并在轻微网络抖动时自动重试。"""
        url = f"{self.settings.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.model_name,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
            method="POST",
        )

        raw = self._request_with_retry(req)

        parsed = json.loads(raw)
        content = parsed["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise RuntimeError("Model returned non-text content.")
        return json.loads(_strip_json_fence(content))

    def _request_with_retry(self, req: request.Request, max_retries: int = 2) -> str:
        """执行 HTTP 请求，并在网络层错误时做有限次重试。

        这里不会重试 HTTP 4xx/5xx 这种明确的服务端失败，
        只会在连接建立或 TLS 握手阶段的临时错误上做补偿。
        """
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                with request.urlopen(req, timeout=180) as response:
                    return response.read().decode("utf-8")
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"LLM request failed with {exc.code}: {detail}") from exc
            except error.URLError as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                time.sleep(1.5 * (attempt + 1))

        raise RuntimeError(f"LLM request failed: {last_error}") from last_error
