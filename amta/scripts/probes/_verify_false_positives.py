"""快速验证：p32 r05 和 p39 r03 的完整 confidence 分布，对比假框 p31 t08。"""
from __future__ import annotations

import os, sys, json
from pathlib import Path
import torch
from PIL import Image

for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("HF_HUB_OFFLINE","1")
os.environ.setdefault("TRANSFORMERS_OFFLINE","1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
MODEL_DIR = r"E:\models\hayai-ocr-v2"
if MODEL_DIR not in sys.path:
    sys.path.insert(0, MODEL_DIR)

from hayai_ocr import HayaiOcr
from amta.ocr_engines import _hayai_greedy_decode_with_conf

print("加载模型...")
ocr = HayaiOcr(pretrained_model_name_or_path=MODEL_DIR)
print("模型加载完成\n")

cases = [
    ("p32 r05 (误伤-嫦娥)", ROOT/"workspace/exp-q3-full-ocr-test/crops/page_32/r05.png"),
    ("p39 r03 (误伤-八意様)", ROOT/"workspace/exp-q3-full-ocr-test/crops/page_39/r03.png"),
    ("p31 t08 (假框-美術館は、)", ROOT/"workspace/exp-q3-full-ocr-test/crops/page_31/t08.png"),
    ("p2 t04 (假框-...)", ROOT/"workspace/exp-q3-full-ocr-test/crops/page_2/t04.png"),
]

for name, path in cases:
    if not path.exists():
        print(f"{name}: 裁图不存在 {path}")
        continue
    img = Image.open(path).convert("RGB")
    with torch.no_grad():
        # 用完整的 decoding 获取所有 token conf
        # 这里复用 _hayai_greedy_decode_with_conf，但它只返回 first_token_conf
        # 我们需要完整的 token_confs，所以用探针里的完整版本
        result = _hayai_greedy_decode_with_conf(ocr.model, ocr.processor, ocr.tokenizer, img)
    print(f"{'='*60}")
    print(f"{name}")
    print(f"  OCR: {result['text']}")
    print(f"  first_token_conf: {result['first_token_conf']:.4f}")
    print(f"  num_tokens: {result['num_tokens']}")
    print()

# _hayai_greedy_decode_with_conf 只返回 first_token_conf，不返回完整 token_confs
# 让我用探针里的完整版本重新跑
print("\n\n=== 用完整 decoding 获取逐 token confidence ===")

# 复制探针里的 greedy_decode_with_confidence
import torch.nn.functional as F
import modeling_hayai
compute_batch_2d_mrope_freqs = modeling_hayai.compute_batch_2d_mrope_freqs

def full_decode(model, processor, tokenizer, img, max_new_tokens=128):
    device = next(model.parameters()).device
    inputs = processor(images=[img], max_num_patches=256, return_tensors="pt")
    pixel_values = inputs.pixel_values.to(device)
    pixel_attention_mask = inputs.pixel_attention_mask.to(device)
    spatial_shapes = inputs.spatial_shapes.to(device)
    b = pixel_values.size(0)
    bos_id = tokenizer.bos_token_id if tokenizer.bos_token_id is not None else 1
    eos_id = tokenizer.eos_token_id if tokenizer.eos_token_id is not None else 2
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else eos_id

    vision_outputs = model.vision_encoder(pixel_values=pixel_values, pixel_attention_mask=pixel_attention_mask, spatial_shapes=spatial_shapes)
    visual_features = vision_outputs.last_hidden_state
    m_vision = visual_features.size(1)
    bos_tokens = torch.full((b,1), bos_id, dtype=torch.long, device=device)
    vision_embeddings = model.decoder.projector(visual_features)
    bos_embeddings = model.decoder.token_embeddings(bos_tokens)
    x = torch.cat([vision_embeddings, bos_embeddings], dim=1)
    d_axis = model.decoder.layers[0].attn.d_head // 2
    freqs = 1.0 / (10000.0 ** (torch.arange(0, d_axis, 2, device=device).float() / d_axis))
    t_text_all = torch.arange(max_new_tokens+1, device=device, dtype=torch.float32)
    text_freqs_1d_all = torch.outer(t_text_all, freqs)
    text_freqs_all = torch.cat([text_freqs_1d_all, text_freqs_1d_all], dim=-1)
    cos_text_all = torch.cos(text_freqs_all)
    sin_text_all = torch.sin(text_freqs_all)
    mask = model.decoder.generate_block_causal_mask(m_vision, 1, device)
    cos_batch, sin_batch = compute_batch_2d_mrope_freqs(spatial_shapes, m_vision, 1, d_head=64, device=device)
    kv_cache = {}
    for i, layer in enumerate(model.decoder.layers):
        x = layer(x, mask=mask, cos_sin=(cos_batch, sin_batch), kv_cache=kv_cache, layer_idx=i)
    x_bos = model.decoder.final_norm(x[:, -1:])
    logits = model.decoder.output_head(x_bos)
    next_token_logits = logits[:, -1, :].clone()
    all_logits = [next_token_logits.clone()]
    next_tokens = torch.argmax(next_token_logits, dim=-1)
    generated_tokens = torch.full((b, max_new_tokens+1), pad_id, dtype=torch.long, device=device)
    generated_tokens[:, 0] = bos_id
    generated_tokens[:, 1] = next_tokens
    unfinished = (next_tokens != eos_id) & (next_tokens != pad_id)
    for step in range(1, max_new_tokens):
        if not unfinished.any(): break
        cur_input_tokens = next_tokens.unsqueeze(1)
        x_step = model.decoder.token_embeddings(cur_input_tokens)
        cos_step = cos_text_all[step].unsqueeze(0).expand(b, 1, -1)
        sin_step = sin_text_all[step].unsqueeze(0).expand(b, 1, -1)
        for i, layer in enumerate(model.decoder.layers):
            x_step = layer(x_step, mask=None, cos_sin=(cos_step, sin_step), kv_cache=kv_cache, layer_idx=i)
        x_step = model.decoder.final_norm(x_step)
        logits_step = model.decoder.output_head(x_step)[:, -1, :].clone()
        all_logits.append(logits_step.clone())
        next_tokens = torch.argmax(logits_step, dim=-1)
        next_tokens = next_tokens * unfinished + pad_id * (~unfinished)
        generated_tokens[:, step+1] = next_tokens
        unfinished = unfinished & (next_tokens != eos_id) & (next_tokens != pad_id)
    seq = generated_tokens[0].tolist()
    clean_tokens = [t for t in seq[1:] if t not in (eos_id, pad_id)]
    text = tokenizer.decode(clean_tokens, skip_special_tokens=True)
    token_confs = []
    for i, tid in enumerate(clean_tokens):
        if i < len(all_logits):
            probs = F.softmax(all_logits[i][0], dim=-1)
            conf = probs[tid].item()
            tok_str = tokenizer.decode([tid])
            token_confs.append((tok_str, conf))
    avg_conf = sum(c for _,c in token_confs)/len(token_confs) if token_confs else 0
    min_conf = min(c for _,c in token_confs) if token_confs else 0
    low_ratio = sum(1 for _,c in token_confs if c < 0.5)/len(token_confs) if token_confs else 0
    return {"text": text, "token_confs": token_confs, "avg_conf": avg_conf, "min_conf": min_conf, "low_ratio": low_ratio, "num_tokens": len(token_confs)}


for name, path in cases:
    if not path.exists(): continue
    img = Image.open(path).convert("RGB")
    with torch.no_grad():
        r = full_decode(ocr.model, ocr.processor, ocr.tokenizer, img)
    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"  OCR: {r['text']}")
    print(f"  first_conf: {r['token_confs'][0][1]:.4f}" if r['token_confs'] else "  N/A")
    print(f"  avg_conf: {r['avg_conf']:.4f}")
    print(f"  min_conf: {r['min_conf']:.4f}")
    print(f"  low_ratio(<0.5): {r['low_ratio']:.0%}")
    print(f"  num_tokens: {r['num_tokens']}")
    print(f"  逐 token:")
    for i, (tok, conf) in enumerate(r['token_confs'][:10]):
        bar = "█" * int(conf * 20)
        print(f"    [{i:2d}] '{tok}' conf={conf:.4f} {bar}")
