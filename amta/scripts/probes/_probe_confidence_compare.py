"""
探针v3：对比真实文本 vs 假框/乱码的置信度分布。
重点测t08（疑似p6黑竖条）、t04、t05。
"""
import os
import sys
import torch
import torch.nn.functional as F

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
sys.path.insert(0, "src")

_model_dir = r"E:\models\hayai-ocr-v2"
if _model_dir not in sys.path:
    sys.path.insert(0, _model_dir)

from hayai_ocr import HayaiOcr
from PIL import Image
import modeling_hayai
compute_batch_2d_mrope_freqs = modeling_hayai.compute_batch_2d_mrope_freqs

model_path = os.environ.get("HAYAI_OCR_MODEL", r"E:\models\hayai-ocr-v2")
print(f"加载模型: {model_path}")
ocr = HayaiOcr(pretrained_model_name_or_path=model_path)
print("模型加载完成\n")

model = ocr.model
processor = ocr.processor
tokenizer = ocr.tokenizer
device = ocr.device


def greedy_decode_with_confidence(model, processor, tokenizer, img,
                                    max_new_tokens=128, repetition_penalty=1.0):
    device = next(model.parameters()).device
    inputs = processor(images=[img], max_num_patches=256, return_tensors="pt")
    pixel_values = inputs.pixel_values.to(device)
    pixel_attention_mask = inputs.pixel_attention_mask.to(device)
    spatial_shapes = inputs.spatial_shapes.to(device)

    b = pixel_values.size(0)
    bos_id = tokenizer.bos_token_id if tokenizer.bos_token_id is not None else 1
    eos_id = tokenizer.eos_token_id if tokenizer.eos_token_id is not None else 2
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else eos_id

    vision_outputs = model.vision_encoder(
        pixel_values=pixel_values, pixel_attention_mask=pixel_attention_mask,
        spatial_shapes=spatial_shapes)
    visual_features = vision_outputs.last_hidden_state
    m_vision = visual_features.size(1)

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
        results.append({"text": text, "token_confs": token_confs,
                        "avg_conf": avg_conf, "min_conf": min_conf,
                        "max_conf": max_conf, "num_tokens": len(token_confs)})
    return results


# ============================================================
# 测试对比
# ============================================================
crops_dir = r"E:\manga translator agent\amta\workspace\touhou-remove-geo-rules\artifacts\crops"

# 测t08（疑似黑竖条）、t04、t05，以及一个真实文本r00做对照
test_files = ["t08.png", "t04.png", "t05.png", "r00.png"]

all_results = []
for fname in test_files:
    fpath = os.path.join(crops_dir, fname)
    if not os.path.exists(fpath):
        print(f"跳过（不存在）: {fname}")
        continue

    print(f"\n{'='*60}")
    print(f"测试: {fname}")
    img = Image.open(fpath).convert("RGB")
    print(f"图片尺寸: {img.size}")

    text_high = ocr(fpath)
    print(f"高层API文本: {text_high[:80]}")

    with torch.no_grad():
        results = greedy_decode_with_confidence(model, processor, tokenizer, img)
    r = results[0]
    print(f"自定义文本: {r['text'][:80]}")
    print(f"token数: {r['num_tokens']}")
    print(f"平均置信度: {r['avg_conf']:.4f}")
    print(f"最低置信度: {r['min_conf']:.4f}")
    print(f"最高置信度: {r['max_conf']:.4f}")

    # 置信度分布统计
    confs = [c for _, c in r['token_confs']]
    low_count = sum(1 for c in confs if c < 0.5)
    mid_count = sum(1 for c in confs if 0.5 <= c < 0.8)
    high_count = sum(1 for c in confs if c >= 0.8)
    print(f"置信度分布: <0.5={low_count}, 0.5-0.8={mid_count}, >0.8={high_count}")

    print(f"逐token（前20个）:")
    for i, (tok, conf) in enumerate(r['token_confs'][:20]):
        bar = "█" * int(conf * 20)
        print(f"  [{i:2d}] '{tok}' conf={conf:.4f} {bar}")

    all_results.append({"file": fname, **r})

# 汇总对比
print(f"\n{'='*60}")
print("汇总对比")
print(f"{'文件':<10} {'类型':<8} {'token数':<8} {'平均conf':<10} {'最低conf':<10} {'<0.5占比':<10}")
print("-" * 60)
for r in all_results:
    confs = [c for _, c in r['token_confs']]
    low_ratio = sum(1 for c in confs if c < 0.5) / len(confs) if confs else 0
    ftype = "真实" if r['avg_conf'] > 0.85 else "疑似假框"
    print(f"{r['file']:<10} {ftype:<8} {r['num_tokens']:<8} {r['avg_conf']:<10.4f} {r['min_conf']:<10.4f} {low_ratio:<10.2%}")

print("\n探针结束")
