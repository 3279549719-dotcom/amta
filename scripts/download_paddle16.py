"""稳健下载 PaddleOCR-VL-1.6 GGUF（绕过 huggingface_hub 的 HEAD 校验问题，走 hf-mirror resolve URL 分块拉取）。"""
import os
import urllib.request
from pathlib import Path

HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
REPO = "PaddlePaddle/PaddleOCR-VL-1.6-GGUF"
FILES = ["PaddleOCR-VL-1.6-GGUF.gguf", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf", "chat_template.jinja"]
DL = Path(r"E:\manga translator agent\amta\models\paddle-vl16")
DL.mkdir(parents=True, exist_ok=True)

def download(url, dest: Path):
    if dest.exists() and dest.stat().st_size > 0:
        # 校验已完整（用 Content-Length 对比）
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            expected = int(r.headers.get("Content-Length", "0"))
        if dest.stat().st_size >= expected:
            print(f"SKIP exists {dest.name} {dest.stat().st_size}")
            return True
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url)
    # 断点续传：若已有 part 则 Range 续传
    start = tmp.stat().st_size if tmp.exists() else 0
    if start:
        req.add_header("Range", f"bytes={start}-")
    with urllib.request.urlopen(req, timeout=60) as r:
        mode = "ab" if start else "wb"
        with open(tmp, mode) as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        print(f"DONE {dest.name} size={tmp.stat().st_size}")
    tmp.replace(dest)
    return True

ok = True
for f in FILES:
    url = f"{HF_ENDPOINT}/{REPO}/resolve/main/{f}"
    dest = DL / f
    try:
        download(url, dest)
    except Exception as e:
        print(f"FAIL {f}: {type(e).__name__} {str(e)[:200]}")
        ok = False
print("ALL_DONE" if ok else "PARTIAL_FAIL")
