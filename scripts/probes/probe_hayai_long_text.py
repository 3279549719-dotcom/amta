"""探针：hayai 对长段无框线文字的 OCR，调大 max_new_tokens / max_num_patches 能否救回。

对照 4 组：
  A. baseline: max_new_tokens=128, max_num_patches=256（现状硬编码）
  B. 只加 token: max_new_tokens=512, max_num_patches=256
  C. 只加视觉:   max_new_tokens=128, max_num_patches=1024
  D. 都加:       max_new_tokens=512, max_num_patches=1024

用法: uv run python scripts/probes/probe_hayai_long_text.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch
import torch.nn.functional as F
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

CROP = ROOT / "workspace" / "touhou-single-wing" / "artifacts" / "crops" / "r00.png"


def run_once(model, processor, tokenizer, img, *, max_new_tokens, max_num_patches):
    """复制 _hayai_greedy_decode_with_conf 的核心逻辑，参数化 max_new_tokens / max_num_patches。"""
    import modeling_hayai
    compute_batch_2d_mrope_freqs = modeling_hayai.compute_batch_2d_mrope_freqs

    device = next(model.parameters()).device
    inputs = processor(images=[img], max_num_patches=max_num_patches, return_tensors="pt")
    pixel_values = inputs.pixel_values.to(device)
    pixel_attention_mask = inputs.pixel_attention_mask.to(device)
    spatial_shapes = inputs.spatial_shapes.to(device)

    b = pixel_values.size(0)
    bos_id = tokenizer.bos_token_id if tokenizer.bos_token_id is not None else 1
    eos_id = tokenizer.eos_token_id if tokenizer.eos_token_id is not None else 2
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else eos_id

    with torch.no_grad():
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

        x_bos = model.decoder.final_norm(x[:, -1:])
        logits = model.decoder.output_head(x_bos)
        next_token_logits = logits[:, -1, :].clone()
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
            next_tokens = torch.argmax(logits_step, dim=-1)
            next_tokens = next_tokens * unfinished + pad_id * (~unfinished)
            generated_tokens[:, step + 1] = next_tokens
            unfinished = unfinished & (next_tokens != eos_id) & (next_tokens != pad_id)

    seq = generated_tokens[0].tolist()
    clean_tokens = [t for t in seq[1:] if t not in (eos_id, pad_id)]
    text = tokenizer.decode(clean_tokens, skip_special_tokens=True)
    return text, len(clean_tokens)


def main():
    from hayai_ocr import HayaiOcr
    model_path = os.environ.get("HAYAI_OCR_MODEL", r"E:\models\hayai-ocr-v2")
    if model_path not in sys.path:
        sys.path.insert(0, model_path)

    print(f"[probe] loading hayai from {model_path} ...")
    t0 = time.time()
    ocr = HayaiOcr(pretrained_model_name_or_path=model_path)
    print(f"[probe] loaded in {time.time()-t0:.1f}s")

    img = Image.open(CROP).convert("RGB")
    print(f"[probe] crop size: {img.size}")

    configs = [
        ("A baseline (128 tok, 256 patch)", 128, 256),
        ("B +token (512 tok, 256 patch)", 512, 256),
        ("C +visual (128 tok, 1024 patch)", 128, 1024),
        ("D both (512 tok, 1024 patch)", 512, 1024),
    ]
    for name, nt, np_ in configs:
        t1 = time.time()
        text, n_tok = run_once(ocr.model, ocr.processor, ocr.tokenizer, img,
                               max_new_tokens=nt, max_num_patches=np_)
        dt = time.time() - t1
        print(f"\n===== {name} | {dt:.1f}s | {n_tok} tokens =====")
        print(text[:500])


if __name__ == "__main__":
    main()
