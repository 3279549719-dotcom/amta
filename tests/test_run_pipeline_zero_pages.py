"""The CLI must not report an empty run as a successful clean run."""

from types import SimpleNamespace

import scripts.run_pipeline as cli


def test_zero_page_run_fails_without_quality_clean_message(monkeypatch, capsys, tmp_path):
    from amta.common import book_store, state_manager, workstate

    monkeypatch.setattr(cli, "run_environment_check", lambda _stages: True)
    monkeypatch.setattr(
        state_manager.StateManager,
        "bootstrap",
        lambda self, env_check=False: SimpleNamespace(
            branch="test", dirty=False, git_status="", git_log=""
        ),
    )
    monkeypatch.setattr(book_store, "book_id_from_src_dir", lambda _src: "test-book")
    monkeypatch.setattr(book_store, "save_meta", lambda *_args: None)
    monkeypatch.setattr(book_store, "has_glossary", lambda _book: True)
    monkeypatch.setattr(workstate, "load_state", lambda _work: {})
    monkeypatch.setattr(workstate, "save_state", lambda *_args: None)
    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda _config: SimpleNamespace(
            run_id="empty", pages=[], failed_pages=[], stages=["detect"],
            total_duration_s=0.0,
            failed_step={"page": "?", "stage": "pipeline", "reason": "no valid pages found"},
        ),
    )
    monkeypatch.setattr(
        cli, "audit_run", lambda *_args: (_ for _ in ()).throw(AssertionError("audited zero pages"))
    )
    monkeypatch.setattr(
        "sys.argv",
        ["run_pipeline.py", "--work-id", "test-empty", "--src-dir", str(tmp_path),
         "--stages", "detect"],
    )

    assert cli.main() == 1
    output = capsys.readouterr().out
    assert "未处理任何页面" in output
    assert "quality audit: all clean" not in output
