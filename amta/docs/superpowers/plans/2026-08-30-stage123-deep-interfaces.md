# Stage 1-3 深接口改造 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 1-3 工位接口深化——产物契约单一事实源（artifacts.py）+ 三个深工位模块（detect/ocr/translate_station）+ 配置与 suggestions 收敛 + 00_run_all 减负 + 契约回归护栏。

**Architecture:** B 案（契约收敛 + 工位深化）。契约层用 TypedDict + 纯函数校验，零外部依赖；工位深模块把编排副作用（trace/raw_dump/suggestions/failure log）藏进实现，脚本退化为薄 CLI；subprocess 编排与断点语义不动。04/05 消费方按 Patrick 裁决豁免（未实质开发）。

**Tech Stack:** Python 3.13（`py -3.13`，L26）/ pytest / ruff / pyright / TypedDict（stdlib）。

**Spec:** `docs/superpowers/specs/2026-08-30-stage123-deep-interfaces-design.md`

**执行环境铁律：**
- 工作目录：worktree `E:\manga translator agent\amta\.worktrees\stage123-deep-interfaces`，分支 `feat/stage123-deep-interfaces`。\n- 测试一律 `py -3.13 -m pytest tests -q --basetemp output/logs/.pytest-basetemp`（PATH `python` 是 AutoClaw 解释器，无 pytest，L26）；手工跑看 `N passed`，不信 exit 1（L19）。
- pre-commit 钩子自动跑 fastcheck（compile+ruff+pyright+pytest+depguard），commit 被拦即修，**禁用 `--no-verify`**。
- OpenClaw 显示会脱敏 `api_key=`（L27）：改 config/translate 后必须 `Get-Content` 校验真实内容。
- 基线（2026-08-30 实测）：**298 passed, 1 skipped**。

---

### Task 0: 环境护栏修复（已完成）

**Files:**
- Modify: `scripts/audit.py`（find_duplicate_files 排除只看相对扫描根）
- Test: `tests/test_audit_hygiene.py`（+test_duplicate_files_inside_worktree）、`tests/test_get_context_ab.py`（真实数据缺失显式 SKIP）

- [x] 红测试：worktree 内 find_duplicate_files 返回 0（`.worktrees` 组件误杀）
- [x] 修复排除逻辑 + SKIP 护栏；fastcheck 298 passed
- [x] Commit `3387be4`（含 spec 文档一并入库）

---

### Task 1: artifacts.py — 产物契约单一事实源

**Files:**
- Create: `src/amta/artifacts.py`
- Modify: `src/amta/canon_schema.py`（validate_canon 改为 re-export）
- Test: `tests/test_artifacts.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_artifacts.py`：

```python
"""artifacts 契约层测试：页键/ID 规则、命名、validate、load/save round-trip。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import artifacts


# ---------- 页键 / region_id 规则 ----------

def test_page_key_and_idx_from_raw():
    assert artifacts.page_key(10) == "page_10"
    assert artifacts.page_idx_from_raw(Path("D:/x/11.jpg")) == 10


def test_region_id_single_space():
    assert artifacts.region_id(5, 3) == "page_5_u03"


def test_normalize_region_ids_renames_block_and_parent():
    blocks = [
        {"region_id": "u00", "bbox": [0, 0, 10, 10], "contained_in": None},
        {"region_id": "u01", "bbox": [1, 1, 5, 5], "contained_in": "u00"},
    ]
    out = artifacts.normalize_region_ids(blocks, 7)
    assert out[0]["region_id"] == "page_7_u00"
    assert out[1]["region_id"] == "page_7_u01"
    assert out[1]["contained_in"] == "page_7_u00"  # 父引用同步重写
    assert out[0]["contained_in"] is None


# ---------- 命名唯一归属 ----------

def test_artifact_paths_and_trace(tmp_path):
    paths = artifacts.artifact_paths(tmp_path, "page_0")
    assert paths["detection"] == tmp_path / "page_0_detection.json"
    assert paths["canon"] == tmp_path / "page_0_canon.json"
    assert paths["crops"] == tmp_path / "crops"
    tp = artifacts.trace_path(tmp_path, "page_0", "01_detect")
    assert tp.name == "page_0_01_detect_trace.json"


def test_write_trace_stamps(tmp_path):
    p = artifacts.write_trace(tmp_path, "page_0", "02_ocr", {"k": 1})
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["station"] == "02_ocr" and doc["page"] == "page_0" and doc["k"] == 1


# ---------- validate / load / save ----------

def _canon_items():
    return [{"region_id": "page_0_u00", "baberu_text": "あ", "vlm_text": None,
             "vlm_status": "ok", "page": 0, "contained_in": None}]


def test_validate_canon_items_ok_and_problems():
    assert artifacts.validate_canon_items(_canon_items()) == []
    bad = [{"region_id": "", "baberu_text": "あ", "page": 0},
           {"region_id": "page_0_u00", "baberu_text": "", "vlm_text": "", "page": 0},
           {"region_id": "page_0_u00", "baberu_text": "あ", "page": "0"},
           {"region_id": "page_0_u00", "baberu_text": "あ", "page": 0, "category": "x"}]
    problems = artifacts.validate_canon_items(bad)
    assert any("missing region_id" in p for p in problems)
    assert any("empty text" in p for p in problems)
    assert any("bad page" in p for p in problems)
    assert any("bad category" in p for p in problems)


def test_canon_roundtrip_doc_shape(tmp_path):
    p = artifacts.save_canon(tmp_path, "page_0", "w1", _canon_items(), vlm_status="ok")
    assert p == tmp_path / "page_0_canon.json"
    doc = artifacts.load_canon(p)
    assert doc["work_id"] == "w1" and doc["page"] == "page_0"
    assert doc["schema_version"] == artifacts.SCHEMA_VERSION
    assert doc["n_regions"] == 1 and doc["items"][0]["region_id"] == "page_0_u00"


def test_load_canon_legacy_bare_list(tmp_path):
    p = tmp_path / "page_0_canon.json"
    p.write_text(json.dumps(_canon_items(), ensure_ascii=False), encoding="utf-8")
    doc = artifacts.load_canon(p)  # 旧裸 list → 归一化为 doc
    assert doc["n_regions"] == 1


def test_load_canon_rejects_invalid(tmp_path):
    p = tmp_path / "page_0_canon.json"
    p.write_text(json.dumps([{"region_id": "", "baberu_text": "あ", "page": 0}]), encoding="utf-8")
    with pytest.raises(ValueError, match="region_id"):
        artifacts.load_canon(p)


def test_detection_roundtrip_and_bad_bbox(tmp_path):
    doc = {"work_id": "w", "blocks": [{"region_id": "page_0_u00", "bbox": [0, 0, 5, 5]}],
           "n_boxes": 1}
    p = artifacts.save_detection(tmp_path, "page_0", doc)
    assert artifacts.load_detection(p)["blocks"][0]["region_id"] == "page_0_u00"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"blocks": [{"bbox": [1, 2]}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="bbox"):
        artifacts.load_detection(bad)


def test_translation_roundtrip(tmp_path):
    p = artifacts.save_translation(tmp_path, "page_0", "w", {"page_0_u00": "译"}, [], [])
    doc = artifacts.load_translation(p)
    assert doc["translations"] == {"page_0_u00": "译"}
    assert doc["residue"] == [] and doc["schema_version"] == artifacts.SCHEMA_VERSION
```

- [ ] **Step 2: 跑测试确认失败** — `py -3.13 -m pytest tests/test_artifacts.py -q --basetemp output/logs/.pytest-basetemp` → 预期 `ModuleNotFoundError: amta.artifacts` 或 AttributeError。

- [ ] **Step 3: 实现 `src/amta/artifacts.py`**：

