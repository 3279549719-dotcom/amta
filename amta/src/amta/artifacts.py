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
        return ["canon must be a list"]
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
    if not isinstance(items, list):  # 类型收窄：校验通过即必为 list（pyright）
        raise ValueError(f"artifact invalid ({path}): canon must be a list")
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


# ---------------------------------------------------------------------------
# 后续阶段 Artifact schema（预留 — 工位实现时填充具体字段）
# ---------------------------------------------------------------------------

class InpaintArtifact(TypedDict, total=False):
    """Stage 4 擦除产物 — 原图去掉文字后的干净图 + mask + 擦除计划。"""
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    clean_image: str          # 擦除后的图片路径（相对 artifacts_dir）
    masks: dict[str, list]   # region_id -> mask 多边形点列表
    plan: list[dict]         # 擦除计划（来自 inpaint_strategy.plan_inpaint）


class TypesetArtifact(TypedDict, total=False):
    """Stage 5 排版产物 — 译文排到气泡后的最终图 + 排版信息。"""
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    final_image: str                # 最终图片路径
    layout: dict[str, dict]         # region_id -> 排版信息（font, size, direction, lines, position）


class SegmentArtifact(TypedDict, total=False):
    """文本分割产物 — 气泡/文本区域的精细分割 mask。"""
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    segments: dict[str, dict]       # region_id -> 分割信息（mask, area, perimeter）
