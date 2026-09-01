"""纯文本翻译模块 — minimal 路径唯一实现（2 LLM calls/page, zero tools）。

与 ocr_engines（带图多模态）互补：本模块只发纯文本 messages。
机制来源（ADR-014）：
- glossary 相关条目提取 — 借鉴 manga-image-translator (GPL-3.0) 设计
- 分层拆分重试 — 借鉴 manga-image-translator (GPL-3.0) 数量校验+二分拆分设计
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from amta.chat_client import chat, chat_text
from amta.config import get_chat_config as _config_get_chat_config
from amta.guardrails import mechanical_guardrails
from amta.metrics import levenshtein, norm
from amta.paths import ROOT

_ENV_PATH = ROOT / ".env"  # 测试会 monkeypatch 它


def get_chat_config() -> dict[str, str]:
    """薄壳 → amta.config（唯一实现）；_ENV_PATH 保留供旧测试 monkeypatch。"""
    return _config_get_chat_config(env_path=_ENV_PATH)


def text_chat(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    api_key: str | None = None,
    timeout: int = 120,
    temperature: float | None = None,
) -> str:
    """发一次 OpenAI 兼容纯文本 chat 请求，返回回复文本；解析失败返回空串。"""
    kwargs: dict[str, Any] = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return chat_text(base_url, model, messages, api_key=api_key, timeout=timeout, **kwargs)


def extract_relevant_terms(text: str, glossary: dict) -> dict[str, Any]:
    """只返回与当前文本相关的术语（Levenshtein + 归一化 + 部分匹配）。

    借鉴 manga-image-translator 的 extract_relevant_terms 设计——防大词表稀释 system 权重。
    """
    if not glossary:
        return {}
    norm_text = norm(text)
    relevant: dict[str, Any] = {}
    for term, meta in glossary.items():
        norm_term = norm(term)
        if not norm_term:
            continue
        if norm_term in norm_text or norm_text in norm_term:
            relevant[term] = meta
        elif levenshtein(norm_term[: min(len(norm_term), 6)], norm_text[: min(len(norm_text), 6)]) <= 2:
            relevant[term] = meta
    return relevant


def parse_translation_response(raw: str, region_ids: list[str]) -> dict[str, str]:
    """解析 LLM 输出为 {region_id: 译文}；容忍 markdown 代码块包裹与额外键。"""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v).strip() for k, v in data.items() if k in region_ids and str(v).strip()}


def translate_plain(canon: list[dict], llm, *, system_extra: str = "",
                    context_prefix: str = "", max_retries: int = 1) -> dict[str, str]:
    """Plain-text batch translate — zero tools, zero loops, one call per batch.

    Copies mit's _assemble_prompts pattern: all regions in one prompt with
    region_id tags, JSON response, 1 retry on guardrail failure, then binary split.
    """
    def _build_content(batch: list[dict]) -> str:
        instr = 'Translate the following Japanese text to Chinese. Output STRICT JSON: {"r01": "译文", ...}. region_id must match input exactly.\n'
        blocks = []
        for r in batch:
            rid = r["region_id"]
            text = r.get("baberu_text") or r.get("text") or ""
            blocks.append(f"{rid}|{text}")
        cur = instr + "\n".join(blocks)
        return f"{context_prefix}\n\n{cur}" if context_prefix else cur

    def _one(batch: list[dict]) -> dict[str, str]:
        region_ids = [r["region_id"] for r in batch]
        system = f"你是专业日文→中文漫画翻译专家，输出严格 JSON，不要输出任何额外文字。\n{system_extra}".strip()
        for _ in range(max_retries + 1):
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_content(batch)},
            ]
            raw = llm(messages)
            parsed = parse_translation_response(raw, region_ids)
            if not mechanical_guardrails(batch, parsed):
                return parsed
        if len(batch) > 1:
            mid = len(batch) // 2
            merged = {}
            merged.update(_one(batch[:mid]))
            merged.update(_one(batch[mid:]))
            return merged
        return {r["region_id"]: "" for r in batch}

    return _one(list(canon))
