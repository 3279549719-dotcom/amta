"""快速测试：hayai model.generate(output_scores=True) 是否可行"""
import os, sys
import torch
from pathlib import Path
from PIL import Image

for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("HF_HUB_OFFLINE","1")
os.environ.setdefault("TRANSFORMERS_OFFLINE","1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))

from hayai_ocr import HayaiOcr

MODEL_DIR = r"E:\models\hayai-ocr-v2"
print("加载模型...")
ocr = HayaiOcr(pretrained_model_name_or_path=MODEL_DIR)
model = ocr.model
processor = ocr.processor
tokenizer = ocr.tokenizer
device = ocr.device
print(f"模型加载完成, device={device}")

# 用 p2 r00 的裁图测试
crop_path = ROOT / "workspace/exp-q3-garbled-box-visual/conf_p2_r00_crop.png"
if not crop_path.exists():
    # 从原图裁
    raw = Image.open(r"D:\我的汉化\汉化作品\东方\单翼停留之地\2.jpg").convert("RGB")
    crop = raw.crop((654,2305,817,2917))
    crop.save(crop_path)

img = Image.open(crop_path).convert("RGB")
print(f"测试图片: {crop_path}, size={img.size}")

# 高层API对照
text_high = ocr(str(crop_path))
if isinstance(text_high, list): text_high = "".join(text_high)
print(f"高层API: {text_high[:50]}")

# 底层 generate + output_scores
print("\n=== 测试 model.generate(output_scores=True) ===")
inputs = processor(images=[img], max_num_patches=256, return_tensors="pt")
pixel_values = inputs.pixel_values.to(device)
pixel_attention_mask = inputs.pixel_attention_mask.to(device)
spatial_shapes = inputs.spatial_shapes.to(device)

try:
    with torch.no_grad():
        output = model.generate(
            pixel_values=pixel_values,
            pixel_attention_mask=pixel_attention_mask,
            spatial_shapes=spatial_shapes,
            tokenizer=tokenizer,
            max_new_tokens=64,
            repetition_penalty=1.0,
            output_scores=True,
            return_dict_in_generate=True,
        )
    print(f"返回类型: {type(output)}")
    print(f"属性: {[a for a in dir(output) if not a.startswith('_')]}")

    if hasattr(output, 'sequences'):
        seqs = output.sequences
        text_low = tokenizer.decode(seqs[0], skip_special_tokens=True)
        print(f"\n底层decode文本: {text_low[:50]}")

    if hasattr(output, 'scores'):
        scores = output.scores
        print(f"\nscores 类型: {type(scores)}, 长度: {len(scores)}")
        if len(scores) > 0:
            print(f"scores[0] shape: {scores[0].shape}")
            # 计算前5个token的confidence
            print("\n前5个token的max-prob confidence:")
            for i, score in enumerate(scores[:5]):
                probs = torch.softmax(score[0], dim=-1)
                max_prob, max_idx = probs.max(dim=-1)
                tok = tokenizer.decode([max_idx.item()])
                print(f"  [{i}] '{tok}' conf={max_prob.item():.4f}")
            print("\n✅ output_scores=True 可行!")
    else:
        print("\n❌ 没有scores属性")
        print(f"输出对象: {output}")

except Exception as e:
    print(f"\n❌ 报错: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
