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
    """运行 artifact CLI，返回 CompletedProcess。

    **必须显式 `encoding="utf-8"`**（2026-09-11 实测）：
    只写 `text=True` 时 subprocess 用宿主 locale（本机 cp936/gbk）解码，
    而 artifact.py 的错误信息是中文 —— 解码在 reader thread 内抛
    UnicodeDecodeError，被线程吞掉，于是 `result.stderr` 静默变成 **None**，
    断言 `result.stderr.lower()` 炸成 AttributeError: 'NoneType' object
    has no attribute 'lower'。

    这正是本项目 2026-09-10 修过的同一个坑（`state.py bootstrap` 崩溃），
    修法一致：收口到 UTF-8，不依赖宿主 locale。见 `amta.common.encoding`。
    """
    cmd = [sys.executable, str(SCRIPT)] + args
    return subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=cwd,
    )


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


# ---- query 命令（深接口原语） ----


class TestReadFingerprint:
    """`.fingerprint` 解析必须是**单行短串**（2026-09-11 实测修）。

    真实 `.fingerprint` 文件是 **JSON**：
        {"stage":"ocr","page":"page_16","schema_version":"1.0",
         "generated_at":"...","input_hash":"83ad83...","code_hash":"...","config_hash":"..."}
    旧实现 `content[:16]` 切出的是 `'{\\n  "stage": "o'` —— 含换行，把
    `--format table` 整张表冲烂；而且**所有产物**的这 16 个字符完全相同（零识别价值）。

    直接测函数而不是测 CLI：`query` 扫的是仓库自己的 `workspace/`（见
    `_discover_workspaces`），不读任意 cwd，用 tmp_path 造 CLI 场景是假场景。
    """

    @staticmethod
    def _fn():
        """从 scripts/artifact.py 导入 _read_fingerprint（脚本内的私有函数）。

        必须先把模块注册进 sys.modules —— 否则 `@dataclass` 解析注解时
        `sys.modules[cls.__module__]` 取到 None，抛
        `AttributeError: 'NoneType' object has no attribute '__dict__'`（实测）。
        """
        import importlib.util
        import sys

        name = "artifact_cli_mod_for_test"
        if name in sys.modules:
            return sys.modules[name]._read_fingerprint
        spec = importlib.util.spec_from_file_location(name, SCRIPT)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod          # ← dataclass 需要它
        spec.loader.exec_module(mod)
        return mod._read_fingerprint

    def _artifact_with_fp(self, tmp_path: Path, payload: dict) -> Path:
        d = tmp_path / "canon"
        d.mkdir(parents=True, exist_ok=True)
        art = d / "page_11.json"
        art.write_text("{}", encoding="utf-8")
        (d / "page_11.json.fingerprint").write_text(
            json.dumps(payload), encoding="utf-8",
        )
        return art

    def test_returns_input_hash_prefix(self, tmp_path):
        """应从 JSON 取 input_hash 前缀，而不是切 JSON 的前 16 个字符。"""
        art = self._artifact_with_fp(tmp_path, {
            "stage": "ocr", "page": "page_11", "schema_version": "1.0",
            "input_hash": "83ad8360cdb06a05bb72f8fbdcb24702cc",
        })
        assert self._fn()(art) == "83ad8360cdb06a05"

    def test_no_newlines_in_result(self, tmp_path):
        """结果绝不能含换行（含换行 = 表格被冲烂）。"""
        art = self._artifact_with_fp(tmp_path, {
            "stage": "ocr", "input_hash": "a" * 64,
        })
        got = self._fn()(art)
        assert got is not None
        assert "\n" not in got and "\r" not in got, f"fp 含换行：{got!r}"

    def test_different_inputs_give_different_fp(self, tmp_path):
        """两个不同产物的 fp 必须不同——否则这一列没有识别价值。"""
        fn = self._fn()
        a = self._artifact_with_fp(tmp_path / "a", {"input_hash": "a" * 64})
        b = self._artifact_with_fp(tmp_path / "b", {"input_hash": "b" * 64})
        assert fn(a) != fn(b)

    def test_falls_back_to_stage_version(self, tmp_path):
        """没有 hash 字段时退化为 stage-schema 标签，仍是单行短串。"""
        art = self._artifact_with_fp(tmp_path, {
            "stage": "ocr", "schema_version": "1.0",
        })
        got = self._fn()(art)
        assert got is not None and "\n" not in got
        assert "ocr" in got

    def test_malformed_json_falls_back_to_flattened_text(self, tmp_path):
        """非 JSON 内容也要压成单行（不可崩、不可含换行）。"""
        d = tmp_path / "canon"
        d.mkdir(parents=True, exist_ok=True)
        art = d / "page_11.json"
        art.write_text("{}", encoding="utf-8")
        (d / "page_11.json.fingerprint").write_text("line1\nline2\nline3", encoding="utf-8")
        got = self._fn()(art)
        assert got is not None and "\n" not in got

    def test_no_fingerprint_file_returns_none(self, tmp_path):
        """没有 .fingerprint 就返回 None（CLI 显示 '-'）。"""
        d = tmp_path / "canon"
        d.mkdir(parents=True, exist_ok=True)
        art = d / "page_11.json"
        art.write_text("{}", encoding="utf-8")
        assert self._fn()(art) is None
