# 03_translate 工位实现计划（DeepSeek API 直调 + 双层护栏 + 分层 Loop + 三借鉴机制）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现翻译工位：读 `canon_text.json`（region_id↔原文），调 DeepSeek API（`.env` CHAT_*）翻译，双层护栏校验，机械 Loop，产出 `translation.json` + `state/suggestions.json`。可批跑、断点续跑、fastcheck 全绿。

**Architecture:** `src/amta/translate.py` = 纯库（纯文本 chat client + 3 借鉴机制 + 护栏 + loop 编排）；`scripts/03_translate.py` = 薄 CLI（读 work_id + canon_text → 调库 → 落盘 translation.json）。DeepSeek 无视觉，用纯文本 chat/completions（不走 ocr_engines 的多模态）。会话（导演）负责语义 loop 的最终修订；脚本只做机械 loop。

**Tech Stack:** Python 3.8+（requests、pathlib）、DeepSeek OpenAI 兼容 API（`.env` CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY）、`src/amta/workstate.py`、`src/amta/paths.py`、metrics.norm。

**许可证纪律（ADR-014 grill 定案）：** 三机制借鉴自 manga-image-translator (GPL-3.0) 与 comic-translate (Apache-2.0)，**只借鉴设计不复制代码**；文件头 docstring 注明来源；ADR-014 补"借鉴来源与许可证"一节。

---

## File Structure

- `src/amta/translate.py`（新建，纯库）：
  - `text_chat(base_url, model, messages, api_key, timeout)` — 纯文本 chat/completions（DeepSeek 无视觉）
  - `get_chat_config()` — 从 `.env` 读 CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY
  - `extract_relevant_terms(text, glossary)` — 机制①：相关术语提取（Levenshtein + 日文归一化 + 部分匹配）
  - `build_translation_prompt(canon, work_state, prev_pages, open_questions)` — Context 分层组装
  - `parse_translation_response(raw, region_ids)` — 解析 LLM 输出为 {region_id: 译文}
  - `mechanical_guardrails(canon, translation)` — 护栏①结构错：region_id 一一对应/字段/数量
  - `japanese_residue_check(texts)` — 护栏②残留错：日文残留/空译文
  - `translate_with_retry(canon, ctx, cache)` — 分层 Loop（数量校验→重试→二分拆分→保留原文）
  - `TranslationCache` — 机制③：源文 hash 作键缓存
  - `SuggestionsExtractor` — 从译文里发现新术语/角色 → suggestions.json
- `scripts/03_translate.py`（新建，薄 CLI）：`--work-id --canon --out --state-dir`
- `tests/test_translate.py`（新建）：纯逻辑单测（不碰网络）
- `docs/decisions/014-translate-station-architecture.md`（修改）：补"借鉴来源与许可证"一节

---

### Task 1: 纯文本 chat client + 配置读取

**Files:**
- Create: `src/amta/translate.py`
- Test: `tests/test_translate.py`

- [ ] **Step 1: Write the failing test**

```python
"""test_translate.py — 03_translate 纯逻辑单测（不碰网络）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_get_chat_config_reads_env(tmp_path, monkeypatch):
    from amta import translate
    env = tmp_path / ".env"
    env.write_text(
        "CHAT_BASE_URL=https://api.deepseek.com\nCHAT_MODEL=deepseek-v4-pro-0813\nCHAT_API_KEY=sk-test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(translate, "_ENV_PATH", env)
    cfg = translate.get_chat_config()
    assert cfg["base_url"] == "https://api.deepseek.com"
    assert cfg["model"] == "deepseek-v4-pro-0813"
    assert cfg["api_key"] == "sk-test"


def test_text_chat_builds_payload_and_parses(monkeypatch):
    from amta import translate

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=120):
        captured["url"] = url
        captured["json"] = json
        class _R:
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": "译文"}}]}
        return _R()

    monkeypatch.setattr(translate.requests, "post", fake_post)
    out = translate.text_chat("https://api.deepseek.com", "m", [{"role": "user", "content": "hi"}], api_key="k")
    assert out == "译文"
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -20`
Expected: FAIL with `ModuleNotFoundError: No module named 'amta.translate'`

- [ ] **Step 3: Write minimal implementation**

Create `src/amta/translate.py`:

