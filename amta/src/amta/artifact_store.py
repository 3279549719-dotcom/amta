"""ArtifactStore — 目录即索引（dir-as-index）产物访问门。

布局定死为「目录即索引」，消灭「靠 glob / 平铺命名反查」找产物：
- 新布局：`artifacts/<stage>/<page>.json`（stage 即目录，文件名退成 `page_N.json`）
- 旧平铺：`artifacts/<page>_<stage>.json`（只读回退，不迁移存量文件）

图片类子目录（clean/final/crops）不经本门（维持现状）。
查询一律走 store.resolve / store.pages / store.list_files —— glob 只允许出现在本模块内部。
"""
from __future__ import annotations

from pathlib import Path

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
    def from_artifacts_dir(cls, artifacts_dir: Path | str) -> "ArtifactStore":
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
