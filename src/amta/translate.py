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

import requests

from amta.paths import ROOT

_ENV_PATH = ROOT.parent / ".env"  # 测试会 monkeypatch 它

_JAPANESE = re.compile(r"[\u3040-\u30ff]")  # 假名即日文残留的判别特征；汉字与中文共用 U+4E00-U+9FFF 不可作残留依据
_NORM_STRIP = re.compile(r"[^\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9]")


def _norm(text: str) -> str:
    """与 metrics.norm 同口径：去空白+去标点，保留假名/汉字/字母数字。"""
    return _NORM_STRIP.sub("", text or "")


def _levenshtein(a: str, b: str) -> int:
    """编辑距离（供术语相关度匹配）。"""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
        prev = cur
    return prev[-1]


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


def extract_relevant_terms(text: str, glossary: dict) -> dict[str, Any]:
    """机制①：只返回与当前文本相关的术语（Levenshtein + 归一化 + 部分匹配）。

    借鉴自 manga-image-translator 的 extract_relevant_terms 设计——防大词表稀释 system 权重。
    """
    if not glossary:
        return {}
    norm_text = _norm(text)
    relevant: dict[str, Any] = {}
    for term, meta in glossary.items():
        norm_term = _norm(term)
        if not norm_term:
            continue
        if norm_term in norm_text or norm_text in norm_term:
            relevant[term] = meta
        elif _levenshtein(norm_term[: min(len(norm_term), 6)], norm_text[: min(len(norm_text), 6)]) <= 2:
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
    """拆出 System 层 + 上下文前缀（History/Knowledge/Uncertainty，不含当前页块）。

    System 含角色/术语一致性约束；前缀含前页译文与待确认事项。两者对单页分批（二分拆分）只算一次。
    """
    system_lines = ["你是专业日文→中文漫画翻译专家，输出严格 JSON，不要输出任何额外文字。"]
    cur_text = " ".join(r["text"] for r in canon)
    chars = work_state.get("characters", {})
    terms = work_state.get("terms", {})
    rel_chars = extract_relevant_terms(cur_text, chars)
    rel_terms = extract_relevant_terms(cur_text, terms)
    if rel_chars or rel_terms:
        system_lines.append("本子已确认术语/角色（翻译时保持一致性）：")
        for k, v in rel_chars.items():
            system_lines.append(f"- 角色 {k}（来源 {v.get('source', '?')}）")
        for k, v in rel_terms.items():
            system_lines.append(f"- 术语 {k} = {v.get('translation', '?')}")

    user_blocks = []
    if prev_pages:
        hist = "\n".join(f"[{p.get('page', '?')}] {p.get('translated', '')}" for p in prev_pages[-3:])
        user_blocks.append(f"前几页译文（保持风格/术语一致）：\n{hist}")
    if open_questions:
        qs = "\n".join(f"- {q['question']}（{q.get('status', 'open')}）" for q in open_questions)
        user_blocks.append(f"待确认事项：\n{qs}")
    return "\n".join(system_lines), "\n\n".join(user_blocks)


# ADR-016 Tools Contract：预算常量（vision 最贵，token 受控）
TERM_BUDGET = 10      # 每页预取术语上限
VISION_BUDGET = 2     # 每页 vision 调用预算


def build_tools_context(canon: list[dict], work_state: dict,
                        prev_pages: list[dict] | None = None,
                        open_questions: list[dict] | None = None) -> str:
    """预取式 Tools 上下文（ADR-016）：当前页相关术语 + 前页译文显式注入。

    lookup_term/get_context 为本地文件读（免费），按 TERM_BUDGET 限条防 prompt 膨胀。
    """
    parts = []
    terms = work_state.get("terms", {})
    cur_text = " ".join(r["text"] for r in canon)
    rel = {k: v for k, v in terms.items()
           if _norm(k) and (_norm(k) in _norm(cur_text) or _norm(cur_text) in _norm(k))}
    if rel:
        parts.append(f"工具查得·本页相关术语(最多{TERM_BUDGET}条):")
        for k, v in list(rel.items())[:TERM_BUDGET]:
            parts.append(f"- {k} = {v.get('translation', '?')} (status={v.get('status', '?')})")
    if prev_pages:
        parts.append("工具查得·前页译文:")
        parts.extend(f"[{p.get('page', '?')}] {p.get('translated', '')}" for p in prev_pages[-3:])
    return "\n".join(parts)


