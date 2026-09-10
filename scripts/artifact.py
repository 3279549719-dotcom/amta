"""artifact — 统一产物管理 CLI（ArtifactStore + ArtifactCache 的命令行包装）。

用法:
  python scripts/artifact.py find --stage <stage> --page <page> [--artifacts-dir <dir>]
  python scripts/artifact.py list --stage <stage> [--artifacts-dir <dir>]
  python scripts/artifact.py status [--artifacts-dir <dir>]
  python scripts/artifact.py invalidate --page <page> [--artifacts-dir <dir>]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.common.paths import ROOT
from amta.stores.artifact_cache import cache_status, invalidate_cache_for_page
from amta.stores.artifact_store import JSON_STAGES, ArtifactStore

# 图片类 stage（不经 ArtifactStore，直接按文件名找）
IMAGE_STAGES = ("final", "clean", "crops")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")




def _resolve_artifacts_dir(args: argparse.Namespace) -> Path:
    """根据 --work-id 或 --artifacts-dir 解析 artifacts 目录。

    优先级：--artifacts-dir > --work-id > 默认。
    work-id 对应的目录：ROOT/workspace/<work-id>/artifacts/
    """
    if getattr(args, "artifacts_dir", None) and args.artifacts_dir != "workspace/touhou-single-wing/artifacts":
        return Path(args.artifacts_dir)
    if getattr(args, "work_id", None):
        return ROOT / "workspace" / args.work_id / "artifacts"
    return Path(args.artifacts_dir)

def _normalize_page(page: str) -> str:
    """把 '11' 转成 'page_11'，已经是 page_ 开头的原样返回。"""
    if page.startswith("page_"):
        return page
    if page.isdigit():
        return f"page_{page}"
    return page


def _resolve_image(artifacts_dir: Path, stage: str, page: str) -> Path | None:
    """定位图片类产物，支持两种命名：
    - artifacts/<stage>/<page>.<ext>        (如 page_11.png)
    - artifacts/<stage>/<page>_<stage>.<ext> (如 page_11_final.png)
    """
    stage_dir = artifacts_dir / stage
    if not stage_dir.is_dir():
        return None
    candidates = [f"{page}{ext}" for ext in IMAGE_EXTENSIONS]
    candidates += [f"{page}_{stage}{ext}" for ext in IMAGE_EXTENSIONS]
    for name in candidates:
        candidate = stage_dir / name
        if candidate.exists():
            return candidate
    return None


def cmd_find(args: argparse.Namespace) -> int:
    """find — 定位单个产物（JSON + 图片）。"""
    artifacts_dir = _resolve_artifacts_dir(args)
    stage = args.stage
    page = _normalize_page(args.page)

    if stage in JSON_STAGES:
        store = ArtifactStore(artifacts_dir)
        path = store.resolve(stage, page)
    elif stage in IMAGE_STAGES:
        path = _resolve_image(artifacts_dir, stage, page)
    else:
        print(f"ERROR: unknown stage '{stage}' (valid: {', '.join(JSON_STAGES + IMAGE_STAGES)})",
              file=sys.stderr)
        return 2

    if path is None:
        print(f"ERROR: artifact not found: stage={stage} page={page} dir={artifacts_dir}",
              file=sys.stderr)
        return 1

    print(str(path))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """list — 列出某阶段所有产物。"""
    artifacts_dir = _resolve_artifacts_dir(args)
    stage = args.stage

    if stage in JSON_STAGES:
        store = ArtifactStore(artifacts_dir)
        files = store.list_files(stage)
    elif stage in IMAGE_STAGES:
        stage_dir = artifacts_dir / stage
        files = []
        if stage_dir.is_dir():
            for ext in IMAGE_EXTENSIONS:
                files.extend(sorted(stage_dir.glob(f"*{ext}")))
    else:
        print(f"ERROR: unknown stage '{stage}'", file=sys.stderr)
        return 2

    if not files:
        print(f"(no artifacts for stage={stage})", file=sys.stderr)
        return 1

    for f in files:
        print(str(f))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """status — 缓存状态统计。"""
    artifacts_dir = _resolve_artifacts_dir(args)
    status = cache_status(artifacts_dir)
    print(f"Total artifacts:    {status['total_artifacts']}")
    print(f"Cached (fingerprint): {status['cached_with_fingerprint']}")
    print(f"Pages tracked:       {status['pages_tracked']}")
    return 0


def cmd_invalidate(args: argparse.Namespace) -> int:
    """invalidate — 失效某页缓存（删 .fingerprint，不删产物）。"""
    artifacts_dir = _resolve_artifacts_dir(args)
    page = args.page
    count = invalidate_cache_for_page(artifacts_dir, page)
    print(f"Invalidated {count} fingerprint(s) for page={page}")
    return 0


def _add_artifacts_dir(p: argparse.ArgumentParser) -> None:
    p.add_argument("--work-id", default=None,
                   help="工作区 ID（如 q11-verify-latest），自动定位到 workspace/<id>/artifacts/")
    p.add_argument("--artifacts-dir", default="workspace/touhou-single-wing/artifacts",
                   help="artifacts 目录路径（优先级高于 --work-id）")


def main() -> int:
    parser = argparse.ArgumentParser(description="amta 统一产物管理 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # find
    p_find = sub.add_parser("find", help="定位单个产物")
    p_find.add_argument("--stage", required=True, help="阶段名")
    p_find.add_argument("--page", required=True, help="页键（如 page_11）")
    _add_artifacts_dir(p_find)
    p_find.set_defaults(func=cmd_find)

    # list
    p_list = sub.add_parser("list", help="列出某阶段所有产物")
    p_list.add_argument("--stage", required=True, help="阶段名")
    _add_artifacts_dir(p_list)
    p_list.set_defaults(func=cmd_list)

    # status
    p_status = sub.add_parser("status", help="缓存状态统计")
    _add_artifacts_dir(p_status)
    p_status.set_defaults(func=cmd_status)

    # invalidate
    p_inv = sub.add_parser("invalidate", help="失效某页缓存")
    p_inv.add_argument("--page", required=True, help="页键（如 page_11）")
    _add_artifacts_dir(p_inv)
    p_inv.set_defaults(func=cmd_invalidate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
