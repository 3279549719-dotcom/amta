"""CHAT_* 配置读取：环境变量优先，回退仓库上级 .env（配置读取唯一归属）。

从 translate.py 拆出（refactor/modular-architecture，L28）：06_page_judge /
repair_failed / translate_semantic_check 都需要 CHAT_* 配置但并非翻译编排，
配置接缝独立成模块，translate.py 保留兼容 re-export。
"""
from __future__ import annotations

import os

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
