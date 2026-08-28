"""纯文本 chat client —— 翻译工位直调 DeepSeek API（无视觉，走纯文本 chat/completions）。

与 ocr_engines.send_chat（带图多模态）互补：本模块只发纯文本 messages。

机制来源（许可证纪律，ADR-014 grill 定案：只借鉴设计不复制代码）：
- 机制① glossary 相关条目提取 —— 借鉴自 manga-image-translator (GPL-3.0) 的 extract_relevant_terms 设计
- 机制② 分层拆分重试 —— 借鉴自 manga-image-translator (GPL-3.0) 的数量校验+二分拆分设计
- 机制③ 翻译缓存层 —— 借鉴自 comic-translate (Apache-2.0) 的块级源文匹配复用设计
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from amta.chat_client import chat, chat_text
from amta.guardrails import (_run_guardrails_for_test,  # noqa: F401  # 测试桥回导出
                             japanese_residue_check,  # noqa: F401
                             mechanical_guardrails)
from amta.metrics import levenshtein, norm
from amta.paths import ROOT
from amta.translate_tools import (GET_CONTEXT_BUDGET, MAX_TOOL_ROUNDS,  # noqa: F401
                                  TERM_BUDGET, TOOLS_SCHEMA, VISION_BUDGET,  # noqa: F401
                                  build_tools_context,  # noqa: F401
                                  execute_tool,  # noqa: F401
                                  run_tool_loop)

_ENV_PATH = ROOT.parent / ".env"  # 测试会 monkeypatch 它

# 日文残留判别特征唯一归属 metrics.contains_japanese；汉字与中文共用 U+4E00-U+9FFF 不可作残留依据
# 工具机（TOOLS_SCHEMA/预算/execute_tool/run_tool_loop）与机械护栏（mechanical/japanese_residue）
# 均已拆到 amta.translate_tools / amta.guardrails 深模块，此处仅 re-export 保持向后兼容。


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
    """发一次 OpenAI 兼容纯文本 chat 请求，返回回复文本；解析失败返回空串。

    深模块代理：HTTP/解析逻辑唯一归属 chat_client.chat_text（translate/ocr_engines 共用接缝）。
    """
    return chat_text(base_url, model, messages, api_key=api_key, timeout=timeout)


def chat_with_tools(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    api_key: str | None = None,
    timeout: int = 120,
) -> dict:
    """发一次 OpenAI 兼容 chat 请求（支持 tools/function calling），返回完整 message 结构。

    深模块代理：请求构造/响应解析唯一归属 chat_client.chat。
    """
    return chat(base_url, model, messages, tools=tools, api_key=api_key, timeout=timeout)


def extract_relevant_terms(text: str, glossary: dict) -> dict[str, Any]:
    """机制①：只返回与当前文本相关的术语（Levenshtein + 归一化 + 部分匹配）。

    借鉴自 manga-image-translator 的 extract_relevant_terms 设计——防大词表稀释 system 权重。
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


