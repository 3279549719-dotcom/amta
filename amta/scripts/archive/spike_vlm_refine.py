"""Spike: VLM full-page OCR refine + scene extraction A/B test.

v3 re-run on the CORRECT image: pipeline page_11 (0-based) = file 12.jpg.
v1/v2 ran against 11.jpg (off-by-one from detect_contract's source field),
which explains their ungrounded "re-read" outputs — the image simply did not
contain the canon texts. Controller forensics + VLM transcription verified:
12.jpg contains the exact canon lines (またしても八意様は研究室へ来なくなった,
輝夜様のお世話以外にも…, いずれにせよ私には関係ないことだ).

Tests one VLM model on page_11:
  A: qwen3.5-omni-plus (DashScope, .env VISION_MODEL)

  B: deepseek-v4-flash-vision-exp — dropped in v2 (see MODELS comment):
     S5 failed input-independently in the v1 run (latency is a provider
     property, not an input-canon property).

Each model runs 3 times. Measures: JSON parseability, OCR refine quality,
invalid/duplicate marking accuracy, scene description relevance, latency.

Deviations from the brief (minimal, required to run at all):
- PAGE_11_CANON points to output/data/run_11_20/canon_contract_p11.json:
  the brief's output/data/detect_contract/p11.json is a *detection* contract
  (no region_id/text keys; load_canon raises ValueError on it), so the
  page-11 canon contract artifact is used instead. That artifact carries no
  bbox, so prompt lines show an empty [bbox: []].
- call_vlm catches requests.RequestException so a provider HTTP error (e.g.
  DeepSeek 402 out-of-balance, pre-ruled risk) is recorded as that run's
  result instead of aborting the whole A/B before the report is written.
- The parent-dir .env defines DASHSCOPE_KEY (no DASHSCOPE_API_KEY); the
  runner maps DASHSCOPE_KEY -> DASHSCOPE_API_KEY in-process before invoking
  this script (model name in .env VISION_MODEL matches the hardcoded one).
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import requests  # noqa: E402

from amta.artifacts import load_canon  # noqa: E402
from amta.chat_client import chat  # noqa: E402

# Brief path output/data/detect_contract/p11.json is the detection contract
# (blocks only, no region_id/text) — the actual canon for page 11:
PAGE_11_CANON = Path("output/data/run_11_20/canon_contract_p11.json")
# NOTE: pipeline page_11 (0-based) = file 12.jpg — verified 2026-08-31 by VLM transcription; the old source field "11.jpg" in detect_contract is off-by-one (see SDD ledger).
RAW_IMAGE = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地\12.jpg")
OUTPUT_REPORT = Path("output/reports/spike-vlm-refine-page11.md")

MODELS = [
    {"name": "qwen3.5-omni-plus", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "env_key": "DASHSCOPE_API_KEY"},
    # v2 re-run is qwen-only. deepseek-v4-flash-vision-exp dropped: its S5
    # failure (106.2s avg vs <=30s limit in the v1 run) is input-independent
    # (latency is a provider property), so re-testing it on the corrected
    # canon would spend time/money without changing the verdict.
    # {"name": "deepseek-v4-flash-vision-exp", "base_url": "https://api.deepseek.com",
    #  "env_key": "CHAT_API_KEY"},
]

SYSTEM_PROMPT = """You are a manga OCR refinement engine. Given a full manga page image and a list of OCR text regions, output STRICT JSON with these keys:
{
  "ocr_refinements": {"r01": "corrected text", ...},
  "bubble_types": {"r01": "dialogue"|"narration"|"sfx", ...},
  "scene": "one sentence describing the scene setting (location/time/mood)",
  "invalid_regions": ["r01", ...],
  "duplicate_regions": {"r02": "r01", ...}
}
Rules:
- ocr_refinements: only include regions where you CORRECT the OCR text. If OCR is correct, omit the key.
- invalid_regions: regions that are NOT valid text (noise, decoration, page numbers, illustration).
- duplicate_regions: regions whose text duplicates another region (map duplicate -> original).
- Output ONLY valid JSON. No markdown, no explanation."""


def load_image_b64(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def build_user_prompt(canon_items: list[dict]) -> str:
    lines = ["OCR text regions:"]
    for item in canon_items:
        rid = item["region_id"]
        text = item.get("baberu_text") or item.get("text") or ""
        bbox = item.get("bbox", [])
        lines.append(f"{rid}: {text} [bbox: {bbox}]")
    return "\n".join(lines)


def call_vlm(model: dict, image_b64: str, user_prompt: str) -> tuple[str, float]:
    import os
    api_key = os.environ.get(model["env_key"], "")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": image_b64}},
        ]},
    ]
    t0 = time.time()
    try:
        resp = chat(model["base_url"], model["name"], messages, api_key=api_key, timeout=120)
    except requests.RequestException as e:
        elapsed = time.time() - t0
        status = getattr(getattr(e, "response", None), "status_code", None)
        return f"HTTP_ERROR {status}: {e}", elapsed
    elapsed = time.time() - t0
    content = resp.get("content") or ""
    return content, elapsed


def parse_json_safe(raw: str) -> dict | None:
    text = raw.strip()
    # strip markdown code fences
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def run_spike():
    canon = load_canon(PAGE_11_CANON)
    items = canon.get("items", [])
    image_b64 = load_image_b64(RAW_IMAGE)
    user_prompt = build_user_prompt(items)

    results = {}
    for model in MODELS:
        runs = []
        for i in range(3):
            raw, elapsed = call_vlm(model, image_b64, user_prompt)
            parsed = parse_json_safe(raw)
            runs.append({"run": i + 1, "elapsed": round(elapsed, 2),
                         "parse_ok": parsed is not None, "raw": raw[:500],
                         "parsed": parsed})
        results[model["name"]] = runs

    # Write report
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# VLM Full-Page Refine Spike — page_11 A/B Test\n"]
    lines.append(f"## Input\n- Regions: {len(items)}\n- Image: {RAW_IMAGE}\n")
    for model_name, runs in results.items():
        lines.append(f"\n## Model: {model_name}\n")
        parse_rate = sum(1 for r in runs if r["parse_ok"]) / len(runs)
        avg_elapsed = sum(r["elapsed"] for r in runs) / len(runs)
        lines.append(f"- JSON parse rate: {parse_rate:.0%} ({sum(1 for r in runs if r['parse_ok'])}/{len(runs)})")
        lines.append(f"- Avg latency: {avg_elapsed:.1f}s")
        for r in runs:
            lines.append(f"\n### Run {r['run']} ({r['elapsed']}s, parse_ok={r['parse_ok']})")
            if r["parsed"]:
                p = r["parsed"]
                lines.append(f"- ocr_refinements: {json.dumps(p.get('ocr_refinements', {}), ensure_ascii=False)}")
                lines.append(f"- bubble_types: {json.dumps(p.get('bubble_types', {}), ensure_ascii=False)}")
                lines.append(f"- scene: {p.get('scene', '')}")
                lines.append(f"- invalid_regions: {p.get('invalid_regions', [])}")
                lines.append(f"- duplicate_regions: {json.dumps(p.get('duplicate_regions', {}), ensure_ascii=False)}")
            else:
                lines.append(f"- RAW (first 500 chars): {r['raw']}")
    OUTPUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {OUTPUT_REPORT}")


if __name__ == "__main__":
    run_spike()
