"""Opt-in experiment: replace stations in this process, then use the supported CLI.

uv run python scripts/probes/probe_paratext.py --work-id exp-paratext-getten
  --src-dir <source> --start-page 1 --end-page 1 --stages detect,ocr,translate,inpaint,typeset
The production registry and CLI remain unchanged on disk.
"""
from __future__ import annotations

import sys
import time
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image

from amta.common.paths import read_json, write_json
from amta.orchestrator.context import StationContext, StationResult
from amta.orchestrator.registry import get_registry
from amta.stores import artifacts
from amta.translation.translate import get_chat_config, text_chat, translate_plain
from scripts.probes.paratext_layout import read_layout, validate_regions
from scripts.probes.paratext_render import render_text


def ocr(ctx: StationContext) -> StationResult:
    start = time.perf_counter()
    det = read_json(ctx.inputs["detect"])
    out = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["canon"]
    cached = read_json(out).get("layout_observation") if out.exists() else None
    observed = read_layout(ctx.raw_image, det["blocks"], cached)
    if observed is cached:
        return StationResult(ctx.page, "ocr", "ok", out, time.perf_counter()-start)
    items = []
    for r in observed["regions"]:
        if not r["text"].strip():
            continue
        items.append({**r, "baberu_text": r["text"], "page": ctx.page_idx,
                      "ocr_engine": "vlm-direct-layout", "vlm_status": "vlm-direct-layout",
                      "contained_in": None})
    doc = artifacts.stamp({"items": items, "n_regions": len(items), "ocr_engine": "vlm-direct-layout",
                           "layout_observation": observed}, ctx.work_id, ctx.page)
    out = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["canon"]
    write_json(out, doc)
    return StationResult(ctx.page, "ocr", "ok", out, time.perf_counter()-start)


def translate(ctx: StationContext) -> StationResult:
    start = time.perf_counter()
    canon = read_json(ctx.inputs["ocr"])
    cfg = get_chat_config()
    signature = hashlib.sha256(json.dumps([canon["items"], cfg["model"], cfg["base_url"], "paratext-translation-v1"],
                                          sort_keys=True).encode()).hexdigest()
    out = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["translation"]
    if out.exists() and read_json(out).get("request_sha256") == signature:
        return StationResult(ctx.page, "translate", "ok", out, time.perf_counter()-start)

    def llm(messages):
        return text_chat(cfg["base_url"], cfg["model"], messages, api_key=cfg["api_key"],
                         timeout=240, temperature=0.1)

    translations = translate_plain(canon["items"], llm, context_enabled=False, system_extra=(
        "本页含书籍副文本。忠实、自然、完整翻译，不删句。保留输入每条中的换行与段落，尤其日期、活动名和版权字段。"
        "日期、邮箱、网址、账号原样保留，社团名、笔名可保留日文。保留段落正常标点。"
        "东方角色使用常用名：八意永琳、绵月依姬、绵月丰姬、蓬莱山辉夜、稀神探女、铃仙。"))
    if any(not translations.get(item["region_id"], "").strip() for item in canon["items"]):
        raise ValueError("translation missing; do not erase or typeset incomplete output")
    out = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["translation"]
    write_json(out, artifacts.stamp({"translations": translations, "request_sha256": signature}, ctx.work_id, ctx.page))
    return StationResult(ctx.page, "translate", "ok", out, time.perf_counter()-start)


def typeset(ctx: StationContext) -> StationResult:
    start = time.perf_counter()
    canon = read_json(ctx.inputs["ocr"])
    trans = read_json(ctx.inputs["translate"])["translations"]
    clean = read_json(ctx.inputs["inpaint"])["clean_image"]
    img = Image.open(ctx.artifacts_dir / clean).convert("RGB")
    validate_regions(canon["items"], img.size)
    rendered = []
    for item in canon["items"]:
        meta = render_text(img, trans[item["region_id"]], item)
        rendered.append({**meta, "region_id": item["region_id"]})
    final = ctx.artifacts_dir / "final" / f"{ctx.page}_final.png"
    final.parent.mkdir(parents=True, exist_ok=True)
    img.save(final)
    out = artifacts.artifact_paths(ctx.artifacts_dir, ctx.page)["typeset"]
    write_json(out, artifacts.stamp({"rendered_items": rendered, "layout": {r["region_id"]: r for r in rendered},
        "final_image": f"final/{final.name}",
        "checks": {"rendered": len(rendered), "translated": len(trans), "coverage_complete": len(rendered)==len(trans),
                   "overflow": [], "skipped_no_bbox": []}}, ctx.work_id, ctx.page))
    return StationResult(ctx.page, "typeset", "ok", out, time.perf_counter()-start)


def install_experiment() -> None:
    reg = get_registry()
    for name, fn, files in [
        ("ocr", ocr, ["paratext_layout.py"]),
        ("translate", translate, []),
        ("typeset", typeset, ["paratext_render.py"]),
    ]:
        reg[name].station = fn
        reg[name].code_files += [str(Path(__file__).resolve()), *[str(Path(__file__).with_name(f).resolve()) for f in files]]
        reg[name].default_config["experiment"] = "paratext-v1"


if __name__ == "__main__":
    install_experiment()
    from scripts.run_pipeline import main
    raise SystemExit(main())