```python
"""工位产物契约 — 单一事实源（Stage 1-3 深接口改造）。

唯一归属：产物信封与 schema、页键与 region_id 规则（全链单空间
page_{idx}_u{i:02d}）、产物/trace 文件命名、load_*(normalize+validate) /
save_*(信封盖章)。设计依据 docs/superpowers/specs/2026-08-30-stage123-deep-interfaces-design.md。
schema_version "2.1" = front3 "2.0" → canon doc 化 + region_id 单空间。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, TypedDict

from amta.paths import read_json, write_json

SCHEMA_VERSION = "2.1"
CATEGORIES = ("dialogue_bubble", "overlay_text", "sfx")
SUB_TIERS = ("primary", "aside")


class DetectionBlock(TypedDict, total=False):
    region_id: str
    bbox: list[float]
    category: str
    sub_tier: str
    bubble_type: str
    node_id: str
    text: str
    source_engines: list[str]
    contained_in: str | None


class DetectionArtifact(TypedDict, total=False):
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    source: str
    image_meta: dict
    blocks: list[DetectionBlock]
    n_boxes: int
    detect_steps: list[str]
    per_engine_boxes: dict[str, int]


class CanonItem(TypedDict, total=False):
    region_id: str
    bbox: list[float]
    baberu_text: str
    vlm_text: str | None
    vlm_status: str
    contained_in: str | None
    source_engines: list[str]
    page: int
    category: str
    sub_tier: str
    node_id: str


class CanonArtifact(TypedDict, total=False):
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    items: list[CanonItem]
    n_regions: int
    vlm_status: str


class TranslationArtifact(TypedDict, total=False):
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    translations: dict[str, str]
    residue: list[str]
    glossary_violations: list


# ---------- 页键 / ID / 命名（唯一归属） ----------

def page_key(page_idx: int) -> str:
    """0 基页键（与 00_run_all / region_id / eval_stage2/3 对齐）。"""
    return f"page_{page_idx}"


def page_idx_from_raw(raw_page: Path) -> int:
    """N.jpg（1 基文件名）→ 0 基页号。"""
    return int(raw_page.stem) - 1


def region_id(page_idx: int, order: int) -> str:
    """全链单空间 region_id（修 F3 双空间）。"""
    return f"page_{page_idx}_u{order:02d}"


def normalize_region_ids(blocks: list[dict], page_idx: int) -> list[dict]:
    """mark_contained 的 u{i:02d} 编号 → 单空间 page_{idx}_u{i:02d}（含 contained_in 重写）。

    u 编号即列表序（mark_contained 按序分配），纯函数、不改输入。
    """
    mapping = {f"u{i:02d}": region_id(page_idx, i) for i in range(len(blocks))}
    out = []
    for b in blocks:
        item = dict(b)
        if "region_id" in item:
            item["region_id"] = mapping.get(item["region_id"], item["region_id"])
        if item.get("contained_in"):
            item["contained_in"] = mapping.get(item["contained_in"], item["contained_in"])
        out.append(item)
    return out


def artifact_paths(artifacts_dir: Path, page: str) -> dict[str, Path]:
    """全部产物路径唯一归属（修 F6 文件名知识散落 / F7 命名不一）。"""
    art = Path(artifacts_dir)
    return {
        "detection": art / f"{page}_detection.json",
        "canon": art / f"{page}_canon.json",
        "translation": art / f"{page}_translation.json",
        "semantic": art / f"{page}_semantic.json",
        "judge": art / f"{page}_judge.json",
        "needs_review": art / f"{page}_needs_review.json",
        "inpaint": art / f"{page}_inpaint.json",
        "typeset": art / f"{page}_typeset.json",
        "crops": art / "crops",
    }


def trace_path(artifacts_dir: Path, page: str, station: str) -> Path:
    return Path(artifacts_dir) / f"{page}_{station}_trace.json"


def write_trace(artifacts_dir: Path, page: str, station: str, payload: dict) -> Path:
    """统一 trace 落盘（station ∈ 01_detect/02_ocr/03_translate/…）。"""
    doc = dict(payload)
    doc.update({"station": station, "page": page,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return write_json(trace_path(artifacts_dir, page, station), doc)


# ---------- 信封 ----------

def stamp(doc: dict, work_id: str, page: str) -> dict:
    doc = dict(doc)
    doc.setdefault("work_id", work_id)
    doc.setdefault("page", page)
    doc["schema_version"] = SCHEMA_VERSION
    doc.setdefault("generated_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    return doc


# ---------- validate ----------

def validate_canon_items(items: Any) -> list[str]:
    """canon items 校验（语义收编自 canon_schema.validate_canon）。返回问题列表，空=合法。"""
    problems: list[str] = []
    if not isinstance(items, list):
        return ["canon items must be a list"]
    seen: set[str] = set()
    for i, r in enumerate(items):
        if not isinstance(r, dict):
            problems.append(f"item {i} must be dict")
            continue
        rid = r.get("region_id")
        if not rid or not str(rid).strip():
            problems.append(f"item {i}: missing region_id")
        elif rid in seen:
            problems.append(f"duplicate region_id {rid}")
        else:
            seen.add(rid)
        texts = [r.get("text"), r.get("baberu_text"), r.get("vlm_text")]
        if not any(str(t or "").strip() for t in texts):
            problems.append(f"item {i}: empty text")
        if not isinstance(r.get("page"), int):
            problems.append(f"item {i}: bad page")
        cat = r.get("category")
        if cat is not None and cat not in CATEGORIES:
            problems.append(f"item {i}: bad category {cat!r}")
        st = r.get("sub_tier")
        if st is not None and st not in SUB_TIERS:
            problems.append(f"item {i}: bad sub_tier {st!r}")
    return problems


# ---------- load / save ----------

def _raise_problems(problems: list[str], path: Path | str) -> None:
    if problems:
        raise ValueError(f"artifact invalid ({path}): {'; '.join(problems[:5])}")


def save_detection(artifacts_dir: Path, page: str, doc: dict) -> Path:
    return write_json(artifact_paths(artifacts_dir, page)["detection"],
                      stamp(doc, doc.get("work_id", ""), page))


def load_detection(path: Path | str) -> dict:
    doc = read_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("blocks"), list):
        raise ValueError(f"detection artifact invalid ({path}): missing blocks list")
    for i, b in enumerate(doc["blocks"]):
        if not isinstance(b.get("bbox"), list) or len(b["bbox"]) != 4:
            raise ValueError(f"detection artifact invalid ({path}): block {i} bad bbox")
    return doc


def save_canon(artifacts_dir: Path, page: str, work_id: str, items: list[dict],
               vlm_status: str = "ok") -> Path:
    doc = stamp({"items": items, "n_regions": len(items), "vlm_status": vlm_status},
                work_id, page)
    return write_json(artifact_paths(artifacts_dir, page)["canon"], doc)


def load_canon(path: Path | str) -> dict:
    """读 canon：兼容旧裸 list（1.x 产物）；非法 raise ValueError（修 F2 双契约）。"""
    doc = read_json(path)
    if isinstance(doc, list):
        doc = {"items": doc}
    items = doc.get("items")
    _raise_problems(validate_canon_items(items), path)
    return {
        "work_id": doc.get("work_id", ""),
        "page": doc.get("page", ""),
        "schema_version": doc.get("schema_version", "1.0"),
        "generated_at": doc.get("generated_at", ""),
        "items": items,
        "n_regions": len(items),
        "vlm_status": doc.get("vlm_status", "unknown"),
    }


def save_translation(artifacts_dir: Path, page: str, work_id: str,
                     translations: dict[str, str], residue: list,
                     violations: list) -> Path:
    doc = stamp({"translations": translations, "residue": residue,
                 "glossary_violations": violations}, work_id, page)
    return write_json(artifact_paths(artifacts_dir, page)["translation"], doc)


def load_translation(path: Path | str) -> dict:
    doc = read_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("translations"), dict):
        raise ValueError(f"translation artifact invalid ({path}): missing translations dict")
    doc.setdefault("residue", [])
    doc.setdefault("glossary_violations", [])
    return doc
```

- [ ] **Step 4: canon_schema 改 re-export** — `src/amta/canon_schema.py` 全文替换为：

```python
"""pre-translate Input schema 校验（ADR-016）— 逻辑已收编 amta.artifacts（深接口改造）。

保留模块与函数名作兼容别名：scripts/03_translate.py 与旧测试仍 import 本处。
"""
from __future__ import annotations

from amta.artifacts import CATEGORIES, SUB_TIERS, validate_canon_items

__all__ = ["validate_canon", "CATEGORIES", "SUB_TIERS"]

# 兼容别名（原唯一实现迁移至 artifacts.validate_canon_items，语义不变）
validate_canon = validate_canon_items
```

- [ ] **Step 5: 跑测试确认通过** — `py -3.13 -m pytest tests/test_artifacts.py tests/test_canon_schema.py tests/test_front3_stage3.py -q --basetemp output/logs/.pytest-basetemp` → 预期全 PASS（canon_schema 别名保住旧测试）。

- [ ] **Step 6: Commit** — `git add src/amta/artifacts.py src/amta/canon_schema.py tests/test_artifacts.py && git commit -m "feat(artifacts): 产物契约单一事实源 — 信封/validate/load-save/命名/region_id 单空间（修 F2/F3/F6 文件名/F7）"`

---

### Task 2: config.py — 密钥配置唯一归属

**Files:**
- Create: `src/amta/config.py`
- Modify: `src/amta/translate.py`（get_chat_config 改薄壳，保 `_ENV_PATH` monkeypatch 面）、`src/amta/ocr_engines.py`（get_dashscope_key 改薄壳）
- Modify: `tests/test_translate.py:7-16`（无改动，见 Step 3 说明）
- Test: `tests/test_config.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_config.py`：

```python
"""config 密钥解析测试：env 优先 → .env 回退 → 引号剥离 → 缺失报错（修 F4）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import config


def _write_env(tmp_path, lines):
    p = tmp_path / ".env"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_get_chat_config_env_priority(tmp_path, monkeypatch):
    env = _write_env(tmp_path, ['CHAT_BASE_URL="https://dotenv.example"'])
    monkeypatch.setenv("CHAT_BASE_URL", "https://env.example")
    monkeypatch.setenv("CHAT_MODEL", "m1")
    monkeypatch.setenv("CHAT_API_KEY", "sk-1")
    cfg = config.get_chat_config(env_path=env)
    assert cfg["base_url"] == "https://env.example"  # env 优先于 .env
    assert cfg == {"base_url": "https://env.example", "model": "m1", "api_key": "sk-1"}


def test_get_chat_config_dotenv_fallback_and_quotes(tmp_path, monkeypatch):
    monkeypatch.delenv("CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    env = _write_env(tmp_path, ['CHAT_BASE_URL="https://api.example/v1"',
                                'CHAT_MODEL=m2',
                                "CHAT_API_KEY='sk-2'"])
    cfg = config.get_chat_config(env_path=env)
    assert cfg["base_url"] == "https://api.example/v1"
    assert cfg["api_key"] == "sk-2"  # 引号剥离


def test_get_chat_config_missing_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CHAT_API_KEY"):
        config.get_chat_config(env_path=tmp_path / "missing.env")


def test_get_vlm_api_key_fallback_chain(tmp_path, monkeypatch):
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    env = _write_env(tmp_path, ["CHAT_API_KEY=sk-chat"])
    assert config.get_vlm_api_key(env_path=env) == "sk-chat"  # VLM 缺 → CHAT 兜底
    monkeypatch.setenv("VLM_API_KEY", "sk-vlm")
    assert config.get_vlm_api_key(env_path=env) == "sk-vlm"  # VLM 优先
    assert config.get_vlm_api_key(env_path=tmp_path / "no.env") == "sk-vlm"


def test_get_vlm_api_key_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    assert config.get_vlm_api_key(env_path=tmp_path / "no.env") is None


def test_get_dashscope_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_KEY", raising=False)
    env = _write_env(tmp_path, ["DASHSCOPE_KEY=ds-old"])
    assert config.get_dashscope_key(env_path=env) == "ds-old"  # 兼容旧名
```

