"""Touhou Manga Translator GUI — 端到端上传→翻译→轮询→导出流程测试。

与 test_gui_server.py 的端点单元测试互补：这里走真实 HTTP 请求路径
（TestClient），覆盖 upload → translate → jobs 轮询 → artifacts 的完整链路。

前三个用例只验证「提交成功即返回」，不等后台管线跑完（daemon 线程会自己跑，
测试退出时随进程销毁）。第四个用例在 API key + 模型权重 + OCR 运行时都配齐时
才真正跑完整管线，否则 skip。
"""
from __future__ import annotations

import os
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from amta.gui.server import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# skip 检测
# ---------------------------------------------------------------------------
def _has_api_keys() -> bool:
    return bool(os.environ.get("CHAT_API_KEY")) or Path(".env").exists()


def _has_detect_models() -> bool:
    models_dir = Path("models")
    return models_dir.exists() and any(models_dir.glob("**/*.pt"))


def _ocr_runtime_ready() -> bool:
    """hayai-ocr v2 除本地权重外，还需从 HF 拉取 google/siglip2 图像处理器。

    本机/CI 若未缓存该处理器，OCR 阶段会在联网下载时失败，整条管线跑不通。
    这里做一次纯缓存探测（local_files_only，不发网络请求）：探测不到就 skip。
    任何探测异常都视为「未就绪」——宁可 skip 也不要在缺依赖环境里红。
    """
    try:
        from huggingface_hub import try_to_load_from_cache

        p = try_to_load_from_cache(
            "google/siglip2-base-patch16-naflex", "preprocessor_config.json"
        )
        return p is not None
    except Exception:  # noqa: BLE001 — 探测本身失败按未就绪处理
        return False


def _make_pipeline_image() -> BytesIO:
    """造一张白底带一小块日文的测试图。

    纯白图在 detect 阶段找不到文字框，ocr 阶段会直接 raise（不是跳过），
    导致 page 标记 failed。画上一小段日文让 detect 能框到区域，管线才能走完
    detect→ocr→translate→inpaint→typeset。字体缺失时退回默认字体。
    """
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 24)
    except Exception:  # noqa: BLE001 — 非 Windows/无日文字体时退回默认
        font = ImageFont.load_default()
    draw.text((30, 85), "テスト", fill=(0, 0, 0), font=font)
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# 1. VLM 模式提交
# ---------------------------------------------------------------------------
def test_e2e_vlm_mode_submission(tmp_path: Path) -> None:
    """造一个含 1.jpg 白图的 src_dir，以 VLM 模式提交翻译。"""
    src = tmp_path / "vlm-pages"
    src.mkdir()
    Image.new("RGB", (100, 100), (255, 255, 255)).save(src / "1.jpg")

    resp = client.post(
        "/api/translate",
        json={
            "src_dir": str(src),
            "work_id": "e2e-vlm-submit",
            "mode": "vlm",
            "pages": [1],
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["mode"] == "vlm"
    assert body["job_id"]
    # 不等后台管线完成——daemon 线程会自己跑。


# ---------------------------------------------------------------------------
# 2. 非法 mode 被拒
# ---------------------------------------------------------------------------
def test_e2e_invalid_mode_rejected() -> None:
    """mode 不在 default/vlm 白名单内 → 400。"""
    resp = client.post(
        "/api/translate",
        json={
            "src_dir": "whatever",
            "work_id": "e2e-bad-mode",
            "mode": "invalid",
            "pages": [1],
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 3. 上传后再提交
# ---------------------------------------------------------------------------
def test_e2e_upload_then_submit() -> None:
    """上传一张白图拿到 src_dir，再用它提交 default 模式翻译。"""
    img_bytes = BytesIO()
    Image.new("RGB", (50, 50), (255, 255, 255)).save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    work_id = "e2e-upload-submit"
    up = client.post(
        "/api/upload",
        files={"files": ("1.jpg", img_bytes, "image/jpeg")},
        data={"work_id": work_id},
    )
    assert up.status_code == 200
    up_body = up.json()
    assert up_body["page_count"] == 1
    assert Path(up_body["src_dir"], "1.jpg").exists()
    assert up_body["pages"] == [1]

    resp = client.post(
        "/api/translate",
        json={
            "src_dir": up_body["src_dir"],
            "work_id": work_id,
            "mode": "default",
            "pages": [1],
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    assert body["mode"] == "default"
    # 不等完成。


# ---------------------------------------------------------------------------
# 4. 完整管线：上传 → 翻译 → 轮询 → artifacts
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not (_has_api_keys() and _has_detect_models() and _ocr_runtime_ready()),
    reason="API keys or model weights not configured",
)
def test_e2e_full_pipeline() -> None:
    """真正跑完整管线：upload → translate → 轮询 → 检查 artifacts 端点。

    画上一小块日文，让 detect 能框到文字区域、ocr 有活可干。只要 job 最终
    status=done 即算通过；artifacts 列表为空也不算失败。
    """
    work_id = "e2e-full-pipeline"
    up = client.post(
        "/api/upload",
        files={"files": ("1.jpg", _make_pipeline_image(), "image/jpeg")},
        data={"work_id": work_id},
    )
    assert up.status_code == 200
    src_dir = up.json()["src_dir"]

    sub = client.post(
        "/api/translate",
        json={
            "src_dir": src_dir,
            "work_id": work_id,
            "mode": "default",
            "pages": [1],
        },
    )
    assert sub.status_code == 202
    job_id = sub.json()["job_id"]

    # 轮询最多 60 秒
    deadline = time.monotonic() + 60.0
    status = "queued"
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        status = r.json()["status"]
        if status in ("done", "failed"):
            break
        time.sleep(1.0)

    assert status == "done", f"pipeline ended with status={status}"

    # artifacts 端点必须 200（空列表也可接受）
    art = client.get(f"/api/artifacts/{work_id}")
    assert art.status_code == 200
    assert art.json()["work_id"] == work_id
