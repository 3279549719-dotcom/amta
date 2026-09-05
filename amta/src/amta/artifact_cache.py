"""Artifact Cache — 基于内容哈希的增量构建模块。

核心原理（参考 Make/Snakemake/doit）：
每个 artifact 旁边存一个 .fingerprint 文件，记录：
  - 输入文件的哈希
  - 代码文件的哈希
  - 配置参数的哈希
运行前计算当前指纹，与已存指纹对比：
  - 一致 → 跳过，直接加载已有 artifact
  - 不一致 → 执行生成函数，保存新 artifact 和新指纹

使用方式：
    result = run_stage_if_needed(
        stage_name="typeset",
        page="page_11",
        input_files={"canon": canon_path, "translation": trans_path},
        code_files=["typeset_engine.py", "typeset_render.py"],
        config={"font_max": 52},
        output_path=typeset_path,
        generate_fn=lambda: run_typeset(...),
    )
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# 哈希计算
# ---------------------------------------------------------------------------

def compute_file_hash(path: Path | str) -> str:
    """计算单个文件的 sha256 哈希。"""
    path = Path(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def compute_code_hash(code_files: list[Path | str]) -> str:
    """计算多个代码文件的合并哈希（顺序无关）。"""
    hashes = sorted(compute_file_hash(f) for f in code_files if Path(f).exists())
    if not hashes:
        return "0" * 64
    combined = "|".join(hashes)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def compute_config_hash(config: dict[str, Any]) -> str:
    """计算配置字典的哈希（序列化后哈希）。"""
    if not config:
        return "0" * 64
    # sort_keys 确保顺序无关
    serialized = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_fingerprint(
    input_files: dict[str, Path | str],
    code_files: list[Path | str],
    config: dict[str, Any],
) -> dict[str, str]:
    """计算完整指纹：输入哈希 + 代码哈希 + 配置哈希。"""
    input_hashes = {
        name: compute_file_hash(path)
        for name, path in input_files.items()
        if Path(path).exists()
    }
    return {
        "input_hash": hashlib.sha256(
            "|".join(f"{k}={v}" for k, v in sorted(input_hashes.items())).encode("utf-8")
        ).hexdigest() if input_hashes else "0" * 64,
        "code_hash": compute_code_hash(code_files),
        "config_hash": compute_config_hash(config),
    }


# ---------------------------------------------------------------------------
# 指纹存储
# ---------------------------------------------------------------------------

def fingerprint_path(output_path: Path | str) -> Path:
    """返回 artifact 对应的 .fingerprint 文件路径。"""
    output_path = Path(output_path)
    return output_path.with_suffix(output_path.suffix + ".fingerprint")


def save_fingerprint(
    output_path: Path | str,
    stage: str,
    page: str,
    fingerprint: dict[str, str],
) -> Path:
    """保存指纹到 .fingerprint 文件。"""
    output_path = Path(output_path)
    fp_path = fingerprint_path(output_path)
    doc = {
        "stage": stage,
        "page": page,
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **fingerprint,
    }
    fp_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return fp_path


def load_fingerprint(output_path: Path | str) -> dict[str, Any] | None:
    """加载指纹，文件不存在返回 None。"""
    fp_path = fingerprint_path(output_path)
    if not fp_path.exists():
        return None
    try:
        return json.loads(fp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def is_fresh(
    output_path: Path | str,
    input_files: dict[str, Path | str],
    code_files: list[Path | str],
    config: dict[str, Any],
) -> bool:
    """检查 artifact 是否新鲜（输入/代码/配置都没变）。"""
    output_path = Path(output_path)
    # 输出文件不存在 → 不新鲜
    if not output_path.exists():
        return False
    # 指纹文件不存在 → 不新鲜
    saved = load_fingerprint(output_path)
    if saved is None:
        return False
    # 计算当前指纹
    current = compute_fingerprint(input_files, code_files, config)
    # 对比三个哈希
    return (
        saved.get("input_hash") == current["input_hash"]
        and saved.get("code_hash") == current["code_hash"]
        and saved.get("config_hash") == current["config_hash"]
    )


# ---------------------------------------------------------------------------
# 条件执行封装
# ---------------------------------------------------------------------------

def run_stage_if_needed(
    stage_name: str,
    page: str,
    input_files: dict[str, Path | str],
    code_files: list[Path | str],
    config: dict[str, Any],
    output_path: Path | str,
    generate_fn: Callable[[], Any],
) -> dict[str, Any]:
    """条件执行：如果 artifact 新鲜则跳过，否则执行 generate_fn 并保存指纹。

    Returns:
        {
            "cache_hit": bool,        # True=跳过，False=重新执行
            "stage": str,
            "page": str,
            "output_path": str,
        }
    """
    output_path = Path(output_path)

    # 检查是否新鲜
    if is_fresh(output_path, input_files, code_files, config):
        return {
            "cache_hit": True,
            "stage": stage_name,
            "page": page,
            "output_path": str(output_path),
        }

    # 不新鲜 → 执行生成
    generate_fn()

    # 生成后保存指纹
    fingerprint = compute_fingerprint(input_files, code_files, config)
    save_fingerprint(output_path, stage_name, page, fingerprint)

    return {
        "cache_hit": False,
        "stage": stage_name,
        "page": page,
        "output_path": str(output_path),
    }


# ---------------------------------------------------------------------------
# 批量工具
# ---------------------------------------------------------------------------

def invalidate_cache(output_path: Path | str) -> bool:
    """删除指定 artifact 的指纹文件，强制下次重跑。返回是否删除成功。"""
    fp_path = fingerprint_path(output_path)
    if fp_path.exists():
        fp_path.unlink()
        return True
    return False


def invalidate_cache_for_page(artifacts_dir: Path | str, page: str) -> int:
    """删除某页所有 artifact 的指纹，返回删除的指纹文件数。"""
    artifacts_dir = Path(artifacts_dir)
    count = 0
    for fp_path in artifacts_dir.glob(f"{page}_*.fingerprint"):
        fp_path.unlink()
        count += 1
    return count


def cache_status(artifacts_dir: Path | str) -> dict[str, int]:
    """统计缓存状态：总artifact数、有指纹的数、可统计的页数。"""
    artifacts_dir = Path(artifacts_dir)
    all_json = list(artifacts_dir.glob("*.json"))
    fingerprints = list(artifacts_dir.glob("*.fingerprint"))
    pages = set()
    for f in all_json:
        parts = f.stem.split("_")
        if len(parts) >= 2 and parts[0] == "page":
            pages.add(f"page_{parts[1]}")
    return {
        "total_artifacts": len(all_json),
        "cached_with_fingerprint": len(fingerprints),
        "pages_tracked": len(pages),
    }
