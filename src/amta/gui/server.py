"""Touhou Manga Translator — 本地 FastAPI 后端。

为 Web GUI 提供的本地 API：
  GET  /api/health                — 健康检查
  POST /api/translate             — 提交翻译任务（后台跑管线）
  GET  /api/jobs/{job_id}         — 轮询任务状态
  GET  /api/artifacts/{work_id}   — 列出最终成图
  GET  /api/image/{work_id}/{page}— 取某页最终成图

产品名：Touhou Manga Translator（本地漫画翻译器的 Web 壳）。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from amta.common.environment import run_environment_check
from amta.common.paths import ROOT
from amta.orchestrator import PipelineConfig, run_pipeline
from amta.orchestrator.quality_audit import audit_run, format_redlist

app = FastAPI(title="Touhou Manga Translator", version="0.1.0")

# 内存任务表：job_id -> {job_id, status, mode, work_id, error}
# 进程内状态，重启即失（MVP 不做持久化）。
_jobs: dict[str, dict[str, object]] = {}


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------
class TranslateRequest(BaseModel):
    """提交翻译任务的请求体。"""

    src_dir: str
    work_id: str
    mode: str = "default"          # "default" 或 "vlm"
    pages: list[int] | None = None


class JobResponse(BaseModel):
    """任务提交 / 状态查询的统一响应。"""

    job_id: str
    status: str                    # "queued" / "running" / "done" / "failed"
    mode: str
    work_id: str
    error: str | None = None
    quality_warning: str | None = None


# ---------------------------------------------------------------------------
# 后台管线运行
# ---------------------------------------------------------------------------
def _run_pipeline_background(job_id: str, req: TranslateRequest) -> None:
    """后台线程：构造 PipelineConfig 并跑完整管线，结果写回 _jobs。

    作为 daemon 线程跑：服务退出时不阻塞进程。单页/单阶段失败由编排器内部
    捕获并记为 failed；这里只兜底整个管线抛异常的情况。
    """
    # 直接 `uvicorn amta.gui.server:app` 启动时，src/ 可能不在 sys.path，
    # server.py 在 src/amta/gui/ 下，上溯四级到项目根再加 src（与 common/paths 同源）。
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root / "src") not in sys.path:
        sys.path.insert(0, str(project_root / "src"))

    try:
        _jobs[job_id]["status"] = "running"  # type: ignore[index]
        _validate_workspace_tree(req.work_id)
        # pages 为 None（整本跑）时，从 src_dir 实际扫描 .jpg 文件名数字得到页号，
        # 避免 end_page=9999 让管线遍历近万页、刷大量 "not found" WARN。
        # 扫描结果为空列表时，管线会走 "no valid pages found" 正常返回。
        pages = req.pages
        if pages is None:
            src = Path(req.src_dir)
            pages = sorted(int(p.stem) for p in src.glob("*.jpg") if p.stem.isdigit())
        # VLM 模式：把离散页作为 vlm_pages，编排器会给这些页的 ocr/translate/typeset
        # 注入 vlm_mode=True。pages 为空时不做 VLM 路由（不生效但不报错）。
        vlm_pages = list(pages) if (req.mode == "vlm" and pages) else []
        config = PipelineConfig(
            work_id=req.work_id,
            src_dir=Path(req.src_dir),
            start_page=1,
            end_page=9999,
            pages=pages,
            vlm_pages=vlm_pages,
            stages=["detect", "ocr", "translate", "inpaint", "typeset"],
            stage_configs={"typeset": {"export_psd": True}},
            continue_on_error=True,
        )
        if not run_environment_check(config.stages):
            raise RuntimeError("Environment check failed; pipeline was not started")
        result = run_pipeline(config)
        _jobs[job_id]["quality_warning"] = format_redlist(
            audit_run(_workspace_path(req.work_id, "artifacts"), result.pages)
        ) or None
        if result.failed_pages or result.failed_step or not result.pages:
            _jobs[job_id]["status"] = "failed"  # type: ignore[index]
            _jobs[job_id]["error"] = (  # type: ignore[index]
                str(result.failed_step["reason"]) if result.failed_step else
                f"{len(result.failed_pages)} page(s) failed" if result.failed_pages else
                "no valid pages found"
            )
        else:
            _jobs[job_id]["status"] = "done"  # type: ignore[index]
    except Exception as exc:  # noqa: BLE001 — 后台容错：错误存进 job，不炸线程
        _jobs[job_id]["status"] = "failed"  # type: ignore[index]
        _jobs[job_id]["error"] = str(exc)  # type: ignore[index]


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health_check() -> dict[str, str]:
    """健康检查 — 返回服务名与版本。"""
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/translate", status_code=202)
def submit_translation_job(req: TranslateRequest) -> JobResponse:
    """提交一个翻译任务，立即返回 job_id；管线在后台线程跑。"""
    if req.mode not in ("default", "vlm"):
        raise HTTPException(status_code=400, detail="mode must be 'default' or 'vlm'")
    _validate_workspace_tree(req.work_id)

    job_id = uuid.uuid4().hex
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "mode": req.mode,
        "work_id": req.work_id,
        "error": None,
    }
    thread = threading.Thread(
        target=_run_pipeline_background, args=(job_id, req), daemon=True
    )
    thread.start()
    return JobResponse(
        job_id=job_id, status="queued", mode=req.mode, work_id=req.work_id
    )


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> JobResponse:
    """轮询任务状态；未知 job_id 返回 404。"""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found")
    return JobResponse(**job)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 产物浏览
# ---------------------------------------------------------------------------
def _workspace_dir(work_id: str) -> Path:
    """本子工作区根目录：workspace/<work_id>/。"""
    if not re.fullmatch(r"[\w-]+(?:\.[\w-]+)*", work_id):
        raise HTTPException(status_code=400, detail="invalid work_id")
    workspace = (ROOT / "workspace").resolve()
    target = (workspace / work_id).resolve()
    if target == workspace or not target.is_relative_to(workspace):
        raise HTTPException(status_code=400, detail="work_id escapes workspace")
    return target


def _workspace_path(work_id: str, *parts: str) -> Path:
    """Resolve links before any read, write or recursive removal."""
    work = _workspace_dir(work_id)
    target = work.joinpath(*parts).resolve()
    if target == work or not target.is_relative_to(work):
        raise HTTPException(status_code=400, detail="path escapes work directory")
    return target


def _validate_workspace_tree(work_id: str) -> None:
    """Reject existing links that could redirect a pipeline write outside its work."""
    work = _workspace_dir(work_id)
    for directory, dirs, files in os.walk(work, followlinks=False):
        for name in dirs + files:
            target = (Path(directory) / name).resolve()
            if not target.is_relative_to(work):
                raise HTTPException(status_code=400, detail="path escapes work directory")


def _page_path(work_id: str, page: str, *, psd: bool = False) -> Path:
    if not re.fullmatch(r"[0-9]+", page):
        raise HTTPException(status_code=400, detail="page must be numeric")
    return _workspace_path(
        work_id, "artifacts", "psd" if psd else "final",
        f"page_{page}.psd" if psd else f"page_{page}_final.png",
    )


@app.get("/api/artifacts/{work_id}")
def list_artifacts(work_id: str) -> dict[str, object]:
    """列出某本子的最终成图页号。

    扫描 artifacts/final/page_<N>_final.png，返回 [{page: "N", url: ...}]，
    按页号数字升序排序。目录不存在或没有成图时返回空列表。
    """
    final_dir = _workspace_path(work_id, "artifacts", "final")
    artifacts: list[dict[str, str]] = []
    if final_dir.is_dir():
        pages = []
        for p in final_dir.glob("page_*_final.png"):
            page = p.stem.removeprefix("page_").removesuffix("_final")
            if not page.isascii() or not page.isdigit():
                continue
            _page_path(work_id, page)
            pages.append((int(page), page))
        for _, page in sorted(pages):
            artifacts.append({
                "page": page,
                "url": f"/api/image/{work_id}/{page}",
            })
    return {"work_id": work_id, "artifacts": artifacts}


@app.get("/api/image/{work_id}/{page}")
def get_image(work_id: str, page: str) -> FileResponse:
    """按纯数字页号返回最终成图 artifacts/final/page_<page>_final.png。"""
    image_path = _page_path(work_id, page)
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail=f"page {page} image not found")
    return FileResponse(image_path, media_type="image/png")


# ---------------------------------------------------------------------------
# 文件上传
# ---------------------------------------------------------------------------
@app.post("/api/upload")
async def upload_images(
    files: list[UploadFile] = File(...), work_id: str = Form(...)
) -> dict:
    """接收用户上传的漫画页，统一转存为 workspace/<work_id>/input/<n>.jpg。

    管线的 _resolve_page_list 只查找 {n}.jpg，因此 PNG/WebP 等一律用 Pillow
    转成 RGB 再存为 JPEG，文件名用 1-based 序号，丢弃原文件名。
    """
    input_dir = _workspace_path(work_id, "input")
    if input_dir.exists():
        shutil.rmtree(input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, f in enumerate(files, start=1):
        content = await f.read()
        # 统一转存为 .jpg（管线只认 .jpg）
        pil_img = Image.open(BytesIO(content)).convert("RGB")
        dest = input_dir / f"{i}.jpg"
        pil_img.save(dest, "JPEG")
        saved.append(str(dest))
    return {
        "work_id": work_id,
        "src_dir": str(input_dir),
        "page_count": len(saved),
        "pages": list(range(1, len(saved) + 1)),
    }


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------
@app.get("/api/export/{work_id}/{page}/png")
def export_png(work_id: str, page: str) -> FileResponse:
    """下载某页最终成图 PNG（artifacts/final/page_<page>_final.png）。"""
    image_path = _page_path(work_id, page)
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(
        image_path, media_type="image/png", filename=f"{work_id}_{page}.png"
    )


@app.get("/api/export/{work_id}/{page}/psd")
def export_psd(work_id: str, page: str) -> FileResponse:
    """下载某页分层 PSD；未产出时 404 提示（UI 不暴露入口）。"""
    psd_path = _page_path(work_id, page, psd=True)
    if not psd_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="PSD not found — run typeset with PSD export enabled",
        )
    return FileResponse(
        psd_path,
        media_type="image/vnd.adobe.photoshop",
        filename=f"{work_id}_{page}.psd",
    )


# ---------------------------------------------------------------------------
# 静态前端 —— 必须挂在所有 API 路由之后（兜底 catch-all）。
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
