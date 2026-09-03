"""VLM 三态过滤 — keep(保留) / fix(修正) / drop(丢弃)。

照抄自 exp_guardrails_v2.py 的 vlm_filter_v2 实现，不做任何修改。
在规则过滤之后、翻译之前执行，对每个 OCR 区域分类为 keep/fix/drop。
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

from amta.chat_client import chat
from amta.config import get_dashscope_key

# === API 配置 ===
# 支持通过 VLM_BASE_URL / VLM_API_KEY 切换视觉模型后端（如 deepseek 视觉模型），
# 未设置时回退到原 dashscope 配置，默认行为不变。
VLM_BASE = os.environ.get("VLM_BASE_URL",
           os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
VLM_MODEL = os.environ.get("VISION_MODEL", "qwen3.5-omni-plus")
try:
    VLM_KEY = os.environ.get("VLM_API_KEY") or get_dashscope_key()
except RuntimeError:
    VLM_KEY = ""

# === v2 三态 VLM 提示词（完全照抄，不改）===
VLM_V2_SYSTEM = """You are a manga text validation and correction engine. Given a full manga page image and a list of OCR text regions with coordinates, classify each region into ONE of three categories:

1. "keep" — The OCR text is correct and the region contains real text. Keep as-is.
2. "fix" — The region DOES contain real text, but the OCR text is wrong/incomplete. Provide the corrected text.
3. "drop" — The region contains NO text (blank area, screentone, hatching, speed lines, illustration detail, page border, or binding edge). The OCR output is a hallucination.

Output STRICT JSON:
{
  "keep": ["r01", "r02", ...],
  "fix": {"r03": "corrected Japanese text here", ...},
  "drop": ["r04", "r05", ...],
  "reasons": {"r03": "OCR misread 蓬莱山 as 落菜", "r04": "blank background area", ...}
}

Rules:
- For "fix": you MUST provide the corrected Japanese text exactly as it appears on the page. Look carefully at the image region.
- For "drop": only mark drop if you are confident there is NO text in that region.
- For "keep": OCR is correct, no change needed.
- Every region_id must appear in exactly ONE of keep/fix/drop.
- Short text (SFX, onomatopoeia, single characters) is legitimate — do not drop just because it is short.
- Output ONLY valid JSON. No markdown, no explanation."""


def _parse_json_safe(raw: str) -> dict | None:
    """照抄 exp_guardrails_v2.py 的 JSON 解析。"""
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


def vlm_filter_v2(image_path: Path, blocks: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """三态 VLM 筛选，返回 (kept, fixed, dropped)。完全照抄 exp_guardrails_v2.py。

    kept: OCR 正确，保留原文本
    fixed: OCR 错误，已修正文本（b["text"] 已替换为修正后文本）
    dropped: 无文本，丢弃
    """
    if not blocks:
        return [], [], []
    if not VLM_KEY:
        print("  [vlm-v2] WARNING: no API key, all kept")
        return blocks, [], []

    img_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    img_url = f"data:image/jpeg;base64,{img_b64}"

    lines = ["OCR text regions (region_id: text [bbox]):"]
    for i, b in enumerate(blocks):
        rid = f"r{i:02d}"
        b["_rid"] = rid
        lines.append(f"{rid}: {b.get('text', '')[:80]} [bbox: {[round(v) for v in b['bbox']]}]")
    user_prompt = "\n".join(lines)

    messages = [
        {"role": "system", "content": VLM_V2_SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": img_url}},
        ]},
    ]

    t0 = time.perf_counter()
    try:
        resp = chat(VLM_BASE, VLM_MODEL, messages, api_key=VLM_KEY, timeout=120)
        raw = resp.get("content", "")
    except Exception as e:
        print(f"  [vlm-v2] ERROR: {e}, all kept")
        return blocks, [], []
    elapsed = time.perf_counter() - t0

    parsed = _parse_json_safe(raw)
    if not parsed:
        print(f"  [vlm-v2] WARNING: JSON parse failed, all kept. raw[:200]={raw[:200]}")
        return blocks, [], []

    # 注意：VLM 的 "keep" 无需显式处理——未 drop/未 fix 的框默认保留（else 分支），
    # 与 "keep" 语义一致，故不读 keep 列表（F841）。
    fix_dict = parsed.get("fix", {})
    drop_ids = set(parsed.get("drop", []))
    reasons = parsed.get("reasons", {})

    kept, fixed, dropped = [], [], []
    for b in blocks:
        rid = b.get("_rid", "")
        if rid in drop_ids:
            b["filter_reason"] = f"vlm-drop:{reasons.get(rid, 'no text')}"
            dropped.append(b)
        elif rid in fix_dict:
            original = b.get("text", "")
            corrected = fix_dict[rid]
            b["original_text"] = original
            b["text"] = corrected
            b["filter_reason"] = f"vlm-fix:{reasons.get(rid, 'OCR corrected')}"
            fixed.append(b)
        else:  # VLM 标 keep 或未分类 → 默认保留
            kept.append(b)

    print(f"  [vlm-v2] {elapsed:.1f}s, keep={len(kept)}, fix={len(fixed)}, drop={len(dropped)}")
    if fixed:
        for b in fixed:
            print(f"    FIX: \"{b.get('original_text','')[:40]}\" -> \"{b.get('text','')[:40]}\"")
    return kept, fixed, dropped
