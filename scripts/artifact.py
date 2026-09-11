"""artifact — 统一产物管理 CLI（深接口版）。

设计原则（参考 MLflow / Airflow XCom / DVC / Pachyderm / W&B）：
- 一个查询原语 + 可选参数，不按场景硬编码命令
- 必填最粗粒度（work-id 或 --all），可选下钻（stage / page）
- 返回结构化对象（路径+元数据），不返回裸路径字符串
- 追溯靠生产时的依赖声明（页键+阶段即血缘），不靠查询时临时拼

用法:
  uv run python scripts/artifact.py query --work-id <id> [--stage <stage>] [--page <page>] [--format json|table]
  uv run python scripts/artifact.py query --all [--stage <stage>] [--page <page>] [--format json|table]
  uv run python scripts/artifact.py invalidate --work-id <id> --page <page>
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.paths import ROOT
from amta.stores.artifact_cache import invalidate_cache_for_page
from amta.stores.artifact_store import JSON_STAGES, ArtifactStore, fingerprint_of

# 图片类阶段（不经 ArtifactStore，直接按文件名找）
IMAGE_STAGES = ("final", "clean", "crops")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

# 所有已知阶段（JSON + 图片）
ALL_STAGES = JSON_STAGES + IMAGE_STAGES


# ---------------------------------------------------------------------------
# 结构化产物信息
# ---------------------------------------------------------------------------

@dataclass
class ArtifactInfo:
    """单个产物的结构化描述。"""
    work_id: str
    stage: str
    page: str
    path: str
    type: str          # json / image
    size: int          # bytes
    mtime: str         # ISO 8601
    fingerprint: str | None  # .fingerprint 文件内容（前 16 位），无则 None


def _read_fingerprint(path: Path) -> str | None:
    """读取产物旁边的 .fingerprint 文件，返回前 16 位（足够识别）。"""
    fp = fingerprint_of(path)
    if fp.exists():
        try:
            content = fp.read_text(encoding="utf-8").strip()
            return content[:16] if content else None
        except OSError:
            return None
    return None


def _file_meta(path: Path) -> tuple[int, str]:
    """获取文件大小和修改时间（ISO 8601）。"""
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    return stat.st_size, mtime


def _page_from_filename(filename: str, stage: str) -> str:
    """从文件名推断 page 键。
    - 新布局：page_11.json → page_11
    - 旧平铺：page_11_typeset.json → page_11
    - 图片：page_11_final.png → page_11 / page_11.png → page_11
    """
    stem = Path(filename).stem  # 去扩展名
    # 旧平铺：page_11_typeset
    if stem.endswith(f"_{stage}"):
        return stem[: -len(f"_{stage}")]
    # 新布局 / 图片：page_11
    return stem


# ---------------------------------------------------------------------------
# 核心查询原语
# ---------------------------------------------------------------------------

def query_artifacts(
    work_id: str | None = None,
    all_workspaces: bool = False,
    stage: str | None = None,
    page: str | None = None,
) -> list[ArtifactInfo]:
    """统一查询原语：按 work-id + stage + page 过滤，返回结构化产物列表。

    参数：
        work_id: 工作区 ID（与 all_workspaces 二选一）
        all_workspaces: 全局搜索所有工作区
        stage: 阶段过滤（可选，不填=所有阶段）
        page: 页过滤（可选，不填=所有页）

    返回：
        按 work_id → stage → page 排序的 ArtifactInfo 列表
    """
    if not work_id and not all_workspaces:
        raise ValueError("必须指定 --work-id 或 --all-workspaces")

    # 确定要查询的阶段列表
    stages = [stage] if stage else list(ALL_STAGES)

    # 确定要查询的工作区列表
    if all_workspaces:
        work_ids = _discover_workspaces()
    else:
        work_ids = [work_id]  # type: ignore[list-item]

    results: list[ArtifactInfo] = []
    for wid in work_ids:
        results.extend(_query_workspace(wid, stages, page))

    # 排序：work_id → stage → page
    results.sort(key=lambda a: (a.work_id, a.stage, _page_sort_key(a.page)))
    return results


def _discover_workspaces() -> list[str]:
    """发现 workspace/ 下所有有 artifacts/ 子目录的工作区。"""
    workspace_root = ROOT / "workspace"
    if not workspace_root.is_dir():
        return []
    work_ids = []
    for d in sorted(workspace_root.iterdir()):
        if d.is_dir() and (d / "artifacts").is_dir():
            work_ids.append(d.name)
    return work_ids


def _page_sort_key(page: str) -> tuple[int, str]:
    """page_N → (N, page) 排序键；非 page_N 命名垫底。"""
    if page.startswith("page_") and page[5:].isdigit():
        return (int(page[5:]), page)
    return (10**9, page)


def _query_workspace(
    work_id: str,
    stages: list[str],
    page_filter: str | None,
) -> list[ArtifactInfo]:
    """查询单个工作区的产物。"""
    artifacts_dir = ROOT / "workspace" / work_id / "artifacts"
    if not artifacts_dir.is_dir():
        return []

    results: list[ArtifactInfo] = []
    store = ArtifactStore(artifacts_dir)

    for stage in stages:
        if stage in JSON_STAGES:
            results.extend(_collect_json_stage(work_id, store, stage, page_filter))
        elif stage in IMAGE_STAGES:
            results.extend(_collect_image_stage(work_id, artifacts_dir, stage, page_filter))
        # 未知阶段静默跳过（可拓展：未来加新阶段只需加进 STAGES 元组）

    return results


def _collect_json_stage(
    work_id: str,
    store: ArtifactStore,
    stage: str,
    page_filter: str | None,
) -> list[ArtifactInfo]:
    """收集一个 JSON 阶段的所有产物。"""
    results = []
    pages = store.pages(stage)
    for page in pages:
        if page_filter and page != page_filter:
            continue
        path = store.resolve(stage, page)
        if path is None or not path.exists():
            continue
        size, mtime = _file_meta(path)
        results.append(ArtifactInfo(
            work_id=work_id,
            stage=stage,
            page=page,
            path=str(path.relative_to(ROOT)),
            type="json",
            size=size,
            mtime=mtime,
            fingerprint=_read_fingerprint(path),
        ))
    return results


def _collect_image_stage(
    work_id: str,
    artifacts_dir: Path,
    stage: str,
    page_filter: str | None,
) -> list[ArtifactInfo]:
    """收集一个图片阶段的所有产物（final / clean / crops）。"""
    stage_dir = artifacts_dir / stage
    if not stage_dir.is_dir():
        return []

    results = []
    for ext in IMAGE_EXTENSIONS:
        for path in sorted(stage_dir.glob(f"*{ext}")):
            if not path.is_file():
                continue
            page = _page_from_filename(path.name, stage)
            if page_filter and page != page_filter:
                continue
            size, mtime = _file_meta(path)
            results.append(ArtifactInfo(
                work_id=work_id,
                stage=stage,
                page=page,
                path=str(path.relative_to(ROOT)),
                type="image",
                size=size,
                mtime=mtime,
                fingerprint=_read_fingerprint(path),
            ))
    return results


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def format_output(artifacts: list[ArtifactInfo], fmt: str) -> str:
    """格式化输出。"""
    if fmt == "json":
        return json.dumps([asdict(a) for a in artifacts], ensure_ascii=False, indent=2)
    elif fmt == "table":
        if not artifacts:
            return "(no artifacts)"
        # 表头
        lines = [f"{'work_id':<30} {'stage':<14} {'page':<12} {'type':<6} {'size':>8} {'mtime':<20} {'fp':<6}"]
        lines.append("-" * 100)
        for a in artifacts:
            size_str = f"{a.size:,}" if a.size < 1024 * 1024 else f"{a.size / 1024 / 1024:.1f}M"
            fp_str = a.fingerprint[:6] if a.fingerprint else "-"
            lines.append(f"{a.work_id:<30} {a.stage:<14} {a.page:<12} {a.type:<6} {size_str:>8} {a.mtime:<20} {fp_str:<6}")
        return "\n".join(lines)
    else:
        raise ValueError(f"unknown format: {fmt}")


# ---------------------------------------------------------------------------
# CLI 命令
# ---------------------------------------------------------------------------

def cmd_query(args: argparse.Namespace) -> int:
    """query — 统一查询原语。"""
    try:
        artifacts = query_artifacts(
            work_id=args.work_id,
            all_workspaces=args.all,
            stage=args.stage,
            page=args.page,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    output = format_output(artifacts, args.format)
    print(output)

    if not artifacts:
        return 1
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    """find — 兼容旧接口：按 stage + page 在指定 artifacts-dir 找单个产物。"""
    artifacts_dir = Path(args.artifacts_dir)
    stage = args.stage
    page = args.page if args.page.startswith("page_") else f"page_{args.page}"

    # 尝试新目录结构：<stage>/<page>.<ext>
    stage_dir = artifacts_dir / stage
    candidates = []
    if stage_dir.is_dir():
        for f in stage_dir.iterdir():
            if f.stem == page or f.stem.startswith(page + "_"):
                candidates.append(f)

    # 回退旧平铺结构：<page>_<stage>.<ext>
    if not candidates:
        for f in artifacts_dir.iterdir():
            if f.is_file() and f.name.startswith(page + "_" + stage):
                candidates.append(f)

    if not candidates:
        print(f"ERROR: artifact not found for stage={stage} page={page} in {artifacts_dir}",
              file=sys.stderr)
        return 1

    for f in sorted(candidates):
        print(str(f))
    return 0


def cmd_invalidate(args: argparse.Namespace) -> int:
    """invalidate — 失效某页缓存（删 .fingerprint，不删产物）。"""
    if not args.work_id:
        print("ERROR: --work-id is required for invalidate", file=sys.stderr)
        return 2
    artifacts_dir = ROOT / "workspace" / args.work_id / "artifacts"
    page = args.page if args.page.startswith("page_") else f"page_{args.page}"
    count = invalidate_cache_for_page(artifacts_dir, page)
    print(f"Invalidated {count} fingerprint(s) for work_id={args.work_id} page={page}")
    return 0


# ---------------------------------------------------------------------------
# CLI 定义
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="amta 统一产物管理 CLI（深接口：一个 query 原语 + 可选参数）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # query — 统一查询原语
    p_query = sub.add_parser("query", help="查询产物（一个原语，参数组合出所有场景）")
    p_query.add_argument("--work-id", default=None,
                         help="工作区 ID（如 ab-no-prefix-b），与 --all 二选一")
    p_query.add_argument("--all", action="store_true",
                         help="全局搜索所有工作区")
    p_query.add_argument("--stage", default=None,
                         help=f"阶段过滤（可选）：{'/'.join(ALL_STAGES)}")
    p_query.add_argument("--page", default=None,
                         help="页过滤（可选）：如 page_11 或 11")
    p_query.add_argument("--format", choices=["json", "table"], default="json",
                         help="输出格式（默认 json，AI 易解析）")
    p_query.set_defaults(func=cmd_query)

    # find — 兼容旧接口（按 stage + page 在指定 artifacts-dir 找单个产物）
    p_find = sub.add_parser("find", help="查找单个产物（兼容旧接口）")
    p_find.add_argument("--stage", required=True,
                        help=f"阶段：{'/'.join(ALL_STAGES)}")
    p_find.add_argument("--page", required=True,
                        help="页键（如 page_11 或 11）")
    p_find.add_argument("--artifacts-dir", required=True,
                        help="artifacts 目录路径")
    p_find.set_defaults(func=cmd_find)

    # invalidate — 写操作（独立命令，职责分离）
    p_inv = sub.add_parser("invalidate", help="失效某页缓存（删 .fingerprint）")
    p_inv.add_argument("--work-id", required=True, help="工作区 ID")
    p_inv.add_argument("--page", required=True, help="页键（如 page_11 或 11）")
    p_inv.set_defaults(func=cmd_invalidate)

    args = parser.parse_args()

    # page 归一化：11 → page_11
    if hasattr(args, "page") and args.page and not args.page.startswith("page_") and args.page.isdigit():
        args.page = f"page_{args.page}"

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
