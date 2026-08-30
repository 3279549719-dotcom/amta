"""密钥与模型配置 — env → .env 回退唯一归属（深接口改造，修 F4 三处重复解析）。

原则：env 优先、.env 兼容双位置（amta/.env 与 仓库父目录/.env，对应旧
ocr_engines 与 translate 的各自实现）、引号剥离、绝不打印密钥（L27）。
测试通过 env_path 参数注入临时 .env，无需 monkeypatch。
"""
from __future__ import annotations

import os
from pathlib import Path

from amta.paths import ROOT

# 兼容旧双位置：translate 用 ROOT.parent/.env，ocr_engines 依次找 ROOT/.env
_ENV_PATHS = (ROOT / ".env", ROOT.parent / ".env")


def _read_key(source: Path, key: str) -> str | None:
    if not source.exists():
        return None
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _resolve(key: str, env_path: Path | None) -> str | None:
    v = os.environ.get(key)
    if v:
        return v
    if env_path is not None:
        return _read_key(env_path, key)
    for p in _ENV_PATHS:
        v = _read_key(p, key)
        if v:
            return v
    return None


def get_chat_config(env_path: Path | None = None) -> dict[str, str]:
    """CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY；任一缺失 raise RuntimeError（列出全部缺失键）。"""
    values: dict[str, str] = {}
    missing: list[str] = []
    for key in ("CHAT_BASE_URL", "CHAT_MODEL", "CHAT_API_KEY"):
        v = _resolve(key, env_path)
        if not v:
            missing.append(key)
        else:
            values[key] = v
    if missing:
        raise RuntimeError(f"缺少 {', '.join(missing)}：请在 .env 配置或设置环境变量")
    return {"base_url": values["CHAT_BASE_URL"],
            "model": values["CHAT_MODEL"],
            "api_key": values["CHAT_API_KEY"]}


def get_vlm_api_key(env_path: Path | None = None) -> str | None:
    """VLM_API_KEY → CHAT_API_KEY → None（原 02_ocr._get_vlm_api_key 语义）。"""
    for key in ("VLM_API_KEY", "CHAT_API_KEY"):
        v = _resolve(key, env_path)
        if v:
            return v
    return None


def get_dashscope_key(env_path: Path | None = None) -> str:
    """DASHSCOPE_API_KEY（兼容旧名 DASHSCOPE_KEY）；缺失 raise。"""
    for name in ("DASHSCOPE_API_KEY", "DASHSCOPE_KEY"):
        v = _resolve(name, env_path)
        if v:
            return v
    raise RuntimeError("缺少 DASHSCOPE_API_KEY：请在 .env 配置或设置环境变量")
