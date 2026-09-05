"""artifact_cache 模块测试 — 基于内容哈希的增量构建。"""
import json
import time
from pathlib import Path

import pytest


def test_compute_file_hash_deterministic(tmp_path):
    """同一文件内容哈希一致。"""
    from amta.artifact_cache import compute_file_hash
    f = tmp_path / "test.json"
    f.write_text('{"key": "value"}', encoding="utf-8")
    h1 = compute_file_hash(f)
    h2 = compute_file_hash(f)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_compute_file_hash_changes_with_content(tmp_path):
    """内容变化哈希变化。"""
    from amta.artifact_cache import compute_file_hash
    f = tmp_path / "test.json"
    f.write_text('{"key": "value"}', encoding="utf-8")
    h1 = compute_file_hash(f)
    f.write_text('{"key": "changed"}', encoding="utf-8")
    h2 = compute_file_hash(f)
    assert h1 != h2


def test_compute_code_hash_multiple_files(tmp_path):
    """多个代码文件合并哈希。"""
    from amta.artifact_cache import compute_code_hash
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo(): pass", encoding="utf-8")
    f2.write_text("def bar(): pass", encoding="utf-8")
    h1 = compute_code_hash([f1, f2])
    h2 = compute_code_hash([f1, f2])
    assert h1 == h2
    # 顺序不影响结果
    h3 = compute_code_hash([f2, f1])
    assert h1 == h3


def test_compute_config_hash():
    """配置字典哈希。"""
    from amta.artifact_cache import compute_config_hash
    cfg1 = {"font_size": 52, "direction": "vertical"}
    cfg2 = {"font_size": 52, "direction": "vertical"}
    cfg3 = {"font_size": 48, "direction": "vertical"}
    assert compute_config_hash(cfg1) == compute_config_hash(cfg2)
    assert compute_config_hash(cfg1) != compute_config_hash(cfg3)


def test_save_and_load_fingerprint(tmp_path):
    """指纹保存到 .fingerprint 文件，可加载。"""
    from amta.artifact_cache import save_fingerprint, load_fingerprint, fingerprint_path
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    fp = {"input_hash": "a" * 64, "code_hash": "b" * 64, "config_hash": "c" * 64}
    save_fingerprint(output, "typeset", "page_11", fp)
    fp_path = fingerprint_path(output)
    assert fp_path.exists()
    loaded = load_fingerprint(output)
    assert loaded["stage"] == "typeset"
    assert loaded["page"] == "page_11"
    assert loaded["input_hash"] == "a" * 64


def test_is_fresh_when_fingerprint_matches(tmp_path):
    """指纹匹配时 is_fresh 返回 True。"""
    from amta.artifact_cache import is_fresh, save_fingerprint, compute_fingerprint
    inp = tmp_path / "input.json"
    inp.write_text('{"data": 123}', encoding="utf-8")
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    fp = compute_fingerprint({"input": inp}, [], {})
    save_fingerprint(output, "test", "page_1", fp)
    assert is_fresh(output, {"input": inp}, [], {}) is True


def test_is_fresh_when_input_changes(tmp_path):
    """输入文件变化后 is_fresh 返回 False。"""
    from amta.artifact_cache import is_fresh, save_fingerprint, compute_fingerprint
    inp = tmp_path / "input.json"
    inp.write_text('{"data": 123}', encoding="utf-8")
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    fp = compute_fingerprint({"input": inp}, [], {})
    save_fingerprint(output, "test", "page_1", fp)
    inp.write_text('{"data": 456}', encoding="utf-8")
    assert is_fresh(output, {"input": inp}, [], {}) is False


def test_is_fresh_when_output_missing(tmp_path):
    """输出文件不存在时 is_fresh 返回 False。"""
    from amta.artifact_cache import is_fresh
    inp = tmp_path / "input.json"
    inp.write_text("{}", encoding="utf-8")
    output = tmp_path / "nonexistent.json"
    assert is_fresh(output, {"input": inp}, [], {}) is False


def test_run_stage_if_needed_skips_when_fresh(tmp_path):
    """输入未变时跳过执行，直接返回已有结果。"""
    from amta.artifact_cache import run_stage_if_needed
    inp = tmp_path / "input.json"
    inp.write_text('{"data": 123}', encoding="utf-8")
    output = tmp_path / "result.json"
    call_count = 0
    def generate():
        nonlocal call_count
        call_count += 1
        output.write_text(f'{{"result": {call_count}}}', encoding="utf-8")
    result1 = run_stage_if_needed(
        stage_name="test", page="page_1",
        input_files={"input": inp}, code_files=[], config={},
        output_path=output, generate_fn=generate,
    )
    assert result1["cache_hit"] is False
    assert call_count == 1
    result2 = run_stage_if_needed(
        stage_name="test", page="page_1",
        input_files={"input": inp}, code_files=[], config={},
        output_path=output, generate_fn=generate,
    )
    assert result2["cache_hit"] is True
    assert call_count == 1


def test_run_stage_if_needed_reruns_when_input_changes(tmp_path):
    """输入变化时重新执行。"""
    from amta.artifact_cache import run_stage_if_needed
    inp = tmp_path / "input.json"
    inp.write_text('{"data": 123}', encoding="utf-8")
    output = tmp_path / "result.json"
    call_count = 0
    def generate():
        nonlocal call_count
        call_count += 1
        output.write_text(f'{{"result": {call_count}}}', encoding="utf-8")
    run_stage_if_needed("test", "p1", {"input": inp}, [], {}, output, generate)
    assert call_count == 1
    inp.write_text('{"data": 456}', encoding="utf-8")
    run_stage_if_needed("test", "p1", {"input": inp}, [], {}, output, generate)
    assert call_count == 2


def test_invalidate_cache(tmp_path):
    """invalidate_cache 删除指纹文件。"""
    from amta.artifact_cache import invalidate_cache, save_fingerprint, compute_fingerprint, fingerprint_path
    inp = tmp_path / "input.json"
    inp.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    fp = compute_fingerprint({"input": inp}, [], {})
    save_fingerprint(output, "test", "p1", fp)
    assert fingerprint_path(output).exists()
    result = invalidate_cache(output)
    assert result is True
    assert not fingerprint_path(output).exists()
