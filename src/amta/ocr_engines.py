"""OCR 引擎抽象 — 本地 llama-server（PaddleOCR-VL-For-Manga）与 DashScope qwen-vl-ocr。

两者同为 OpenAI 兼容 chat/completions + image_url(data URI) + "OCR" 提示词，
差异仅在 base_url 与 Authorization 头，故收敛为一个 send_chat。
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from amta.chat_client import chat_text
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
    """发一次 OpenAI 兼容 OCR 请求（base_url 为 API 根），返回识别文本；解析失败返回空串。

    HTTP/解析接缝唯一归属 chat_client.chat_text；本函数只负责构多模态 message（image_url+OCR）。
    cache_prompt=False 时禁用 llama-server 的 prompt cache（L17：多模态 cache 误命中不同图像）。
    """
    payload = build_payload(model, img_path, prompt, cache_prompt)
    extra = {"cache_prompt": cache_prompt} if cache_prompt is not None else {}
    return chat_text(base_url, model, payload["messages"], api_key=api_key, timeout=timeout, **extra)


def send_one(base_url: str, model: str, img_path: str | Path, prompt: str = DEFAULT_PROMPT, timeout: int = 120) -> str:
    """本地 llama-server 单图 OCR（无鉴权）。保留旧名供 ocr_eval_86 等复用。

    默认关闭 prompt cache（L17：多模态 cache 误命中不同图像）。
    """
    return send_chat(base_url, model, img_path, prompt=prompt, cache_prompt=False, timeout=timeout)


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


# ---- 可插拔 OCR 接口（ADR-018 编排器 + v2 引擎对比策略：baberu fast path + 回退）----

# 引擎分发名（给 02_ocr --engine 与 ocr_run --engine 共用，避免硬编码）
ENGINES = ("auto", "baberu", "local", "dashscope")
# 长文本回退阈值：baberu 对长文本/背景文字偏弱（v2 评测），超长转 local
BABERU_LONG_TEXT_FALLBACK = 80


def _baberu_batch(crops) -> list[dict]:
    """懒加载 baberu-OCR（models/baberu-ocr/ 内嵌 onnx，depguard 白名单）。"""
    from PIL import Image

    from amta.paths import ROOT

    model_root = ROOT / "models" / "baberu-ocr"
    if not (model_root / "onnx").exists():
        raise RuntimeError("baberu-OCR 模型缺失（models/baberu-ocr/onnx）——请先下载模型")
    sys.path.insert(0, str(model_root))
    from onnx_infer import BaberuOnnxOCR  # noqa: PLC0415  # type: ignore[import-not-found]  # 运行时动态 import（depguard 白名单）

    ocr = BaberuOnnxOCR(model_root / "onnx", model_root / "tokenizer", vision="vision_int4.onnx")
    out = []
    for p in crops:
        try:
            text = ocr(Image.open(p))
        except Exception as e:  # noqa: BLE001
            text = f"__ERROR__ {e}"
        out.append({"crop": p, "ocr": text or ""})
    return out


def ocr_batch(crops, engine: str = "auto", *,
              base_url: str = LOCAL_DEFAULT_URL, model: str = "paddle",
              dashscope_model: str = "qwen-vl-ocr-latest") -> list[dict]:
    """统一 OCR 分发器（02_ocr / 调用方共用，按 engine 名路由，不硬编码）。

    engine ∈ ENGINES：
      - "local"    : llama-server For-Manga（OCR 引擎抽象，send_chat）
      - "baberu"   : 纯 onnx 轻量引擎（快 ~22 倍，v2 评测 ALL CER 0.1135）
      - "dashscope": 云端 qwen-vl-ocr
      - "auto"（默认）: baberu fast path，空输出/长文本自动回退 local（v2 评测策略）
    """
    if engine == "local":
        return local_ocr_batch(crops, base_url=base_url, model=model)
    if engine == "dashscope":
        return dashscope_ocr_batch(crops, model=dashscope_model)
    if engine == "baberu":
        return _baberu_batch(crops)
    # auto：baberu 优先，空/长文本回退 local
    try:
        fast = _baberu_batch(crops)
    except Exception as e:  # noqa: BLE001
        print(f"[ocr_engines] baberu 不可用({e})，回退 local", file=sys.stderr)
        return local_ocr_batch(crops, base_url=base_url, model=model)
    fast_map = {r["crop"]: r["ocr"] for r in fast}
    # 空输出或超长文本（baberu 对长文本/背景文字偏弱）→ 回退 local
    needs_fallback = [p for p in crops
                      if not fast_map.get(p, "") or len(fast_map.get(p, "")) > BABERU_LONG_TEXT_FALLBACK]
    if needs_fallback:
        fall = local_ocr_batch(needs_fallback, base_url=base_url, model=model)
        fast_map.update({r["crop"]: r["ocr"] for r in fall})
    return [{"crop": p, "ocr": fast_map.get(p, "")} for p in crops]
