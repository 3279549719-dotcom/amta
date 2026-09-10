"""pipeline_log 编排器测试(ADR-018)。

2026-09-10 改造：原先本文件还测 01_detect / 02_ocr / 00_run_all 的编排行为，
但那 6 个数字前缀脚本已删除（scripts/run_pipeline.py 取代）→ 4 条测试变永久红灯，
测的是已经不存在的世界。已删除，归属迁移登记如下：
- canon 命名/字段契约                                  → tests/test_canon_schema.py
- 合并 translation / 跳过已有产物 / failed_step 锚点    → tests/test_orchestrator_smoke.py
保留下来的是真正在跑的 pipeline_log 行为。
"""
import json

# ---------- pipeline_log ----------

def test_pipeline_log_span_and_fail(tmp_path):
    from amta.common.pipeline_log import PipelineLog
    log = PipelineLog(tmp_path / "pipeline_log.json")
    rid = log.start_run("pages 1-1")
    log.add_span(rid, step="01_detect", page="page_0", status="ok",
                 input="1.jpg", output="page_0_detection.json", duration_s=1.5)
    log.fail_run(rid, step="02_ocr", page="page_0", reason="no valid bbox")
    doc = json.loads((tmp_path / "pipeline_log.json").read_text(encoding="utf-8"))
    run = doc["runs"][0]
    assert run["git_head"]  # 记录了代码版本
    assert run["steps"][0]["status"] == "ok"
    assert run["failed_step"]["reason"] == "no valid bbox"


def test_pipeline_log_skip_append(tmp_path):
    from amta.common.pipeline_log import PipelineLog
    log = PipelineLog(tmp_path / "pl.json")
    r1 = log.start_run("a")
    r2 = log.start_run("b")
    log.add_span(r1, step="s", page="p", status="skipped")
    log.add_span(r2, step="s", page="p", status="ok")
    assert len(log.last_runs(5)) == 2  # append 不覆盖