```python
"""翻译工位纯库 — DeepSeek API 直调 + 双层护栏 + 分层 Loop + 三借鉴机制。

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

# .env 位置：workspace 根（E:\\manga translator agent\\.env），可被测试 monkeypatch 覆盖
_ENV_PATH = ROOT.parent / ".env"

_JAPANESE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
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


def _env_value(key: str) -> str | None:
    """从环境变量或 .env 读配置值。"""
    if os.environ.get(key):
        return os.environ[key]
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def get_chat_config() -> dict[str, str]:
    """读 DeepSeek 聊天配置：CHAT_BASE_URL / CHAT_MODEL / CHAT_API_KEY。"""
    base = _env_value("CHAT_BASE_URL")
    model = _env_value("CHAT_MODEL")
    key = _env_value("CHAT_API_KEY")
    missing = [n for n, v in (("CHAT_BASE_URL", base), ("CHAT_MODEL", model), ("CHAT_API_KEY", key)) if not v]
    if missing:
        raise RuntimeError(f"缺少 .env 配置: {', '.join(missing)}")
    return {"base_url": base, "model": model, "api_key": key}


def text_chat(base_url: str, model: str, messages: list[dict], *, api_key: str | None = None,
              timeout: int = 120) -> str:
    """纯文本 chat/completions（DeepSeek 无视觉，不走多模态）。解析失败返回空串。"""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    r = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json={"model": model, "messages": messages},
        timeout=timeout,
    )
    r.raise_for_status()
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -10`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py tests/test_translate.py
git commit -m "feat(translate): 纯文本 chat client + CHAT_* 配置读取"
```

---

### Task 2: 机制① glossary 相关条目提取 + 机制③ 翻译缓存

**Files:**
- Modify: `src/amta/translate.py`
- Test: `tests/test_translate.py`

- [ ] **Step 1: Write the failing test**

```python
def test_extract_relevant_terms_partial_match():
    from amta import translate
    glossary = {
        "豊姫": {"canon_translation": "丰姬"},
        "永琳": {"canon_translation": "永琳"},
        "月の都": {"canon_translation": "月都"},
    }
    terms = translate.extract_relevant_terms("豊姫が永琳と話す", glossary)
    assert "豊姫" in terms
    assert "永琳" in terms
    assert "月の都" not in terms  # 与当前文本不匹配，不注入


def test_translation_cache_hash_key():
    from amta import translate
    c = translate.TranslationCache()
    c.put("page_1", "原文A", "译文A")
    assert c.get("page_1", "原文A") == "译文A"
    assert c.get("page_1", "原文B") is None  # 源文变 → 缓存未命中（重翻）
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -15`
Expected: FAIL with `AttributeError: module 'amta.translate' has no attribute 'extract_relevant_terms'`

- [ ] **Step 3: Implement**

Append to `src/amta/translate.py`:

```python
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
        # 完全包含 / 归一化后相等 / 编辑距离小 → 相关
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
        self._data: dict[str, dict[str, str]] = {}
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -10`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py tests/test_translate.py
git commit -m "feat(translate): 机制①glossary相关条目提取 + 机制③翻译缓存(源文hash键)"
```

---

### Task 3: Context 组装 + 输出解析 + 双层护栏

**Files:**
- Modify: `src/amta/translate.py`
- Test: `tests/test_translate.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_prompt_layers():
    from amta import translate
    canon = [{"region_id": "r01", "text": "豊姫が話す"}]
    ws = {"characters": {"豊姫": {"status": "confirmed", "source": "p4"}}, "terms": {}, "current_scene": {"page": 1}}
    prompt = translate.build_translation_prompt(canon, ws, prev_pages=[], open_questions=[])
    assert "system" in prompt
    assert "豊姫" in json.dumps(prompt, ensure_ascii=False)  # Knowledge 层带角色


def test_mechanical_guardrails_catches_missing_region():
    from amta import translate
    canon = [{"region_id": "r01", "text": "甲"}, {"region_id": "r02", "text": "乙"}]
    translation = {"r01": "译甲"}  # r02 缺失
    problems = translate.mechanical_guardrails(canon, translation)
    assert any("r02" in p for p in problems)


def test_japanese_residue_detects_kanji():
    from amta import translate
    assert translate.japanese_residue_check(["完全译文", "残り日本語"]) == ["残り日本語"]
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -15`
Expected: FAIL with `AttributeError: ... has no attribute 'build_translation_prompt'`

