"""
Q3 全量实验：hayai OCR token 级 confidence — 全量可疑框 + 对照框。

样本策略:
  - 全部 detect conf < 0.85 的框 (39个: 20副引擎新增 + 19主引擎低conf)
  - 随机抽样 20 个 detect conf > 0.95 的真实框作为对照
  - 总共约 59 个框

方法: 自定义 greedy decoding 收集每步 logits, softmax 计算 token 级 confidence。
支持断点续跑: 已保存的框跳过。
"""
from __future__ import annotations

import os, sys, json, random, time
from pathlib import Path

import torch
import torch.nn.functional as F
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
import modeling_hayai
compute_batch_2d_mrope_freqs = modeling_hayai.compute_batch_2d_mrope_freqs

RAW_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DET_DIR = ROOT / "workspace/touhou-tiling-e2e/artifacts/detection"
OUT_DIR = ROOT / "workspace/exp-q3-garbled-box-visual"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULT_PATH = OUT_DIR / "q3_ocr_confidence_full.json"
CROP_DIR = OUT_DIR / "crops_full"
CROP_DIR.mkdir(exist_ok=True)

random.seed(42)


# ============================================================
# 自定义 greedy decoding with confidence (复用 v3 探针)
# ============================================================
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
    cos_batch, sin_batch = compute_batch_2d_mrope_freqs(
        spatial_shapes, m_vision, 1, d_head=64, device=device)

    kv_cache = {}
    for i, layer in enumerate(model.decoder.layers):
        x = layer(x, mask=mask, cos_sin=(cos_batch, sin_batch),
                  kv_cache=kv_cache, layer_idx=i)

    x_bos = model.decoder.final_norm(x[:, -1:])
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

    generated_tokens = torch.full((b, max_new_tokens+1), pad_id, dtype=torch.long, device=device)
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
                tok_str = tokenizer.decode([tid])
                token_confs.append((tok_str, conf))
        avg_conf = sum(c for _,c in token_confs)/len(token_confs) if token_confs else 0
        min_conf = min(c for _,c in token_confs) if token_confs else 0
        max_conf = max(c for _,c in token_confs) if token_confs else 0
        results.append({
            "text": text, "token_confs": token_confs,
            "avg_conf": avg_conf, "min_conf": min_conf, "max_conf": max_conf,
            "num_tokens": len(token_confs),
        })
    return results


