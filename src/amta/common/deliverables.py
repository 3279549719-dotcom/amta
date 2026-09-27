"""交付物命名：内部用 page_N 编号，对外下载时用原图文件名。

入库（上传）时把 {1-based 页号: 去重后的原图 stem} 写进
workspace/<work_id>/input_manifest.json；导出（下载）时读它，把 PNG/PSD
命名成用户投喂的原名。没有 manifest 的老工作区回退到页号本身。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_MANIFEST_NAME = "input_manifest.json"
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_stem(name: str) -> str:
    """原图文件名 → 安全的交付 stem；去扩展名、替换非法字符、空则回退。"""
    stem = os.path.splitext(name)[0].strip()
    stem = _ILLEGAL.sub("_", stem).strip(" .")
    return stem or "page"


def write_input_manifest(work_dir: Path, source_names: list[str]) -> Path:
    """记录 {1-based 页号: 去重后的原图 stem}。source_names 按上传顺序。"""
    used: dict[str, int] = {}
    pages: list[dict] = []
    for n, raw in enumerate(source_names, start=1):
        stem = sanitize_stem(raw)
        count = used.get(stem, 0) + 1
        used[stem] = count
        unique = stem if count == 1 else f"{stem}_{count}"
        pages.append({"n": n, "stem": unique, "source_name": raw})
    path = work_dir / _MANIFEST_NAME
    path.write_text(
        json.dumps({"pages": pages}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_stems(work_dir: Path) -> dict[int, str]:
    """读 manifest → {页号: stem}；文件缺失/损坏返回 {}。"""
    path = work_dir / _MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, str] = {}
    for entry in doc.get("pages", []):
        n, stem = entry.get("n"), entry.get("stem")
        if isinstance(n, int) and isinstance(stem, str) and stem:
            out[n] = stem
    return out


def deliverable_stem(work_dir: Path, page_num: int) -> str:
    """对外下载用的文件名 stem：优先 manifest 里的原图名，否则用页号。"""
    return load_stems(work_dir).get(page_num) or str(page_num)
