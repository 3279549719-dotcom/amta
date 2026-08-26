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
        with_review: bool = False, ocr_engine: str = "auto") -> int:
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
            if det_path.exists():
                log.add_span(run_id, step="01_detect", page=page, status="skipped",
                             input=str(raw), output=str(det_path))
                print(f"[00_run_all] {page} 01_detect skipped (exists)")
            else:
                t0 = time.time()
                _run_cli([str(HERE / "01_detect.py"), "--work-id", work_id,
                          "--raw", str(raw), "--out", str(det_path)])
                log.add_span(run_id, step="01_detect", page=page, status="ok",
                             input=str(raw), output=str(det_path),
                             duration_s=time.time() - t0)

            # ---- 02 ocr ----
            if canon_path.exists():
                log.add_span(run_id, step="02_ocr", page=page, status="skipped",
                             input=str(det_path), output=str(canon_path))
                print(f"[00_run_all] {page} 02_ocr skipped (exists)")
            else:
                t0 = time.time()
                _run_cli([str(HERE / "02_ocr.py"), "--work-id", work_id,
                          "--det", str(det_path), "--raw", str(raw),
                          "--out", str(canon_path), "--page-idx", str(page_idx),
                          "--engine", ocr_engine])
                log.add_span(run_id, step="02_ocr", page=page, status="ok",
                             input=str(det_path), output=str(canon_path),
                             duration_s=time.time() - t0)

            # ---- 03 translate ----
            if trans_path.exists():
                log.add_span(run_id, step="03_translate", page=page, status="skipped",
                             input=str(canon_path), output=str(trans_path))
                print(f"[00_run_all] {page} 03_translate skipped (exists)")
            else:
                t0 = time.time()
                _run_cli([str(HERE / "03_translate.py"), "--canon", str(canon_path),
                          "--out", str(trans_path), "--work-id", work_id,
                          "--state-dir", str(state_dir), "--trace", str(trace_path)])
                log.add_span(run_id, step="03_translate", page=page, status="ok",
                             input=str(canon_path), output=str(trans_path),
                             duration_s=time.time() - t0)
            # 每完成一页刷新合并 translation.json（get_context 前页回溯读取）
            _refresh_merged_translation(ws_root)

            # ---- ③ semantic review + auto-repair (optional) ----
            if with_review:
                if sem_path.exists():
                    log.add_span(run_id, step="semantic_check", page=page, status="skipped",
                                 input=str(trans_path), output=str(sem_path))
                    print(f"[00_run_all] {page} semantic skipped (exists)")
                else:
                    t0 = time.time()
                    _run_cli([str(HERE / "translate_semantic_check.py"),
                              "--canon", str(canon_path), "--trans", str(trans_path),
                              "--crops", str(crops_dir), "--out", str(sem_path)])
                    log.add_span(run_id, step="semantic_check", page=page, status="ok",
                                 input=str(trans_path), output=str(sem_path),
                                 duration_s=time.time() - t0)
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
    ap.add_argument("--with-review", action="store_true", help="附带 ③ 评审 + 自动修复")
    ap.add_argument("--ocr-engine", default="auto",
                    choices=["auto", "baberu", "local", "dashscope"],
                    help="OCR 引擎(auto=baberu fast path+回退; 默认 auto)")
    a = ap.parse_args()
    return run(a.work_id, a.src_dir, a.start_page, a.end_page,
               with_review=a.with_review, ocr_engine=a.ocr_engine)


if __name__ == "__main__":
    raise SystemExit(main())