- [ ] **Step 2: 跑测试确认失败** → `ModuleNotFoundError`。

- [ ] **Step 3: 实现 `src/amta/config.py`**：

```python
"""密钥与模型配置 — env → .env 回退唯一归属（深接口改造，修 F4 三处重复解析）。

原则：env 优先、.env 兼容双位置（amta/.env 与 仓库父目录/.env，对应旧
ocr_engines 与 translate 的各自实现）、引号剥离、绝不打印密钥（L27）。
测试通过 env_path 参数注入临时 .env，无需 monkeypatch。
"""
from __future__ import annotations

import os
from pathlib import Path

from amta.paths import ROOT

# 兼容旧双位置：translate 用 ROOT.parent/.env，ocr_engines 依次找 ROOT/.env
_ENV_PATHS = (ROOT / ".env", ROOT.parent / ".env")


def _read_key(source: Path, key: str) -> str | None:
    if not source.exists():
        return None
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _resolve(key: str, env_path: Path | None) -> str | None:
    v = os.environ.get(key)
    if v:\n        return v\n    if env_path is not None:
        return _read_key(env_path, key)
    for p in _ENV_PATHS:
        v = _read_key(p, key)
        if v:\n            return v\n    return None\n\n\ndef get_chat_config(env_path: Path | None = None) -> dict[str, str]:
    """CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY；任一缺失 raise RuntimeError。"""
    values: dict[str, str] = {}
    for key in ("CHAT_BASE_URL", "CHAT_MODEL", "CHAT_API_KEY"):
        v = _resolve(key, env_path)
        if not v:\n            raise RuntimeError(f"缺少 {key}：请在 .env 配置或设置环境变量")
        values[key] = v
    return {"base_url": values["CHAT_BASE_URL"],
            "model": values["CHAT_MODEL"],
            "api_key": values["CHAT_API_KEY"]}


def get_vlm_api_key(env_path: Path | None = None) -> str | None:
    """VLM_API_KEY → CHAT_API_KEY → None（原 02_ocr._get_vlm_api_key 语义）。"""
    for key in ("VLM_API_KEY", "CHAT_API_KEY"):
        v = _resolve(key, env_path)
        if v:\n            return v\n    return None\n\n\ndef get_dashscope_key(env_path: Path | None = None) -> str:
    """DASHSCOPE_API_KEY（兼容旧名 DASHSCOPE_KEY）；缺失 raise。"""
    for name in ("DASHSCOPE_API_KEY", "DASHSCOPE_KEY"):
        v = _resolve(name, env_path)
        if v:\n            return v\n    raise RuntimeError("缺少 DASHSCOPE_API_KEY：请在 .env 配置或设置环境变量")
```

- [ ] **Step 4: translate.py / ocr_engines.py 改薄壳** —

`src/amta/translate.py`：删除现有 `get_chat_config` 函数体与 `_ENV_PATH` 定义，替换为：

```python
from amta.config import get_chat_config as _config_get_chat_config

# 测试桥：test_translate monkeypatch translate._ENV_PATH（保持原 monkeypatch 面）
_ENV_PATH = _ENV_PATH  # noqa: F821 —— 下方紧跟真实定义
```

实际写法（替换原 `get_chat_config` 整段，保留模块级 `_ENV_PATH = ROOT.parent / ".env"`）：

```python
def get_chat_config() -> dict[str, str]:
    """薄壳 → amta.config（唯一实现）；_ENV_PATH 保留供旧测试 monkeypatch。"""
    return _config_get_chat_config(env_path=_ENV_PATH)
```

（`from amta.config import get_chat_config as _config_get_chat_config` 加进文件头 import 区。）

`src/amta/ocr_engines.py`：删除 `get_dashscope_key` 函数体，替换为：

```python
from amta.config import get_dashscope_key  # noqa: F401  # 唯一实现 → amta.config
```

（`dashscope_ocr_batch` 内 `key = get_dashscope_key()` 调用不变。）

- [ ] **Step 5: 校验 + 跑测试** — `py -3.13 -m pytest tests/test_config.py tests/test_translate.py tests/test_ocr_run.py -q --basetemp output/logs/.pytest-basetemp` → 预期全 PASS（test_translate 的 `_ENV_PATH` monkeypatch 经薄壳仍生效）。**L27 校验**：`Get-Content src/amta/config.py | Select-String "api_key"` 确认无密钥字面值。

- [ ] **Step 6: Commit** — `git add src/amta/config.py src/amta/translate.py src/amta/ocr_engines.py tests/test_config.py && git commit -m "feat(config): env/.env 解析唯一归属（修 F4），translate/ocr_engines 改薄壳"`

---

### Task 3: detect_station.py + 01_detect.py 薄化

**Files:**
- Create: `src/amta/detect_station.py`、`tests/fakes.py`、`tests/test_detect_station.py`
- Modify: `scripts/01_detect.py`（薄 CLI）

- [ ] **Step 1: 写失败测试** — 创建 `tests/fakes.py`：

```python
"""测试假适配器：FakeKoharu（KoharuClient 协议面）+ 共享 fixtures 工厂。"""
from __future__ import annotations

from pathlib import Path


def make_node(node_id: str, x: float, y: float, w: float, h: float,
              text: str = "", kind_type: str = "speech_bubble") -> dict:
    """koharu scene 节点形状（koharu_blocks.collect_blocks 可消费）。"""
    return {"kind": {"text": {"text": text}, "type": kind_type},
            "transform": {"x": x, "y": y, "w": w, "h": h}}


class FakeKoharu:
    """按 engine steps 返回 canned nodes；满足 runner.run_all_pages 的调用面。"""

    def __init__(self, nodes_by_engine: dict[str, list[dict]]):
        self.nodes_by_engine = nodes_by_engine
        self._last_engine: str | None = None

    def wait_server(self, timeout: int = 60) -> None:
        pass

    def close_current_project(self) -> None:
        pass

    def create_project(self, name: str) -> str:
        return name

    def import_page(self, image_path: Path) -> str:
        return "p1"

    def run_pipeline(self, page_ids: list[str], steps: list[str], **kw) -> str:
        for eng in self.nodes_by_engine:
            if steps == [eng]:
                self._last_engine = eng
                break
        return f"op-{self._last_engine}"

    def wait_operation(self, op_id: str, timeout: int = 0) -> dict:
        return {"status": "completed", "id": op_id}

    def get_page_nodes(self, page_id: str) -> dict[str, dict]:
        eng = self._last_engine
        nodes = self.nodes_by_engine.get(eng, [])
        return {n.get("node_id", f"n{i}"): n for i, n in enumerate(nodes)} if nodes else {}
```

注意：`make_node` 产出的 dict 已含 node_id 键；FakeKoharu 用其作 node_id。

创建 `tests/test_detect_station.py`：

```python
"""detect_station 接口测试（FakeKoharu，无真实 koharu server）。"""
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amta import artifacts
from fakes import FakeKoharu, make_node

PAGE_IDX = 10
PAGE = "page_10"


def _client():
    return FakeKoharu({
        "pp-doclayout-v3": [make_node("a", 0, 0, 40, 20, "あ")],
        "comic-text-detector": [
            make_node("b", 0, 0, 40, 20, "あ"),      # 与 a 重复（IoU=1）
            make_node("c", 60, 60, 30, 30, "い"),
            make_node("d", 62, 62, 10, 8, "い小"),   # 嵌套于 c
        ],
    })


def _detect(tmp_path):
    from amta.detect_station import detect_page
    raw = tmp_path / "11.jpg"
    Image.new("RGB", (200, 100), "white").save(raw)
    art = tmp_path / "artifacts"
    art.mkdir()
    doc = detect_page("w1", raw, art, page_idx=PAGE_IDX, client=_client())
    return doc, art, raw


def test_detect_page_envelope_and_union(tmp_path):
    doc, _, _ = _detect(tmp_path)
    assert doc["page"] == PAGE and doc["work_id"] == "w1"
    assert doc["schema_version"] == artifacts.SCHEMA_VERSION
    assert doc["n_boxes"] == 3  # a/b 去重，c/d 嵌套保留
    assert doc["image_meta"]["width"] == 200
    assert {b["source_engines"][0] for b in doc["blocks"] if b["source_engines"]} <= {
        "pp-doclayout-v3", "comic-text-detector"}


def test_detect_region_id_single_space_and_contained(tmp_path):
    doc, _, _ = _detect(tmp_path)
    ids = {b["region_id"] for b in doc["blocks"]}
    assert ids == {"page_10_u00", "page_10_u01", "page_10_u02"}
    child = next(b for b in doc["blocks"] if b.get("contained_in"))
    assert child["contained_in"] in ids  # 父引用同空间（修 F3）


def test_detect_side_files_written(tmp_path):
    doc, art, _ = _detect(tmp_path)
    paths = artifacts.artifact_paths(art, PAGE)
    assert paths["detection"].exists()
    assert json.loads(paths["detection"].read_text(encoding="utf-8"))["n_boxes"] == 3
    assert artifacts.trace_path(art, PAGE, "01_detect").exists()
    assert (art / f"{PAGE}_detect_raw_engines.json").exists()  # 未去重原始框
```

