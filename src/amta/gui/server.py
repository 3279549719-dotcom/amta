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

from amta.common import workstate
from amta.common.book_store import (
    book_id_from_src_dir,
    load_glossary,
    save_glossary,
)
from amta.common.deliverables import deliverable_stem, write_input_manifest
from amta.common.environment import run_environment_check
from amta.common.paths import ROOT
from amta.orchestrator import PipelineConfig, run_pipeline
from amta.orchestrator.quality_audit import audit_run, format_redlist
from amta.stores import artifacts

app = FastAPI(title="Touhou Manga Translator", version="0.1.0")

# 内存任务表：job_id -> {job_id, status, mode, work_id, error}
# 进程内状态，重启即失（MVP 不做持久化）。
_jobs: dict[str, dict[str, object]] = {}

# 按需 PSD 生成表：key=f"{work_id}:{page}" -> {status, error}
# Photoshop 冷启动慢（1~3 分钟），不放在流水线热路径上；用户点"导出 PSD"才触发。
_psd_jobs: dict[str, dict[str, object]] = {}
_psd_jobs_lock = threading.Lock()


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
            pages = sorted(artifacts.discover_pages(src))
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
            stage_configs={"typeset": {"export_psd": False}},
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
    source_names: list[str] = []
    for i, f in enumerate(files, start=1):
        content = await f.read()
        # 统一转存为 .jpg（管线只认 .jpg）；同时记住原图名用于交付命名
        pil_img = Image.open(BytesIO(content)).convert("RGB")
        dest = input_dir / f"{i}.jpg"
        pil_img.save(dest, "JPEG")
        source_names.append(f.filename or f"{i}.jpg")
    write_input_manifest(_workspace_dir(work_id), source_names)
    return {
        "work_id": work_id,
        "src_dir": str(input_dir),
        "page_count": len(source_names),
        "pages": list(range(1, len(source_names) + 1)),
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
    stem = deliverable_stem(_workspace_dir(work_id), int(page))
    return FileResponse(
        image_path, media_type="image/png", filename=f"{stem}.png"
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
    stem = deliverable_stem(_workspace_dir(work_id), int(page))
    return FileResponse(
        psd_path,
        media_type="image/vnd.adobe.photoshop",
        filename=f"{stem}.psd",
    )


# ---------------------------------------------------------------------------
# 按需 PSD 生成（异步：点击导出 PSD 才拉起 Photoshop，不堵流水线）
# ---------------------------------------------------------------------------
def _psd_job_key(work_id: str, page: str) -> str:
    return f"{work_id}:{page}"


def _run_psd_export(work_id: str, page: str, psd_path: Path) -> None:
    """后台线程：调 Photoshop 生成分层 PSD，结果写回 _psd_jobs。"""
    key = _psd_job_key(work_id, page)
    try:
        from amta.typeset.psd_jsx_export import export_page_psd

        artifacts_dir = _workspace_path(work_id, "artifacts")
        exported = export_page_psd(artifacts_dir, f"page_{page}", psd_path)
        if exported and psd_path.is_file() and psd_path.stat().st_size > 0:
            with _psd_jobs_lock:
                _psd_jobs[key] = {"status": "done", "error": None}
        else:
            with _psd_jobs_lock:
                _psd_jobs[key] = {
                    "status": "failed",
                    "error": "Photoshop 未产出 PSD（可能被卡死，重试一次或手动关闭 Photoshop）",
                }
    except Exception as exc:  # noqa: BLE001
        with _psd_jobs_lock:
            _psd_jobs[key] = {"status": "failed", "error": str(exc)[:200]}


@app.post("/api/psd/{work_id}/{page}")
def request_psd(work_id: str, page: str) -> dict:
    """按需触发某页 PSD 生成。幂等：已生成返回 ready，生成中返回 running。

    前端轮询本接口直到 ready，再 window.open 下载。
    """
    if not re.fullmatch(r"[0-9]+", page):
        raise HTTPException(status_code=400, detail="page must be numeric")
    psd_path = _page_path(work_id, page, psd=True)

    # 已经有成品文件 → 直接 ready（不重复跑）
    if psd_path.is_file() and psd_path.stat().st_size > 0:
        with _psd_jobs_lock:
            _psd_jobs[_psd_job_key(work_id, page)] = {"status": "done", "error": None}
        return {"status": "ready"}

    key = _psd_job_key(work_id, page)
    with _psd_jobs_lock:
        existing = _psd_jobs.get(key)
        if existing and existing.get("status") in ("running", "pending"):
            return {"status": "running"}
        # 标记 running，然后开后台线程
        _psd_jobs[key] = {"status": "running", "error": None}

    threading.Thread(
        target=_run_psd_export, args=(work_id, page, psd_path),
        name=f"psd-{work_id}-{page}", daemon=True,
    ).start()
    return {"status": "started"}


# ---------------------------------------------------------------------------
# 书级术语表确认（GUI 人工核对 / 编辑）
# ---------------------------------------------------------------------------
@app.get("/api/book/resolve")
def resolve_book(dir: str) -> dict[str, object]:
    """根据图片所在文件夹的真实路径，识别这是哪本同人册。

    这是"指纹"的入口：路径 → book_id → 已有 glossary 自动挂上。
    新文件夹 = 新 book_id = 空 glossary（自动开新槽，互不污染）。
    前端拿到 book_id 后用 work_id="book-<book_id>" 固定工作区，用户看不见 work_id。
    """
    d = Path(dir).expanduser()
    if not d.exists():
        raise HTTPException(status_code=400, detail=f"path not found: {dir}")
    if d.is_file():  # 手滑填成单个图片也能兜住：用它所在文件夹
        d = d.parent
    bid = book_id_from_src_dir(d)
    glossary = load_glossary(bid)
    pages = sorted(artifacts.discover_pages(d))
    return {
        "book_id": bid,
        "work_id": f"book-{bid}",
        "src_dir": str(d),
        "glossary": glossary,
        "page_count": len(pages),
        "pages": pages,
    }


def _known_books() -> list[dict[str, object]]:
    """列出所有已登记的书：book_id -> src_dir。来自 workspace/books/*/meta.json。"""
    out = []
    books_root = ROOT / "workspace" / "books"
    if not books_root.is_dir():
        return out
    for bid_dir in books_root.iterdir():
        meta = bid_dir / "meta.json"
        if not meta.is_file():
            continue
        try:
            from amta.common.paths import read_json
            m = read_json(meta)
            src = Path(m.get("src_dir", ""))
            if src.is_dir():
                out.append({"book_id": bid_dir.name, "src_dir": src})
        except (OSError, ValueError):
            continue
    return out


@app.post("/api/book/match")
async def match_book(files: list[UploadFile] = File(...)) -> dict[str, object]:
    """用户直接丢图片进来 —— 服务器在已登记的书文件夹里比对这些图是从哪本掉出来的。

    这是"零路径"的关键：浏览器不给绝对路径，但服务器在本机，能拿文件名+大小
    (+内容哈希) 去每本书的 src_dir 里找同名同大小的图。匹配到唯一一本就自动绑定，
    不用手填路径。匹配不到（新书）就返回 matched=false，前端才退回去要路径。
    """
    known = _known_books()
    if not known:
        return {"matched": False, "reason": "还没有任何已登记的书，先填一次文件夹建立档案"}

    # 第一遍：按 文件名+大小 粗筛
    per_file_candidates: list[set[str]] = []
    for f in files:
        content = await f.read()
        fname = Path(f.filename or "").name  # 防路径穿越，只取文件名
        size = len(content)
        cand: set[str] = set()
        for b in known:
            target = b["src_dir"] / fname  # type: ignore[operator]
            try:
                if target.is_file() and target.stat().st_size == size:
                    cand.add(b["book_id"])  # type: ignore[union-attr]
            except OSError:
                continue
        per_file_candidates.append(cand)

    if not per_file_candidates:
        return {"matched": False, "reason": "没有收到图片"}

    common = set.intersection(*per_file_candidates)
    if len(common) != 1:
        return {
            "matched": False,
            "reason": ("这些图在已登记的书里对不上（可能是新书或换了文件）。"
                       "请在文件夹栏指一次它所在文件夹，之后自动记住。"),
        }

    bid = common.pop()
    src_dir = next(b["src_dir"] for b in known if b["book_id"] == bid)
    glossary = load_glossary(bid)
    pages = sorted(artifacts.discover_pages(src_dir))
    return {
        "matched": True,
        "book_id": bid,
        "work_id": f"book-{bid}",
        "src_dir": str(src_dir),
        "glossary": glossary,
        "page_count": len(pages),
        "pages": pages,
    }


@app.post("/api/book/bootstrap")
def bootstrap_book_endpoint(req: dict) -> dict[str, object]:
    """新书一键建档：对整个文件夹跑 detect+ocr，LLM 抽人名，返回 glossary 草稿。

    注意：只返回草稿、不写盘。用户在 Glossary 面板里核对/修改后点保存，
    才由 POST /api/glossary 落盘锁定。
    """
    src = (req.get("src_dir") or "").strip()
    if not src:
        raise HTTPException(status_code=400, detail="src_dir required")
    d = Path(src).expanduser()
    if d.is_file():
        d = d.parent
    if not d.is_dir():
        raise HTTPException(status_code=400, detail=f"folder not found: {src}")

    from amta.common.book_store import save_meta
    from amta.guards.book_bootstrap import bootstrap_book

    bid = book_id_from_src_dir(d)
    save_meta(bid, d)
    work_id = f"book-{bid}"
    # 把 book_id 写进 work_state，免得翻译时又认不出书
    ws = workstate.load_state(work_id)
    ws["book_id"] = bid
    workstate.save_state(work_id, ws)

    draft = bootstrap_book(d, work_id)
    return {
        "book_id": bid,
        "work_id": work_id,
        "src_dir": str(d),
        "glossary": draft,
        "count": len(draft),
    }


@app.get("/api/glossary")
def get_glossary(work_id: str) -> dict[str, object]:
    """返回本 work 所属书的已确认术语表。

    book_id 记录在 work_state 里（由 src_dir 推导，见 book_store）；
    没有 book_id（本 work 尚未绑定书）时返回空表 + book_id=None。
    """
    _workspace_dir(work_id)
    ws = workstate.load_state(work_id)
    book_id = ws.get("book_id")
    if not book_id:
        return {"glossary": {}, "book_id": None}
    return {"glossary": load_glossary(str(book_id)), "book_id": book_id}


@app.post("/api/glossary")
def save_glossary_endpoint(req: dict) -> dict[str, object]:
    """保存 GUI 中人工确认/编辑后的术语表，写回磁盘。"""
    work_id = req.get("work_id", "")
    glossary = req.get("glossary", {})
    if not work_id or not isinstance(glossary, dict):
        raise HTTPException(status_code=400, detail="work_id and glossary required")
    _workspace_dir(work_id)
    ws = workstate.load_state(work_id)
    book_id = ws.get("book_id")
    if not book_id:
        raise HTTPException(status_code=400, detail="no book_id in work_state")
    save_glossary(str(book_id), glossary)
    return {"ok": True, "count": len(glossary)}


# ---------------------------------------------------------------------------
# 静态前端 —— 必须挂在所有 API 路由之后（兜底 catch-all）。
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
