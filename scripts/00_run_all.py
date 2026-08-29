"""00_run_all 编排器 — 断点续跑 + step tracing + 全链驱动(借鉴 Metaflow resume / Prefect task 思想,零依赖,ADR-018)。

用法:
  python scripts/00_run_all.py --work-id touhou-single-wing \
      --src-dir "D:\\我的汉化\\汉化作品\\东方\\单翼停留之地" \
      --start-page 11 --end-page 11 [--with-review]

页面映射: src-dir/N.jpg → page_idx = N-1(0 基,与评测 canon 对齐)
断点:     artifacts 产物存在 → skipped(文件存在=跳过,失败修复后重跑自动续)
追溯:     state/pipeline_log.json 每步 span;失败写 failed_step 锚点 + reason
阶段:     01_detect → 02_ocr → 03_translate → [③ 语义评审 → 自动修复](--with-review)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.paths import read_json, write_json  # noqa: E402
from amta.pipeline_log import PipelineLog  # noqa: E402
from amta.workstate import ensure_workspace  # noqa: E402

HERE = Path(__file__).resolve().parent
PY = sys.executable


def _run_cli(args: list[str]) -> None:
    r = subprocess.run([PY, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"cli failed: {args[0]}\n{(r.stdout or '')[-800:]}\n{(r.stderr or '')[-800:]}")


def _out(ws_root: Path, name: str) -> Path:
    return ws_root / "artifacts" / name


def _step(log: PipelineLog, run_id: str, step: str, page: str, *,
          inp: Path, out: Path, cmd: list[str]) -> None:
    """执行单个工位步骤（ADR-018 统一抽象）：产物存在→skip；否则 timed 运行并记 span。"""
    if out.exists():
        log.add_span(run_id, step=step, page=page, status="skipped",
                     input=str(inp), output=str(out))
        print(f"[00_run_all] {page} {step} skipped (exists)")
        return
    t0 = time.time()
    _run_cli(cmd)
    log.add_span(run_id, step=step, page=page, status="ok",
                 input=str(inp), output=str(out),
                 duration_s=time.time() - t0)



def _refresh_merged_translation(ws_root: Path) -> None:
    """刷新 artifacts/translation.json：合并所有 page_*_translation.json（get_context 前页回溯读取）。

    get_context（translate.py）只读合并单文件，故每完成一页都要并进去。
    """
    import re as _re

    artifacts = ws_root / "artifacts"
    merged: dict[str, str] = {}
    for p in sorted(artifacts.glob("page_*_translation.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for rid, t in (doc.get("translations") or {}).items():
            if _re.match(r"page_\d+_", str(rid)):
                merged[str(rid)] = t
    if merged:
        write_json(artifacts / "translation.json",
                   {"work_id": ws_root.name, "translations": merged,
                    "residue": [], "glossary_violations": []})


def run(work_id: str, src_dir: Path, start_page: int, end_page: int, *,
        with_review: bool = False, ocr_engine: str = "auto",
        with_inpaint: bool = False, with_typeset: bool = False,
        with_judge: bool = False) -> int:
    ws_root = ensure_workspace(work_id)
    state_dir = ws_root / "state"
    log = PipelineLog(state_dir / "pipeline_log.json")
    run_id = log.start_run(trigger=f"pages {start_page}-{end_page}{' +review' if with_review else ''}")
    failed = None

    for n in range(start_page, end_page + 1):
        page_idx = n - 1
        raw = src_dir / f"{n}.jpg"
        if not raw.exists():
            print(f"[00_run_all] WARN {raw} not found, skip")
            continue
        page = f"page_{page_idx}"
        det_path = _out(ws_root, f"{page}_detection.json")
        canon_path = _out(ws_root, f"{page}_canon.json")
        trans_path = _out(ws_root, f"{page}_translation.json")
        trace_path = _out(ws_root, f"{page}_trace.json")
        crops_dir = _out(ws_root, "crops")
        sem_path = _out(ws_root, f"{page}_semantic.json")

        try:
            # ---- 01 detect ----
            _step(log, run_id, "01_detect", page, inp=raw, out=det_path,
                  cmd=[str(HERE / "01_detect.py"), "--work-id", work_id,
                       "--raw", str(raw), "--out", str(det_path)])

            # ---- 02 ocr ----
            _step(log, run_id, "02_ocr", page, inp=det_path, out=canon_path,
                  cmd=[str(HERE / "02_ocr.py"), "--work-id", work_id,
                       "--det", str(det_path), "--raw", str(raw),
                       "--out", str(canon_path), "--page-idx", str(page_idx),
                       "--engine", ocr_engine])

            # ---- 03 translate ----
            _step(log, run_id, "03_translate", page, inp=canon_path, out=trans_path,
                  cmd=[str(HERE / "03_translate.py"), "--canon", str(canon_path),
                       "--out", str(trans_path), "--work-id", work_id,
                       "--state-dir", str(state_dir), "--trace", str(trace_path)])
            # 每完成一页刷新合并 translation.json（get_context 前页回溯读取）
            _refresh_merged_translation(ws_root)

            # ---- ③ semantic review + auto-repair (optional) ----
            if with_review:
                _step(log, run_id, "semantic_check", page, inp=trans_path, out=sem_path,
                      cmd=[str(HERE / "translate_semantic_check.py"),
                           "--canon", str(canon_path), "--trans", str(trans_path),
                           "--crops", str(crops_dir), "--out", str(sem_path)])
                # 自动修复:有 FAILED 才跑
                sem = read_json(sem_path) if sem_path.exists() else {}
                if sem.get("failed"):
                    t0 = time.time()
                    _run_cli([str(HERE / "repair_failed.py"),
                              "--canon", str(canon_path), "--trans", str(trans_path),
                              "--semantic", str(sem_path), "--crops", str(crops_dir),
                              "--state-dir", str(state_dir),
                              "--out-review", str(_out(ws_root, f"{page}_needs_review.json"))])
                    log.add_span(run_id, step="auto_repair", page=page, status="ok",
                                 input=str(sem_path), output=str(trans_path),
                                 duration_s=time.time() - t0)

            # ---- ④ AI judge (Stage 1 半自主循环：AI 决策 repair/ticket/pass) ----
            if with_judge:
                # judge 依赖 semantic_check；没开 with_review 时这里补跑
                if not sem_path.exists():
                    _step(log, run_id, "semantic_check", page, inp=trans_path, out=sem_path,
                          cmd=[str(HERE / "translate_semantic_check.py"),
                               "--canon", str(canon_path), "--trans", str(trans_path),
                               "--crops", str(crops_dir), "--out", str(sem_path)])
                judge_path = _out(ws_root, f"{page}_judge.json")
                _step(log, run_id, "ai_judge", page, inp=sem_path, out=judge_path,
                      cmd=[str(HERE / "06_page_judge.py"),
                           "--canon", str(canon_path), "--trans", str(trans_path),
                           "--sem", str(sem_path), "--out", str(judge_path)])
                # 按 judge 决策执行
                judge_doc = read_json(judge_path) if judge_path.exists() else {}
                decisions = judge_doc.get("decisions", [])
                repair_ids = [d["args"]["region_id"] for d in decisions
                              if d["tool"] == "repair_region" and d.get("args", {}).get("region_id")]
                ticket_decisions = [d["args"] for d in decisions
                                    if d["tool"] == "open_ticket" and d.get("args", {}).get("region_id")]
                # repair: 只修 semantic 已标记 fail 的（repair_failed 限制）
                sem = read_json(sem_path) if sem_path.exists() else {}
                sem_failed_ids = {f["region_id"] for f in sem.get("failed", [])}
                repairable = [rid for rid in repair_ids if rid in sem_failed_ids]
                unrepairable = [rid for rid in repair_ids if rid not in sem_failed_ids]
                if repairable:
                    t0 = time.time()
                    _run_cli([str(HERE / "repair_failed.py"),
                              "--canon", str(canon_path), "--trans", str(trans_path),
                              "--semantic", str(sem_path), "--crops", str(crops_dir),
                              "--state-dir", str(state_dir),
                              "--only", ",".join(repairable),
                              "--out-review", str(_out(ws_root, f"{page}_needs_review.json"))])
                    log.add_span(run_id, step="judge_repair", page=page, status="ok",
                                 input=",".join(repairable), output=str(trans_path),
                                 duration_s=time.time() - t0)
                    print(f"[00_run_all] {page} judge_repair: {repairable}")
                # ticket: judge 开的工单 + semantic 未标记但 judge 建议修的
                if ticket_decisions or unrepairable:
                    from amta.tickets import TicketStore
                    ts = TicketStore(state_dir / "tickets.json")
                    for t in ticket_decisions:
                        ts.create(work_id=work_id, region_id=t["region_id"],
                                  reason=t.get("reason", ""), auto_rounds=0,
                                  kind=t.get("kind", "unknown"))
                    for rid in unrepairable:
                        ts.create(work_id=work_id, region_id=rid,
                                  reason="judge 建议修复但 semantic 未标记 fail，需人工确认",
                                  auto_rounds=0, kind="hard_case")
                    print(f"[00_run_all] {page} judge_tickets: {[t['region_id'] for t in ticket_decisions] + unrepairable}")

            # ---- 04 inpaint / 05 typeset (optional, Stage 4/5) ----
            if with_inpaint:
                inpaint_path = _out(ws_root, f"{page}_inpaint.json")
                _step(log, run_id, "04_inpaint", page, inp=det_path, out=inpaint_path,
                      cmd=[str(HERE / "04_inpaint.py"), "--work-id", work_id,
                           "--det", str(det_path), "--raw", str(raw),
                           "--out", str(inpaint_path),
                           "--clean-dir", str(_out(ws_root, "clean"))])
            if with_typeset:
                typeset_path = _out(ws_root, f"{page}_typeset.json")
                clean_img = _out(ws_root, "clean") / f"{page}_clean.png"
                if not clean_img.exists():
                    print(f"[00_run_all] WARN {page} 05_typeset skipped (no clean image; need --with-inpaint)")
                else:
                    _step(log, run_id, "05_typeset", page, inp=clean_img, out=typeset_path,
                          cmd=[str(HERE / "05_typeset.py"), "--work-id", work_id,
                               "--canon", str(canon_path), "--trans", str(trans_path),
                               "--det", str(det_path), "--clean", str(clean_img),
                               "--out", str(typeset_path),
                               "--final", str(_out(ws_root, "final") / f"{page}_final.png")])

        except Exception as e:  # noqa: BLE001
            log.fail_run(run_id, step="pipeline", page=page, reason=str(e)[:300])
            failed = (page, str(e)[:200])
            break

    if failed is None:
        log.end_run(run_id)
        print(f"[00_run_all] DONE run={run_id} pages {start_page}-{end_page}")
        return 0
    print(f"[00_run_all] FAILED run={run_id} at {failed[0]}: {failed[1]}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="00_run_all 编排器")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--src-dir", required=True, type=Path, help="源图目录(N.jpg)")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--end-page", type=int, required=True)
    ap.add_argument("--with-review", action="store_true", help="semantic review")
    ap.add_argument("--with-inpaint", action="store_true", help="04_inpaint station")
    ap.add_argument("--with-typeset", action="store_true", help="05_typeset station")
    ap.add_argument("--with-judge", action="store_true", help="Stage 1: AI judge 自动决策 repair/ticket/pass")
    ap.add_argument("--ocr-engine", default="auto",
                    choices=["auto", "baberu", "local", "dashscope"],
                    help="OCR 引擎(auto=baberu fast path+回退; 默认 auto)")
    a = ap.parse_args()
    return run(a.work_id, a.src_dir, a.start_page, a.end_page,
               with_review=a.with_review, ocr_engine=a.ocr_engine,
               with_inpaint=a.with_inpaint, with_typeset=a.with_typeset,
               with_judge=a.with_judge)


if __name__ == "__main__":
    raise SystemExit(main())