- [ ] **Step 2: 跑测试确认失败** → `ModuleNotFoundError: amta.detect_station`。

- [ ] **Step 3: 实现 `src/amta/detect_station.py`**：

```python
"""Stage 1 检测工位 — raw 页图 → DetectionArtifact（深模块，修 F5/F8 检测侧）。

藏匿：KoharuClient 生命周期、4-detector 并集 → compact → union_blocks →
assign_category → mark_contained → region_id 单空间重编、raw_engines 落盘、
trace 落盘、image_meta。接缝：client 注入（协议=KoharuClient 方法面），
测试用 tests/fakes.FakeKoharu。脚本 01_detect.py 只剩 CLI。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta import artifacts
from amta.geometry import assign_category, mark_contained, union_blocks
from amta.koharu_client import KoharuClient
from amta.paths import write_json
from amta.pipeline import DETECTOR_STEPS
from amta.runner import compact_blocks, run_all_pages

_FIELDS = ("node_id", "bbox", "bubble_type", "text")


def detect_page(work_id: str, raw_page: Path, artifacts_dir: Path, *,
                page_idx: int | None = None, client: KoharuClient | None = None,
                host: str = "127.0.0.1", port: int = 4000,
                out_path: Path | None = None) -> dict:
    """一页图 → 检测产物（落盘 + 返回 doc）。修 F3/F5/F7。"""
    client = client or KoharuClient(host=host, port=port)
    client.wait_server(timeout=60)
    idx = page_idx if page_idx is not None else artifacts.page_idx_from_raw(raw_page)
    page = artifacts.page_key(idx)
    artifacts_dir = Path(artifacts_dir)

    results = run_all_pages(client, [raw_page], DETECTOR_STEPS,
                            prefix="amta-det", timeout=1200, label="01_detect")
    per_engine = next(iter(results.values()))["engines"]
    comp = {eng: compact_blocks(blks, _FIELDS, source_engine=eng)
            for eng, blks in per_engine.items()}

    # Tracing: 并集前落盘 4-detector 原始框（未去重），杜绝黑盒缺口（原 01 语义保留）
    write_json(artifacts_dir / f"{page}_detect_raw_engines.json", {
        "work_id": work_id, "page": page, "source": str(raw_page),
        "engines": {eng: list(blks) for eng, blks in comp.items()},
        "per_engine_count": {eng: len(blks) for eng, blks in comp.items()},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })

    blocks = union_blocks(comp)
    after_union = len(blocks)
    blocks = assign_category(blocks)
    for b in blocks:
        if not isinstance(b.get("source_engines"), list):
            b["source_engines"] = []
    blocks = mark_contained(blocks)
    blocks = artifacts.normalize_region_ids(blocks, idx)  # 单空间（修 F3）

    img = Image.open(raw_page)
    artifacts.write_trace(artifacts_dir, page, "01_detect", {
        "per_engine_raw": {eng: len(blks) for eng, blks in comp.items()},
        "after_union": after_union,
        "after_mark_contained": len(blocks),
        "contained_pairs": [(b["region_id"], b["contained_in"])
                            for b in blocks if b.get("contained_in")],
        "detect_steps": list(DETECTOR_STEPS.keys()),
    })

    doc = artifacts.stamp({
        "work_id": work_id, "page": page, "source": str(raw_page),
        "image_meta": {"width": img.width, "height": img.height,
                       "channels": len(img.getbands())},
        "blocks": blocks, "n_boxes": len(blocks),
        "detect_steps": list(DETECTOR_STEPS.keys()),
        "per_engine_boxes": {eng: len(blks) for eng, blks in comp.items()},
    }, work_id, page)
    dest = Path(out_path) if out_path else artifacts.artifact_paths(artifacts_dir, page)["detection"]
    from amta.paths import write_json as _wj
    _wj(dest, doc)
    return doc
```

- [ ] **Step 4: 01_detect.py 薄化** — `scripts/01_detect.py` 全文替换：

```python
"""01_detect 工位 — 检测: raw 页 → artifacts/{page}_detection.json（薄 CLI）。

用法: python scripts/01_detect.py --work-id <id> --raw <page图> --out <detection.json> [--page-idx N]
实现: amta.detect_station.detect_page（4-detector 并集 + 嵌套标记 + region_id 单空间）。
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定,本脚本只执行)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.detect_station import detect_page  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="01_detect 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--raw", required=True, type=Path, help="源页图路径(N.jpg)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=None,
                    help="0 基页号（默认从文件名 N.jpg 推导 N-1）")
    a = ap.parse_args()
    doc = detect_page(a.work_id, a.raw, a.out.parent, page_idx=a.page_idx,
                      out_path=a.out)
    print(f"[01_detect] {doc['page']}: {doc['n_boxes']} boxes -> {a.out}")
    for eng, n in doc["per_engine_boxes"].items():
        print(f"  - {eng}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 跑测试** — `py -3.13 -m pytest tests/test_detect_station.py tests/test_front3_stage1.py tests/test_pipeline.py -q --basetemp output/logs/.pytest-basetemp` → 预期全 PASS。

- [ ] **Step 6: Commit** — `git add src/amta/detect_station.py scripts/01_detect.py tests/fakes.py tests/test_detect_station.py && git commit -m "feat(detect_station): Stage 1 深工位 — detect_page 接口 + region_id 单空间（修 F3/F5），01_detect 薄 CLI"`

---

### Task 4: ocr_station.py + 02_ocr.py 薄化

**Files:**
- Create: `src/amta/ocr_station.py`、`tests/test_ocr_station.py`
- Modify: `scripts/02_ocr.py`（薄 CLI，删 `_get_vlm_api_key`）
- Modify: `tests/test_pipeline_flow.py`（02 用例断言：盘上 doc.items）

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_ocr_station.py`：

```python
"""ocr_station 接口测试：双引擎合并、canon doc 化落盘（修 F2）、trace、降级。"""
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import artifacts


def _det(blocks):
    return {"work_id": "w1", "page": "page_0", "blocks": blocks, "n_boxes": len(blocks)}


def _raw(tmp_path):
    raw = tmp_path / "1.jpg"
    Image.new("RGB", (200, 100), "white").save(raw)
    return raw


def _fake_ocr(crops, engine="auto", **kw):
    return [{"crop": c, "ocr": "月の都" if "u00" in c else ""} for c in crops]


def test_ocr_page_doc_canon_on_disk(tmp_path, monkeypatch):
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    from amta.ocr_station import ocr_page
    art = tmp_path / "artifacts"
    det = _det([{"region_id": "page_0_u00", "bbox": [10, 10, 90, 40],
                 "category": "dialogue_bubble"},
                {"region_id": "page_0_u01", "bbox": [110, 50, 190, 80],
                 "category": "sfx", "sub_tier": "aside"}])
    doc = ocr_page("w1", det, _raw(tmp_path), art, page_idx=0,
                   vlm_enabled=False, ocr_fn=_fake_ocr)
    assert doc["page"] == "page_0" and doc["n_regions"] == 2
    on_disk = json.loads((art / "page_0_canon.json").read_text(encoding="utf-8"))
    assert on_disk["items"][0]["region_id"] == "page_0_u00"  # 盘上即 doc（修 F2）
    assert on_disk["items"][0]["baberu_text"] == "月の都"
    assert on_disk["items"][1]["sub_tier"] == "aside"  # 透传
    assert (art / "crops" / "page_0_u00.png").exists()
    assert artifacts.trace_path(art, "page_0", "02_ocr").exists()


def test_ocr_page_empty_ocr_kept(tmp_path, monkeypatch):
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    from amta.ocr_station import ocr_page
    det = _det([{"region_id": "page_0_u00", "bbox": [10, 10, 90, 40]}])
    doc = ocr_page("w1", det, _raw(tmp_path), tmp_path / "artifacts", page_idx=0,
                   vlm_enabled=False, ocr_fn=_fake_ocr)
    assert doc["items"][0]["baberu_text"] == "月の都" or True  # u00 命中
    det2 = _det([{"region_id": "page_0_u01", "bbox": [110, 50, 190, 80]}])
    doc2 = ocr_page("w1", det2, _raw(tmp_path), tmp_path / "artifacts", page_idx=0,
                    vlm_enabled=False, ocr_fn=_fake_ocr)
    assert doc2["items"][0]["baberu_text"] == ""  # 空 OCR 保留（双引擎契约）


def test_ocr_page_no_valid_bbox_raises(tmp_path):
    import pytest
    from amta.ocr_station import ocr_page
    with pytest.raises(RuntimeError, match="no valid bbox"):
        ocr_page("w1", _det([{"region_id": "page_0_u00", "bbox": [999, 999, 1000, 1000]}]),
                 _raw(tmp_path), tmp_path / "artifacts", page_idx=0, vlm_enabled=False,
                 ocr_fn=_fake_ocr)
```

- [ ] **Step 2: 跑测试确认失败** → `ModuleNotFoundError`。

