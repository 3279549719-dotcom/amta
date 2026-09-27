"""工位产物契约 + 目录即索引访问门 — 单一事实源。

唯一归属：
- schema 信封与 TypedDict（Detection/Canon/Translation/Inpaint/Typeset/Segment）
- 页键与 region_id 规则（全链单空间 page_{idx}_u{i:02d}）
- 产物/trace 文件命名、ArtifactStore（新布局 artifacts/<stage>/<page>.json，旧平铺只读回退）
- load_*(normalize+validate) / save_*(信封盖章)
schema_version "2.1" = front3 "2.0" → canon doc 化 + region_id 单空间。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, TypedDict

from amta.common.paths import read_json, write_json

SCHEMA_VERSION = "2.1"
CATEGORIES = ("dialogue_bubble", "overlay_text", "sfx")
SUB_TIERS = ("primary", "aside")


class DetectionBlock(TypedDict, total=False):
    region_id: str
    bbox: list[float]
    category: str
    sub_tier: str
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


# 子目录化 JSON 阶段（= artifact_paths 契约键，除 crops 目录键外）
JSON_STAGES = ("detection", "canon", "translation", "needs_review", "inpaint", "typeset")

# 旧平铺文件名模板（page=page_N）；resolve/pages/clear 回退推导用
LEGACY_NAME: dict[str, str] = {
    "detection": "{page}_detection.json",
    "canon": "{page}_canon.json",
    "translation": "{page}_translation.json",
    "needs_review": "{page}_needs_review.json",
    "inpaint": "{page}_inpaint.json",
    "typeset": "{page}_typeset.json",
}


def fingerprint_of(path: Path) -> Path:
    """artifact 对应的 .fingerprint 兄弟文件路径（与 artifact_cache.fingerprint_path 同规则）。"""
    return Path(str(path) + ".fingerprint")


def _page_no(page: str) -> int:
    """page_N → N（排序键）；非 page_N 命名垫底。"""
    if page.startswith("page_") and page[5:].isdigit():
        return int(page[5:])
    return 10**9


class ArtifactStore:
    """artifacts/ 目录即索引的访问门：新布局向前写，旧平铺只读回退。"""

    def __init__(self, artifacts_dir: Path | str) -> None:
        self.artifacts_dir = Path(artifacts_dir)

    @classmethod
    def from_artifacts_dir(cls, artifacts_dir: Path | str) -> ArtifactStore:
        """显式构造入口（与 ArtifactStore(artifacts_dir) 等价）。"""
        return cls(artifacts_dir)

    # ---- 路径 ----

    def path(self, stage: str, page: str) -> Path:
        """新布局确定路径：artifacts/<stage>/<page>.json（不检查存在）。"""
        return self.artifacts_dir / stage / f"{page}.json"

    def legacy_path(self, stage: str, page: str) -> Path:
        """旧平铺路径推导：artifacts/<page>_<stage>.json。"""
        template = LEGACY_NAME.get(stage)
        if template is None:
            raise KeyError(f"unknown artifact stage: {stage!r}")
        return self.artifacts_dir / template.format(page=page)

    def resolve(self, stage: str, page: str) -> Path | None:
        """先新布局、后旧平铺定位单个产物；两处都不存在返回 None。"""
        new = self.path(stage, page)
        if new.exists():
            return new
        legacy = self.legacy_path(stage, page)
        return legacy if legacy.exists() else None

    def exists(self, stage: str, page: str) -> bool:
        """产物在任一布局存在（resolve 短路）。"""
        return self.resolve(stage, page) is not None

    # ---- 索引 ----

    def pages(self, stage: str) -> list[str]:
        """该 stage 全部页键（新布局子目录 listdir + 旧平铺根目录并集），按页号升序。"""
        keys: set[str] = set()
        stage_dir = self.artifacts_dir / stage
        if stage_dir.is_dir():
            keys.update(f.stem for f in stage_dir.glob("*.json"))
        suffix = f"_{stage}.json"
        for f in self.artifacts_dir.glob(f"*{suffix}"):
            if f.is_file() and f.name.startswith("page_"):
                keys.add(f.name[: -len(suffix)])
        return sorted(keys, key=lambda k: (_page_no(k), k))

    def list_files(self, stage: str) -> list[Path]:
        """该 stage 全部产物文件（新布局子目录 + 旧平铺根目录），供统计/清理。"""
        files: list[Path] = []
        stage_dir = self.artifacts_dir / stage
        if stage_dir.is_dir():
            files.extend(sorted(stage_dir.glob("*.json")))
        suffix = f"_{stage}.json"
        for f in sorted(self.artifacts_dir.glob(f"*{suffix}")):
            if f.is_file() and f.name.startswith("page_"):
                files.append(f)
        return files

    # ---- 清理 ----

    def clear_stage(self, stage: str) -> int:
        """删除该 stage 全部产物（新+旧）及其 .fingerprint，返回删除文件数。"""
        removed = 0
        for artifact in self.list_files(stage):
            for p in (artifact, fingerprint_of(artifact)):
                removed += _unlink_if_exists(p)
        _rmdir_if_empty(self.artifacts_dir / stage)
        return removed

    def clear_page(self, page: str) -> int:
        """删除某页全部 stage 产物（新+旧）及其 .fingerprint，返回删除文件数。"""
        removed = 0
        for stage in JSON_STAGES:
            for p in (self.path(stage, page), self.legacy_path(stage, page)):
                for cand in (p, fingerprint_of(p)):
                    removed += _unlink_if_exists(cand)
        return removed


def _unlink_if_exists(path: Path) -> int:
    try:
        if path.exists():
            path.unlink()
            return 1
    except OSError:
        pass
    return 0


def _rmdir_if_empty(path: Path) -> None:
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass


def resolve_artifact(artifacts_dir: Path | str, stage: str, page: str) -> Path | None:
    """模块级便捷 helper：新→旧布局回退查询单个产物，不存在返回 None。"""
    return ArtifactStore(artifacts_dir).resolve(stage, page)



# ---------- 页键 / ID / 命名（唯一归属） ----------

def page_key(page_idx: int) -> str:
    """1 基页键（page_N ↔ N.jpg，与原图序号一致）。"""
    return f"page_{page_idx}"


def page_idx_from_raw(raw_page: Path) -> int:
    """N.jpg → 页号 N（1 基，与原图序号一致）。"""
    return int(raw_page.stem)


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
    """全部产物路径唯一归属（修 F6 文件名知识散落 / F7 命名不一）。

    布局 = 目录即索引（ADR 2026-09-06）：JSON 阶段产物落 `<dir>/<stage>/<page>.json`
    （stage 即目录）；`crops` 目录键维持。旧平铺回退见 artifact_store.resolve。
    """
    art = Path(artifacts_dir)
    store = ArtifactStore(art)
    return {
        "detection": store.path("detection", page),
        "canon": store.path("canon", page),
        "translation": store.path("translation", page),
        "needs_review": store.path("needs_review", page),
        "inpaint": store.path("inpaint", page),
        "typeset": store.path("typeset", page),
        "crops": art / "crops",
    }



def fingerprint_paths(artifacts_dir: Path, page: str) -> dict[str, Path]:
    """返回各 artifact 对应的 fingerprint 文件路径（增量构建缓存用）。"""
    paths = artifact_paths(artifacts_dir, page)
    return {k: fingerprint_of(v) for k, v in paths.items() if k != "crops"}

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


class RenderedItem(TypedDict, total=False):
    """Shared PNG/PSD text metadata; positions and spacing are image pixels."""
    region_id: str
    lines: list[str]
    layout_direction: str
    font_size: float
    font_path: str
    font_family: str
    anchor_pos: list[float]
    rendered_color: str
    rendered_stroke: float
    stroke_color: str | None
    line_step: float
    col_step: float
    align: str


def normalize_rendered_item(item: dict) -> dict:
    """Normalize legacy VLM metadata at the shared artifact boundary.

    Both renderers emit this contract. Old artifacts remain exportable, but a
    missing position must never silently put text at the canvas origin.
    """
    out = dict(item)
    if "anchor_pos" not in out:
        bounds = out.get("ink_bbox")
        if not bounds or len(bounds) != 4:
            raise ValueError("rendered item missing anchor_pos/ink_bbox")
        out["anchor_pos"] = [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]
    out.setdefault("font_family", Path(out.get("font_path", "msyh.ttc")).name)
    out.setdefault("rendered_color", out.get("color", "#000000"))
    out.setdefault("rendered_stroke", out.get("stroke_width", 0))
    out.setdefault("align", "center")
    vertical = out.get("layout_direction") == "vertical"
    out.setdefault("line_step", out.get("font_size", 40) * (1.2 if vertical else 1.15))
    return out


class TypesetArtifact(TypedDict, total=False):
    """Stage 5 排版产物 — 译文排到气泡后的最终图 + 排版信息。"""
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    final_image: str                # 最终图片路径
    layout: dict[str, dict]         # region_id -> 排版信息（font, size, direction, lines, position）
    rendered_items: list[RenderedItem]


class SegmentArtifact(TypedDict, total=False):
    """文本分割产物 — 气泡/文本区域的精细分割 mask。"""
    work_id: str
    page: str
    schema_version: str
    generated_at: str
    segments: dict[str, dict]       # region_id -> 分割信息（mask, area, perimeter）
