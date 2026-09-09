"""
Q3 实验：hayai OCR token 级 confidence 对比 — 杂质框 vs 真实文本框。

测试框:
  杂质框:
    - p2 t04:  页面刻度线, OCR="...",       detect conf=0.704
    - p6 t08:  纯黑竖条/装订线, OCR=乱码,    detect conf=0.789
    - p31 t08: 边缘装饰线, OCR="美術館は、",  detect conf=0.725 (胡说八道!)
  真实文本框(对照):
    - p2 r00:  对话, detect conf=0.964
    - p6 r00:  对话, detect conf=0.962
    - p31 r00: 对话, detect conf=0.940

方法: 自定义 greedy decoding 收集每步 logits, softmax 计算 token 级 confidence。
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image

# 清除代理
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# hayai 模型目录加入 sys.path 以导入 modeling_hayai
MODEL_DIR = r"E:\models\hayai-ocr-v2"
if MODEL_DIR not in sys.path:
    sys.path.insert(0, MODEL_DIR)

from hayai_ocr import HayaiOcr
import modeling_hayai
compute_batch_2d_mrope_freqs = modeling_hayai.compute_batch_2d_mrope_freqs

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT_DIR = ROOT / "workspace" / "exp-q3-garbled-box-visual"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 测试框定义
# ============================================================
CASES = [
    # 杂质框
    {"page": 2,  "rid": "t04", "bbox": [463, 2247, 519, 2494],  "det_conf": 0.704, "type": "杂质-刻度线",   "expected_ocr": "..."},
    {"page": 6,  "rid": "t08", "bbox": [0, 1476, 26, 2333],     "det_conf": 0.789, "type": "杂质-黑竖条",   "expected_ocr": "(乱码)"},
    {"page": 31, "rid": "t08", "bbox": [246, 1490, 287, 2109],  "det_conf": 0.725, "type": "杂质-装饰线",   "expected_ocr": "美術館は、"},
    # 真实文本框(对照)
    {"page": 2,  "rid": "r00", "bbox": [654, 2305, 817, 2917],  "det_conf": 0.964, "type": "真实-对话",     "expected_ocr": ""},
    {"page": 6,  "rid": "r00", "bbox": [1443, 282, 1600, 900],  "det_conf": 0.962, "type": "真实-对话",     "expected_ocr": ""},
    {"page": 31, "rid": "r00", "bbox": [1729, 2105, 2003, 3030], "det_conf": 0.940, "type": "真实-对话",     "expected_ocr": ""},
]


# ============================================================
# 自定义 greedy decoding with confidence
# ============================================================
def greedy_decode_with_confidence(model, processor, tokenizer, img,
                                    max_new_tokens=128, repetition_penalty=1.0):
    """复制 HayaiModel.generate 的 greedy 路径，收集每步 logits 计算置信度。"""
    device = next(model.parameters()).device

    inputs = processor(images=[img], max_num_patches=256, return_tensors="pt")
    pixel_values = inputs.pixel_values.to(device)
    pixel_attention_mask = inputs.pixel_attention_mask.to(device)
    spatial_shapes = inputs.spatial_shapes.to(device)

    b = pixel_values.size(0)
    bos_id = tokenizer.bos_token_id if tokenizer.bos_token_id is not None else 1
    eos_id = tokenizer.eos_token_id if tokenizer.eos_token_id is not None else 2
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else eos_id

    # Vision Encoder
    vision_outputs = model.vision_encoder(
        pixel_values=pixel_values, pixel_attention_mask=pixel_attention_mask,
        spatial_shapes=spatial_shapes)
    visual_features = vision_outputs.last_hidden_state
    m_vision = visual_features.size(1)

    # Prefill (Vision + BOS)
    bos_tokens = torch.full((b, 1), bos_id, dtype=torch.long, device=device)
    vision_embeddings = model.decoder.projector(visual_features)
    bos_embeddings = model.decoder.token_embeddings(bos_tokens)
    x = torch.cat([vision_embeddings, bos_embeddings], dim=1)

    d_axis = model.decoder.layers[0].attn.d_head // 2
    freqs = 1.0 / (10000.0 ** (torch.arange(0, d_axis, 2, device=device).float() / d_axis))
    t_text_all = torch.arange(max_new_tokens + 1, device=device, dtype=torch.float32)
    text_freqs_1d_all = torch.outer(t_text_all, freqs)
    text_freqs_all = torch.cat([text_freqs_1d_all, text_freqs_1d_all], dim=-1)
    cos_text_all = torch.cos(text_freqs_all)
    sin_text_all = torch.sin(text_freqs_all)

    mask = model.decoder.generate_block_causal_mask(m_vision, 1, device)
    cos_batch, sin_batch = compute_batch_2d_mrope_freqs(
        spatial_shapes, m_vision, 1, d_head=64, device=device)

    kv_cache = {}
    for i, layer in enumerate(model.decoder.layers):
        x = layer(x, mask=mask, cos_sin=(cos_batch, sin_batch),
                  kv_cache=kv_cache, layer_idx=i)

    x_bos = x[:, -1:]
    x_bos = model.decoder.final_norm(x_bos)
    logits = model.decoder.output_head(x_bos)
    next_token_logits = logits[:, -1, :].clone()

    all_logits = []

    if repetition_penalty != 1.0:
        penalty = torch.full_like(next_token_logits, 1.0)
        penalty[:, bos_id] = repetition_penalty
        next_token_logits = torch.where(
            next_token_logits < 0, next_token_logits * penalty, next_token_logits / penalty)
    all_logits.append(next_token_logits.clone())
    next_tokens = torch.argmax(next_token_logits, dim=-1)

    generated_tokens = torch.full((b, max_new_tokens + 1), pad_id, dtype=torch.long, device=device)
    generated_tokens[:, 0] = bos_id
    generated_tokens[:, 1] = next_tokens
    unfinished = (next_tokens != eos_id) & (next_tokens != pad_id)

    for step in range(1, max_new_tokens):
        if not unfinished.any():
            break
        cur_input_tokens = next_tokens.unsqueeze(1)
        x_step = model.decoder.token_embeddings(cur_input_tokens)
        cos_step = cos_text_all[step].unsqueeze(0).expand(b, 1, -1)
        sin_step = sin_text_all[step].unsqueeze(0).expand(b, 1, -1)
        for i, layer in enumerate(model.decoder.layers):
            x_step = layer(x_step, mask=None, cos_sin=(cos_step, sin_step),
                           kv_cache=kv_cache, layer_idx=i)
        x_step = model.decoder.final_norm(x_step)
        logits_step = model.decoder.output_head(x_step)[:, -1, :].clone()
        if repetition_penalty != 1.0:
            penalty = torch.ones_like(logits_step)
            penalty = penalty.scatter(1, generated_tokens[:, :step+1], repetition_penalty)
            logits_step = torch.where(
                logits_step < 0, logits_step * penalty, logits_step / penalty)
        all_logits.append(logits_step.clone())
        next_tokens = torch.argmax(logits_step, dim=-1)
        next_tokens = next_tokens * unfinished + pad_id * (~unfinished)
        generated_tokens[:, step+1] = next_tokens
        unfinished = unfinished & (next_tokens != eos_id) & (next_tokens != pad_id)

    results = []
    for batch_idx in range(b):
        seq = generated_tokens[batch_idx].tolist()
        clean_tokens = [t for t in seq[1:] if t not in (eos_id, pad_id)]
        text = tokenizer.decode(clean_tokens, skip_special_tokens=True)
        token_confs = []
        for i, tid in enumerate(clean_tokens):
            if i < len(all_logits):
                probs = F.softmax(all_logits[i][batch_idx], dim=-1)
                conf = probs[tid].item()
                token_str = tokenizer.decode([tid])
                token_confs.append((token_str, conf))
        avg_conf = sum(c for _, c in token_confs) / len(token_confs) if token_confs else 0
        min_conf = min(c for _, c in token_confs) if token_confs else 0
        max_conf = max(c for _, c in token_confs) if token_confs else 0
        results.append({
            "text": text, "token_confs": token_confs,
            "avg_conf": avg_conf, "min_conf": min_conf, "max_conf": max_conf,
            "num_tokens": len(token_confs),
        })
    return results


# ============================================================
# 主流程
# ============================================================
def main():
    print("加载 hayai OCR 模型...")
    ocr = HayaiOcr(pretrained_model_name_or_path=MODEL_DIR)
    model = ocr.model
    processor = ocr.processor
    tokenizer = ocr.tokenizer
    print("模型加载完成\n")

    all_results = []

    for case in CASES:
        page = case["page"]
        rid = case["rid"]
        bbox = case["bbox"]
        ctype = case["type"]

        print(f"{'='*70}")
        print(f"测试: p{page} {rid} ({ctype})")
        print(f"  bbox: {bbox}, detect conf: {case['det_conf']}")

        # 裁框
        raw_path = RAW_DIR / f"{page}.jpg"
        raw_img = Image.open(raw_path).convert("RGB")
        x1, y1, x2, y2 = bbox
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(raw_img.width, x2), min(raw_img.height, y2)
        crop = raw_img.crop((x1, y1, x2, y2))
        crop_w, crop_h = crop.size
        print(f"  裁剪尺寸: {crop_w}x{crop_h}")

        # 保存裁剪图供调试
        crop_path = OUT_DIR / f"conf_p{page}_{rid}_crop.png"
        crop.save(crop_path)

        # 高层 API 对照
        try:
            text_high = ocr(str(crop_path))
            if isinstance(text_high, list):
                text_high = "".join(text_high)
            print(f"  高层API OCR: {text_high[:60]}")
        except Exception as e:
            text_high = f"ERROR: {e}"
            print(f"  高层API OCR 错误: {e}")

        # 自定义 decoding with confidence
        print(f"  运行自定义 greedy decoding...")
        with torch.no_grad():
            results = greedy_decode_with_confidence(model, processor, tokenizer, crop)
        r = results[0]

        print(f"  OCR 文本: {r['text'][:60]}")
        print(f"  token 数: {r['num_tokens']}")
        print(f"  平均 confidence: {r['avg_conf']:.4f}")
        print(f"  最低 confidence: {r['min_conf']:.4f}")
        print(f"  最高 confidence: {r['max_conf']:.4f}")

        confs = [c for _, c in r["token_confs"]]
        low_count = sum(1 for c in confs if c < 0.5)
        mid_count = sum(1 for c in confs if 0.5 <= c < 0.8)
        high_count = sum(1 for c in confs if c >= 0.8)
        low_ratio = low_count / len(confs) if confs else 0
        print(f"  confidence 分布: <0.5={low_count} ({low_ratio:.0%}), "
              f"0.5-0.8={mid_count}, >=0.8={high_count}")

        print(f"  逐 token confidence:")
        for i, (tok, conf) in enumerate(r["token_confs"][:20]):
            bar = "█" * int(conf * 20)
            print(f"    [{i:2d}] '{tok}' conf={conf:.4f} {bar}")

        all_results.append({
            "page": page, "rid": rid, "type": ctype,
            "det_conf": case["det_conf"],
            "bbox": bbox, "crop_size": [crop_w, crop_h],
            "ocr_text": r["text"], "num_tokens": r["num_tokens"],
            "avg_conf": round(r["avg_conf"], 4),
            "min_conf": round(r["min_conf"], 4),
            "max_conf": round(r["max_conf"], 4),
            "low_ratio": round(low_ratio, 4),
            "token_confs": [(tok, round(conf, 4)) for tok, conf in r["token_confs"]],
        })
        print()

    # ============================================================
    # 汇总对比
    # ============================================================
    print(f"\n{'='*70}")
    print("汇总对比")
    print(f"{'='*70}")
    print(f"{'页面':<6} {'ID':<5} {'类型':<12} {'det_conf':<9} {'token数':<7} "
          f"{'avg_conf':<9} {'min_conf':<9} {'<0.5占比':<9} {'OCR文本'}")
    print("-" * 100)
    for r in all_results:
        print(f"p{r['page']:<4} {r['rid']:<5} {r['type']:<12} {r['det_conf']:<9.3f} "
              f"{r['num_tokens']:<7} {r['avg_conf']:<9.4f} {r['min_conf']:<9.4f} "
              f"{r['low_ratio']:<9.0%} {r['ocr_text'][:30]}")

    # 保存 JSON
    json_path = OUT_DIR / "q3_ocr_confidence_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {json_path}")

    # 关键结论
    print(f"\n{'='*70}")
    print("关键观察")
    print(f"{'='*70}")
    garbled = [r for r in all_results if "杂质" in r["type"]]
    real = [r for r in all_results if "真实" in r["type"]]
    if garbled and real:
        g_avg = sum(r["avg_conf"] for r in garbled) / len(garbled)
        r_avg = sum(r["avg_conf"] for r in real) / len(real)
        print(f"  杂质框平均 avg_conf: {g_avg:.4f}")
        print(f"  真实框平均 avg_conf: {r_avg:.4f}")
        print(f"  差距: {r_avg - g_avg:.4f}")
        g_min = min(r["min_conf"] for r in garbled)
        r_min = min(r["min_conf"] for r in real)
        print(f"  杂质框最低 min_conf: {g_min:.4f}")
        print(f"  真实框最低 min_conf: {r_min:.4f}")

    # p31 t08 特别关注
    p31 = [r for r in all_results if r["page"] == 31 and r["rid"] == "t08"]
    if p31:
        r = p31[0]
        print(f"\n  ★ p31 t08 (胡说八道框) 重点观察:")
        print(f"    OCR: '{r['ocr_text']}'")
        print(f"    avg_conf={r['avg_conf']:.4f}, min_conf={r['min_conf']:.4f}, <0.5占比={r['low_ratio']:.0%}")
        if r["avg_conf"] > 0.8:
            print(f"    ⚠️  avg_conf > 0.8 — OCR confidence 区分不了胡说八道框!")
        else:
            print(f"    ✅ avg_conf < 0.8 — OCR confidence 可以区分胡说八道框!")


if __name__ == "__main__":
    main()