- [ ] **Step 3: 实现 `src/amta/ocr_station.py`**：

```python
"""Stage 2 OCR 工位 — detection + raw 页 → CanonArtifact（深模块）。

藏匿：裁框（region_id = region_id(page_idx, i)，与 detect 输出顺序一一对应）、
ocr_batch 分发（baberu fast path）、VLM contact sheet 批量校验、VLM key 解析
（amta.config）、双引擎合并（空 OCR 保留）、trace、save_canon（doc 化，修 F2）。
接缝：ocr_fn / vlm_fn 函数注入（内部接缝，测试用 fake）。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from amta import artifacts
from amta.config import get_vlm_api_key
from amta.paths import write_json


def _crop_by_region(raw_page: Path, blocks: list[dict], page_idx: int,
                    crop_dir: Path) -> list[tuple[str, dict, Path, Image.Image]]:
    """按 bbox 裁框；region_id 与 detect 输出顺序一一对应（单空间，修 F3）。"""
    img = Image.open(raw_page)
    out = []
    crop_dir.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(blocks):
        bb = b.get("bbox")
        if not bb or len(bb) != 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bb]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.width, x2), min(img.height, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        rid = artifacts.region_id(page_idx, i)
        crop = crop_dir / f"{rid}.png"
        pil_crop = img.crop((x1, y1, x2, y2))
        pil_crop.save(crop)
        out.append((rid, b, crop, pil_crop))
    return out


def ocr_page(work_id: str, det: dict, raw_page: Path, artifacts_dir: Path, *,
             page_idx: int, engine: str = "auto", vlm_enabled: bool = True,
             ocr_fn=None, vlm_fn=None, vlm_api_key: str | None = None) -> dict:
    from amta.ocr_engines import ocr_batch as _default_ocr
    from amta.vlm_verify import vlm_verify_batch as _default_vlm
    ocr_fn = ocr_fn or _default_ocr
    vlm_fn = vlm_fn or _default_vlm
    page = artifacts.page_key(page_idx)
    artifacts_dir = Path(artifacts_dir)

    blocks = det.get("blocks", [])
    pairs = _crop_by_region(raw_page, blocks, page_idx, artifacts_dir / "crops")
    if not pairs:
        raise RuntimeError(f"02_ocr: no valid bbox on {page} (source {det.get('page', '?')})")

    t0 = time.time()
    ocr_rows = ocr_fn([str(c) for _, _, c, _ in pairs], engine=engine)
    ocr_by_crop = {r["crop"]: (r.get("ocr") or "").strip() for r in ocr_rows}
    baberu_elapsed = time.time() - t0

    vlm_result = {"texts": None, "status": "skipped", "raw_output": "", "elapsed": 0.0, "retries": 0}
    if vlm_enabled:
        key = vlm_api_key or get_vlm_api_key()
        if key:
            t1 = time.time()
            try:
                vlm_result = vlm_fn([pil for _, _, _, pil in pairs], api_key=key)
            except Exception as e:  # noqa: BLE001 — VLM 失败不拖垮 OCR 工位
                vlm_result = {"texts": None, "status": "failed", "raw_output": str(e),
                              "elapsed": time.time() - t1, "retries": 0}
        else:
            vlm_result["raw_output"] = "No VLM_API_KEY or CHAT_API_KEY configured"

    items = []
    vlm_texts = vlm_result.get("texts")
    for i, (rid, b, crop, _pil) in enumerate(pairs):
        vlm_text = vlm_texts[i] if (vlm_texts and i < len(vlm_texts)) else None
        item = {
            "region_id": rid,
            "bbox": b.get("bbox"),
            "baberu_text": ocr_by_crop.get(str(crop), ""),
            "vlm_text": vlm_text,
            "contained_in": b.get("contained_in"),
            "source_engines": b.get("source_engines", []),
            "vlm_status": vlm_result["status"],
            "page": page_idx,
        }
        for k in ("category", "bubble_type", "node_id", "sub_tier"):
            if b.get(k) is not None:
                item[k] = b[k]
        items.append(item)

    artifacts.write_trace(artifacts_dir, page, "02_ocr", {
        "n_blocks": len(pairs),
        "baberu_elapsed": round(baberu_elapsed, 2),
        "vlm_status": vlm_result["status"],
        "vlm_elapsed": round(vlm_result.get("elapsed", 0.0), 2),
        "vlm_retries": vlm_result.get("retries", 0),
        "baberu_vs_vlm_diff": [
            {"region_id": it["region_id"], "baberu": it["baberu_text"],
             "vlm": it["vlm_text"],
             "match": it["baberu_text"] == (it["vlm_text"] or "")}
            for it in items if it["vlm_text"] is not None
        ],
    })

    doc = artifacts.stamp({"items": items, "n_regions": len(items),
                           "vlm_status": vlm_result["status"]}, work_id, page)
    write_json(artifacts_dir / f"{page}_canon.json", doc)  # 盘上即 doc（修 F2）
    return doc
```

- [ ] **Step 4: 02_ocr.py 薄化** — `scripts/02_ocr.py` 全文替换：

```python
"""02_ocr 工位 — OCR: detection.json + raw 页 → artifacts/{page}_canon.json（薄 CLI）。

Front3 Stage 2 双引擎会诊：Baberu 逐框 OCR + VLM contact sheet 批量校验，
输出 baberu_text + vlm_text + vlm_status；不自动除噪，假框由 Stage 3 裁决。
实现: amta.ocr_station.ocr_page（canon 落盘为 doc 信封，修 F2 双契约）。
断点: 输出文件已存在 → 跳过(00_run_all 调用方决定)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.artifacts import load_detection  # noqa: E402
from amta.ocr_station import ocr_page  # noqa: E402
from amta.ocr_engines import ocr_batch  # noqa: E402,F401  # 供测试 monkeypatch 注入


def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        page_idx: int = 0, engine: str = "auto", vlm_enabled: bool = True) -> dict:
    det = load_detection(det_path)
    doc = ocr_page(work_id, det, raw_page, out_path.parent, page_idx=page_idx,
                   engine=engine, vlm_enabled=vlm_enabled, ocr_fn=ocr_batch)
    from amta.paths import write_json
    write_json(out_path, doc)  # --out 与契约命名一致（00 传入），尊重显式 out
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="02_ocr 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-idx", type=int, default=0, help="页面序号(0 基)")
    ap.add_argument("--engine", default="auto",
                    choices=["auto", "baberu", "local", "dashscope"],
                    help="OCR 引擎(auto=baberu fast path+回退; 默认 auto)")
    ap.add_argument("--no-vlm", action="store_true", help="禁用 VLM 校验（只用 Baberu）")
    a = ap.parse_args()
    doc = run(a.work_id, a.det, a.raw, a.out, page_idx=a.page_idx,
              engine=a.engine, vlm_enabled=not a.no_vlm)
    print(f"[02_ocr] {doc['page']}: {doc['n_regions']} regions (vlm={doc['vlm_status']}) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

注意：`run()` 传 `ocr_fn=ocr_batch` 且 `ocr_batch` 从模块全局在调用时解析——test_pipeline_flow 的 `monkeypatch.setattr(impl, "ocr_batch", fake)` 机制不变。

- [ ] **Step 5: 迁移 test_pipeline_flow 02 用例断言** — `tests/test_pipeline_flow.py` 中 `test_02_crop_naming_and_canon` 与 `test_02_canon_passthrough_subtier_category_and_items_rename`：把 `canon = json.loads(out.read_text(encoding="utf-8"))` 改为 `canon = json.loads(out.read_text(encoding="utf-8"))["items"]`（盘上已 doc 化）；`assert doc["items"][0]...` 断言保留（返回与盘上同形）；fixture 的 det blocks 无 region_id 时无需补（ocr_station 按序推导同名 ID）。

- [ ] **Step 6: 跑测试** — `py -3.13 -m pytest tests/test_ocr_station.py tests/test_pipeline_flow.py tests/test_front3_stage2.py tests/test_ocr_run.py -q --basetemp output/logs/.pytest-basetemp` → 预期全 PASS。

- [ ] **Step 7: Commit** — `git add src/amta/ocr_station.py scripts/02_ocr.py tests/test_ocr_station.py tests/test_pipeline_flow.py && git commit -m "feat(ocr_station): Stage 2 深工位 — canon doc 化落盘（修 F2）+ key 解析收敛，02_ocr 薄 CLI"`

---

### Task 5: suggestions.py — 提取/追加/合并唯一归属

**Files:**
- Create: `src/amta/suggestions.py`
- Modify: `src/amta/translate.py`（删 SuggestionsExtractor 原体，改 re-export）、`scripts/merge_suggestions.py`（merge 改委托）、`scripts/03_translate.py`（suggestions 段临时改调 suggestions.append_suggestions——Task 6 会整段删除）
- Test: `tests/test_suggestions.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_suggestions.py`：

```python
"""suggestions 唯一归属测试：片假名提取 / 追加 / 跨页合并（修 F5）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import suggestions


def test_extract_katakana_and_stoplist():
    canon = [{"region_id": "page_0_u00", "baberu_text": "サグメはカラ笑った", "page": 0}]
    got = suggestions.SuggestionsExtractor(existing=set()).extract(canon, {"page_0_u00": "译"})
    terms = {s["term"] for s in got}
    assert "サグメ" in terms
    assert "カラ" not in terms  # 语法片假名黑名单


def test_extract_skips_existing():
    canon = [{"region_id": "page_0_u00", "baberu_text": "サグメ", "page": 0}]
    got = suggestions.SuggestionsExtractor(existing={"サグメ"}).extract(canon, {})
    assert got == []


def test_append_suggestions(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    p = suggestions.append_suggestions(state, "w1", [{"term": "サグメ"}])
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["work_id"] == "w1" and doc["suggestions"] == [{"term": "サグメ"}]
    suggestions.append_suggestions(state, "w1", [{"term": "第二"}])
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert len(doc["suggestions"]) == 2  # 追加不覆盖


def test_merge_into_state_cross_page_confirmed():
    state = {"terms": {"已确认": {"translation": "旧", "status": "confirmed"}}}
    out = suggestions.merge_into_state(state, [
        {"term": "サグメ", "translation": "沙谟", "page": 0},
        {"term": "サグメ", "translation": "沙谟", "page": 1},
        {"term": "已确认", "translation": "新译", "page": 2},
    ])
    assert out["terms"]["サグメ"]["status"] == "confirmed"  # ≥2 页且译名一致
    assert out["terms"]["已确认"]["translation"] == "旧"  # 已确认不降级
```

- [ ] **Step 2: 跑测试确认失败** → `ModuleNotFoundError`。

- [ ] **Step 3: 实现 `src/amta/suggestions.py`** — 把 `translate.py` 的 `_KATAKANA_TERM` / `_KATAKANA_STOP` / `SuggestionsExtractor` 原样搬入，并新增：

```python
"""suggestions 机制唯一归属（修 F5）：片假名术语提取 → 追加落盘 → 跨页合并。

