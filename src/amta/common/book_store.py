"""Book-level glossary store: keyed by src_dir path hash, shared across all work-ids.

This is the "熟客档案" — regardless of which work-id (seat) you sit at,
the book's confirmed glossary follows the source image folder.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from amta.common.paths import ROOT

# workspace/_books/<book_id>/
WORKSPACE_ROOT = ROOT / "workspace"
BOOKS_DIR = "books"


def book_id_from_src_dir(src_dir: str | Path) -> str:
    """Derive a stable book fingerprint from the source image directory path.

    Uses realpath (resolves symlinks/..) then sha1 — so renaming the folder
    breaks the fingerprint, but normal operation (same folder, multiple work-ids)
    stays stable.
    """
    real = Path(src_dir).resolve()
    return hashlib.sha1(str(real).encode("utf-8")).hexdigest()[:16]


def _book_dir(book_id: str) -> Path:
    d = WORKSPACE_ROOT / BOOKS_DIR / book_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def glossary_path(book_id: str) -> Path:
    return _book_dir(book_id) / "glossary.json"


def meta_path(book_id: str) -> Path:
    return _book_dir(book_id) / "meta.json"


def load_glossary(book_id: str) -> dict[str, str]:
    """Load confirmed glossary {surface: translation}. Missing → empty dict."""
    p = glossary_path(book_id)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_glossary(book_id: str, glossary: dict[str, str]) -> Path:
    """Write confirmed glossary to disk."""
    p = glossary_path(book_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)
    return p


def save_meta(book_id: str, src_dir: str | Path) -> None:
    """Record source path + timestamp for traceability."""
    import datetime
    p = meta_path(book_id)
    data = {
        "src_dir": str(Path(src_dir).resolve()),
        "created_at": datetime.datetime.now().isoformat(),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def has_glossary(book_id: str) -> bool:
    """True if a confirmed glossary already exists for this book."""
    return glossary_path(book_id).exists()