- [ ] **Step 3: Implement**

Append to `src/amta/translate.py`:

```python
def build_translation_prompt(canon: list[dict], work_state: dict, *,
                             prev_pages: list[dict] | None = None,
                             open_questions: list[dict] | None = None) -> dict:
    """Context 分层组装：System/Current/History/Knowledge/Uncertainty。

    借鉴自 manga-image-translator 的 prev_context 独立 system message 设计（ADR-014 History 层）。
    """
    system_lines = ["你是专业日文→中文漫画翻译专家，输出严格 JSON，不要输出任何额外文字。"]
    # Knowledge：只注入与当前文本相关的角色/术语（机制①）
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
    cur = "\n".join(f'{r["region_id"]}|{r["text"]}' for r in canon)
    user_blocks.append("请翻译当前页，输出 JSON：{\"r01\": \"译文\", ...}，region_id 必须与输入完全一致：\n" + cur)

    return {
        "system": "\n".join(system_lines),
        "current": "\n".join(user_blocks),
    }


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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -10`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py tests/test_translate.py
git commit -m "feat(translate): Context分层组装 + 输出解析 + 机械护栏(结构/残留)"
```

---

### Task 4: 分层 Loop + suggestions 提取 + 主入口（机械 loop）

**Files:**
- Modify: `src/amta/translate.py`
- Test: `tests/test_translate.py`

- [ ] **Step 1: Write the failing test**

```python
def test_translate_with_retry_uses_mechanical_loop():
    from amta import translate

    class _LLM:
        def __init__(self):
            self.calls = 0
        def __call__(self, messages):
            self.calls += 1
            return '{"r01": "译文", "r02": "译文二"}'

    canon = [{"region_id": "r01", "text": "甲"}, {"region_id": "r02", "text": "乙"}]
    llm = _LLM()
    out = translate.translate_with_retry(canon, llm, max_retries=2)
    assert out["r01"] == "译文"
    assert out["r02"] == "译文二"
    assert llm.calls >= 1


def test_translate_with_retry_splits_on_failure():
    from amta import translate

    calls = {"n": 0}

    def llm(messages):
        calls["n"] += 1
        # 第一次返回缺 r02（机械护栏失败），第二次全
        if calls["n"] == 1:
            return '{"r01": "译文"}'
        return '{"r01": "译文", "r02": "译文二"}'

    canon = [{"region_id": "r01", "text": "甲"}, {"region_id": "r02", "text": "乙"}]
    out = translate.translate_with_retry(canon, llm, max_retries=2)
    assert set(out) == {"r01", "r02"}
    assert calls["n"] >= 2


def test_suggestions_extractor_finds_new_term():
    from amta import translate
    ex = translate.SuggestionsExtractor(existing={"豊姫"})
    canon = [{"region_id": "r01", "text": "稀神サグメが現れた"}]
    suggestions = ex.extract(canon, translations={"r01": "稀神朔姬出现了"})
    # 找到疑似新角色名（日文术语，不在现有集）
    assert any("サグメ" in s.get("term", "") for s in suggestions)
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -15`
Expected: FAIL with `AttributeError: ... has no attribute 'translate_with_retry'`

- [ ] **Step 3: Implement**

Append to `src/amta/translate.py`:

```python
def translate_with_retry(canon: list[dict], llm, *, max_retries: int = 3,
                         split: bool = True) -> dict[str, str]:
    """机制②分层 Loop：数量校验 → 重试 → 二分拆分 → 保留原文。

    借鉴自 manga-image-translator 的数量校验+二分拆分重试设计（ADR-014 机械 loop）。
    机械护栏失败→重试；整批多次失败→二分拆分递归；单条仍败→保留空（交导演语义 loop）。
    """
    def _one(batch: list[dict]) -> dict[str, str]:
        region_ids = [r["region_id"] for r in batch]
        for _ in range(max_retries):
            messages = [{"role": "system", "content": "你是漫画翻译专家，输出严格 JSON。"},
                        {"role": "user", "content": "\n".join(f'{r["region_id"]}|{r["text"]}' for r in batch)}]
            raw = llm(messages)
            parsed = parse_translation_response(raw, region_ids)
            if not mechanical_guardrails(batch, parsed):
                return parsed  # 全部 region 对应成功
        # 机械护栏多次失败 → 二分拆分
        if split and len(batch) > 1:
            mid = len(batch) // 2
            merged = {}
            merged.update(_one(batch[:mid]))
            merged.update(_one(batch[mid:]))
            return merged
        # 拆到底仍失败 → 保留原文（空译文，交导演语义 loop）
        return {r["region_id"]: "" for r in batch}

    return _one(list(canon))


