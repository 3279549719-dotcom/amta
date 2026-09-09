"""gc — 记忆地产自动清理（腐坏不再等人工点出来）。

三件自动维护：
  1. archive_today  把 today-YYYY-MM-DD.md（未归档）追加进 recent.md 头部并标 .done；
     过旧（>14 天）的 .done 归档进 archive.md 防止 recent 无限膨胀。
  2. refresh_now    把 recent.md 最新一条摘要写入 now.md（压缩恢复现场用）；
     若 now.md 为空则从 recent 表取。
  3. prune_tmp      清空 .remember/tmp 与项目 output 下的一次性临时目录（.pytest_cache 等），
     防止 pytest/调试残留堆积。

原则：幂等（重复跑无碍）、只动 .remember 与临时目录、绝不碰 docs/ 权威源。
所有写操作显式 UTF-8（L30，Windows 编码坑）。用法见 scripts/memory.py gc --help。
"""
from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path

ARCHIVE_DAYS = 14  # .done 归档进 archive.md 的年龄阈值
TODAY_RE = re.compile(r"today-(\d{4}-\d{2}-\d{2})(?:\.done)?\.md$")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def archive_today(root: Path, today: datetime.date, dry: bool) -> list[str]:
    """未归档 today-*.md → 标 .done；超龄 .done → archive.md。返回操作日志。"""
    log: list[str] = []
    r = root / ".remember"
    if not r.exists():
        return log
    for f in sorted(r.glob("today-*.md")):
        m = TODAY_RE.match(f.name)
        if not m:
            continue
        fdate = datetime.date.fromisoformat(m.group(1))
        if f.name.endswith(".done.md"):
            # 超龄归档进 archive.md
            if (today - fdate).days > ARCHIVE_DAYS:
                body = _read(f)
                arch = r / "archive.md"
                if dry:
                    log.append(f"[dry] archive {f.name} -> archive.md")
                else:
                    _write(arch, _read(arch) + body + "\n")
                    f.unlink()
                    log.append(f"archived {f.name} ({len(body)} chars)")
            continue
        # 未归档 → 标 .done（追加到 recent 头部在 refresh_now 里做；这里直接归档到 recent）
        body = _read(f)
        rec = r / "recent.md"
        if dry:
            log.append(f"[dry] finalize {f.name}")
        else:
            rec_text = _read(rec)
            stamp = f"\n## {m.group(1)}\n{body.strip()}"
            _write(rec, rec_text.rstrip() + "\n" + stamp + "\n")
            f.rename(f.with_name(f.name.replace(".md", ".done.md")))
            log.append(f"finalized {f.name} -> recent.md ({len(body)} chars)")
    return log


def refresh_now(root: Path, dry: bool) -> list[str]:
    """now.md = 最近摘要（压缩恢复现场）。空则从 recent 表取。"""
    log: list[str] = []
    r = root / ".remember"
    now = r / "now.md"
    rec = r / "recent.md"
    if not rec.exists():
        return log
    rec_text = _read(rec)
    # 取「最新」一个日期节（now.md = 压缩恢复现场，要最新状态）
    secs = re.findall(r"## (\d{4}-\d{2}-\d{2})\n(.+?)(?=\n## |\Z)", rec_text, re.DOTALL)
    if not secs:
        return log
    stamp, body = secs[-1]
    summary = f"## 最近 {stamp}\n{body.strip()}\n"
    if dry:
        log.append("[dry] refresh now.md")
        return log
    if _read(now).strip() != summary.strip():
        _write(now, summary)
        log.append(f"refreshed now.md ({len(summary)} chars)")
    else:
        log.append("now.md 已最新")
    return log


def prune_tmp(root: Path, dry: bool) -> list[str]:
    """清空 .remember/tmp 与 output 下的一次性临时目录。返回操作日志。"""
    log: list[str] = []
    targets = [root / ".remember" / "tmp"]
    out = root / "output"
    if out.exists():
        for d in ("logs", ".pytest-basetemp"):
            targets.append(out / d)
        for p in out.iterdir():
            if p.name.startswith("tmp"):
                targets.append(p)
    for t in targets:
        if not t.exists():
            continue
        if dry:
            log.append(f"[dry] prune {t.relative_to(root)}")
            continue
        try:
            # 只清内容不删根目录（.pytest-basetemp 可能被 pytest 占用时静默跳过）
            n = 0
            for child in t.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                n += 1
            log.append(f"pruned {t.relative_to(root)} ({n} items)")
        except (OSError, PermissionError) as e:
            log.append(f"skip {t.relative_to(root)} (locked: {type(e).__name__})")
    return log


def main(argv: list[str] | None = None) -> int:
    """CLI 入口（由 scripts/memory.py gc 复用）。root 取 cwd（与调用处一致）。"""
    import argparse

    ap = argparse.ArgumentParser(description="记忆地产自动清理")
    ap.add_argument("--dry-run", action="store_true", help="只报告不改")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD（默认为今天，测试可注入）")
    a = ap.parse_args(argv)
    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()
    root = Path.cwd()
    print(f"== memory_gc {('DRY-RUN' if a.dry_run else 'run')} @ {today} ==")
    for label, fn in (
        ("archive_today", lambda: archive_today(root, today, a.dry_run)),
        ("refresh_now", lambda: refresh_now(root, a.dry_run)),
        ("prune_tmp", lambda: prune_tmp(root, a.dry_run)),
    ):
        for line in fn():
            print(f"  [{label}] {line}")
    return 0
