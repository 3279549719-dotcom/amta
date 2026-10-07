"""Bootstrap a brand-new book: OCR its whole folder, then LLM-extract names.

This is the "one-time setup" a new doujinshi needs:
    point at the folder -> run detect+ocr on every page -> collect OCR text
    -> one LLM call picks out katakana names -> draft glossary.

The draft is returned to the GUI for human editing; only after the user clicks
save does it get locked into books/<book_id>/glossary.json. We deliberately do
NOT save here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from amta.guards.name_pre_scan import build_extraction_prompt, parse_extraction_response


def collect_ocr_text(artifacts_dir: Path) -> tuple[str, list[int]]:
    """Gather all OCR text from canon/page_*.json under artifacts_dir.

    Returns (combined_text, pages_covered_sorted). Order of pages in the text
    does not matter for name extraction.
    """
    canon = artifacts_dir / "canon"
    if not canon.is_dir():
        return "", []

    parts: list[str] = []
    pages: set[int] = set()
    for cf in sorted(canon.glob("page_*.json")):
        try:
            page_num = int(cf.stem.split("_")[1])
        except (ValueError, IndexError):
            continue
        pages.add(page_num)
        import json
        try:
            doc = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in doc.get("items", []):
            txt = item.get("baberu_text") or item.get("text") or ""
            if txt.strip():
                parts.append(txt)

    return "\n".join(parts), sorted(pages)


def bootstrap_book(src_dir: Path, work_id: str) -> dict[str, str]:
    """Run detect+ocr over the whole folder, then LLM-extract names.

    Returns the DRAFT glossary {surface: translation} (not saved). The GUI
    shows it for human editing; saving happens via POST /api/glossary.
    """
    from amta.orchestrator import PipelineConfig, run_pipeline

    # discover pages once
    page_index: dict[int, Path] = {}
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        for p in Path(src_dir).glob(ext):
            if p.stem.isdigit():
                page_index.setdefault(int(p.stem), p)
    pages = sorted(page_index)
    if not pages:
        return {}

    config = PipelineConfig(
        work_id=work_id,
        src_dir=Path(src_dir),
        start_page=1, end_page=9999,
        pages=pages,
        stages=["detect", "ocr"],
        continue_on_error=True,
    )
    run_pipeline(config)

    from amta.common.workstate import ensure_workspace
    artifacts_dir = ensure_workspace(work_id) / "artifacts"
    combined, _ = collect_ocr_text(artifacts_dir)

    from amta.backends.chat_client import chat_text
    from amta.translation.translate import get_chat_config
    cfg = get_chat_config()

    def _llm(prompt: str) -> str:
        return chat_text(
            cfg["base_url"], cfg["model"],
            [{"role": "user", "content": prompt}],
            api_key=cfg["api_key"],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

    return prescan_names_from_text(combined, _llm)


def prescan_names_from_text(combined_text: str, llm: Callable[[str], str]) -> dict[str, str]:
    """Build the extraction prompt, call the LLM, parse names.

    `llm` takes the prompt string and returns the raw model string — injected
    so tests don't need a real chat client.
    """
    if not combined_text.strip():
        return {}
    prompt = build_extraction_prompt(combined_text)
    raw = llm(prompt)
    return parse_extraction_response(raw)
