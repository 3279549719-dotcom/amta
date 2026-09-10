"""Lesson 03 实践：get_context 语义化传递 — TDD 测试。

Seam：execute_tool("get_context", ...) 的返回值行为。
验证：category 标注、relationships 附加、术语筛选、边界回退、条数限制。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _write_page_artifacts(artifacts_dir: Path, page: int, canon: list[dict], translations: dict[str, str]):
    """辅助：写单页 canon 和 translation 文件到 artifacts 目录。"""
    canon_path = artifacts_dir / f"page_{page}_canon.json"
    canon_path.write_text(json.dumps(canon, ensure_ascii=False), encoding="utf-8")
    trans_path = artifacts_dir / f"page_{page}_translation.json"
    trans_path.write_text(json.dumps({
        "work_id": "test",
        "translations": translations,
    }, ensure_ascii=False), encoding="utf-8")


def test_get_context_reads_canon_category_and_labels(tmp_path):
    """Red→Green：get_context 同时读 canon 和 translation，返回带 category 标注的文本。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    _write_page_artifacts(artifacts_dir, page=1, canon=[
        {"region_id": "page_1_u00", "text": "こんにちは", "page": 1, "category": "dialogue_bubble"},
        {"region_id": "page_1_u01", "text": "ドカン", "page": 1, "category": "sfx"},
        {"region_id": "page_1_u02", "text": "注意書き", "page": 1, "category": "overlay_text"},
    ], translations={
        "page_1_u00": "你好",
        "page_1_u01": "轰隆",
        "page_1_u02": "注意事项",
    })

    out = build_semantic_context(1, {}, None, state_dir)

    assert "[对话]" in out
    assert "[拟声]" in out
    assert "[覆盖文字]" in out
    assert "你好" in out
    assert "轰隆" in out
    assert "注意事项" in out


def test_get_context_falls_back_to_plain_when_canon_missing(tmp_path):
    """边界：canon 文件不存在时，回退到纯文本（无 category 标注），不崩溃。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    # 只写 translation，不写 canon
    trans_path = artifacts_dir / "page_1_translation.json"
    trans_path.write_text(json.dumps({
        "work_id": "test",
        "translations": {"page_1_u00": "你好"},
    }, ensure_ascii=False), encoding="utf-8")

    out = build_semantic_context(1, {}, None, state_dir)

    assert "你好" in out
    # 无 canon 时不应该有 category 标注，但也不应该崩溃
    assert "[对话]" not in out


def test_get_context_appends_confirmed_and_inferred_relationships(tmp_path):
    """Red→Green：get_context 附加 work_state 的 relationships（confirmed + inferred，标置信度）。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    _write_page_artifacts(artifacts_dir, page=1, canon=[
        {"region_id": "page_1_u00", "text": "こんにちは", "page": 1, "category": "dialogue_bubble"},
    ], translations={"page_1_u00": "你好"})

    ws = {
        "relationships": [
            {"from": "八意永琳", "to": "蓬莱山辉夜", "kind": "主从", "status": "confirmed", "source": "p8"},
            {"from": "博丽灵梦", "to": "雾雨魔理沙", "kind": "朋友", "status": "inferred", "source": "p3"},
        ]
    }

    out = build_semantic_context(1, ws, None, state_dir)

    assert "八意永琳" in out
    assert "主从" in out
    assert "蓬莱山辉夜" in out
    assert "博丽灵梦" in out
    assert "朋友" in out
    # inferred 的应该标低置信度
    assert "推断" in out or "inferred" in out


def test_get_context_filters_relevant_terms_from_prev_pages(tmp_path):
    """Red→Green：get_context 筛选前页原文中出现的术语（norm 模糊匹配，最多 5 条）。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    _write_page_artifacts(artifacts_dir, page=1, canon=[
        {"region_id": "page_1_u00", "text": "八意様が月の民と話す", "page": 1, "category": "dialogue_bubble"},
    ], translations={"page_1_u00": "八意大人和月之民说话"})

    ws = {
        "terms": {
            "八意様": {"translation": "八意大人", "status": "confirmed", "source": "p1"},
            "月の民": {"translation": "月之民", "status": "confirmed", "source": "p2"},
            "豊姫": {"translation": "丰姬", "status": "confirmed", "source": "p5"},  # 不相关
        }
    }

    out = build_semantic_context(1, ws, None, state_dir)

    assert "八意大人" in out
    assert "月之民" in out
    assert "丰姬" not in out  # 不相关的术语不应该出现


def test_get_context_limits_relationships_to_three(tmp_path):
    """条数限制：relationships 最多附加 3 条，按置信度排序（confirmed 优先）。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    _write_page_artifacts(artifacts_dir, page=1, canon=[
        {"region_id": "page_1_u00", "text": "test", "page": 1, "category": "dialogue_bubble"},
    ], translations={"page_1_u00": "测试"})

    ws = {
        "relationships": [
            {"from": f"角色{i}", "to": f"对象{i}", "kind": f"关系{i}",
             "status": "confirmed" if i < 2 else "inferred", "source": f"p{i}"}
            for i in range(5)  # 5 条关系，只应该出现 3 条
        ]
    }

    out = build_semantic_context(1, ws, None, state_dir)

    # confirmed 的 2 条应该都在
    assert "角色0" in out
    assert "角色1" in out
    # inferred 的 3 条里只应该有 1 条（总共 3 条）
    inferred_count = sum(1 for i in range(2, 5) if f"角色{i}" in out)
    assert inferred_count == 1