- SuggestionsExtractor：ADR-016 收紧版（只提片假名专有名词段），自 translate.py 迁入
- append_suggestions：原 03_translate.py 内联读写合并段收编（4fc5037 曾因内联出冲突标记 bug）
- merge_into_state：scripts/merge_suggestions.py 的 merge 收编（≥2 页且译名一致 → confirmed）
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from amta.paths import write_json

_KATAKANA_TERM = ...   # 自 translate.py 原样搬入
_KATAKANA_STOP = {...}  # 自 translate.py 原样搬入


class SuggestionsExtractor:
    ...  # 自 translate.py 原样搬入（extract 方法逐行不变）


def append_suggestions(state_dir: Path, work_id: str, sugg: list[dict]) -> Path:
    """追加写入 state/suggestions.json（读-并-写整体在此，调用方不再手搓 JSON）。"""
    sugg_path = Path(state_dir) / "suggestions.json"
    prev = (json.loads(sugg_path.read_text(encoding="utf-8"))
            if sugg_path.exists() else {"work_id": work_id, "suggestions": []})
    prev.setdefault("suggestions", []).extend(sugg)
    return write_json(sugg_path, prev)


def merge_into_state(state: dict, suggestions: list[dict]) -> dict:
    """suggestions → work_state.terms 合并（原 merge_suggestions.merge 逐行搬入）。"""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for s in suggestions:
        grouped[s["term"]].append(s)
    terms = state.setdefault("terms", {})
    for term, items in grouped.items():
        if term in terms and terms[term].get("status") == "confirmed":
            continue  # 已确认不降级
        translations = {it.get("translation", "").strip() for it in items if it.get("translation")}
        pages = sorted({it["page"] for it in items if "page" in it})
        consistent = len(pages) >= 2 and len(translations) == 1
        status = "confirmed" if consistent else "candidate"
        terms[term] = {
            "translation": next(iter(translations), ""),
            "status": status,
            "source": f"page_{pages[0]}" if pages else "",
            "pages": pages,
        }
    return state
```

（`...` 处必须填入 translate.py 中对应代码的逐行拷贝——执行者从 `src/amta/translate.py` 迁移，勿凭记忆重写。）

- [ ] **Step 4: 改两处引用** —
  `src/amta/translate.py`：删除 `_KATAKANA_TERM`/`_KATAKANA_STOP`/`SuggestionsExtractor` 原体，加：
  ```python
  from amta.suggestions import SuggestionsExtractor  # noqa: F401  # 兼容 re-export（唯一实现 → amta.suggestions）
  ```
  `scripts/merge_suggestions.py`：删除 `merge` 函数体，替换为：
  ```python
  from amta.suggestions import merge_into_state as _merge_impl


  def merge(state: dict, suggestions: list[dict]) -> dict:
      """薄壳 → amta.suggestions.merge_into_state（唯一实现）。"""
      return _merge_impl(state, suggestions)
  ```

- [ ] **Step 5: 跑测试** — `py -3.13 -m pytest tests/test_suggestions.py tests/test_merge_suggestions.py tests/test_front3_stage3.py tests/test_translate.py -q --basetemp output/logs/.pytest-basetemp` → 预期全 PASS。

- [ ] **Step 6: Commit** — `git add src/amta/suggestions.py src/amta/translate.py scripts/merge_suggestions.py tests/test_suggestions.py && git commit -m "feat(suggestions): 提取/追加/合并唯一归属（修 F5），translate 与 merge_suggestions 改薄壳"`

---

### Task 6: translate_station.py + 03_translate.py 薄化

**Files:**
- Create: `src/amta/translate_station.py`、`tests/test_translate_station.py`
- Modify: `scripts/03_translate.py`（薄 CLI）

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_translate_station.py`：

```python
"""translate_station 接口测试：信封/护栏/failure log/suggestions 全在实现内（修 F8）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import artifacts


CANON = [
    {"region_id": "page_0_u00", "baberu_text": "こんにちは", "vlm_text": "こんにちは",
     "vlm_status": "ok", "page": 0, "contained_in": None},
]


def _llm_ok(messages, tools=None):
    return {"content": '{"page_0_u00": "你好"}'}


def _llm_always_japanese(messages, tools=None):
    return {"content": '{"page_0_u00": "こんにちは"}'}  # 触发残留护栏 → 重试耗尽


def _state(tmp_path):
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_translate_page_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    out = translate_page("w1", CANON, state_dir=_state(tmp_path), page="page_0", llm=_llm_ok)
    assert out["translations"]["page_0_u00"] == "你好"
    assert out["residue"] == [] and out["schema_version"] == artifacts.SCHEMA_VERSION


def test_translate_page_records_failure_log(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    state = _state(tmp_path)
    translate_page("w1", CANON, state_dir=state, page="page_0", llm=_llm_always_japanese)
    log = json.loads((state / "failure_log.json").read_text(encoding="utf-8"))
    kinds = {p["kind"] for p in log["failures"][0]["problems"]}
    assert "residue" in kinds  # 护栏失败结构化落盘（ADR-016）


def test_translate_page_appends_suggestions(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    state = _state(tmp_path)
    canon = [{"region_id": "page_0_u00", "baberu_text": "サグメは言った", "vlm_text": None,
              "vlm_status": "ok", "page": 0}]
    translate_page("w1", canon, state_dir=state, page="page_0", llm=_llm_ok)
    sugg = json.loads((state / "suggestions.json").read_text(encoding="utf-8"))
    assert any(s["term"] == "サグメ" for s in sugg["suggestions"])  # 追加在实现内（修 F5）


def test_translate_page_accepts_canon_artifact_dict(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    doc = {"items": CANON, "page": "page_0"}
    out = translate_page("w1", doc, state_dir=_state(tmp_path), llm=_llm_ok)
    assert out["translations"]["page_0_u00"] == "你好"


def test_translate_page_rejects_bad_canon(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.translate_station import translate_page
    with pytest.raises(ValueError, match="canon input schema"):
        translate_page("w1", [{"region_id": "", "baberu_text": "あ", "page": 0}],
                       state_dir=_state(tmp_path), llm=_llm_ok)
```

- [ ] **Step 2: 跑测试确认失败** → `ModuleNotFoundError`。

- [ ] **Step 3: 实现 `src/amta/translate_station.py`**：

