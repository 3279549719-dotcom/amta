"""Koharu v0.59.1 REST API client — AMTA 执行器的确定性封装。

基于本地轮子 manga-localization 验证过的 API 通路重写（参数化、无硬编码路径）。
Koharu headless: http://127.0.0.1:4000/api/v1
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

KOHARU_HOST = "127.0.0.1"
KOHARU_PORT = 4000
DEFAULT_TIMEOUT = 60
PIPELINE_TIMEOUT = 1200  # 秒；41 页实测单页 pipeline 600-1200s 为合理窗口


def ensure_no_proxy() -> None:
    """Clash/V2Ray 代理会破坏 localhost 直连，必须显式排除。"""
    for key in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(key, "")
        if "127.0.0.1" not in current:
            os.environ[key] = f"{current},127.0.0.1,localhost".lstrip(",")


ensure_no_proxy()


class KoharuError(RuntimeError):
    pass


class KoharuClient:
    def __init__(self, host: str = KOHARU_HOST, port: int = KOHARU_PORT, timeout: int = DEFAULT_TIMEOUT):
        self.base = f"http://{host}:{port}/api/v1"
        self.timeout = timeout

    # ---------- 服务与健康 ----------

    def wait_server(self, timeout: int = 120) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                requests.get(f"http://{KOHARU_HOST}:{KOHARU_PORT}/", timeout=5)
                return
            except requests.RequestException:
                time.sleep(2)
        raise KoharuError(f"Koharu server not ready on port {KOHARU_PORT}")

    def llm_status(self) -> dict:
        resp = requests.get(f"{self.base}/llm/current", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def ensure_llm_ready(self) -> None:
        llm = self.llm_status()
        if llm.get("status") not in ("ready", "loaded"):
            raise KoharuError(f"LLM not ready: {llm}")

    def engines(self) -> list[dict]:
        resp = requests.get(f"{self.base}/engines", timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ---------- 项目 ----------

    def create_project(self, name: str) -> str:
        resp = requests.post(f"{self.base}/projects", json={"name": name}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("id", "")

    def close_current_project(self) -> None:
        try:
            requests.delete(f"{self.base}/projects/current", timeout=30)
        except requests.RequestException:
            pass

    # ---------- 页面 ----------

    def import_page(self, image_path: Path) -> str:
        mime, _ = mimetypes.guess_type(image_path.name)
        mime = mime or "application/octet-stream"
        with image_path.open("rb") as f:
            resp = requests.post(
                f"{self.base}/pages",
                files={"file": (image_path.name, f, mime)},
                timeout=180,
            )
        resp.raise_for_status()
        pages = resp.json().get("pages", [])
        if not pages:
            raise KoharuError("No page ID returned from import")
        return pages[0]

    # ---------- 流水线 ----------

    def run_pipeline(
        self,
        page_ids: list[str],
        steps: list[str],
        target_language: str = "zh",
        system_prompt: str | None = None,
        default_font: str = "SimHei",
    ) -> str:
        body: dict[str, Any] = {
            "steps": steps,
            "pages": page_ids,
            "targetLanguage": target_language,
            "defaultFont": default_font,
        }
        if system_prompt:
            body["systemPrompt"] = system_prompt
        resp = requests.post(f"{self.base}/pipelines", json=body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["operationId"]

    def wait_operation(self, op_id: str, timeout: int = PIPELINE_TIMEOUT) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = requests.get(f"{self.base}/operations", timeout=30)
            resp.raise_for_status()
            for op in resp.json().get("operations", []):
                if op.get("id") == op_id:
                    status = op.get("status", "")
                    if status in ("completed", "failed", "cancelled", "completed_with_errors"):
                        return op
            time.sleep(5)
        raise KoharuError(f"Pipeline timeout after {timeout}s (op={op_id})")

    # ---------- 场景与 mask ----------

    def get_scene(self) -> dict:
        resp = requests.get(f"{self.base}/scene.json", timeout=60)
        resp.raise_for_status()
        return resp.json()

    def get_page_nodes(self, page_id: str) -> dict[str, dict]:
        """返回 page 的全部节点 {node_id: {kind, transform, ...}}。"""
        scene = self.get_scene()
        pages = scene.get("scene", {}).get("pages", {})
        page = pages.get(page_id)
        if page is None:
            raise KoharuError(f"Page {page_id} not in scene")
        return page.get("nodes", {})

    def get_mask_blob_hash(self, page_id: str, role: str) -> str | None:
        """找到指定 role 的 Mask 节点并返回其 blob 引用（没有则 None）。"""
        for node in self.get_page_nodes(page_id).values():
            kind = node.get("kind", {})
            mask = kind.get("mask") if isinstance(kind, dict) else None
            if mask and mask.get("role") == role:
                # blob 引用可能在 mask 数据里，字段名兼容 blob/hash/image
                return mask.get("blob") or mask.get("hash") or node.get("blob") or node.get("image")
        return None

    def get_blob(self, blob_ref: str) -> bytes:
        resp = requests.get(f"{self.base}/blobs/{blob_ref}", timeout=60)
        resp.raise_for_status()
        return resp.content

    def save_mask(self, page_id: str, role: str, dest: Path) -> Path | None:
        """把 Mask{role} 存成 PNG；没有该 mask 返回 None。"""
        ref = self.get_mask_blob_hash(page_id, role)
        if not ref:
            return None
        data = self.get_blob(ref)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def put_mask(self, page_id: str, role: str, png_bytes: bytes, engine: str | None = None) -> dict:
        """上传/覆盖 mask（segment|brushInpaint），可选随后跑指定 inpaint 引擎。"""
        params = {"engine": engine} if engine else {}
        resp = requests.put(
            f"{self.base}/pages/{page_id}/masks/{role}",
            params=params,
            data=png_bytes,
            headers={"Content-Type": "image/png"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ---------- 导出 ----------

    def export_page(self, page_id: str, fmt: str, dest: Path, timeout: int = 300) -> Path:
        resp = requests.post(
            f"{self.base}/projects/current/export",
            json={"format": fmt, "pages": [page_id]},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.content
        dest.parent.mkdir(parents=True, exist_ok=True)
        if data[:2] == b"PK":  # zip 包裹
            with zipfile.ZipFile(BytesIO(data)) as zf:
                matches = [n for n in zf.namelist() if n.lower().endswith(f".{fmt.lower()}")]
                if not matches:
                    raise KoharuError(f"Export zip has no .{fmt} file")
                dest.write_bytes(zf.read(matches[0]))
        else:
            dest.write_bytes(data)
        return dest

    # ---------- 结果回读 ----------

    @staticmethod
    def collect_blocks(nodes: dict[str, dict]) -> list[dict]:
        """从 scene 节点提取文字块（含 bubble_type 推断），与轮子逻辑一致。"""
        blocks = []
        for node_id, node in nodes.items():
            kind = node.get("kind", {})
            if not (isinstance(kind, dict) and "text" in kind):
                continue
            text_data = kind["text"]
            raw_type = ""
            if isinstance(kind, dict):
                raw_type = kind.get("type", "")
            if not raw_type:
                kind_keys = set(kind.keys()) - {"text"}
                if "speech_bubble" in kind_keys:
                    raw_type = "speech_bubble"
                elif "narration" in kind_keys:
                    raw_type = "narration"
                elif "sfx" in kind_keys:
                    raw_type = "sfx"
                else:
                    raw_type = "dialogue"
            rt = raw_type.lower()
            if "narration" in rt:
                bubble_type = "narration"
            elif "sfx" in rt:
                bubble_type = "sfx"
            elif any(k in rt for k in ("speech", "bubble", "dialogue", "text")):
                bubble_type = "dialogue"
            else:
                bubble_type = "unknown"

            blocks.append({
                "node_id": node_id,
                "ocr": (text_data.get("text") or "").strip(),
                "translation": (text_data.get("translation") or "").strip(),
                "confidence": text_data.get("confidence"),
                "alternatives": text_data.get("alternatives"),
                "transform": node.get("transform") or {},
                "bubble_type": bubble_type,
            })
        return blocks

    @staticmethod
    def sort_by_reading_order(blocks: list[dict]) -> list[dict]:
        """y 升序、同行 x 降序（日漫阅读序）。"""
        def key(b: dict) -> tuple[float, float]:
            t = b.get("transform", {})
            return (t.get("y", 0), -t.get("x", 0))
        return sorted(blocks, key=key)


# 便捷单例
client = KoharuClient()