def _current_block(canon: list[dict]) -> str:
    """当前批的 region_id|text 块（分批时每批单独拼）。"""
    return "\n".join(f'{r["region_id"]}|{r["text"]}' for r in canon)


def build_translation_prompt(canon: list[dict], work_state: dict, *,
                             prev_pages: list[dict] | None = None,
                             open_questions: list[dict] | None = None) -> dict:
    """Context 分层组装：System/Current/History/Knowledge/Uncertainty。

    借鉴自 manga-image-translator 的 prev_context 独立 system message 设计（ADR-014 History 层）。
    """
    system, prefix = _prompt_parts(canon, work_state, prev_pages, open_questions)
    cur = "请翻译当前页，输出 JSON：{\"r01\": \"译文\", ...}，region_id 必须与输入完全一致：\n" + _current_block(canon)
    current = f"{prefix}\n\n{cur}" if prefix else cur
    return {"system": system, "current": current}


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


def mechanical_guardrails(canon: list[dict], translation: dict[str, str]) -> list[str]:
    """护栏①结构错：region_id 与输入一一对应（无漏无重）、字段齐全。"""
    problems = []
    ids = {r["region_id"] for r in canon}
    for r in canon:
        rid = r["region_id"]
        if rid not in translation:
            problems.append(f"missing region_id {rid}")
        elif not translation[rid].strip():
            problems.append(f"empty translation for {rid}")
    extra = set(translation) - ids
    if extra:
        problems.append(f"extra region_ids: {sorted(extra)}")
    return problems


def japanese_residue_check(texts: list[str]) -> list[str]:
    """护栏②残留错：日文残留/空译文检测。返回有问题文本列表。"""
    bad = []
    for t in texts:
        t = t or ""
        if not t.strip():
            bad.append("")
        elif _JAPANESE.search(t):
            bad.append(t)
    return bad


def translate_with_retry(canon: list[dict], llm, *, max_retries: int = 3,
                         split: bool = True, work_state: dict | None = None,
                         prev_pages: list[dict] | None = None,
                         open_questions: list[dict] | None = None,
                         tools_ctx: str | None = None) -> dict[str, str]:
    """机制②分层 Loop：数量校验 → 重试 → 二分拆分 → 保留原文。

    借鉴自 manga-image-translator 的数量校验+二分拆分重试设计（ADR-014 机械 loop）。

    Context 分层接入：System 层与上下文前缀（History/Knowledge/Uncertainty）对整页算一次，
    分批重试时仅当前批的 region_id|text 块变化。
    tools_ctx：ADR-016 Tools 预取上下文（build_tools_context 产出），注入 System 层。
    """
    ws = work_state or {}
    system, prefix = _prompt_parts(canon, ws, prev_pages, open_questions)
    if tools_ctx:
        system = f"{system}\n\n{tools_ctx}"

    def _one(batch: list[dict]) -> dict[str, str]:
        region_ids = [r["region_id"] for r in batch]
        for _ in range(max_retries):
            cur = "请翻译当前页，输出 JSON：{\"r01\": \"译文\", ...}，region_id 必须与输入完全一致：\n" + _current_block(batch)
            content = f"{prefix}\n\n{cur}" if prefix else cur
            messages = [{"role": "system", "content": system},
                        {"role": "user", "content": content}]
            raw = llm(messages)
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
            text = r["text"] or ""
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


def _run_guardrails_for_test(canon: list[dict], translation: dict[str, str],
                             work_state: dict) -> list[str]:
    """测试桥：机械护栏 + Glossary Validator 合并（ADR-016 双层机械硬约束）。"""
    from amta.glossary import check_glossary
    return mechanical_guardrails(canon, translation) + check_glossary(canon, translation, work_state)


def record_failure(log_path: Path, entry: dict) -> None:
    """on-failure 结构化落盘（ADR-016）：追加失败条目供 00_run_all 断点重跑。"""
    doc = {"failures": []}
    if log_path.exists():
        doc = json.loads(log_path.read_text(encoding="utf-8"))
    doc.setdefault("failures", []).append(entry)
    log_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