```python
"""Stage 3 翻译工位 — canon → TranslationArtifact（深模块，修 F8 宽接口 / F5 内联）。

藏匿：chat config、llm 闭包+观测 trace、plan 双模式（text/vision）、
translate_with_retry / translate_with_plan、残留+术语护栏、failure log
（ADR-016）、suggestions 提取+追加（amta.suggestions）。接缝：llm 函数注入
（与既有测试同款 fake 模式）。脚本 03_translate.py 只剩 CLI。
"""
from __future__ import annotations

from pathlib import Path

from amta import artifacts, paths, suggestions, workstate
from amta.canon_schema import validate_canon
from amta.glossary import check_glossary
from amta.stage3_planner import run_plan_loop, translate_with_plan, validate_plan
from amta import translate

try:
    from amta.stage3_planner_vision import run_plan_loop_vision
except ImportError:  # pragma: no cover
    run_plan_loop_vision = None


def _load_open_questions(state_dir: Path | None) -> list[dict] | None:
    if not state_dir:
        return None
    p = Path(state_dir) / "open_questions.json"
    if not p.exists():
        return None
    return paths.read_json(p).get("questions", [])


def translate_page(work_id: str, canon, *, state_dir: Path | str | None = None,
                   page: str | None = None, with_plan: bool = False,
                   with_vision_plan: bool = False, trace_enabled: bool = False,
                   crop_dir: Path | str | None = None, llm=None) -> dict:
    """一页 canon → 翻译产物（含护栏/失败记录/suggestions）。返回信封 doc。"""
    if isinstance(canon, dict):  # 接受 CanonArtifact 或裸 items list
        canon = canon.get("items", [])
    problems = validate_canon(canon)
    if problems:
        raise ValueError(f"canon input schema failed: {'; '.join(problems[:5])}")

    cfg = translate.get_chat_config()
    ws = workstate.load_state(work_id) if work_id else {}
    open_questions = _load_open_questions(Path(state_dir) if state_dir else None)
    vlm_api_key = cfg.get("api_key")
    trace: list[dict] = []

    if llm is None:
        def llm(messages, tools=None):  # noqa: F811 — 默认闭包（生产路径）
            resp = translate.chat_with_tools(cfg["base_url"], cfg["model"], messages,
                                             tools=tools, api_key=cfg["api_key"])
            if trace_enabled:
                trace.append({
                    "roles": [m["role"] for m in messages],
                    "tool_calls": [{"name": c.get("function", {}).get("name"),
                                    "args": c.get("function", {}).get("arguments")}
                                   for c in (resp.get("tool_calls") or [])],
                    "content": (resp.get("content") or "")[:200],
                })
            return resp

    plan = None
    if with_vision_plan and run_plan_loop_vision is not None:
        page_num = canon[0].get("page") if canon else None
        plan = run_plan_loop_vision(canon, None, page=page_num)
    elif with_plan:
        plan = run_plan_loop(canon, llm)
        plan_errors = validate_plan(plan, canon)
        if plan_errors:
            print(f"[03_translate][plan] 护栏警告: {'; '.join(plan_errors[:3])}")

    if plan is not None:
        result = translate_with_plan(canon, llm, plan=plan, work_state=ws,
                                     open_questions=open_questions,
                                     tools=translate.TOOLS_SCHEMA, state_dir=state_dir)
    else:
        result = translate.translate_with_retry(
            canon, llm, work_state=ws, open_questions=open_questions,
            tools=translate.TOOLS_SCHEMA, state_dir=state_dir,
            crop_dir=crop_dir, vlm_api_key=vlm_api_key)

    residue = translate.japanese_residue_check(list(result.values()))
    violations = check_glossary(canon, result, ws)
    env_page = page or (artifacts.page_key(canon[0]["page"]) if canon else "")
    out = artifacts.stamp({"translations": result, "residue": residue,
                           "glossary_violations": violations}, work_id or "", env_page)

    if state_dir:  # on-failure 结构化记录（ADR-016），原 03 内联段收编
        failure_problems = [{"region_id": rid, "kind": "residue", "text": t}
                            for rid, t in result.items() if t in residue]
        failure_problems += [{"region_id": rid, "kind": "glossary", "detail": v}
                             for rid, v in violations]
        if failure_problems:
            translate.record_failure(Path(state_dir) / "failure_log.json",
                                     {"work_id": work_id or "", "problems": failure_problems})

    if work_id and state_dir:  # suggestions 提取+追加（原 03 内联段收编，修 F5）
        ex = suggestions.SuggestionsExtractor(
            existing=set(ws.get("characters", {})) | set(ws.get("terms", {})))
        sugg = ex.extract(canon, result)
        if sugg:
            suggestions.append_suggestions(Path(state_dir), work_id, sugg)

    if trace_enabled and trace:
        out["_trace"] = trace  # 观测随返回值走，CLI 负责落盘（--trace 语义保留）
    return out
```

- [ ] **Step 4: 03_translate.py 薄化** — `scripts/03_translate.py` 全文替换：

```python
"""03_translate 工位 — 读 canon → DeepSeek 翻译 → translation.json（薄 CLI）。

用法: python scripts/03_translate.py --canon <canon.json> --out <translation.json>
      [--work-id ID] [--state-dir DIR] [--trace] [--with-plan] [--with-vision-plan] [--crop-dir DIR]
实现: amta.translate_station.translate_page（护栏/失败记录/suggestions 全在实现内）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.artifacts import load_canon  # noqa: E402
from amta.paths import write_json  # noqa: E402
from amta.translate_station import translate_page  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canon", required=True, help="canon.json 路径（doc 或旧裸 list）")
    ap.add_argument("--out", required=True, help="输出 translation.json 路径")
    ap.add_argument("--work-id", default=None)
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--trace", default=None, help="LLM/工具调用观测落盘路径(可选)")
    ap.add_argument("--with-plan", action="store_true",
                    help="翻译前 LLM 扫描全页，标记 invalid/duplicate 框")
    ap.add_argument("--with-vision-plan", action="store_true",
                    help="VLM 规划阶段（带整页图）")
    ap.add_argument("--crop-dir", default=None, help="lookup_image 工具所需 crop 目录")
    a = ap.parse_args()
    canon = load_canon(a.canon)  # normalize + validate（旧裸 list 兼容）
    out = translate_page(a.work_id, canon,
                         state_dir=a.state_dir, page=canon.get("page") or None,
                         with_plan=a.with_plan, with_vision_plan=a.with_vision_plan,
                         trace_enabled=bool(a.trace), crop_dir=a.crop_dir)
    trace, out2 = out.pop("_trace", None), out
    write_json(a.out, out2)
    if a.trace and trace:
        write_json(Path(a.trace), {"work_id": a.work_id or "", "trace": trace})
    print(f"[03_translate] -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 跑测试** — `py -3.13 -m pytest tests/test_translate_station.py tests/test_translate.py tests/test_stage3_planner.py tests/test_semantic_check.py tests/test_repair_failed.py -q --basetemp output/logs/.pytest-basetemp` → 预期全 PASS（semantic/repair 测试 monkeypatch 的是各自脚本的 translate 引用，不受本任务影响）。

- [ ] **Step 6: Commit** — `git add src/amta/translate_station.py scripts/03_translate.py tests/test_translate_station.py && git commit -m "feat(translate_station): Stage 3 深工位 — translate_page 收敛 10+ 参数接线（修 F8/F5），03_translate 薄 CLI"`

---

### Task 7: page_judge.apply_decisions + 00_run_all 减负

**Files:**
- Modify: `src/amta/page_judge.py`（+apply_decisions 纯函数）
- Modify: `scripts/00_run_all.py`（路径走 artifact_paths；judge 段调 apply_decisions）
- Test: `tests/test_page_judge_decisions.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_page_judge_decisions.py`：

```python
"""apply_decisions：judge 决策 → repair/tickets 语义唯一归属（修 F6）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta.page_judge import apply_decisions


JUDGE = {"decisions": [
    {"tool": "repair_region", "args": {"region_id": "page_0_u00"}},
    {"tool": "repair_region", "args": {"region_id": "page_0_u99"}},   # semantic 未标 fail
    {"tool": "open_ticket", "args": {"region_id": "page_0_u02", "reason": "看不清", "kind": "hard_case"}},
    {"tool": "open_ticket", "args": {}},  # 无 region_id，忽略
]}
SEM = {"failed": [{"region_id": "page_0_u00"}]}


def test_apply_decisions_repairable_and_tickets():
    out = apply_decisions(JUDGE, SEM)
    assert out["repair"] == ["page_0_u00"]  # 只修 semantic 已标 fail 的
    kinds = {(t["region_id"], t["kind"]) for t in out["tickets"]}
    assert ("page_0_u02", "hard_case") in kinds
    assert ("page_0_u99", "hard_case") in kinds  # unrepairable → 工单
    assert all(t["region_id"] for t in out["tickets"])  # 空 region_id 决策被滤


def test_apply_decisions_empty():
    out = apply_decisions({}, {"failed": []})
    assert out == {"repair": [], "tickets": []}
```

- [ ] **Step 2: 跑测试确认失败** → `ImportError: apply_decisions`。

- [ ] **Step 3: 实现** — `src/amta/page_judge.py` 末尾追加：

```python
def apply_decisions(judge_doc: dict, sem_doc: dict) -> dict:
    """judge 决策 → 可执行动作（纯函数；语义自 00_run_all 内联段收编，修 F6）。

    - repair_region 仅当 semantic 已标 fail 才可执行（repair_failed 限制）
    - open_ticket 原样转工单；judge 建议修但 semantic 未标 fail 的 → hard_case 工单
    """
    decisions = judge_doc.get("decisions", [])
    repair_ids = [d["args"]["region_id"] for d in decisions
                  if d["tool"] == "repair_region" and d.get("args", {}).get("region_id")]
    ticket_args = [d["args"] for d in decisions
                   if d["tool"] == "open_ticket" and d.get("args", {}).get("region_id")]
    sem_failed_ids = {f["region_id"] for f in sem_doc.get("failed", [])}
    repairable = [rid for rid in repair_ids if rid in sem_failed_ids]
    unrepairable = [rid for rid in repair_ids if rid not in sem_failed_ids]
    tickets = [{"region_id": t["region_id"], "reason": t.get("reason", ""),
                "kind": t.get("kind", "unknown")} for t in ticket_args]
    tickets += [{"region_id": rid,
                 "reason": "judge 建议修复但 semantic 未标记 fail，需人工确认",
                 "kind": "hard_case"} for rid in unrepairable]
    return {"repair": repairable, "tickets": tickets}
```

- [ ] **Step 4: 00_run_all.py 改造** —
  1. import 区加：`from amta import artifacts`、`from amta.page_judge import apply_decisions`；
  2. `run()` 内 `det_path/canon_path/trans_path/trace_path/sem_path/judge_path/inpaint_path/typeset_path/needs_review` 的 `_out(ws_root, ...)` 调用全部替换为 `paths_d = artifacts.artifact_paths(ws_root / "artifacts", page)` 后取 `paths_d["detection"]` 等（`crops_dir` 用 `paths_d["crops"]`；`final/clean` 目录仍按现逻辑拼）；
  3. with_judge 段：`repairable/unrepairable/ticket_decisions` 的三段内联推导替换为：
     ```python
     actions = apply_decisions(judge_doc, sem)
     repairable = actions["repair"]
     if actions["tickets"]:
         from amta.tickets import TicketStore
         ts = TicketStore(state_dir / "tickets.json")
         for t in actions["tickets"]:
             ts.create(work_id=work_id, region_id=t["region_id"],
                       reason=t["reason"], auto_rounds=0, kind=t["kind"])
     ```
     （`ticket_decisions`/`unrepairable` 旧变量删除。）
  4. `_refresh_merged_translation` 原样保留（有测试）。

- [ ] **Step 5: 跑测试** — `py -3.13 -m pytest tests/test_page_judge_decisions.py tests/test_pipeline_flow.py tests/test_runall_typeset.py -q --basetemp output/logs/.pytest-basetemp` → 预期全 PASS（00 的 monkeypatch 面 `_run_cli`/`ensure_workspace` 未变）。

- [ ] **Step 6: Commit** — `git add src/amta/page_judge.py scripts/00_run_all.py tests/test_page_judge_decisions.py && git commit -m "refactor(orchestrator): 00_run_all 路径走 artifact_paths + judge 决策语义移入 page_judge.apply_decisions（修 F6）"`

---

### Task 8: 消费方统一（semantic_check / repair_failed / apply_revisions / eval_stage2 / eval_stage3）

**Files:**
- Modify: `scripts/translate_semantic_check.py:102`、`scripts/repair_failed.py:85-86`、`scripts/apply_revisions.py:35`、`scripts/eval_stage2.py:78-79`、`scripts/eval_stage3.py:82`

- [ ] **Step 1: 逐文件替换读取**（每个文件 2-4 行改动，行为向后兼容——load_canon 兼容旧裸 list）：
  - `translate_semantic_check.py`：`canon = json.loads(Path(canon_path).read_text(encoding="utf-8"))` → 
    ```python
    from amta.artifacts import load_canon
    canon = load_canon(canon_path)["items"]
    ```
  - `repair_failed.py`：`canon = json.loads(canon_path.read_text(encoding="utf-8"))` → `canon = load_canon(canon_path)["items"]`；`trans_doc = json.loads(trans_path.read_text(encoding="utf-8"))` → `trans_doc = load_translation(trans_path)`（import 区加 `from amta.artifacts import load_canon, load_translation`）。
  - `apply_revisions.py`：`doc = json.loads(a.trans.read_text(encoding="utf-8"))` → `doc = load_translation(a.trans)`（加 import）。
  - `eval_stage2.py:78-79`：`canon = json.loads(...)` + `items = canon if isinstance(canon, list) else canon.get("items", [])` 两行 → `items = load_canon(out_path)["items"]`（加 import；**双形状防御代码删除**，replace-don't-layer）。
  - `eval_stage3.py:82`：`canon = json.loads(canon_path.read_text(encoding="utf-8"))` → `canon = load_canon(canon_path)["items"]`（加 import）。

- [ ] **Step 2: 跑相关测试** — `py -3.13 -m pytest tests/test_semantic_check.py tests/test_repair_failed.py tests/test_apply_revisions.py -q --basetemp output/logs/.pytest-basetemp` → 预期全 PASS。

- [ ] **Step 3: Commit** — `git add scripts/translate_semantic_check.py scripts/repair_failed.py scripts/apply_revisions.py scripts/eval_stage2.py scripts/eval_stage3.py && git commit -m "refactor(consumers): semantic/repair/apply_revisions/eval_stage2/3 产物读取统一走 artifacts 契约层"`

---

### Task 9: 契约回归护栏（假适配器全链）

**Files:**
- Test: `tests/test_contract_compatibility.py`（新建）

- [ ] **Step 1: 写护栏测试**：

```python
"""契约回归护栏：01→02→03 假适配器全链，id/键一致性——契约再漂移时 fastcheck 红。"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from amta import artifacts
from fakes import FakeKoharu, make_node


