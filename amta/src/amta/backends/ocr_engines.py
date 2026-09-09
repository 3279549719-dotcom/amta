"""OCR 引擎分发器 — baberu（默认，ONNX）/ hayai（HayaiOCR-v2.1，PyTorch）。

统一接口: ocr_batch(crops, engine="baberu") -> list[{
    "crop": path, "ocr": text,
    "first_token_conf": float, "avg_conf": float, "low_ratio": float
}]

hayai 引擎通过自定义 greedy decoding 收集每步 logits，计算 token 级 confidence。
Q3 假框过滤策略（组合条件，避免误伤首字识别错误的真实文字）:
  1. first_token_conf < 0.05 → 过滤（极低 confidence，乱码/胡说八道）
  2. first_token_conf < 0.4 且 low_ratio > 0.6 → 过滤（首字低且超六成 token 低）
  3. 否则保留

baberu 引擎不支持 confidence，返回 first_token_conf=1.0, avg_conf=1.0, low_ratio=0.0（不过滤）。

模型路径可通过环境变量覆盖:
  HAYAI_OCR_MODEL  (默认 E:\\models\\hayai-ocr-v2)
"""
from __future__ import annotations

import os
import sys

import torch
import torch.nn.functional as F
from PIL import Image

ENGINES = ("baberu", "hayai")

_HAYAI_DEFAULT = r"E:\models\hayai-ocr-v2"


# ============================================================
# baberu (ONNX, CPU, 默认)
# ============================================================

def _baberu_batch(crops) -> list[dict]:
    """懒加载 baberu-OCR（models/baberu-ocr/ 内嵌 onnx）。不支持 confidence，返回 1.0。"""
    from amta.common.paths import ROOT

    model_root = ROOT / "models" / "baberu-ocr"
    if not (model_root / "onnx").exists():
        raise RuntimeError("baberu-OCR 模型缺失（models/baberu-ocr/onnx）——请先下载模型")
    sys.path.insert(0, str(model_root))
    from onnx_infer import BaberuOnnxOCR  # noqa: PLC0415  # type: ignore[import-not-found]

    ocr = BaberuOnnxOCR(model_root / "onnx", model_root / "tokenizer", vision="vision_int4.onnx")
    out = []
    for p in crops:
        try:
            text = ocr(Image.open(p))
        except Exception:  # noqa: BLE001
            # OCR 崩溃 → 空串（合法结果，下游按"乱码/空框"处理）；
            # 绝不把报错信息当日文原文送翻译制造垃圾数据（Q4）
            text = ""
        out.append({"crop": p, "ocr": text or "",
                    "first_token_conf": 1.0, "avg_conf": 1.0, "low_ratio": 0.0})
    return out


# ============================================================
# HayaiOCR-v2.1 (PyTorch, SigLIP2 + transformer)
# ============================================================

_hayai_instance = None


def _get_hayai():
    global _hayai_instance
    if _hayai_instance is None:
        # 强制离线：hayai v2 内部硬编码 AutoProcessor.from_pretrained("google/siglip2-..."),
        # 会联网拉 processor_config.json（hub 上不存在，429 重试浪费 3 分钟）。
        # 本地缓存已有 preprocessor_config.json，离线模式下 AutoProcessor 会 fallback 到它。
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from hayai_ocr import HayaiOcr
        model_path = os.environ.get("HAYAI_OCR_MODEL", _HAYAI_DEFAULT)
        # 模型目录加入 sys.path，以便 import modeling_hayai（自定义 greedy decoding 需要）
        if model_path not in sys.path:
            sys.path.insert(0, model_path)
        _hayai_instance = HayaiOcr(pretrained_model_name_or_path=model_path)
    return _hayai_instance