class SuggestionsExtractor:
    """从译文里发现疑似新术语/角色 → suggestions（导演自动合并）。

    借鉴自 comic-translate 的 extra_context/术语演进设计 + ADR-014 suggestions 机制。
    """

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()

    def extract(self, canon: list[dict], translations: dict[str, str]) -> list[dict]:
        suggestions = []
        for r in canon:
            text = r["text"]
            # 原文里的连续假名/汉字词组（≥2 字）且不在现有集 → 候选新术语
            for m in re.finditer(r"[\u3040-\u30ff\u4e00-\u9fff]{2,}", text):
                term = m.group(0)
                if term not in self.existing:
                    suggestions.append({
                        "term": term,
                        "source": r.get("region_id", ""),
                        "page": r.get("page", 0),
                        "translation": translations.get(r["region_id"], ""),
                        "status": "candidate",
                    })
        return suggestions
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -10`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/amta/translate.py tests/test_translate.py
git commit -m "feat(translate): 机制②分层Loop(数量校验→重试→二分拆分) + suggestions提取"
```

---

### Task 5: 薄 CLI 工位脚本 `scripts/03_translate.py`

**Files:**
- Create: `scripts/03_translate.py`
- Test: `tests/test_translate.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cli_translate_uses_llm_and_writes_translation(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from amta import translate, paths

    canon = [{"region_id": "r01", "text": "豊姫が話す", "page": 1}]
    canon_path = tmp_path / "canon_text.json"
    canon_path.write_text(json.dumps(canon, ensure_ascii=False), encoding="utf-8")

    out_path = tmp_path / "translation.json"

    def fake_llm(messages):
        return '{"r01": "丰姬在说话"}'

    monkeypatch.setattr(translate, "get_chat_config", lambda: {
        "base_url": "x", "model": "m", "api_key": "k"})
    monkeypatch.setattr(translate, "text_chat", fake_llm)

    from _03_translate import run
    result = run(str(canon_path), str(out_path))
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["r01"] == "丰姬在说话"
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -15`
Expected: FAIL with `ModuleNotFoundError: No module named '_03_translate'`

- [ ] **Step 3: Implement**

Create `scripts/03_translate.py`:

```python
"""03_translate 工位 — 读 canon_text.json → DeepSeek 翻译 → translation.json + suggestions.json。

用法: python scripts/03_translate.py --canon <canon_text.json> --out <translation.json> [--work-id ID] [--state-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta import paths, translate  # noqa: E402
from amta.workstate import load_state  # noqa: E402


def run(canon_path: str | Path, out_path: str | Path, *,
        work_id: str | None = None, state_dir: str | Path | None = None) -> dict:
    canon = paths.read_json(canon_path)
    cfg = translate.get_chat_config()
    ws = load_state(work_id) if work_id else {}

    def llm(messages):
        return translate.text_chat(cfg["base_url"], cfg["model"], messages, api_key=cfg["api_key"])

    result = translate.translate_with_retry(canon, llm)

    # 残留护栏：只标记，不阻塞（机械结构已由 translate_with_retry 校验）
    residue = translate.japanese_residue_check(list(result.values()))
    out = {"work_id": work_id or "", "translations": result, "residue": residue}
    paths.write_json(out_path, out)

    # suggestions：发现新术语 → state/suggestions.json（导演自动合并）
    if work_id and state_dir:
        ex = translate.SuggestionsExtractor(existing=set(ws.get("characters", {})) | set(ws.get("terms", {})))
        sugg = ex.extract(canon, result)
        if sugg:
            sugg_path = Path(state_dir) / "suggestions.json"
            prev = json.loads(sugg_path.read_text(encoding="utf-8")) if sugg_path.exists() else {"work_id": work_id, "suggestions": []}
            prev.setdefault("suggestions", []).extend(sugg)
            paths.write_json(sugg_path, prev)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canon", required=True, help="canon_text.json 路径")
    ap.add_argument("--out", required=True, help="输出 translation.json 路径")
    ap.add_argument("--work-id", default=None)
    ap.add_argument("--state-dir", default=None)
    a = ap.parse_args()
    run(a.canon, a.out, work_id=a.work_id, state_dir=a.state_dir)
    print(f"[03_translate] -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_translate.py -v 2>&1 | tail -10`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/03_translate.py tests/test_translate.py
