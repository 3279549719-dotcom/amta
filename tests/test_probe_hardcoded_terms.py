"""硬编码词探针自身的回归测试。

为什么要给一个"检查脚本"写测试：本脚本存在的理由就是消灭**假阴性**，
而它第一版就有三个真 bug（自指命中、看不见未跟踪文件、BOM 造成假命中）。
一个自己会静默失效的检查，比没有检查更危险——所以它的失效方式必须被锁住。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scripts.probes import probe_hardcoded_terms as probe  # noqa: E402

TERM = "迷幻菇"


def _patterns(tmp_path: Path, text: str, *, encoding: str = "utf-8",
              raw: bytes | None = None) -> Path:
    p = tmp_path / "patterns.txt"
    if raw is not None:
        p.write_bytes(raw)
    else:
        p.write_text(text, encoding=encoding)
    return p


def _run(tmp_path: Path, pattern_file: Path, scope: str = "src/") -> tuple[int, str]:
    import io
    from contextlib import redirect_stderr, redirect_stdout
    argv = sys.argv
    sys.argv = ["probe", "--patterns-file", str(pattern_file), "--scope", scope]
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = probe.main()
    finally:
        sys.argv = argv
    return rc, out.getvalue() + err.getvalue()


def test_planted_violation_is_caught(tmp_path):
    """核心能力：植入违规必须被抓到，且必须命中到具体文件行。

    这条同时锁住 `--untracked`：`git grep` 默认看不见未跟踪的新文件，
    而"刚写出来还没 add"正是植入违规最常见的形态。
    """
    planted = ROOT / "src" / "amta" / "_probe_planted_tmp.py"
    planted.write_text(f'X = "{TERM}"\n', encoding="utf-8")
    try:
        rc, out = _run(tmp_path, _patterns(tmp_path, TERM + "\n"))
        assert rc == 1, f"违规未被抓到：\n{out}"
        assert "_probe_planted_tmp.py" in out
    finally:
        planted.unlink(missing_ok=True)


def test_reports_how_many_files_scanned(tmp_path):
    """"0 命中"必须能区分"干净"和"根本没扫"——所以要报告扫描文件数。"""
    rc, out = _run(tmp_path, _patterns(tmp_path, "絕對不存在的詞xyzzy\n"))
    assert rc == 0
    assert "待查文件" in out
    n = int(out.split("合计待查文件")[1].split("个")[0].strip())
    assert n > 50, f"扫描文件数异常偏少（{n}），检查可能没真的跑"


def test_empty_pattern_file_fails_loudly(tmp_path):
    """空模式文件 = 什么都不查 → 必须失败，不许静默报 PASS。"""
    rc, out = _run(tmp_path, _patterns(tmp_path, ""))
    assert rc == 2
    assert "空的" in out


def test_bom_only_pattern_file_is_treated_as_empty(tmp_path):
    """PowerShell `Set-Content -Encoding UTF8` 会写 BOM。

    不剥 BOM 的话会解析出 `\\ufeff` 这条模式，而它匹配每个文件的第一行，
    报出一堆**假命中**（实测 3 处）。这是"假阳性"，同样会让结论不可信。
    """
    rc, out = _run(tmp_path, _patterns(tmp_path, "", raw=b"\xef\xbb\xbf\r\n"))
    assert rc == 2, f"BOM-only 应判空并失败，实际 rc={rc}:\n{out}"
    assert "空的" in out


def test_missing_pattern_file_fails(tmp_path):
    rc, out = _run(tmp_path, tmp_path / "nope.txt")
    assert rc == 2
    assert "不存在" in out
