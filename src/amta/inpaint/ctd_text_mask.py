"""CTD (Comic Text Detector) 像素级文字 mask 生成器。

利用 CTD ONNX 模型的 DBNet seg 输出，得到紧贴文字笔画的像素级 mask，
替代矩形 bbox 作为 LaMa 的输入。这样 LaMa 只需要补文字像素，不会重建
整块气泡空白。

模型: models/CTD/comictextdetector.pt.onnx
输入: 1x3x1024x1024 (float32, [0,1], RGB)
输出: seg = 1x1x1024x1024 (文字概率热图)
"""
from __future__ import annotations

import threading

import cv2
import numpy as np
from PIL import Image

from amta.common.paths import ROOT

MODEL_PATH = ROOT / "models" / "CTD" / "comictextdetector.pt.onnx"
INPUT_SIZE = 1024

# DBNet seg 热图阈值。>thresh 视为文字像素。
# 探针报告 (gen_ctd_mask_report) 推荐 thresh=0.1 + 9x9 膨胀 7 次。
SEG_THRESH = 0.1


class CtdTextMaskGenerator:
    """CTD 文字 mask 生成器（模块级单例，模型只加载一次）。"""

    _instance: "CtdTextMaskGenerator | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        import onnxruntime as ort

        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"CTD model not found: {MODEL_PATH}")
        self._session = ort.InferenceSession(
            str(MODEL_PATH),
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name

    @classmethod
    def get(cls) -> "CtdTextMaskGenerator":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _letterbox(self, img: np.ndarray, size: int = INPUT_SIZE) -> tuple[np.ndarray, float, tuple[int, int]]:
        """等比缩放并 padding 到 size x size，返回 (padded, scale, (pad_w, pad_h))。"""
        h, w = img.shape[:2]
        scale = min(size / w, size / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        pad_w = (size - new_w) // 2
        pad_h = (size - new_h) // 2
        padded = np.full((size, size, 3), 114, dtype=np.uint8)  # YOLOv5 padding color
        padded[pad_h:pad_h + new_h, pad_w:pad_w + new_w] = resized
        return padded, scale, (pad_w, pad_h)

    def generate(self, image: Image.Image) -> Image.Image:
        """对整页生成文字像素 mask。

        Args:
            image: 原始页 (PIL RGB)

        Returns:
            L-mode PIL Image，与原图同尺寸。255=文字像素，0=其他。
        """
        orig_w, orig_h = image.size
        img = np.array(image.convert("RGB"))

        # letterbox 到 1024
        padded, scale, (pad_w, pad_h) = self._letterbox(img)

        # BGR→RGB 已在 PIL 转换完成；HWC→CHW，归一化到 [0,1]
        tensor = padded.astype(np.float32) / 255.0
        tensor = tensor.transpose(2, 0, 1)[None, ...]  # 1x3x1024x1024

        outputs = self._session.run(["seg"], {self._input_name: tensor})
        seg = np.asarray(outputs[0])[0, 0]  # 1024x1024, float32

        # 阈值化
        mask_1024 = (seg > SEG_THRESH).astype(np.uint8) * 255

        # 撤销 letterbox padding
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        mask_cropped = mask_1024[pad_h:pad_h + new_h, pad_w:pad_w + new_w]

        # 缩回原图尺寸
        mask_full = cv2.resize(mask_cropped, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

        # 轻微膨胀，覆盖文字描边（参考探针推荐 9x9 椭圆核 ×3，保守用 3 次）
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        mask_full = cv2.dilate(mask_full, kernel, iterations=3)

        return Image.fromarray(mask_full, mode="L")
