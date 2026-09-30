"""PSD JSX 导出 — Facade，向后兼容。

内部拆成两层：
  - psd_jsx.py     — 纯 JSX 脚本生成（无 I/O）
  - psd_export.py  — Photoshop 进程管理（查找 exe、subprocess、轮询）

本模块 re-export 公共符号，保持现有 import 路径不变。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from amta.typeset.psd_export import export_psd_with_jsx, find_photoshop_executable
from amta.typeset.psd_jsx import (  # noqa: F401  (re-export for backward compat)
    build_script,
    escape_jsx_path,
    escape_jsx_string,
    generate_text_layer_jsx,
    has_conjoined_punct,
    hex_to_rgb,
    normalize_vertical_punct,
    resolve_font_family,
)

# 向后兼容：测试和旧调用方用下划线名
_generate_text_layer_jsx = generate_text_layer_jsx
_has_conjoined_punct = has_conjoined_punct
_normalize_vertical_punct = normalize_vertical_punct
_hex_to_rgb = hex_to_rgb
_escape_jsx_string = escape_jsx_string
_escape_jsx_path = escape_jsx_path
_resolve_font_family = resolve_font_family
_find_photoshop_executable = find_photoshop_executable


def export_page_psd(
    artifacts_dir: Path,
    page: str,
    output_path: Path,
    script_only: bool = False,
    verbose: bool = False,
) -> Optional[str]:
    """便捷接口：从 artifacts 目录读取 clean 图和 typeset JSON，导出 PSD。"""
    from amta.common.paths import read_json

    inpaint_path = artifacts_dir / "inpaint" / f"{page}.json"
    if not inpaint_path.exists():
        inpaint_path = artifacts_dir / f"{page}_inpaint.json"
    if not inpaint_path.exists():
        return None

    inpaint_doc = read_json(inpaint_path)
    clean_image_name = inpaint_doc.get("clean_image", "")
    if not clean_image_name:
        return None
    clean_path = artifacts_dir / clean_image_name
    if not clean_path.exists():
        return None

    typeset_path = artifacts_dir / "typeset" / f"{page}.json"
    if not typeset_path.exists():
        typeset_path = artifacts_dir / f"{page}_typeset.json"
    if not typeset_path.exists():
        return None

    typeset_data = read_json(typeset_path)

    return export_psd_with_jsx(
        clean_image_path=str(clean_path),
        typeset_data=typeset_data,
        output_psd_path=str(output_path),
        script_only=script_only,
        verbose=verbose,
    )
