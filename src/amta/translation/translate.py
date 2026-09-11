"""纯文本翻译模块 — minimal 路径唯一实现（1 LLM call/page, zero tools）。

与 ocr_engines（带图多模态）互补：本模块只发纯文本 messages。
机制来源（ADR-014）：
- glossary 相关条目提取 — 借鉴 manga-image-translator (GPL-3.0) 设计
- 数组契约加固 — LLM 输出按位置绑定的 JSON 数组，长度严格校验，防止拆条挤占 region_id
"""
from __future__ import annotations

import json
import re
from typing import Any

from amta.backends.chat_client import chat_text
from amta.common.config import get_chat_config as _config_get_chat_config
from amta.common.metrics import levenshtein, norm
from amta.common.paths import ROOT
from amta.guards.guardrails import mechanical_guardrails

_ENV_PATH = ROOT / ".env"  # 测试会 monkeypatch 它；默认指向项目根目录 .env（非 ROOT.parent）

# System prompt（Q8, 2026-09-08）：
# "乱码→空"条款经 Q1 实验验证（25 框：24 正常 + 1 乱码正确输出空）后正式固化。
# 注意实验措辞是"整批输入"视角；正式链路是数组契约批量调用，必须写成"某条→对应位置"，
# 否则模型遇到一个乱码框可能整批返回 []，反而触发长度不符全批作废。
_SYSTEM_PROMPT = (
    "你是日文→中文漫画翻译。输出严格JSON数组，不要输出额外文字。\n"
    "如果某条输入是乱码、无法识别的字符或非日文常用文字，"
    "对应位置输出空字符串，数组长度和顺序保持不变。"
)


def get_chat_config() -> dict[str, str]:
    """薄壳 → amta.common.config（唯一实现）；_ENV_PATH 保留供旧测试 monkeypatch。"""
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
        if norm_term in norm_text or norm_text in norm_term or levenshtein(norm_term[: min(len(norm_term), 6)], norm_text[: min(len(norm_text), 6)]) <= 2:
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
    长度不符 → 返回 None（该批返回空，不重试、不二分），从契约层面防止 LLM 拆条挤占 region_id。
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
                    context_prefix: str = "", max_retries: int = 0,
                    context_enabled: bool = True) -> dict[str, str]:
    """Plain-text batch translate — one call per batch, no retry, no split.

    输出契约：LLM 返回 JSON 数组 ["译文1", "译文2", ...]，按输入顺序、同长度。
    代码侧按位置绑定 region_id，长度不符或解析失败 → 该批返回空（不重试、不二分）。

    prompt-slim 实验（2026-09-07）：删掉所有内容约束（标点/断句/口语化/保留原文标点），
    只保留格式约束（JSON数组、长度一致、顺序一致）+ "漫画"领域提示。
    context_enabled=False 时不注入前页上下文。

    重试/二分/无句末标点重试已移除（2026-09-08）：
    - 数组契约已加固，长度不符是 LLM 输出质量问题，重试无意义
    - 二分拆分是为"批量太大导致错乱"设计的补丁，小批量下不需要
    - 无句末标点重试执行的是已被 prompt-slim 废弃的标点标准，日漫口语短句天然可无标点

    标点精简约束（2026-09-11 加回）：prompt-slim 完全放开后 LLM 句号过多，
    气泡框观感差。在 instr 中加回"口语化、句末少用句号、标点精简"引导，
    非机械删除（保留 2026-09-06 决策：原文标点必须保留，机械删标点自毁）。

    "乱码→空"条款已固化进 _SYSTEM_PROMPT（Q8, 2026-09-08），system_extra 仅保留
    实验/临时追加能力，拼在正式条款之后。
    """
    def _build_content(batch: list[dict]) -> str:
        instr = ('将以下日文漫画内容翻译成中文。'
                 '输出JSON数组，长度和顺序与输入一致。'
                 '漫画口语化表达，句末尽量不用句号，标点精简（能不带就不带）。\n')
        # 不写 region_id 前缀（r01|）：数组契约按位置绑定，前缀是多余标签，
        # 反而可能被 LLM 抄进译文（Q6 实验：移除前缀 + 移除前缀剥离补丁）
        blocks = [r.get("baberu_text") or r.get("text") or "" for r in batch]
        cur = instr + "\n".join(blocks)
        if context_enabled and context_prefix:
            return f"{context_prefix}\n\n{cur}"
        return cur

    def _one(batch: list[dict]) -> dict[str, str]:
        region_ids = [r["region_id"] for r in batch]
        system = f"{_SYSTEM_PROMPT}\n{system_extra}".strip()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": _build_content(batch)},
        ]
        raw = llm(messages)
        arr = parse_translation_array(raw, len(batch))
        if arr is None:
            return {r["region_id"]: "" for r in batch}
        # 按位置绑定 region_id；不过滤空字符串（乱码框应输出为空，是合法结果）
        parsed = {rid: arr[i] for i, rid in enumerate(region_ids)}
        problems = mechanical_guardrails(batch, parsed)
        if problems:
            return {r["region_id"]: "" for r in batch}
        return parsed

    result = _one(list(canon))

    # 前缀剥离补丁已移除（Q6）：输入不再写 r01| 前缀，LLM 无东西可抄；
    # 若输出格式崩坏，由数组契约（长度校验）直接判全批空，不做静默修补
    return result