class TranslationCache:
    """机制③：源文 hash 作键的翻译缓存（源文变才重翻）。

    借鉴自 comic-translate 的块级源文匹配复用设计。
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._data: dict[str, str] = {}
        if path is not None and path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def _key(self, page: str, src: str) -> str:
        return hashlib.sha1(f"{page}:{src}".encode("utf-8")).hexdigest()

    def put(self, page: str, src: str, translated: str) -> None:
        self._data[self._key(page, src)] = translated
        if self.path is not None:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, page: str, src: str) -> str | None:
        return self._data.get(self._key(page, src))


def _prompt_parts(canon: list[dict], work_state: dict,
                  prev_pages: list[dict] | None, open_questions: list[dict] | None) -> tuple[str, str]:
    """拆出 System 层 + 上下文前缀（Uncertainty，不含当前页块）。

    最小披露原则（Patrick 裁决，2026-08-26）：角色/术语/前页译文不再预塞进 Prompt，
    由模型通过 lookup_term / get_context 工具按需获取；仅保留量小的待确认事项披露。
    两者对单页分批（二分拆分）只算一次。
    """
    system_lines = ["你是专业日文→中文漫画翻译专家，输出严格 JSON，不要输出任何额外文字。"]
    user_blocks = []
    if open_questions:
        qs = "\n".join(f"- {q['question']}（{q.get('status', 'open')}）" for q in open_questions)
        user_blocks.append(f"待确认事项：\n{qs}")
    return "\n".join(system_lines), "\n\n".join(user_blocks)


# ADR-016 Tools Contract（TOOLS_SCHEMA/预算/execute_tool/run_tool_loop）→ amta.translate_tools
# （见文件头 re-export）


def _format_region_text(r: dict) -> str:
    """格式化单个区域的文本，支持双引擎（Front3）和旧格式（text）。

    Front3 格式: baberu_text + vlm_text + contained_in
    旧格式: text
    """
    rid = r["region_id"]
    # 旧格式向后兼容
    if "text" in r and "baberu_text" not in r:
        return f'{rid}|{r["text"]}'

    # Front3 双引擎格式
    baberu = r.get("baberu_text", "") or ""
    vlm = r.get("vlm_text")
    vlm_status = r.get("vlm_status", "ok")
    contained = r.get("contained_in")

    parts = [f"[Baberu] {baberu if baberu else '(空)'}"]
    if vlm is not None:
        parts.append(f"[VLM] {vlm}")
    elif vlm_status and vlm_status != "ok":
        parts.append(f"[VLM: {vlm_status}]")

    if contained:
        parts.append(f"[嵌套于 {contained}]")

    return f'{rid}|{" ".join(parts)}'


def _current_block(canon: list[dict]) -> str:
    """当前批的 region_id|text 块（分批时每批单独拼）。

    支持 Front3 双引擎格式（baberu_text + vlm_text + contained_in）
    和旧格式（text）。
    """
    return "\n".join(_format_region_text(r) for r in canon)


def _build_current_content(prefix: str, batch: list[dict]) -> str:
    """组装当前批 user 内容（Current 层）：region_id|text 块 + Uncertainty 前缀。

    Front3 双引擎格式下，每个区域包含 [Baberu] 和 [VLM] 两个 OCR 结果，
    LLM 应自行判断哪个更准确后翻译。
    """
    has_dual_engine = any("baberu_text" in r for r in batch)
    if has_dual_engine:
        instr = (
            "请翻译当前页，输出 JSON：{\"r01\": \"译文\", ...}，region_id 必须与输入完全一致。\n"
            "每个区域有 [Baberu] 和 [VLM] 两个 OCR 结果，请结合上下文判断哪个更准确后翻译。\n"
            "[嵌套于 X] 表示该区域嵌套在区域 X 中，可能是同一气泡的大小字，请结合父区域文本判断。\n"
        )
    else:
        instr = '请翻译当前页，输出 JSON：{"r01": "译文", ...}，region_id 必须与输入完全一致：\n'
    cur = instr + _current_block(batch)
    return f"{prefix}\n\n{cur}" if prefix else cur


def build_translation_prompt(canon: list[dict], work_state: dict, *,
                             prev_pages: list[dict] | None = None,
                             open_questions: list[dict] | None = None) -> dict:
    """Context 分层组装：System/Current/History/Knowledge/Uncertainty。

    借鉴自 manga-image-translator 的 prev_context 独立 system message 设计（ADR-014 History 层）。
    """
    system, prefix = _prompt_parts(canon, work_state, prev_pages, open_questions)
    return {"system": system, "current": _build_current_content(prefix, canon)}


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


def translate_with_retry(canon: list[dict], llm, *, max_retries: int = 3,
                         split: bool = True, work_state: dict | None = None,
                         prev_pages: list[dict] | None = None,
                         open_questions: list[dict] | None = None,
                         tools_ctx: str | None = None,
                         tools: list[dict] | None = None,
                         state_dir: Path | str | None = None) -> dict[str, str]:
    """机制②分层 Loop：数量校验 → 重试 → 二分拆分 → 保留原文。

    借鉴自 manga-image-translator 的数量校验+二分拆分重试设计（ADR-014 机械 loop）。

    Context 分层接入：System 层与上下文前缀（Uncertainty）对整页算一次，
    分批重试时仅当前批的 region_id|text 块变化。
    tools_ctx：ADR-016 旧预取上下文（build_tools_context 产出），向后兼容保留，新代码不再使用。
    tools：真 function calling 工具声明（TOOLS_SCHEMA）。传了则启用工具循环：
    模型请求工具 → execute_tool 执行 → 结果回传 → 继续，直到纯文本输出；
    每工具预算（TERM_BUDGET/GET_CONTEXT_BUDGET）超限拒绝服务，轮次超 MAX_TOOL_ROUNDS 强制终止。
    llm 兼容两种签名：(messages) -> str（旧测试）或 (messages, tools=None) -> dict（chat_with_tools）。
    """
    ws = work_state or {}
    system, prefix = _prompt_parts(canon, ws, prev_pages, open_questions)
    if tools_ctx:
        system = f"{system}\n\n{tools_ctx}"

    def _one(batch: list[dict]) -> dict[str, str]:
        region_ids = [r["region_id"] for r in batch]
        budgets = {"lookup_term": TERM_BUDGET, "get_context": GET_CONTEXT_BUDGET}
        for _ in range(max_retries):
            content = _build_current_content(prefix, batch)
            messages: list[dict[str, Any]] = [{"role": "system", "content": system},
                                        {"role": "user", "content": content}]
            raw = run_tool_loop(llm, messages, budgets, work_state=ws,
                                prev_pages=prev_pages, state_dir=state_dir, tools=tools)
            parsed = parse_translation_response(raw, region_ids)
            if not mechanical_guardrails(batch, parsed):
                return parsed
        if split and len(batch) > 1:
            mid = len(batch) // 2
            merged = {}
            merged.update(_one(batch[:mid]))
            merged.update(_one(batch[mid:]))
            return merged
        return {r["region_id"]: "" for r in batch}

    return _one(list(canon))


# 片假名词段 = 专有名词/外来语特征最强（サグメ）；汉字人名难自动判别，留导演批（ADR-016）
_KATAKANA_TERM = re.compile(r"[\u30a0-\u30ff]{2,}")
# 过滤常见语法片假名（>=2 字仍会误抓），黑名单
_KATAKANA_STOP = {
    "カラ", "デス", "マス", "タリ", "シテ", "トモ", "ノニ", "コト",
    "トキ", "ヒト", "モノ", "コレ", "ソレ", "アレ", "コノ", "ソノ",
    "アイテ", "シテ", "カラ", "デモ", "ナノ", "ノデ", "トイウ", "トシテ",
}


class SuggestionsExtractor:
    """从译文里发现疑似新角色/专有名词 → suggestions（导演自动合并）。

    借鉴自 comic-translate 的 extra_context/术语演进设计 + ADR-014 suggestions 机制。
    ADR-016 收紧：只提片假名专有名词段，不整段日文，防污染 work_state 术语表。
    """

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()

    def extract(self, canon: list[dict], translations: dict[str, str]) -> list[dict]:
        suggestions = []
        for r in canon:
            # Front3 双引擎格式（ADR-023）：text 缺失时回退 baberu_text
            text = r.get("text") or r.get("baberu_text") or ""
            for m in _KATAKANA_TERM.finditer(text):
                term = m.group(0)
                if term in self.existing or term in _KATAKANA_STOP:
                    continue
                suggestions.append({
                    "term": term,
                    "source": r.get("region_id", ""),
                    "page": r.get("page", 0),
                    "translation": translations.get(r["region_id"], ""),
                    "status": "candidate",
                })
        return suggestions


def record_failure(log_path: Path, entry: dict) -> None:
    """on-failure 结构化落盘（ADR-016）：追加失败条目供 00_run_all 断点重跑。"""
    doc = {"failures": []}
    if log_path.exists():
        doc = json.loads(log_path.read_text(encoding="utf-8"))
    doc.setdefault("failures", []).append(entry)
    log_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
