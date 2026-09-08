"""
探针：深入hayai底层模型，测试能不能拿到token级output_scores。
目标：验证"上位者规则"（OCR平均置信度过滤）是否可行。
"""
import os
import sys
import torch

# 代理没开时直连
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, "src")

from hayai_ocr import HayaiOcr
from PIL import Image

model_path = os.environ.get("HAYAI_OCR_MODEL", r"E:\models\hayai-ocr-v2")
print(f"加载模型: {model_path}")
ocr = HayaiOcr(pretrained_model_name_or_path=model_path)
print("模型加载完成")

# 取到底层组件
model = ocr.model
processor = ocr.processor
tokenizer = ocr.tokenizer
device = ocr.device
print(f"底层model类型: {type(model).__name__}")
print(f"device: {device}")

# 测试图片：真实文本（p0的r01）
test_img_path = r"E:\manga translator agent\amta\workspace\touhou-remove-geo-rules\artifacts\crops\r01.png"
if not os.path.exists(test_img_path):
    # 找一张可用的图片
    import glob
    crops = sorted(glob.glob(r"E:\manga translator agent\amta\workspace\touhou-remove-geo-rules\artifacts\crops\*.png"))
    test_img_path = crops[0] if crops else None
    print(f"使用替代图片: {test_img_path}")

if not test_img_path:
    print("没有测试图片，退出")
    sys.exit(1)

print(f"\n测试图片: {os.path.basename(test_img_path)}")
img = Image.open(test_img_path).convert("RGB")

# 第一步：用高层API跑一次，拿到文本作为对照
print("\n=== 第一步：高层API（对照） ===")
text_high = ocr(test_img_path)
print(f"高层API输出: {text_high}")

# 第二步：手动预处理，调用底层generate，尝试output_scores
print("\n=== 第二步：底层generate + output_scores=True ===")
inputs = processor(images=[img], max_num_patches=256, return_tensors="pt")
pixel_values = inputs.pixel_values.to(device)
pixel_attention_mask = inputs.pixel_attention_mask.to(device)
spatial_shapes = inputs.spatial_shapes.to(device)

print(f"pixel_values shape: {pixel_values.shape}")
print(f"pixel_attention_mask shape: {pixel_attention_mask.shape}")
print(f"spatial_shapes: {spatial_shapes}")

try:
    with torch.no_grad():
        output = model.generate(
            pixel_values=pixel_values,
            pixel_attention_mask=pixel_attention_mask,
            spatial_shapes=spatial_shapes,
            tokenizer=tokenizer,
            max_new_tokens=128,
            repetition_penalty=1.0,
            output_scores=True,
            return_dict_in_generate=True,
        )
    print(f"\n底层generate返回类型: {type(output)}")
    print(f"返回对象属性: {dir(output)}")
    
    # 尝试提取各种可能的字段
    if hasattr(output, 'sequences'):
        seqs = output.sequences
        print(f"\nsequences shape: {seqs.shape}")
        text_low = tokenizer.decode(seqs[0], skip_special_tokens=True)
        print(f"底层decode文本: {text_low}")
    
    if hasattr(output, 'scores'):
        scores = output.scores
        print(f"\nscores类型: {type(scores)}, 长度: {len(scores)}")
        if len(scores) > 0:
            print(f"scores[0] shape: {scores[0].shape}")
            # 计算每个token的max概率（置信度）
            print("\n=== 逐token置信度 ===")
            confidences = []
            for i, score in enumerate(scores):
                # score shape: (batch_size, vocab_size)
                probs = torch.softmax(score[0], dim=-1)
                max_prob, max_idx = probs.max(dim=-1)
                token_str = tokenizer.decode([max_idx.item()])
                conf = max_prob.item()
                confidences.append(conf)
                if i < 20:  # 只打印前20个
                    print(f"  token[{i:2d}]: '{token_str}' conf={conf:.4f}")
            
            avg_conf = sum(confidences) / len(confidences) if confidences else 0
            min_conf = min(confidences) if confidences else 0
            print(f"\n统计: 共{len(confidences)}个token")
            print(f"  平均置信度: {avg_conf:.4f}")
            print(f"  最低置信度: {min_conf:.4f}")
            print(f"  最高置信度: {max(confidences):.4f}")
    else:
        print("\n没有scores属性！output_scores可能不被支持")
        # 打印返回对象的所有内容
        print(f"返回对象: {output}")
        
except Exception as e:
    print(f"\n底层generate报错: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\n=== 探针结束 ===")
