"""DeepSeek 对话接口封装（OpenAI 兼容协议）。

约定：
- 业务侧只调用 `chat()`，不关心 HTTP 细节；
- 密钥只来自环境变量 `DEEPSEEK_API_KEY`，不写库、不进日志；
- 调用失败统一抛 `AiError`，由业务层决定降级（如生成纯数据模板）。
"""

from __future__ import annotations

from typing import Final

import httpx

from pms.common.logging import get_logger
from pms.core.config import get_settings

logger = get_logger(__name__)

DEFAULT_BASE_URL: Final[str] = "https://api.deepseek.com"
DEFAULT_MODEL: Final[str] = "deepseek-chat"


class AiError(RuntimeError):
    """模型调用失败（未配置 / 网络异常 / 返回结构异常）。"""


def is_configured() -> bool:
    """是否已配置 API Key。"""
    return bool(get_settings().deepseek_api_key.strip())


async def chat(
    messages: list[dict[str, str]],
    *,
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1800,
    timeout: float = 90.0,
) -> str:
    """发起一次对话补全，返回纯文本内容。

    Args:
        messages: OpenAI 风格消息列表（`role` / `content`）。
        model: 模型名，留空取配置。
        temperature: 采样温度，周报类文本保持较低随机性。
        max_tokens: 最大输出 token。
        timeout: 请求超时（秒），AI 生成较慢需放宽。

    Raises:
        AiError: 未配置密钥、网络失败或返回内容为空。
    """
    settings = get_settings()
    api_key = settings.deepseek_api_key.strip()
    if not api_key:
        raise AiError("未配置 DEEPSEEK_API_KEY，无法调用 AI")
    base_url = (settings.deepseek_base_url or DEFAULT_BASE_URL).rstrip("/")
    payload = {
        "model": model or settings.deepseek_model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            )
    except httpx.HTTPError as exc:
        raise AiError(f"AI 服务连接失败：{exc}") from exc
    if response.status_code >= 400:
        raise AiError(f"AI 服务返回 {response.status_code}：{response.text[:200]}")
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiError("AI 返回结构异常") from exc
    text = str(content or "").strip()
    if not text:
        raise AiError("AI 返回内容为空")
    return text
