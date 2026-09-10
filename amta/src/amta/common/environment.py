"""环境自检门卫 — 管线启动前自动检查并修复环境问题。

设计原则（Embedded，不是 Chained）：
- 不需要 AI 记得去调用，管线启动时自动执行
- 能自动修复的就自动修复（比如关掉不可达的代理）
- 不能修复的就直接报错，给出明确的修复建议
- 检查结果打印到 stdout，AI 和用户都能看到

检查项：
1. 代理：HTTP_PROXY/HTTPS_PROXY 设置了但不可达 → 自动关掉
2. ROOT 路径：确认 ROOT 指向正确的项目根（models/ 存在）
3. 模型文件：根据要跑的阶段检查 detector.onnx / big-lama.pt
4. .env / API key：如果要跑 translate，确认 CHAT_API_KEY 已加载
"""
from __future__ import annotations

import os
import socket
from collections.abc import Sequence
from urllib.parse import urlparse

from amta.common.paths import ROOT


def _check_proxy() -> list[str]:
    """检查代理是否可达，不可达就自动关掉。返回修复信息列表。"""
    fixes = []
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        proxy = os.environ.get(var)
        if not proxy:
            continue
        try:
            parsed = urlparse(proxy)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if host and port:
                sock = socket.create_connection((host, port), timeout=2)
                sock.close()
        except (OSError, ValueError):
            # 代理不可达，自动关掉
            os.environ[var] = ""
            fixes.append(f"代理 {var}={proxy} 不可达，已自动关闭")
    return fixes


def _check_root() -> list[str]:
    """确认 ROOT 路径正确（models/ 目录存在）。"""
    errors = []
    models_dir = ROOT / "models"
    if not models_dir.exists():
        errors.append(
            f"ROOT 路径可能错误：{ROOT}\n"
            f"  预期 models/ 目录存在，但 {models_dir} 不存在。\n"
            f"  请检查 src/amta/common/paths.py 的 ROOT 定义。"
        )
    return errors


def _check_models(stages: Sequence[str]) -> list[str]:
    """根据要跑的阶段检查模型文件。"""
    errors = []
    if "detect" in stages:
        detector = ROOT / "models" / "CTBD" / "detector.onnx"
        if not detector.exists():
            errors.append(f"detect 阶段需要模型文件：{detector}\n  请确认模型已下载。")
    if "inpaint" in stages:
        lama = ROOT / "models" / "big-lama.pt"
        if not lama.exists():
            errors.append(f"inpaint 阶段需要模型文件：{lama}\n  请确认模型已下载。")
    return errors


def _check_env(stages: Sequence[str]) -> list[str]:
    """如果要跑 translate，确认 API key 已加载。"""
    errors = []
    if "translate" in stages:
        # 触发 config 加载 .env
        try:
            from amta.common.config import get_chat_config
            cfg = get_chat_config()
            if not cfg.get("api_key"):
                errors.append(
                    "translate 阶段需要 CHAT_API_KEY，但未找到。\n"
                    f"  请确认 .env 文件存在于 {ROOT} 或 {ROOT.parent}，\n"
                    f"  且包含 CHAT_API_KEY / CHAT_BASE_URL / CHAT_MODEL。"
                )
        except Exception as e:
            errors.append(f"加载 .env 配置失败：{e}")
    return errors


def run_environment_check(stages: Sequence[str] | None = None) -> bool:
    """运行环境自检，自动修复可修复的问题，返回是否通过。

    Args:
        stages: 要跑的阶段列表，用于针对性检查模型和 API key。
                None 表示只做通用检查（代理、ROOT）。

    Returns:
        True 表示所有检查通过（或已自动修复），False 表示有无法修复的错误。
    """
    stages = list(stages or [])
    print("[env-check] === 环境自检开始 ===")

    all_ok = True

    # 1. 代理检查（可自动修复）
    fixes = _check_proxy()
    for f in fixes:
        print(f"[env-check] [自动修复] {f}")

    # 2. ROOT 路径检查
    errors = _check_root()
    for e in errors:
        print(f"[env-check] [错误] {e}")
    if errors:
        all_ok = False

    # 3. 模型文件检查
    errors = _check_models(stages)
    for e in errors:
        print(f"[env-check] [错误] {e}")
    if errors:
        all_ok = False

    # 4. .env / API key 检查
    errors = _check_env(stages)
    for e in errors:
        print(f"[env-check] [错误] {e}")
    if errors:
        all_ok = False

    if all_ok:
        print("[env-check] === 环境自检通过 ===")
    else:
        print("[env-check] === 环境自检失败，请修复上述错误后重试 ===")

    return all_ok
