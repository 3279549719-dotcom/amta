"""TDD 切片1: FFC 模型定义 + lama-manga 权重加载测试。

验证:
1. 能从 amta.inpaint._lama_ffc 导入 FFCResNetGenerator
2. 构建 n_blocks=18 的 large arch 模型
3. 加载 lama-manga.safetensors 权重 (missing=0, unexpected=0)
4. 前向传播输出形状正确 (B,3,H,W)
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import torch
from safetensors.torch import load_file

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def find_lama_manga() -> Path:
    paths = glob.glob(r"D:\我的汉化\workflow\koharu_data\models\**\lama-manga.safetensors", recursive=True)
    assert paths, "lama-manga.safetensors not found"
    return Path(paths[0])


def test_import_ffc_generator():
    """能从 amta.inpaint._lama_ffc 导入 FFCResNetGenerator。"""
    from amta.inpaint._lama_ffc import FFCResNetGenerator
    assert FFCResNetGenerator is not None


def test_build_large_arch():
    """构建 n_blocks=18 的 large arch 模型，参数量约 51M。"""
    from amta.inpaint._lama_ffc import FFCResNetGenerator
    model = FFCResNetGenerator(
        input_nc=4, output_nc=3, ngf=64, n_blocks=18,
        add_out_act=False,
        init_conv_kwargs={'ratio_gin': 0, 'ratio_gout': 0, 'enable_lfu': False},
        downsample_conv_kwargs={'ratio_gin': 0, 'ratio_gout': 0, 'enable_lfu': False},
        resnet_conv_kwargs={'ratio_gin': 0.75, 'ratio_gout': 0.75, 'enable_lfu': False},
    )
    n_params = sum(p.numel() for p in model.parameters())
    assert 50_000_000 < n_params < 52_000_000, f"expected ~51M params, got {n_params}"


def test_load_lama_manga_weights():
    """加载 lama-manga.safetensors 权重，missing=0 unexpected=0。"""
    from amta.inpaint._lama_ffc import FFCResNetGenerator
    model = FFCResNetGenerator(
        input_nc=4, output_nc=3, ngf=64, n_blocks=18,
        add_out_act=False,
        init_conv_kwargs={'ratio_gin': 0, 'ratio_gout': 0, 'enable_lfu': False},
        downsample_conv_kwargs={'ratio_gin': 0, 'ratio_gout': 0, 'enable_lfu': False},
        resnet_conv_kwargs={'ratio_gin': 0.75, 'ratio_gout': 0.75, 'enable_lfu': False},
    )
    sd = load_file(str(find_lama_manga()))
    result = model.load_state_dict(sd, strict=False)
    assert len(result.missing_keys) == 0, f"missing keys: {result.missing_keys[:5]}"
    assert len(result.unexpected_keys) == 0, f"unexpected keys: {result.unexpected_keys[:5]}"


def test_forward_pass():
    """前向传播输出形状正确 (1,3,H,W)。"""
    from amta.inpaint._lama_ffc import FFCResNetGenerator
    model = FFCResNetGenerator(
        input_nc=4, output_nc=3, ngf=64, n_blocks=18,
        add_out_act=False,
        init_conv_kwargs={'ratio_gin': 0, 'ratio_gout': 0, 'enable_lfu': False},
        downsample_conv_kwargs={'ratio_gin': 0, 'ratio_gout': 0, 'enable_lfu': False},
        resnet_conv_kwargs={'ratio_gin': 0.75, 'ratio_gout': 0.75, 'enable_lfu': False},
    )
    model.eval()
    with torch.no_grad():
        img = torch.randn(1, 3, 256, 256)
        mask = torch.zeros(1, 1, 256, 256)
        mask[:, :, 100:150, 100:150] = 1.0
        output = model(img, mask)
    assert output.shape == (1, 3, 256, 256), f"expected (1,3,256,256), got {output.shape}"


if __name__ == "__main__":
    tests = [
        test_import_ffc_generator,
        test_build_large_arch,
        test_load_lama_manga_weights,
        test_forward_pass,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
    print(f"\n{'='*40}")
    print(f"Results: {len(tests)-failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
