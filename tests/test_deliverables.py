from __future__ import annotations

from amta.common.deliverables import (
    deliverable_stem,
    load_stems,
    sanitize_stem,
    write_input_manifest,
)


def test_sanitize_stem_strips_extension_and_illegal_chars():
    assert sanitize_stem("封面.png") == "封面"
    assert sanitize_stem("a<b>c:d?e/f.png") == "a_b_c_d_e_f"
    assert sanitize_stem("   ") == "page"


def test_write_and_load_manifest_roundtrip(tmp_path):
    write_input_manifest(tmp_path, ["封面.png", "02.jpg", "cover.PNG"])
    assert load_stems(tmp_path) == {1: "封面", 2: "02", 3: "cover"}


def test_duplicate_stems_get_suffix(tmp_path):
    write_input_manifest(tmp_path, ["untitled.png", "untitled.jpg", "untitled.png"])
    assert load_stems(tmp_path) == {1: "untitled", 2: "untitled_2", 3: "untitled_3"}


def test_deliverable_stem_falls_back_to_page_number_when_no_manifest(tmp_path):
    assert deliverable_stem(tmp_path, 7) == "7"


def test_deliverable_stem_uses_original_name(tmp_path):
    write_input_manifest(tmp_path, ["封面.png"])
    assert deliverable_stem(tmp_path, 1) == "封面"
