"""本地 LaMa inpainting 封装 — 支持 big-lama (TorchScript) 和 lama-manga (FFC ResNet)。

两种模型:
- big-lama (默认): 通用自然图像模型, simple-lama-inpainting 的 TorchScript 格式
- lama-manga: 漫画微调模型, Koharu 使用, FFC ResNet large arch (n_blocks=18)

lama-manga 质量远优于 big-lama (能去掉漫画文字), 速度相近。
"""
from __future__ import annotations

import glob
import os
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

from ._lama_model import SimpleLama

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "big-lama.pt"

# lama-manga.safetensors 在 Koharu 数据目录下
_LAMA_MANGA_GLOB = r"D:\我的汉化\workflow\koharu_data\models\**\lama-manga.safetensors"


def _find_lama_manga_path() -> Path:
    """查找 lama-manga.safetensors 文件路径。"""
    paths = glob.glob(_LAMA_MANGA_GLOB, recursive=True)
    if not paths:
        raise FileNotFoundError(
            f"lama-manga.safetensors not found. Searched: {_LAMA_MANGA_GLOB}"
        )
    # 优先选 snapshot 下的（非 placeholder）
    for p in paths:
        if "main_placeholder" not in p:
            return Path(p)
    return Path(paths[0])


class _LamaMangaModel:
    """lama-manga FFC ResNet 模型封装。"""

    def __init__(self, device: torch.device, model_path: Path | None = None) -> None:
        from ._lama_ffc import FFCResNetGenerator
        from safetensors.torch import load_file

        self.device = device
        path = model_path or _find_lama_manga_path()
        if not path.exists():
            raise FileNotFoundError(f"lama-manga model not found: {path}")

        self.model = FFCResNetGenerator(
            input_nc=4, output_nc=3, ngf=64, n_blocks=18,
            add_out_act=False,
            init_conv_kwargs={'ratio_gin': 0, 'ratio_gout': 0, 'enable_lfu': False},
            downsample_conv_kwargs={'ratio_gin': 0, 'ratio_gout': 0, 'enable_lfu': False},
            resnet_conv_kwargs={'ratio_gin': 0.75, 'ratio_gout': 0.75, 'enable_lfu': False},
        )
        sd = load_file(str(path))
        self.model.load_state_dict(sd, strict=True)
        self.model.eval()
        self.model.to(device)

    @staticmethod
    def _pad_to_modulo(img: torch.Tensor, mod: int = 8) -> tuple[torch.Tensor, int, int]:
        """将图像 padding 到 mod 的倍数，返回 (padded, pad_h, pad_w)。"""
        _, _, h, w = img.shape
        pad_h = (mod - h % mod) % mod
        pad_w = (mod - w % mod) % mod
        if pad_h > 0 or pad_w > 0:
            img = torch.nn.functional.pad(img, (0, pad_w, 0, pad_h), mode='reflect')
        return img, pad_h, pad_w

    def __call__(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        """推理: image (RGB), mask (L) -> inpainted RGB Image。

        整页推理优化（参考 ADR-029 + inpaint-speed-ab-test 第十二节）:
        - 推理前缩小到 max_width=1024（等比例），推理后放大回原尺寸
        - 速度: ~20s/页（原始尺寸 ~200s+，快 87%）
        - 质量: 全局上下文充足，无白色方框，网点贴合
        - 预处理: 输入 [0,1] 归一化 + mask 二值化
        - 后处理: sigmoid 输出 + 羽化 mask alpha 混合（在原始尺寸做）
        """
        orig_w, orig_h = image.size

        # ---- 推理缩放：大图缩小到 1024 宽 ----
        MAX_INFER_WIDTH = 1024
        scale = 1.0
        infer_img = image
        infer_mask = mask
        if orig_w > MAX_INFER_WIDTH:
            scale = MAX_INFER_WIDTH / orig_w
            new_w = MAX_INFER_WIDTH
            new_h = max(1, int(orig_h * scale))
            infer_img = image.resize((new_w, new_h), Image.LANCZOS)
            infer_mask = mask.resize((new_w, new_h), Image.NEAREST)

        infer_w, infer_h = infer_img.size

        # 归一化: image -> [0, 1], mask -> {0, 1}
        img_np = np.array(infer_img).astype(np.float32) / 255.0
        mask_np = (np.array(infer_mask).astype(np.float32) > 0).astype(np.float32)

        img_t = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0).to(self.device)
        mask_t = torch.from_numpy(mask_np).unsqueeze(0).unsqueeze(0).to(self.device)

        # padding 到 8 的倍数
        img_t, pad_h, pad_w = self._pad_to_modulo(img_t, 8)
        mask_t, _, _ = self._pad_to_modulo(mask_t, 8)

        with torch.inference_mode():
            output = self.model(img_t, mask_t)

        # 输出过 sigmoid (限制到 [0, 1])
        output = torch.sigmoid(output)

        # 裁剪掉 padding（回到推理尺寸）
        if pad_h > 0 or pad_w > 0:
            output = output[:, :, :infer_h, :infer_w]

        # 放大回原始尺寸
        if scale < 1.0:
            output = torch.nn.functional.interpolate(
                output, size=(orig_h, orig_w),
                mode="bilinear", align_corners=False,
            )

        # ---- 在原始尺寸做 mask 羽化 + alpha 混合 ----
        orig_mask_np = (np.array(mask).astype(np.float32) > 0).astype(np.float32)
        orig_mask_blur = cv2.GaussianBlur(orig_mask_np, (21, 21), 0)
        mask_blur = torch.from_numpy(orig_mask_blur).unsqueeze(0).unsqueeze(0).to(self.device)

        orig_img_np = np.array(image).astype(np.float32) / 255.0
        orig_img_t = torch.from_numpy(orig_img_np).permute(2, 0, 1).unsqueeze(0).to(self.device)

        result = orig_img_t * (1 - mask_blur) + output * mask_blur

        # 转回 [0, 255] uint8
        result_np = result[0].permute(1, 2, 0).cpu().numpy() * 255.0
        result_np = np.clip(result_np, 0, 255).astype(np.uint8)
        return Image.fromarray(result_np)


class LocalLamaInpainter:
    """本地 LaMa 推理, 消除 Koharu HTTP 开销。

    支持两种模型:
    - model_type="big-lama" (默认): 通用模型, TorchScript 格式
    - model_type="lama-manga": 漫画微调模型, 质量更好
    """

    def __init__(
        self,
        device: str = "cpu",
        model_path: Path | None = None,
        model_type: str = "big-lama",
    ) -> None:
        self.device = torch.device(device)
        self.model_type = model_type
        t0 = time.time()

        if model_type == "big-lama":
            path = str(model_path or MODEL_PATH)
            if not Path(path).exists():
                raise FileNotFoundError(f"big-lama model not found: {path}")
            os.environ["LAMA_MODEL"] = path
            self.model = SimpleLama(device=self.device)
        elif model_type == "lama-manga":
            self.model = _LamaMangaModel(device=self.device, model_path=model_path)
        else:
            raise ValueError(f"Unknown model_type: {model_type}. Use 'big-lama' or 'lama-manga'.")

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
            mask = mask.resize(image.size, Image.Resampling.NEAREST)
        result = self.model(image, mask)
        # 裁剪回原图尺寸 (padding 可能导致尺寸变化)
        if result.size != (orig_w, orig_h):
            result = result.crop((0, 0, orig_w, orig_h))
        return result

    def inpaint_timed(self, image, mask) -> tuple[Image.Image, float]:
        """inpaint + 计时。"""
        t0 = time.time()
        result = self.inpaint(image, mask)
        return result, time.time() - t0
