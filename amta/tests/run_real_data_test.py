"""真实数据端到端测试 — 用 p11 真实 canon + crops 跑翻译，验证 lookup_image。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import translate
from amta import translate_tools as tt

ARTIFACTS = Path(r"E:\manga translator agent\amta\.worktrees\feat-front3-reconstruction\workspace\touhou-single-wing\artifacts")


def run_real_test(page=11, vision_budget=3):
    """用真实数据跑翻译，记录工具调用和结果。"""
    canon_path = ARTIFACTS / f"page_{page}_canon.json"
    crop_dir = ARTIFACTS / "crops" / f"page_{page}"

    if not canon_path.exists():
        return {"error": f"canon not found: {canon_path}"}
    if not crop_dir.exists():
        return {"error": f"crops not found: {crop_dir}"}

    canon = json.loads(canon_path.read_text(encoding="utf-8"))
    cfg = translate.get_chat_config()
    api_key = cfg["api_key"]

    # 记录工具调用
    tool_calls = []
    vlm_results = []

    original_execute = tt.execute_tool

    def tracking_execute(name, args, work_state, *a, **kw):
        if name == "lookup_image":
            rid = args.get("region_id", "?")
            t0 = time.time()
            result = original_execute(name, args, work_state, *a, **kw)
            elapsed = time.time() - t0
            tool_calls.append({"region_id": rid, "elapsed": round(elapsed, 2), "result": result[:300]})
            # 提取 VLM 结果
            if "OCR 验证：" in result:
                for line in result.split("\n"):
                    if "OCR 验证：" in line:
                        vlm_results.append({"region_id": rid, "verification": line.strip()})
                    if "区域类型：" in line:
                        vlm_results[-1]["visual_type"] = line.replace("区域类型：", "").strip()
                    if "修正建议：" in line:
                        vlm_results[-1]["correction"] = line.replace("修正建议：", "").strip()
            return result
        return original_execute(name, args, work_state, *a, **kw)

    tt.execute_tool = tracking_execute

    # LLM 闭包（记录调用）
    llm_calls = []

    def llm(messages, tools=None):
        llm_calls.append({"n_messages": len(messages), "has_tools": tools is not None})
        return translate.chat_with_tools(cfg["base_url"], cfg["model"], messages,
                                          tools=tools, api_key=api_key)

    try:
        t0 = time.time()
        result = translate.translate_with_retry(
            canon, llm, work_state={}, max_retries=2,
            tools=translate.TOOLS_SCHEMA,
            crop_dir=crop_dir, vlm_api_key=api_key,
            vision_budget=vision_budget)
        elapsed = time.time() - t0
    finally:
        tt.execute_tool = original_execute

    # 统计
    n_translated = sum(1 for v in result.values() if v.strip())
    n_empty = len(result) - n_translated

    return {
        "page": page,
        "n_regions": len(canon),
        "n_translated": n_translated,
        "n_empty": n_empty,
        "elapsed": round(elapsed, 2),
        "vision_budget": vision_budget,
        "n_lookup_image_calls": len(tool_calls),
        "n_llm_calls": len(llm_calls),
        "tool_calls": tool_calls,
        "vlm_results": vlm_results,
        "translations": {k: v for k, v in result.items()},
    }


if __name__ == "__main__":
    page = int(sys.argv[1]) if len(sys.argv) > 1 else 11
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f"Running real data test: page={page}, vision_budget={budget}")
    result = run_real_test(page=page, vision_budget=budget)
    out_path = Path(__file__).parent / f"real_data_test_p{page}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Results saved to {out_path}")
    print(f"  regions: {result.get('n_regions')}, translated: {result.get('n_translated')}")
    print(f"  lookup_image calls: {result.get('n_lookup_image_calls')}")
    print(f"  elapsed: {result.get('elapsed')}s")
    for vc in result.get("vlm_results", []):
        print(f"    {vc['region_id']}: {vc.get('verification', '?')}, type={vc.get('visual_type', '?')}")
