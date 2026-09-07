"""纯文本翻译模块 — minimal 路径唯一实现（2 LLM calls/page, zero tools）。

与 ocr_engines（带图多模态）互补：本模块只发纯文本 messages。
机制来源（ADR-014）：
- glossary 相关条目提取 — 借鉴 manga-image-translator (GPL-3.0) 设计
- 分层拆分重试 — 借鉴 manga-image-translator (GPL-3.0) 数量校验+二分拆分设计
- 数组契约加固 — LLM 输出按位置绑定的 JSON 数组，长度严格校验，防止拆条挤占 region_id
"""
from __future__ import annotations

import json
import re
from typing import Any

from amta.chat_client import chat_text
from amta.config import get_chat_config as _config_get_chat_config
from amta.guardrails import mechanical_guardrails
from amta.metrics import levenshtein, norm
from amta.paths import ROOT

_ENV_PATH = ROOT.parent / ".env"  # 测试会 monkeypatch 它


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
    """解析 LLM 输出为 {region_id: 译文}；容忍 markdown 代码块包裹与额外键。

    保留供旧测试/外部调用；translate_plain 内部已改用数组契约 parse_translation_array。
    """
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v).strip() for k, v in data.items() if k in region_ids and str(v).strip()}


def parse_translation_array(raw: str, expected_count: int) -> list[str] | None:
    """解析 LLM 输出为按输入顺序排列的译文数组。

    数组契约（ADR-014 加固）：LLM 必须返回 JSON 数组，长度严格等于输入条数。
    长度不符 → 返回 None（触发重试或二分拆分），从契约层面防止 LLM 拆条挤占 region_id。
    """
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    if len(data) != expected_count:
        return None
    return [str(v).strip() for v in data]


def translate_plain(canon: list[dict], llm, *, system_extra: str = "",
                    context_prefix: str = "", max_retries: int = 1,
                    context_enabled: bool = True) -> dict[str, str]:
    """Plain-text batch translate — zero tools, zero loops, one call per batch.

    输出契约：LLM 返回 JSON 数组 ["译文1", "译文2", ...]，按输入顺序、同长度。
    代码侧按位置绑定 region_id，长度不符直接失败 → 重试 → 二分拆分。

    prompt-slim 实验（2026-09-07）：删掉所有内容约束（标点/断句/口语化/保留原文标点），
    只保留格式约束（JSON数组、长度一致、顺序一致）+ "漫画"领域提示。
    context_enabled=False 时不注入前页上下文。
    """
    def _build_content(batch: list[dict]) -> str:
        instr = ('将以下日文漫画内容翻译成中文。'
                 '输出JSON数组，长度和顺序与输入一致。\n')
        blocks = []
        for r in batch:
            rid = r["region_id"]
            text = r.get("baberu_text") or r.get("text") or ""
            blocks.append(f"{rid}|{text}")
        cur = instr + "\n".join(blocks)
        if context_enabled and context_prefix:
            return f"{context_prefix}\n\n{cur}"
        return cur

    def _one(batch: list[dict]) -> dict[str, str]:
        region_ids = [r["region_id"] for r in batch]
        system = f"你是日文→中文漫画翻译。输出严格JSON数组，不要输出额外文字。\n{system_extra}".strip()
        for _ in range(max_retries + 1):
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_content(batch)},
            ]
            raw = llm(messages)
            arr = parse_translation_array(raw, len(batch))
            if arr is None:
                continue  # 长度不符或解析失败 → 重试
            # 按位置绑定 region_id
            parsed = {rid: arr[i] for i, rid in enumerate(region_ids) if arr[i]}
            if not mechanical_guardrails(batch, parsed):
                return parsed
        if len(batch) > 1:
            mid = len(batch) // 2
            merged = {}
            merged.update(_one(batch[:mid]))
            merged.update(_one(batch[mid:]))
            return merged
        return {r["region_id"]: "" for r in batch}

    result = _one(list(canon))

    # 后处理：无句末标点的句子单独重试（batch 翻译时 LLM 对部分条目不仔细，不加断句标点）
    _SENTENCE_END = set("。！？…")
    _MIN_LEN = 8
    for r in canon:
        rid = r["region_id"]
        t = result.get(rid, "")
        if len(t) >= _MIN_LEN and not any(c in _SENTENCE_END for c in t):
            single = _one([r])
            if single.get(rid):
                result[rid] = single[rid]

    return result