def test_get_context_reads_dual_engine_canon_baberu_text(tmp_path):
    """TDD：双引擎 canon（baberu_text，无 text 字段）也要能喂术语相关性筛选。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    canon = [
        {"region_id": "page_1_u00", "baberu_text": "八意様が月の民と話す",
         "vlm_text": None, "page": 1, "category": "dialogue_bubble"},
    ]
    (artifacts_dir / "page_1_canon.json").write_text(json.dumps(canon, ensure_ascii=False), encoding="utf-8")
    (artifacts_dir / "page_1_translation.json").write_text(
        json.dumps({"work_id": "test", "translations": {"page_1_u00": "大人和月之民说话"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    ws = {"terms": {"八意様": {"translation": "八意大人", "status": "confirmed", "source": "p1"}}}

    out = build_semantic_context(1, ws, None, state_dir)

    assert "八意大人" in out  # 术语相关性来自 canon 原文——baberu_text 格式必须被读到


def test_get_context_page_header_count_matches_rendered(tmp_path):
    """TDD：页头「共N条」应等于实际渲染条数（截断时=15），而不是页内总数。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    canon = [
        {"region_id": f"page_1_u{i:02d}", "text": f"原文{i}", "page": 1, "category": "dialogue_bubble"}
        for i in range(16)
    ]
    translations = {f"page_1_u{i:02d}": f"译文{i}" for i in range(16)}
    _write_page_artifacts(artifacts_dir, page=1, canon=canon, translations=translations)

    out = build_semantic_context(1, {}, None, state_dir)

    header = next(line for line in out.splitlines() if line.startswith("--- 第1页"))
    assert "共15条" in header
    assert "共16条" not in header


def test_get_context_truncates_regions_to_fifteen(tmp_path):
    """边界：单页 region 数超过 MAX_REGIONS_PER_PAGE(15) 时只渲染前 15 条。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    canon = [
        {"region_id": f"page_1_u{i:02d}", "text": f"原文{i}", "page": 1, "category": "dialogue_bubble"}
        for i in range(16)
    ]
    translations = {f"page_1_u{i:02d}": f"译文{i}" for i in range(16)}
    _write_page_artifacts(artifacts_dir, page=1, canon=canon, translations=translations)

    out = build_semantic_context(1, {}, None, state_dir)

    rendered = [line for line in out.splitlines() if line.startswith("[对话]")]
    assert len(rendered) == 15
    assert "译文0" in out
    assert "译文14" in out
    assert "译文15" not in out  # 第 16 条被截断


def test_get_context_caps_terms_at_five(tmp_path):
    """边界：相关 confirmed 术语超过 MAX_TERMS(5) 时只显示前 5 条（按插入序）。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    combined_src = "八意様 月の民 蓬莱 山の幸 玉鱗 ドカン"
    _write_page_artifacts(
        artifacts_dir, page=1,
        canon=[{"region_id": "page_1_u00", "text": combined_src, "page": 1, "category": "dialogue_bubble"}],
        translations={"page_1_u00": "译文占位"},
    )
    ws = {
        "terms": {
            "八意様": {"translation": "译一", "status": "confirmed", "source": "p1"},
            "月の民": {"translation": "译二", "status": "confirmed", "source": "p1"},
            "蓬莱": {"translation": "译三", "status": "confirmed", "source": "p1"},
            "山の幸": {"translation": "译四", "status": "confirmed", "source": "p1"},
            "玉鱗": {"translation": "译五", "status": "confirmed", "source": "p1"},
            "ドカン": {"translation": "译六", "status": "confirmed", "source": "p1"},  # 第 6 条，应被截断
        }
    }

    out = build_semantic_context(1, ws, None, state_dir)

    assert "译一" in out and "译五" in out
    assert "译六" not in out


def test_get_context_multipage_reads_last_two_pages(tmp_path):
    """pages=2 时读取页码最大的 2 页（translation 文件按页码排序取尾部）。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    for page, text in [(1, "甲页内容"), (2, "乙页内容"), (3, "丙页内容")]:
        _write_page_artifacts(
            artifacts_dir, page=page,
            canon=[{"region_id": f"page_{page}_u00", "text": f"原文{page}", "page": page, "category": "dialogue_bubble"}],
            translations={f"page_{page}_u00": text},
        )

    out = build_semantic_context(2, {}, None, state_dir)

    assert "--- 第2页" in out
    assert "--- 第3页" in out
    assert "乙页内容" in out
    assert "丙页内容" in out
    assert "甲页内容" not in out


def test_get_context_tolerates_malformed_canon(tmp_path):
    """容错：canon 含非 dict 项 / 缺 region_id 项 / 坏 JSON 时不得崩溃，仍输出有效内容。"""
    from amta.translation.stage3_minimal import build_semantic_context

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir()

    canon = [
        "不是字典",
        {"no_region_id": True},
        {"region_id": "page_1_u00", "text": "こんにちは", "page": 1, "category": "dialogue_bubble"},
    ]
    (artifacts_dir / "page_1_canon.json").write_text(json.dumps(canon, ensure_ascii=False), encoding="utf-8")
    (artifacts_dir / "page_1_translation.json").write_text(
        json.dumps({"work_id": "test", "translations": {"page_1_u00": "你好"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    # 另一页 canon 是坏 JSON：该页退化为无 category 标注（label=文本），但不崩溃
    (artifacts_dir / "page_2_canon.json").write_text("{broken json", encoding="utf-8")
    (artifacts_dir / "page_2_translation.json").write_text(
        json.dumps({"work_id": "test", "translations": {"page_2_u00": "第二页"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    out = build_semantic_context(2, {}, None, state_dir)

    assert "你好" in out
    assert "第二页" in out
    assert "[文本]" in out  # 坏 canon 页的 label 回退
