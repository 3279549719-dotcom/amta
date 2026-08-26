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

    响应 message 可能含 tool_calls（模型请求调用工具）或纯 content（最终回答）；
    解析失败返回 {"content": ""}。
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
    r = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    try:
        return r.json()["choices"][0]["message"] or {}
    except (KeyError, IndexError, TypeError):
        return {"content": ""}


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


# ADR-016 Tools Contract：预算常量（真拦截——超限拒绝服务，非死常量）
TERM_BUDGET = 10          # 每页 lookup_term 调用预算
GET_CONTEXT_BUDGET = 3    # 每页 get_context 调用预算
VISION_BUDGET = 2         # 每页 vision 调用预算（第一版未接线，预留）
MAX_TOOL_ROUNDS = 6       # 单批工具循环轮次上限（防死循环）

# 真 function calling 工具声明（DeepSeek OpenAI 兼容 tools 格式）
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "lookup_term",
            "description": "查询本子已确认的术语/角色译名（如 豊姫→丰姬）。翻译中遇到专有名词、角色名、作品术语不确定译法时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "要查询的日文术语或角色名原文"}
                },
                "required": ["term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_context",
            "description": "获取前几页的译文（保持风格/术语一致）。翻译当前页前可调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pages": {"type": "integer", "description": "回溯页数，最多 3"}
                },
                "required": [],
            },
        },
    },
]


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


def execute_tool(name: str, args: dict, work_state: dict,
                 prev_pages: list[dict] | None = None,
                 state_dir: Path | str | None = None) -> str:
    """真工具执行器：lookup_term 查 work_state 术语/角色；get_context 读前页译文。

    返回给模型的文本结果（本地文件读，免费）；预算拦截由调用方（工具循环）负责。
    """
    ws = work_state or {}
    if name == "lookup_term":
        term = str(args.get("term", "")).strip()
        if not term:
            return "参数缺失：请提供 term"
        hit: dict[str, Any] | None = None
        for pool, kind in ((ws.get("terms", {}), "术语"), (ws.get("characters", {}), "角色")):
            for k, v in pool.items():
                if k == term or _norm(k) == _norm(term):
                    hit = {**v, "kind": kind, "key": k}
                    break
            if hit:
                break
        if not hit:
            return f"未找到术语「{term}」的已确认译名（可基于上下文自行判断）"
        trans = hit.get("translation") or hit.get("canon_translation") or "?"
        status = hit.get("status", "?")
        src = hit.get("source", "?")
        return f"{hit['kind']}「{hit['key']}」= {trans}（status={status}，来源 {src}）"
    if name == "get_context":
        pages = max(1, min(int(args.get("pages") or 3), 3))
        # 优先读前页产物:state_dir/../artifacts/translation.json(00_run_all 断点续跑布局),
        # 回退 state_dir/translation.json / prev_pages 参数
        candidates: list[Path] = []
        if state_dir is not None:
            sdir = Path(state_dir)
            candidates = [sdir.parent / "artifacts" / "translation.json",
                          sdir / "translation.json"]
        for p in candidates:
            if p.exists():
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                    trans = doc.get("translations", {})
                    by_page: dict[str, list[str]] = {}
                    for rid, t in trans.items():
                        m = re.match(r"page_(\d+)", str(rid))
                        pg = m.group(1) if m else "?"
                        by_page.setdefault(pg, []).append(f"[{rid}] {t}")
                    ordered = sorted(by_page.items(), key=lambda kv: kv[0])
                    selected = ordered[-pages:]
                    if selected:
                        return "前页译文：\n" + "\n\n".join("\n".join(v) for _, v in selected)
                except (json.JSONDecodeError, OSError):
                    pass
        if prev_pages:
            lines = [f"[{h.get('page', '?')}] {h.get('translated', '')}" for h in prev_pages[-pages:]]
            return "前页译文：\n" + "\n".join(lines)
        return "暂无前页译文"
    return f"未知工具：{name}"


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
            cur = "请翻译当前页，输出 JSON：{\"r01\": \"译文\", ...}，region_id 必须与输入完全一致：\n" + _current_block(batch)
            content = f"{prefix}\n\n{cur}" if prefix else cur
            messages: list[dict[str, Any]] = [{"role": "system", "content": system},
                                        {"role": "user", "content": content}]
            raw = ""
            for _round in range(MAX_TOOL_ROUNDS):
                if tools:
                    resp = llm(messages, tools=tools)
                else:
                    resp = llm(messages)
                if isinstance(resp, str):
                    raw = resp
                    break
                calls = resp.get("tool_calls") or []
                content_text = resp.get("content") or ""
                if not calls:
                    raw = content_text
                    break
                messages.append({"role": "assistant", "content": content_text or None,
                                 "tool_calls": calls})
                for call in calls:
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    if budgets.get(name, 0) <= 0:
                        result = f"工具「{name}」本次调用预算已耗尽，请基于现有信息继续翻译"
                    else:
                        budgets[name] -= 1
                        result = execute_tool(name, args, ws, prev_pages, state_dir)
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                     "content": result})
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
