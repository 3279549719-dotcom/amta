"""Touhou Manga Translator — 本地 FastAPI 后端。

为 Web GUI 提供的本地 API：
  GET  /api/health           — 健康检查
  POST /api/translate        — 提交翻译任务（后台跑管线）
  GET  /api/jobs/{job_id}    — 轮询任务状态
  GET  /api/artifacts/{work_id} — 列出最终成图
  GET  /api/image/{work_id}/{page} — 取某页最终成图

产品名：Touhou Manga Translator（本地漫画翻译器的 Web 壳）。
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Touhou Manga Translator", version="0.1.0")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """健康检查 — 返回服务名与版本。"""
    return {"status": "ok", "version": "0.1.0"}
