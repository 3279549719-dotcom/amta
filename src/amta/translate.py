"""纯文本 chat client —— 翻译工位直调 DeepSeek API（无视觉，走纯文本 chat/completions）。

与 ocr_engines.send_chat（带图多模态）互补：本模块只发纯文本 messages。

机制来源（许可证纪律，ADR-014 grill 定案：只借鉴设计不复制代码）：
- 机制① glossary 相关条目提取 —— 借鉴自 manga-image-translator (GPL-3.0) 的 extract_relevant_terms 设计
- 机制② 分层拆分重试 —— 借鉴自 manga-image-translator (GPL-3.0) 的数量校验+二分拆分设计
- 机制③ 翻译缓存层 —— 借鉴自 comic-translate (Apache-2.0) 的块级源文匹配复用设计
"""
from __future__ import annotations

import os

import requests

from amta.paths import ROOT

_ENV_PATH = ROOT.parent / ".env"  # 测试会 monkeypatch 它


def get_chat_config() -> dict[str, str]:
    """读 CHAT_* 配置：环境变量优先，回退 .env；任一缺失 raise RuntimeError。返回 {base_url, model, api_key}。"""
    values: dict[str, str] = {}
    for key in ("CHAT_BASE_URL", "CHAT_MODEL", "CHAT_API_KEY"):
        v = os.environ.get(key)
        if not v and _ENV_PATH.exists():
            for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{key}="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        if not v:
            raise RuntimeError(f"缺少 {key}：请在 .env 配置或设置环境变量")
        values[key] = v
    return {
        "base_url": values["CHAT_BASE_URL"],
        "model": values["CHAT_MODEL"],
        "api_key": values["CHAT_API_KEY"],
    }


def text_chat(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    api_key: str | None = None,
    timeout: int = 120,
) -> str:
    """发一次 OpenAI 兼容纯文本 chat 请求（base_url 为 API 根，自动拼 /chat/completions），返回回复文本；解析失败返回空串。"""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    r = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json={"model": model, "messages": messages},
        timeout=timeout,
    )
    r.raise_for_status()
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""
