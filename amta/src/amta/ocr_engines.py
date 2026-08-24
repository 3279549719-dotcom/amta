"""OCR 引擎抽象 — 本地 llama-server（PaddleOCR-VL-For-Manga）与 DashScope qwen-vl-ocr。

两者同为 OpenAI 兼容 chat/completions + image_url(data URI) + "OCR" 提示词，
差异仅在 base_url 与 Authorization 头，故收敛为一个 send_chat。
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import requests

from amta.paths import ROOT

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_URL = f"{DASHSCOPE_BASE}/chat/completions"  # 兼容旧名（完整端点）
LOCAL_DEFAULT_URL = "http://127.0.0.1:8118/v1"
DEFAULT_PROMPT = "OCR"


def image_data_uri(img_path: str | Path, mime: str = "image/png") -> str:
    """图片 → data URI（OpenAI 兼容 image_url 格式）。"""
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def build_payload(model: str, img_path: str | Path, prompt: str = DEFAULT_PROMPT, cache_prompt: bool | None = None) -> dict:
    """构造 OpenAI 兼容多模态请求体：单图 + 文本提示。

    cache_prompt=False 时禁用 llama-server 的 prompt cache——多模态下 cache 会误命中
    不同图像（教训 L17），必须逐张真实推理。
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": image_data_uri(img_path)}},
            {"type": "text", "text": prompt},
        ]}],
    }
    if cache_prompt is not None:
        payload["cache_prompt"] = cache_prompt
    return payload


def send_chat(
    base_url: str,
    model: str,
    img_path: str | Path,
    *,
    api_key: str | None = None,
    timeout: int = 120,
    prompt: str = DEFAULT_PROMPT,
    cache_prompt: bool | None = None,
) -> str:
    """发一次 OpenAI 兼容 OCR 请求（base_url 为 API 根，自动拼 /chat/completions），返回识别文本；解析失败返回空串。"""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    r = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=build_payload(model, img_path, prompt, cache_prompt),
        timeout=timeout,
    )
    r.raise_for_status()
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def send_one(base_url: str, model: str, img_path: str | Path, prompt: str = DEFAULT_PROMPT) -> str:
    """本地 llama-server 单图 OCR（无鉴权）。保留旧名供 ocr_eval_86 等复用。

    默认关闭 prompt cache（L17：多模态 cache 误命中不同图像）。
    """
    return send_chat(base_url, model, img_path, prompt=prompt, cache_prompt=False)


def get_dashscope_key() -> str:
    """取 DASHSCOPE_API_KEY：环境变量优先，回退 .env（兼容旧名 DASHSCOPE_KEY）。绝不打印 key。"""
    for name in ("DASHSCOPE_API_KEY", "DASHSCOPE_KEY"):
        v = os.environ.get(name)
        if v:
            return v
    for env_path in (ROOT / ".env", ROOT.parent / ".env"):
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DASHSCOPE_API_KEY=") or line.startswith("DASHSCOPE_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("缺少 DASHSCOPE_API_KEY：请在 .env 配置或设置环境变量")


def local_ocr_batch(crops, base_url: str = LOCAL_DEFAULT_URL, model: str = "paddle", concurrency: int = 1) -> list[dict]:
    """本地 llama-server 批量 OCR；并发固定 1（CPU 单机，参数保留）。

    每张关闭 prompt cache（L17：多模态 cache 误命中不同图像）。
    """
    return [{"crop": p, "ocr": send_chat(base_url, model, p, cache_prompt=False)} for p in crops]


def dashscope_ocr_batch(crops, model: str = "qwen-vl-ocr-latest", concurrency: int = 4) -> list[dict]:
    """DashScope qwen-vl-ocr 批量 OCR（base64 图，纯文本输出）。"""
    key = get_dashscope_key()
    out = []
    for p in crops:
        text = send_chat(DASHSCOPE_BASE, model, p, api_key=key, timeout=60)
        if not text:
            print(f"[ocr_run] WARN dashscope 空响应: {Path(p).name}", file=sys.stderr)
        out.append({"crop": p, "ocr": text})
    return out
