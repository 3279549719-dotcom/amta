"""Bootstrap a brand-new book: run detect+OCR on its folder, extract names via LLM.

These tests cover the pure, testable pieces:
  - collect_ocr_text: gather all canon page text from an artifacts dir
  - prescan_names_from_text: build prompt -> call injected LLM -> parse dict
The expensive detect/OCR pipeline and the real chat client stay thin wrappers.
"""
from __future__ import annotations

import json
from pathlib import Path

from amta.guards.book_bootstrap import collect_ocr_text, prescan_names_from_text


def _write_canon(artifacts_dir: Path, page: int, items: list[dict]) -> None:
    canon = artifacts_dir / "canon"
    canon.mkdir(parents=True, exist_ok=True)
    (canon / f"page_{page}.json").write_text(
        json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8"
    )


def test_collect_ocr_text_merges_pages_in_order(tmp_path: Path) -> None:
    art = tmp_path / "artifacts"
    _write_canon(art, 2, [{"baberu_text": "メディスン"}])
    _write_canon(art, 1, [{"text": "スーさん"}])

    combined, pages = collect_ocr_text(art)

    assert pages == [1, 2]
    assert "スーさん" in combined
    assert "メディスン" in combined


def test_prescan_names_from_text_uses_injected_llm(tmp_path: Path) -> None:
    captured: dict = {}

    def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps({
            "names": [
                {"surface": "スーさん", "translation": "小玲"},
                {"surface": "メディスン", "translation": "梅蒂欣"},
            ]
        }, ensure_ascii=False)

    names = prescan_names_from_text("スーさん\nメディスン", llm=fake_llm)

    assert names == {"スーさん": "小玲", "メディスン": "梅蒂欣"}
    # the OCR text must actually be fed into the LLM prompt
    assert "スーさん" in captured["prompt"]


def test_prescan_names_from_text_bad_llm_output_returns_empty(tmp_path: Path) -> None:
    names = prescan_names_from_text("whatever", llm=lambda prompt: "not json at all")
    assert names == {}