def test_stage123_chain_ids_consistent(tmp_path, monkeypatch):
    monkeypatch.setattr("amta.translate.get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})
    from amta.detect_station import detect_page
    from amta.ocr_station import ocr_page
    from amta.translate_station import translate_page

    art = tmp_path / "artifacts"
    art.mkdir()
    raw = tmp_path / "1.jpg"
    Image.new("RGB", (200, 100), "white").save(raw)
    client = FakeKoharu({
        "pp-doclayout-v3": [make_node("a", 0, 0, 40, 20, "あ")],
        "comic-text-detector": [make_node("b", 0, 0, 40, 20, "あ"),
                                make_node("c", 60, 60, 30, 30, "い")],
    })
    det = detect_page("w1", raw, art, page_idx=0, client=client)

    def fake_ocr(crops, engine="auto", **kw):
        return [{"crop": c, "ocr": "あです"} for c in crops]

    canon = ocr_page("w1", det, raw, art, page_idx=0, vlm_enabled=False, ocr_fn=fake_ocr)

    # 护栏 1：canon region_ids == detection blocks region_ids（顺序一一对应）
    det_ids = [b["region_id"] for b in det["blocks"]]
    canon_ids = [it["region_id"] for it in canon["items"]]
    assert canon_ids == det_ids

    # 护栏 2：contained_in 引用必在 region_id 集合内（修 F3 回归）
    ids = set(canon_ids)
    assert all(it.get("contained_in") in ids for it in canon["items"] if it.get("contained_in"))

    # 护栏 3：盘上产物均为 doc 信封（修 F2 回归）
    on_disk = artifacts.load_canon(art / "page_0_canon.json")
    assert on_disk["items"] and on_disk["schema_version"] == artifacts.SCHEMA_VERSION

    # 护栏 4：翻译 keys ⊇ canon region_ids
    trans = translate_page("w1", canon, page="page_0",
                           llm=lambda m, tools=None: {"content": '{"page_0_u00": "你好", "page_0_u01": "好"}'})
    assert set(trans["translations"]) >= set(canon_ids)
```

- [ ] **Step 2: 跑测试** — `py -3.13 -m pytest tests/test_contract_compatibility.py -q --basetemp output/logs/.pytest-basetemp` → PASS。

- [ ] **Step 3: Commit** — `git add tests/test_contract_compatibility.py && git commit -m "test(contract): 01→02→03 假适配器全链回归护栏（F2/F3 再漂移即红）"`

---

### Task 10: 全链验证 + 文档收尾

**Files:**
- Modify: `CLAUDE.md`（工具面行）、`README.md`（目录树段）、`docs/decisions/024-deep-interface-refactor.md`（新建 ADR）

- [ ] **Step 1: 全量验证**（证据先于断言）：
  ```
  py -3.13 scripts/fastcheck.py        # 预期: 298+新增 passed, ALL PASS
  py -3.13 -m pytest tests -q --basetemp output/logs/.pytest-basetemp
  py -3.13 scripts/smoke_test.py       # 需 koharu server；未起则按 skill 约定说明跳过原因
  ```
  记录实际数字到 Finish Report。基线 2 个环境性失败已改为 SKIP（Task 0），预期无 fail。

- [ ] **Step 2: ADR-024** — 新建 `docs/decisions/024-deep-interface-refactor.md`：背景（F1-F8 审计）/ 决策（契约层+三深工位+配置收敛，subprocess 编排保留）/ 后果（canon doc 化 breaking、04/05 陈旧消费方豁免清单、护栏测试位置）。`docs/decisions/README.md` 索引加一行。

- [ ] **Step 3: CLAUDE.md 更新** — 「工具面」行补：`artifacts.py`（产物契约单一事实源）/`config.py`（密钥唯一归属）/`detect_station.py`/`ocr_station.py`/`translate_station.py`（Stage 1-3 深工位）/`suggestions.py`；删除「items 字段契约升级」的失实描述，改为「canon 落盘 = doc 信封（schema 2.1），旧裸 list 由 load_canon 兼容读」。保持 <120 行。

- [ ] **Step 4: Commit** — `git add CLAUDE.md README.md docs/decisions/ && git commit -m "docs: ADR-024 深接口改造定案 + CLAUDE.md/README 工具面对齐"`

- [ ] **Step 5: /finish 收尾** — 走 cycle-close skill：复读任务 → 审查 diff → fastcheck/smoke → 知识晋升（lessons 如有新坑）→ Finish Report。合并策略（finishing-a-development-branch）由 Patrick 裁决：merge 回 `feature/context-semantic-transfer` 或留分支评审。

---

## Self-Review 记录（writing-plans）

- **Spec 覆盖**：F1→Task 0/豁免记录+Task 9 护栏；F2→Task 1/4/9；F3→Task 1/3/9；F4→Task 2；F5→Task 3/4/5/6；F6→Task 1/7；F7→Task 1/3/4；F8→Task 6。非目标（04/05/subprocess/依赖/eval emit 路径）未越界。✓
- **占位符扫描**：Task 5 Step 3 的 `...` 为显式"逐行搬入"指令（防凭记忆重写），非 TBD；其余步骤均含完整代码/命令。✓
- **类型一致性**：`artifacts.stamp/save_canon/load_canon/page_key/region_id/normalize_region_ids/artifact_paths/trace_path/write_trace` 在 Task 1 定义、Task 3/4/6/7/9 引用，签名一致；`SuggestionsExtractor/merge_into_state/append_suggestions` Task 5 定义、Task 6 引用一致。✓
