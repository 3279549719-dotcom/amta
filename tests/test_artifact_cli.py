"""artifact CLI 测试 — 统一产物管理命令行工具。

覆盖 find/list/status/invalidate 四个子命令。
TDD: 每个测试先失败，再写最小实现。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "artifact.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """运行 artifact CLI，返回 CompletedProcess。"""
    cmd = [sys.executable, str(SCRIPT)] + args
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def _w_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _w_png(path: Path) -> None:
    """写一个最小的 1x1 PNG 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    # 1x1 红色 PNG 的最小字节
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108020000"
        "00907753de0000000c4944415408d763f8cfc00000000300015c35"
        "c3870000000049454e44ae426082"
    )
    path.write_bytes(png_bytes)


# ---- find 命令 ----

class TestFind:
    """artifact find — 定位单个产物（JSON + 图片）。"""

    def test_find_final_image(self, tmp_path):
        """find --stage final --page 11 能找到 final 图片（page_11_final.png 命名）。"""
        art = tmp_path / "artifacts"
        _w_png(art / "final" / "page_11_final.png")

        result = _run(["find", "--stage", "final", "--page", "11",
                       "--artifacts-dir", str(art)])

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "page_11_final.png" in result.stdout
        assert str(art / "final" / "page_11_final.png") in result.stdout

    def test_find_detection_json(self, tmp_path):
        """find --stage detection --page 11 能找到 detection JSON。"""
        art = tmp_path / "artifacts"
        _w_json(art / "detection" / "page_11.json", {"n_boxes": 5})

        result = _run(["find", "--stage", "detection", "--page", "11",
                       "--artifacts-dir", str(art)])

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "page_11.json" in result.stdout

    def test_find_legacy_flat_json(self, tmp_path):
        """find 能回退到旧平铺命名 page_11_detection.json。"""
        art = tmp_path / "artifacts"
        _w_json(art / "page_11_detection.json", {"n_boxes": 3})

        result = _run(["find", "--stage", "detection", "--page", "11",
                       "--artifacts-dir", str(art)])

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "page_11_detection.json" in result.stdout

    def test_find_missing_returns_nonzero(self, tmp_path):
        """找不到产物时返回非零退出码。"""
        art = tmp_path / "artifacts"

        result = _run(["find", "--stage", "final", "--page", "99",
                       "--artifacts-dir", str(art)])

        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "missing" in result.stderr.lower()
