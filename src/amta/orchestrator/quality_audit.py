"""quality_audit — 跑后质量体检聚合（红榜）。

背景（friction 2026-09-16 记账）：质量信号（空译文/残留原文/误删框/溢出/收缩框）
全部埋在各阶段产物 JSON 里，但 run_pipeline 只报执行成败（failed=0）——
第 39 页真台词被 conf 过滤误删，系统一声不吭，靠人眼看图才发现。

设计原则（对齐 orchestrator 现状，零新机制）：
- 纯函数：读 artifacts_dir 下的产物 JSON，聚合返回结构化红榜，不写任何文件
- 只聚合本管线刚跑过的 pages × stages（读 PipelineConfig 的范围，不扫全 workspace）
- 信号清单（与各阶段产物字段一一对应，不发明新指标）：
  * translation: 空译文（translations 值为空白串） / residue 非空
  * ocr: n_conf_removed > 0（低置信度被删的框——可能是误删）
  * typeset checks: overflow / shrunk_bubbles / skipped_no_bbox / coverage_complete=False
- 噪声抑制：shrunk_bubbles 历史多发（设计行为，非事故），默认只计数不列 region；
  其余信号列出具体 region/page，供 gen_report --granularity region 下钻
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageFlags:
    """单页的质量异常汇总。"""

    page: str
    empty_translations: list[str] = field(default_factory=list)  # region ids
    residues: int = 0                                          # 残留原文条数
    conf_removed: int = 0                                      # 低置信度删框数
    overflow: list[str] = field(default_factory=list)          # 溢出 region ids
    shrunk: list[str] = field(default_factory=list)            # 收缩框 region ids
    skipped_no_bbox: list[str] = field(default_factory=list)   # 无 bbox 跳过
    coverage_incomplete: bool = False                          # 渲染覆盖不全

    @property
    def has_flags(self) -> bool:
        return bool(
            self.empty_translations or self.residues or self.conf_removed
            or self.overflow or self.shrunk or self.skipped_no_bbox
            or self.coverage_incomplete
        )


def audit_page(artifacts_dir: Path, page: str) -> PageFlags:
    """聚合单页各阶段产物的质量信号。缺产物（该阶段未跑/被跳过）= 无信号，不算异常。"""
    flags = PageFlags(page=page)

    # translation: 空译文 + residue
    t = _load_json(artifacts_dir / "translation" / f"{page}.json")
    if t:
        flags.empty_translations = [
            rid for rid, v in t.get("translations", {}).items()
            if not str(v).strip()
        ]
        flags.residues = len([r for r in t.get("residue", []) if str(r).strip()])

    # ocr: 低置信度删框（误删风险）
    o = _load_json(artifacts_dir / "ocr" / f"{page}.json")
    if o:
        flags.conf_removed = int(o.get("n_conf_removed", 0) or 0)

    # typeset checks: 溢出/收缩/跳过/覆盖
    tp = _load_json(artifacts_dir / "typeset" / f"{page}.json")
    if tp:
        checks = tp.get("checks", {}) or {}
        flags.overflow = list(checks.get("overflow", []) or [])
        flags.shrunk = list(checks.get("shrunk_bubbles", []) or [])
        flags.skipped_no_bbox = list(checks.get("skipped_no_bbox", []) or [])
        flags.coverage_incomplete = not checks.get("coverage_complete", True)

    return flags


def audit_run(artifacts_dir: Path, pages: list[str]) -> list[PageFlags]:
    """跑后红榜：返回有异常的页（无异常的页不出现）。"""
    flagged = [audit_page(artifacts_dir, p) for p in pages]
    return [f for f in flagged if f.has_flags]


def format_redlist(flags: list[PageFlags]) -> str:
    """红榜文本（给 AI 的短清单，不是给人眼的 HTML）。空列表 → 空串。"""
    if not flags:
        return ""
    lines = []
    for f in flags:
        parts = []
        if f.empty_translations:
            parts.append(f"空译文 {f.empty_translations}")
        if f.residues:
            parts.append(f"残留原文 {f.residues} 条")
        if f.conf_removed:
            parts.append(f"conf 删框 {f.conf_removed} 个（误删风险）")
        if f.overflow:
            parts.append(f"溢出 {f.overflow}")
        if f.shrunk:
            parts.append(f"收缩框 {len(f.shrunk)} 个")
        if f.skipped_no_bbox:
            parts.append(f"无bbox跳过 {f.skipped_no_bbox}")
        if f.coverage_incomplete:
            parts.append("渲染覆盖不全")
        lines.append(f"  {f.page}: " + "；".join(parts))
    return "\n".join(lines)


def _load_json(path: Path) -> dict | None:
    """读产物 JSON；不存在/损坏返回 None（未跑该阶段 ≠ 质量异常）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
