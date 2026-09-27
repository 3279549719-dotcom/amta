"""OpenAI 兼容 chat/completions 的深模块：统一所有「POST /chat/completions + 解析 message」调用。

唯一归属（合并自 translate.text_chat / translate.chat_with_tools / ocr_engines.send_chat）：
- chat_text ← 纯文本，返回回复字符串（解析失败返回空串）
- chat      ← 通用，返回完整 message 结构（含 tool_calls），畸形响应容错返回 {"content": ""}

接口小而深：调用方只需给 base_url / model / messages + 少量可选参数，实现藏住——
Bearer 头拼装、URL 拼接、choices[0].message 解析、畸形响应容错。translate 与 ocr_engines
退化为薄适配器（各自只负责本领域的 message 构造），网络接缝收敛于此单一地点（Locality）。

机制出处（许可证纪律，ADR-014）：仅借鉴 OpenAI 兼容协议形状，不复制第三方代码。
"""
from __future__ import annotations

import time
from typing import Any

import requests


def _headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def chat(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    api_key: str | None = None,
    timeout: int = 120,
    retries: int = 2,
    **extra: Any,
) -> dict:
    """发一次 OpenAI 兼容 chat 请求（支持 tools/function calling），返回完整 message 结构。

    base_url 为 API 根，自动拼 /chat/completions。extra 透传进请求体（如 cache_prompt）。
    响应 message 可能含 tool_calls（模型请求调用工具）或纯 content（最终回答）；
    解析失败返回 {"content": ""}。

    网络抖动（代理/连接挂死）时自动重试 retries 次；连接超时 10s、读超时 60s，
    避免在 CloseWait 状态下傻等。
    """
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
    payload.update(extra)
    # (connect_timeout, read_timeout)：连接 10s 内必须建立，之后 60s 内必须有数据
    to = (10, min(timeout, 60))
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                f"{base_url}/chat/completions",
                headers=_headers(api_key),
                json=payload,
                timeout=to,
            )
            r.raise_for_status()
            try:
                return r.json()["choices"][0]["message"] or {}
            except (KeyError, IndexError, TypeError):
                return {"content": ""}
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    # 不会走到这里，但类型检查需要
    raise last_exc  # type: ignore[misc]


def chat_text(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    api_key: str | None = None,
    timeout: int = 120,
    **extra: Any,
) -> str:
    """发一次 OpenAI 兼容纯文本 chat 请求，返回回复文本；解析失败返回空串。"""
    msg = chat(base_url, model, messages, api_key=api_key, timeout=timeout, **extra)
    return msg.get("content") or ""