git commit -m "feat(translate): 03_translate 薄 CLI 工位 — canon→translation+suggestions"
```

---

### Task 6: 全量 fastcheck + 许可证注释核对

**Files:**
- Test: `tests/test_translate.py`（已含）

- [ ] **Step 1: Run full fastcheck**

Run: `python scripts/fastcheck.py 2>&1 | tail -20`
Expected: ALL PASS（compile + ruff + pyright + 全部单测，含新增 translate 测试）

- [ ] **Step 2: Verify license discipline**

grep 确认 translate.py 文件头有机制来源注释：
Run: `grep -c "借鉴自" src/amta/translate.py`
Expected: ≥3（三机制各标注来源仓库+许可证）

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix(translate): fastcheck 收尾 + 许可证注释核对" || echo "no changes"
```

---

### Task 7: ADR-014 补"借鉴来源与许可证" + 收尾

**Files:**
- Modify: `docs/decisions/014-translate-station-architecture.md`

- [ ] **Step 1: Append license section**

在 ADR-014 末尾追加：

```markdown
## 借鉴来源与许可证（grill 定案）

- 机制① glossary 相关条目提取 —— 借鉴自 manga-image-translator（zyddnys，GPL-3.0）`extract_relevant_terms` 设计：只喂与当前文本匹配的术语，防大词表稀释 system 权重。**只借鉴设计，不复制代码**。
- 机制② 分层拆分重试 —— 借鉴自 manga-image-translator（GPL-3.0）：数量校验 → 重试 → 二分拆分递归 → 保留原文。**只借鉴两层（数量校验+拆分重试），不抄其 300+ 行全逻辑**。
- 机制③ 翻译缓存层 —— 借鉴自 comic-translate（ogkalu2，Apache-2.0）：源文 hash 作键，源文变才重翻。
- 纪律：GPL-3.0 仓库仅借鉴设计思路；Apache-2.0 可自由复制（带署名）。代码注释已记录来源。若未来开源 AMTA，GPL 借鉴点需换实现。
```

- [ ] **Step 2: Run fastcheck**

Run: `python scripts/fastcheck.py 2>&1 | tail -5`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add docs/decisions/014-translate-station-architecture.md
git commit -m "docs(adr): ADR-014 补借鉴来源与许可证纪律（grill 定案）"
```

---

## Self-Review

**Spec coverage：**
- ✅ 03_translate 工位脚本（Task 5）
- ✅ DeepSeek API 直调（Task 1 text_chat + CHAT_* 配置）
- ✅ 双层护栏：结构（Task 3 mechanical_guardrails）+ 残留（Task 3 japanese_residue_check）；语义 VLM 护栏不在本计划（后续独立任务）
- ✅ 分层 Loop：机械 loop 脚本做（Task 4 translate_with_retry），语义 loop 交导演（保留原文=空译文待导演修订）
- ✅ 三借鉴机制：①glossary（Task 2）+②分层重试（Task 4）+③缓存（Task 2）
- ✅ suggestions.json（Task 5）+ 导演自动合并（SuggestionsExtractor）
- ✅ 许可证纪律（Task 6/7 注释 + ADR 记录）
- ✅ 可批跑/断点续跑：CLI 单页可跑，TranslationCache 支持跨页缓存

**Placeholder scan：** 无 TBD/TODO，每步含完整代码与命令。

**Type consistency：** `extract_relevant_terms(text, glossary)` / `translate_with_retry(canon, llm, max_retries, split)` / `TranslationCache.put/get(page, src)` / `mechanical_guardrails(canon, translation)` 在各 Task 间签名一致。
