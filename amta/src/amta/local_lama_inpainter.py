"""本地 LaMa inpainting 封装 — 用 simple-lama-inpainting 的 TorchScript 模型。

与 Koharu lama-manga 的区别:
- 本封装用 big-lama (通用 LaMa), Koharu 用 lama-manga (漫画微调)
- 质量差异部分来自模型, 报告中需标注
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from ._lama_model import SimpleLama

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "big-lama.pt"


class LocalLamaInpainter:
    """本地 LaMa 推理, 消除 Koharu HTTP 开销。"""

    def __init__(self, device: str = "cpu", model_path: Path | None = None) -> None:
        self.device = torch.device(device)
        path = str(model_path or MODEL_PATH)
        if not Path(path).exists():
            raise FileNotFoundError(f"LaMa model not found: {path}")
        os.environ["LAMA_MODEL"] = path
        t0 = time.time()
        self.model = SimpleLama(device=self.device)
        self.load_time_s = time.time() - t0

    def inpaint(self, image: Image.Image | np.ndarray, mask: Image.Image | np.ndarray) -> Image.Image:
        """对单张图做 inpaint, 返回 PIL Image。

        自动对齐 image/mask 尺寸, 推理后裁剪回原图尺寸。
        """
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image)
        if isinstance(mask, np.ndarray):
            mask = Image.fromarray(mask)
        image = image.convert("RGB")
        mask = mask.convert("L")
        orig_w, orig_h = image.size
        # 确保 mask 与 image 同尺寸
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.NEAREST)
        result = self.model(image, mask)
        # 裁剪回原图尺寸 (prepare_img_and_mask 可能做了 padding)
        if result.size != (orig_w, orig_h):
            result = result.crop((0, 0, orig_w, orig_h))
        return result

    def inpaint_timed(self, image, mask) -> tuple[Image.Image, float]:
        """inpaint + 计时。"""
        t0 = time.time()
        result = self.inpaint(image, mask)
        return result, time.time() - t0
