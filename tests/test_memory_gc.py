"""memory_gc 自动清理的确定性测试：归档 today→recent、刷新 now、清临时目录。"""
from pathlib import Path

from amta.memory.gc import archive_today, prune_tmp, refresh_now


def _mk_remember(tmp_path: Path) -> Path:
    """构造一个带记忆仓的最小工程根。"""
    root = tmp_path / "proj"
    r = root / ".remember"
    r.mkdir(parents=True)
    (r / "now.md").write_text("", encoding="utf-8")
    (r / "recent.md").write_text("# Recent\n\n## 2026-08-25\n旧摘要\n", encoding="utf-8")
    (r / "today-2026-08-27.md").write_text("今天干了 X\n", encoding="utf-8")
    (r / "today-2026-08-01.done.md").write_text("远古\n", encoding="utf-8")
    (r / "archive.md").write_text("", encoding="utf-8")
    (r / "tmp").mkdir()
    (r / "tmp" / "junk.tmp").write_text("x", encoding="utf-8")
    return root


def test_archive_today_finalizes_and_appends_to_recent(tmp_path):
    import datetime
    root = _mk_remember(tmp_path)
    log = archive_today(root, datetime.date(2026, 8, 30), dry=False)
    # today-08-27 被标 .done 且内容进 recent
    assert any("finalized today-2026-08-27" in x for x in log)
    assert (root / ".remember" / "today-2026-08-27.done.md").exists()
    recent = (root / ".remember" / "recent.md").read_text(encoding="utf-8")
    assert "## 2026-08-27" in recent and "今天干了 X" in recent
    # 超龄 .done 归档进 archive.md
    assert any("archived today-2026-08-01" in x for x in log)
    assert "远古" in (root / ".remember" / "archive.md").read_text(encoding="utf-8")
    assert not (root / ".remember" / "today-2026-08-01.done.md").exists()


def test_refresh_now_uses_latest_recent_section(tmp_path):
    import datetime
    root = _mk_remember(tmp_path)
    # 先归档让 recent 有 08-27 节
    archive_today(root, datetime.date(2026, 8, 30), dry=False)
    log = refresh_now(root, dry=False)
    assert any("now.md" in x for x in log)
    now = (root / ".remember" / "now.md").read_text(encoding="utf-8")
    assert "2026-08-27" in now and "今天干了 X" in now  # 取最新，而非最旧
    assert "旧摘要" not in now


def test_refresh_now_idempotent(tmp_path):
    import datetime
    root = _mk_remember(tmp_path)
    archive_today(root, datetime.date(2026, 8, 30), dry=False)
    refresh_now(root, dry=False)
    log2 = refresh_now(root, dry=False)
    assert log2 == ["now.md 已最新"]  # 无变化


def test_prune_tmp_cleans_junk(tmp_path):
    root = _mk_remember(tmp_path)
    log = prune_tmp(root, dry=False)
    assert any("pruned" in x for x in log)
    assert not (root / ".remember" / "tmp" / "junk.tmp").exists()


def test_dry_run_makes_no_changes(tmp_path):
    import datetime
    root = _mk_remember(tmp_path)
    before = (root / ".remember" / "today-2026-08-27.md").exists()
    archive_today(root, datetime.date(2026, 8, 30), dry=True)
    refresh_now(root, dry=True)
    # dry-run 不产生 .done、不改 now
    assert not (root / ".remember" / "today-2026-08-27.done.md").exists()
    assert (root / ".remember" / "today-2026-08-27.md").exists() == before
    assert (root / ".remember" / "now.md").read_text(encoding="utf-8") == ""