def _hayai_greedy_decode_with_conf(model, processor, tokenizer, img,
                                     max_new_tokens: int = 128,
                                     repetition_penalty: float = 1.0) -> dict:
    """自定义 greedy decoding，收集每步 logits 计算 token 级 confidence。

    逻辑与 HayaiModel.generate 的 greedy 路径完全一致，仅额外收集每步 logits。
    返回 {"text": str, "first_token_conf": float, "avg_conf": float,
           "low_ratio": float, "num_tokens": int}。

    Q3 背景：hayai 官方 generate 不支持 output_scores，且模型会在无文字区域
    "dream up" 合理句子（作者 README 承认）。组合 confidence 指标可有效区分
    假框与真实文字（包括首字识别错误的真实文字，如生僻汉字"嫦"、数字"八"被误读）。
    """
    import modeling_hayai  # type: ignore[import-not-found]
    compute_batch_2d_mrope_freqs = modeling_hayai.compute_batch_2d_mrope_freqs

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

    x_bos = model.decoder.final_norm(x[:, -1:])
    logits = model.decoder.output_head(x_bos)
    next_token_logits = logits[:, -1, :].clone()

    # 收集每步 logits（用于 token 级 confidence）
    all_logits = []

    # 首 token confidence（repetition_penalty 应用后）
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

    # Decoding loop（与原生 generate 一致，同时收集每步 logits）
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

    # Decode + 计算 token 级 confidence
    seq = generated_tokens[0].tolist()
    clean_tokens = [t for t in seq[1:] if t not in (eos_id, pad_id)]
    text = tokenizer.decode(clean_tokens, skip_special_tokens=True)

    token_confs = []
    for i, tid in enumerate(clean_tokens):
        if i < len(all_logits):
            probs = F.softmax(all_logits[i][0], dim=-1)
            token_confs.append(probs[tid].item())

    first_token_conf = token_confs[0] if token_confs else 1.0
    avg_conf = sum(token_confs) / len(token_confs) if token_confs else 1.0
    low_ratio = sum(1 for c in token_confs if c < 0.5) / len(token_confs) if token_confs else 0.0

    return {
        "text": text,
        "first_token_conf": first_token_conf,
        "avg_conf": avg_conf,
        "low_ratio": low_ratio,
        "num_tokens": len(clean_tokens),
    }


def _hayai_batch(crops) -> list[dict]:
    """HayaiOCR-v2.1 — 支持多行单次前向，中日韩三语。

    使用自定义 greedy decoding 收集每步 logits，计算 token 级 confidence
    （first_token_conf / avg_conf / low_ratio），用于 Q3 假框过滤。
    逻辑与原生 HayaiModel.generate 完全一致，仅额外收集 logits。
    """
    ocr = _get_hayai()
    out = []
    for p in crops:
        try:
            img = Image.open(p).convert("RGB")
            with torch.no_grad():
                result = _hayai_greedy_decode_with_conf(
                    ocr.model, ocr.processor, ocr.tokenizer, img)
            text = result["text"].strip()
            first_conf = result["first_token_conf"]
            avg_conf = result["avg_conf"]
            low_ratio = result["low_ratio"]
        except Exception:  # noqa: BLE001
            # 同 baberu：崩溃 → 空串，不把报错信息当 OCR 文本（Q4）
            # confidence 设为最高，避免异常时误过滤
            text = ""
            first_conf = 1.0
            avg_conf = 1.0
            low_ratio = 0.0
        out.append({
            "crop": p, "ocr": text,
            "first_token_conf": round(first_conf, 4),
            "avg_conf": round(avg_conf, 4),
            "low_ratio": round(low_ratio, 4),
        })
    return out


# ============================================================
# 统一分发器
# ============================================================

_ENGINE_FN = {
    "baberu": _baberu_batch,
    "hayai": _hayai_batch,
}


def ocr_batch(crops, engine: str = "baberu") -> list[dict]:
    """统一 OCR 分发器。

    Args:
        crops: 图片路径列表
        engine: "baberu" (默认, ONNX/CPU) | "hayai" (HayaiOCR-v2.1)
    """
    if engine not in _ENGINE_FN:
        raise ValueError(f"未知 OCR 引擎: {engine}，可选: {', '.join(ENGINES)}")
    return _ENGINE_FN[engine](crops)