# ============================================================
# 主流程
# ============================================================
def load_all_boxes():
    """加载所有检测框"""
    all_boxes = []
    for f in sorted(DET_DIR.glob("page_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        page = data["page"]
        page_num = int(page.replace("page_", ""))
        for b in data["blocks"]:
            b["page"] = page
            b["page_num"] = page_num
            all_boxes.append(b)
    return all_boxes


def select_samples(all_boxes):
    """选择样本: 全部 conf<0.85 + 随机20个 conf>0.95"""
    suspicious = [b for b in all_boxes if b["confidence"] < 0.85]
    high_conf = [b for b in all_boxes if b["confidence"] >= 0.95]
    random.shuffle(high_conf)
    controls = high_conf[:20]
    samples = suspicious + controls
    # 去重
    seen = set()
    unique = []
    for b in samples:
        key = (b["page"], b["region_id"])
        if key not in seen:
            seen.add(key)
            unique.append(b)
    print(f"样本选择: 可疑框(conf<0.85)={len(suspicious)}, 对照框(conf>=0.95)={len(controls)}, 去重后={len(unique)}")
    return unique


def crop_box(box):
    """裁框，返回 PIL Image"""
    page_num = box["page_num"]
    raw_path = RAW_DIR / f"{page_num}.jpg"
    raw_img = Image.open(raw_path).convert("RGB")
    x1, y1, x2, y2 = box["bbox"]
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(raw_img.width, int(x2)), min(raw_img.height, int(y2))
    return raw_img.crop((x1, y1, x2, y2))


def main():
    print("加载 hayai OCR 模型...")
    ocr = HayaiOcr(pretrained_model_name_or_path=MODEL_DIR)
    model = ocr.model
    processor = ocr.processor
    tokenizer = ocr.tokenizer
    print("模型加载完成\n")

    all_boxes = load_all_boxes()
    samples = select_samples(all_boxes)

    # 加载已有结果(断点续跑)
    if RESULT_PATH.exists():
        existing = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        done_keys = {(r["page"], r["rid"]) for r in existing}
        print(f"已有结果: {len(existing)} 个框, 跳过已完成的")
    else:
        existing = []
        done_keys = set()

    results = existing
    total = len(samples)
    skipped = 0
    t0 = time.time()

    for idx, box in enumerate(samples):
        key = (box["page"], box["region_id"])
        if key in done_keys:
            skipped += 1
            continue

        page_num = box["page_num"]
        rid = box["region_id"]
        conf = box["confidence"]
        btype = box["bubble_type"]
        engines = box["source_engines"]
        is_tiled_only = engines == ["rtdetr-v2-tiled"]

        # 裁框
        crop = crop_box(box)
        crop_w, crop_h = crop.size

        # 保存裁图
        crop_path = CROP_DIR / f"p{page_num}_{rid}.png"
        crop.save(crop_path)

        # 跑 confidence
        with torch.no_grad():
            dec_results = greedy_decode_with_confidence(model, processor, tokenizer, crop)
        r = dec_results[0]

        confs = [c for _, c in r["token_confs"]]
        first_conf = confs[0] if confs else 0
        low_count = sum(1 for c in confs if c < 0.5)
        low_ratio = low_count / len(confs) if confs else 0

        elapsed = time.time() - t0
        done_count = len(results) - len(existing) + 1
        avg_time = elapsed / done_count if done_count > 0 else 0
        eta = avg_time * (total - len(results))

        result = {
            "page": box["page"], "page_num": page_num, "rid": rid,
            "det_conf": round(conf, 4), "bubble_type": btype,
            "source_engines": engines, "is_tiled_only": is_tiled_only,
            "bbox": box["bbox"], "crop_size": [crop_w, crop_h],
            "ocr_text": r["text"], "num_tokens": r["num_tokens"],
            "first_token_conf": round(first_conf, 4),
            "avg_conf": round(r["avg_conf"], 4),
            "min_conf": round(r["min_conf"], 4),
            "max_conf": round(r["max_conf"], 4),
            "low_ratio": round(low_ratio, 4),
            "token_confs": [(tok, round(c,4)) for tok, c in r["token_confs"]],
        }
        results.append(result)

        # 实时保存
        RESULT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[{idx+1}/{total}] p{page_num} {rid} det={conf:.3f} "
              f"first={first_conf:.3f} avg={r['avg_conf']:.3f} "
              f"tokens={r['num_tokens']} low={low_ratio:.0%} "
              f"{'TILED' if is_tiled_only else 'main '} "
              f"ETA={eta/60:.1f}min | {r['text'][:30]}")

    print(f"\n完成! 共 {len(results)} 个框, 跳过 {skipped} 个, 耗时 {(time.time()-t0)/60:.1f} 分钟")

    # ============================================================
    # 汇总分析
    # ============================================================
    print(f"\n{'='*80}")
    print("汇总分析")
    print(f"{'='*80}")

    # 按 first_token_conf 排序
    sorted_by_first = sorted(results, key=lambda x: x["first_token_conf"])
    print(f"\n按 first_token_conf 升序 (前20):")
    print(f"{'页面':<8} {'ID':<5} {'det':<6} {'first':<7} {'avg':<7} {'tokens':<7} {'low%':<6} {'类型':<10} OCR")
    print("-" * 100)
    for r in sorted_by_first[:20]:
        print(f"p{r['page_num']:<6} {r['rid']:<5} {r['det_conf']:<6.3f} "
              f"{r['first_token_conf']:<7.4f} {r['avg_conf']:<7.4f} "
              f"{r['num_tokens']:<7} {r['low_ratio']:<6.0%} "
              f"{'TILED' if r['is_tiled_only'] else 'main':<10} {r['ocr_text'][:25]}")

    # 阈值分析: first_token_conf 在不同阈值下的分类
    print(f"\n{'='*80}")
    print("阈值分析 (first_token_conf)")
    print(f"{'='*80}")
    for thresh in [0.3, 0.4, 0.5, 0.6, 0.7]:
        below = [r for r in results if r["first_token_conf"] < thresh]
        above = [r for r in results if r["first_token_conf"] >= thresh]
        tiled_below = [r for r in below if r["is_tiled_only"]]
        main_below = [r for r in below if not r["is_tiled_only"]]
        print(f"\n阈值 {thresh}:")
        print(f"  低于阈值: {len(below)} (副引擎新增={len(tiled_below)}, 主引擎={len(main_below)})")
        print(f"  高于阈值: {len(above)}")
        if below:
            print(f"  低于阈值的框:")
            for r in sorted(below, key=lambda x: x["first_token_conf"]):
                print(f"    p{r['page_num']} {r['rid']} first={r['first_token_conf']:.4f} "
                      f"det={r['det_conf']:.3f} {'TILED' if r['is_tiled_only'] else 'main'} "
                      f"| {r['ocr_text'][:30]}")

    # avg_conf 阈值分析
    print(f"\n{'='*80}")
    print("阈值分析 (avg_conf)")
    print(f"{'='*80}")
    for thresh in [0.5, 0.6, 0.7, 0.8]:
        below = [r for r in results if r["avg_conf"] < thresh]
        above = [r for r in results if r["avg_conf"] >= thresh]
        print(f"  阈值 {thresh}: 低于={len(below)}, 高于={len(above)}")
        if below:
            for r in sorted(below, key=lambda x: x["avg_conf"]):
                print(f"    p{r['page_num']} {r['rid']} avg={r['avg_conf']:.4f} "
                      f"first={r['first_token_conf']:.4f} det={r['det_conf']:.3f} "
                      f"{'TILED' if r['is_tiled_only'] else 'main'} | {r['ocr_text'][:25]}")

    print(f"\n结果已保存: {RESULT_PATH}")


if __name__ == "__main__":
    main()
