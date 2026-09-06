"""00_run_all 编排器 — 断点续跑 + step tracing + 全链驱动(ADR-018)。

用法:
  python scripts/00_run_all.py --work-id touhou-single-wing \
      --src-dir "D:\\我的汉化\\汉化作品\\东方\\单翼停留之地" \
      --start-page 1 --end-page 3

页面映射: src-dir/N.jpg → page_idx = N(1 基,与原图序号一致)
断点:     artifacts 产物存在 → skipped(文件存在=跳过,失败修复后重跑自动续)
追溯:     state/pipeline_log.json 每步 span;失败写 failed_step 锚点 + reason
阶段:     01_detect(RT-DETR-v2, conf=0.7) → 02_ocr(hayai+规则过滤) → 03_translate(单LLM+术语库+前页上下文) → [04_inpaint → 05_typeset]
说明:     conf=0.7 高阈值已过滤假框，不再需要 02b VLM 三态过滤；翻译层单 LLM + 术语库注入 + 前页上下文注入
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
from amta.artifact_store import ArtifactStore  # noqa: E402
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


def _ensure_terms(work_id: str, ws_root: Path) -> None:
    """确保术语表存在：有就复用，没有就自动跑 pre_scan 扫描全本已有 canon。

    术语表是 work_id 级别，只创建一次，写入 state/work_state.json。
    后续重跑翻译时直接复用，不会重复扫描。
    """
    from amta.workstate import load_state

    ws = load_state(work_id)
    if ws.get("terms"):
        return  # 已有术语表，直接复用

    canon_dir = ws_root / "artifacts"
    store = ArtifactStore(canon_dir)
    canon_files = [p for k in store.pages("canon")
                   if (p := store.resolve("canon", k)) is not None]
    if not canon_files:
        print("[00_run_all] pre_scan skipped (no canon files yet)")
        return

    master_dict = HERE.parent / "data" / "thbwiki_master_dict.json"
    if not master_dict.exists():
        print(f"[00_run_all] pre_scan skipped (master_dict not found: {master_dict})")
        return

    print(f"[00_run_all] pre_scan: scanning {len(canon_files)} canon files...")
    _run_cli([str(HERE / "pre_scan.py"), "--work-id", work_id,
              "--artifacts-dir", str(canon_dir),
              "--master-dict", str(master_dict)])


def _refresh_merged_translation(ws_root: Path) -> None:
    """刷新 artifacts/translation.json：合并所有 page_*_translation.json（前页回溯读取）。"""
    import re as _re

    art_dir = ws_root / "artifacts"
    merged: dict[str, str] = {}
    store = ArtifactStore(art_dir)
    for page_key in store.pages("translation"):
        p = store.resolve("translation", page_key)
        if p is None:
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for rid, t in (doc.get("translations") or {}).items():
            if _re.match(r"page_\d+_", str(rid)):
                merged[str(rid)] = t
    if merged:
        write_json(art_dir / "translation.json",
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
        page_idx = n
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
            # ---- 01 detect (RT-DETR-v2, conf=0.7) ----
            if det_path.exists():
                log.add_span(run_id, step="01_detect", page=page, status="skipped",
                             input=str(raw), output=str(det_path))
                print(f"[00_run_all] {page} 01_detect skipped (exists)")
            else:
                t0 = time.time()
                _run_cli([str(HERE / "01_detect.py"), "--work-id", work_id,
                          "--raw", str(raw), "--out", str(det_path),
                          "--conf", "0.7"])
                log.add_span(run_id, step="01_detect", page=page, status="ok",
                             input=str(raw), output=str(det_path),
                             duration_s=time.time() - t0)

            # ---- 02 ocr (hayai + 规则过滤, 无 VLM 校验) ----
            if canon_path.exists():
                log.add_span(run_id, step="02_ocr", page=page, status="skipped",
                             input=str(det_path), output=str(canon_path))
                print(f"[00_run_all] {page} 02_ocr skipped (exists)")
            else:
                t0 = time.time()
                _run_cli([str(HERE / "02_ocr.py"), "--work-id", work_id,
                          "--det", str(det_path), "--raw", str(raw),
                          "--out", str(canon_path), "--page-idx", str(page_idx),
                          "--engine", "hayai"])
                log.add_span(run_id, step="02_ocr", page=page, status="ok",
                             input=str(det_path), output=str(canon_path),
                             duration_s=time.time() - t0)

            # ---- 术语预扫描（只跑一次，有术语表就复用，没有就自动创建）----
            _ensure_terms(work_id, ws_root)

            # ---- 03 translate (deepseek 单 LLM + 术语库 + 前页上下文, 无 VLM 裁决) ----
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
