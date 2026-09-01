"""00_run_all 编排器 — 断点续跑 + step tracing + 全链驱动(ADR-018)。

用法:
  python scripts/00_run_all.py --work-id touhou-single-wing \
      --src-dir "D:\\我的汉化\\汉化作品\\东方\\单翼停留之地" \
      --start-page 1 --end-page 3

页面映射: src-dir/N.jpg → page_idx = N-1(0 基,与评测 canon 对齐)
断点:     artifacts 产物存在 → skipped(文件存在=跳过,失败修复后重跑自动续)
追溯:     state/pipeline_log.json 每步 span;失败写 failed_step 锚点 + reason
阶段:     01_detect(RT-DETR-v2) → 02_ocr(baberu) → 03_translate(v2三态) → [04_inpaint → 05_typeset]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.paths import write_json  # noqa: E402
from amta.pipeline_log import PipelineLog  # noqa: E402
from amta.workstate import ensure_workspace  # noqa: E402
from amta import artifacts  # noqa: E402

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
    """刷新 artifacts/translation.json：合并所有 page_*_translation.json（前页回溯读取）。"""
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
        with_inpaint: bool = False, with_typeset: bool = False) -> int:
    ws_root = ensure_workspace(work_id)
    state_dir = ws_root / "state"
    log = PipelineLog(state_dir / "pipeline_log.json")
    run_id = log.start_run(trigger=f"pages {start_page}-{end_page}")
    failed = None

    for n in range(start_page, end_page + 1):
        page_idx = n - 1
        raw = src_dir / f"{n}.jpg"
        if not raw.exists():
            print(f"[00_run_all] WARN {raw} not found, skip")
            continue
        page = f"page_{page_idx}"
        paths_d = artifacts.artifact_paths(ws_root / "artifacts", page)
        det_path = paths_d["detection"]
        canon_path = paths_d["canon"]
        trans_path = paths_d["translation"]

        try:
            # ---- 01 detect (RT-DETR-v2) ----
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

            # ---- 02 ocr (baberu) ----
            if canon_path.exists():
                log.add_span(run_id, step="02_ocr", page=page, status="skipped",
                             input=str(det_path), output=str(canon_path))
                print(f"[00_run_all] {page} 02_ocr skipped (exists)")
            else:
                t0 = time.time()
                _run_cli([str(HERE / "02_ocr.py"), "--work-id", work_id,
                          "--det", str(det_path), "--raw", str(raw),
                          "--out", str(canon_path), "--page-idx", str(page_idx)])
                log.add_span(run_id, step="02_ocr", page=page, status="ok",
                             input=str(det_path), output=str(canon_path),
                             duration_s=time.time() - t0)

            # ---- 03 translate (v2 三态: qwen VLM + deepseek flash LLM) ----
            if trans_path.exists():
                log.add_span(run_id, step="03_translate", page=page, status="skipped",
                             input=str(canon_path), output=str(trans_path))
                print(f"[00_run_all] {page} 03_translate skipped (exists)")
            else:
                t0 = time.time()
                _run_cli([str(HERE / "03_translate.py"), "--canon", str(canon_path),
                          "--out", str(trans_path), "--work-id", work_id,
                          "--state-dir", str(state_dir)])
                log.add_span(run_id, step="03_translate", page=page, status="ok",
                             input=str(canon_path), output=str(trans_path),
                             duration_s=time.time() - t0)
            # 每完成一页刷新合并 translation.json（前页回溯读取）
            _refresh_merged_translation(ws_root)

            # ---- 04 inpaint / 05 typeset (optional, Stage 4/5) ----
            if with_inpaint:
                inpaint_path = paths_d["inpaint"]
                if inpaint_path.exists():
                    log.add_span(run_id, step="04_inpaint", page=page, status="skipped",
                                 input=str(det_path), output=str(inpaint_path))
                    print(f"[00_run_all] {page} 04_inpaint skipped (exists)")
                else:
                    t0 = time.time()
                    _run_cli([str(HERE / "04_inpaint.py"), "--work-id", work_id,
                              "--det", str(det_path), "--raw", str(raw),
                              "--out", str(inpaint_path),
                              "--clean-dir", str(_out(ws_root, "clean"))])
                    log.add_span(run_id, step="04_inpaint", page=page, status="ok",
                                 input=str(det_path), output=str(inpaint_path),
                                 duration_s=time.time() - t0)
            if with_typeset:
                typeset_path = paths_d["typeset"]
                clean_img = _out(ws_root, "clean") / f"{page}_clean.png"
                if not clean_img.exists():
                    print(f"[00_run_all] WARN {page} 05_typeset skipped (no clean image; need --with-inpaint)")
                elif typeset_path.exists():
                    log.add_span(run_id, step="05_typeset", page=page, status="skipped",
                                 input=str(clean_img), output=str(typeset_path))
                    print(f"[00_run_all] {page} 05_typeset skipped (exists)")
                else:
                    t0 = time.time()
                    _run_cli([str(HERE / "05_typeset.py"), "--work-id", work_id,
                              "--canon", str(canon_path), "--trans", str(trans_path),
                              "--det", str(det_path), "--clean", str(clean_img),
                              "--out", str(typeset_path),
                              "--final", str(_out(ws_root, "final") / f"{page}_final.png")])
                    log.add_span(run_id, step="05_typeset", page=page, status="ok",
                                 input=str(clean_img), output=str(typeset_path),
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
    ap.add_argument("--with-inpaint", action="store_true", help="04_inpaint station")
    ap.add_argument("--with-typeset", action="store_true", help="05_typeset station")
    a = ap.parse_args()
    return run(a.work_id, a.src_dir, a.start_page, a.end_page,
               with_inpaint=a.with_inpaint, with_typeset=a.with_typeset)


if __name__ == "__main__":
    raise SystemExit(main())
