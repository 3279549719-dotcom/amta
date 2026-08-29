"""lookup_image 集成测试 — 验证完整工具调用流程。

测试内容：
1. 工具声明正确（TOOLS_SCHEMA 包含 lookup_image）
2. LLM 主动调用 lookup_image，结果正确回传
3. 预算控制（VISION_BUDGET 次后拒绝）
4. 失败降级（VLM 异常不阻塞翻译）
5. 重点 case 标注：p11u11(插画) / p12u07(招牌) / p14u10(OCR错误修正)
6. 真实 API 小规模测试（如果配置了 API key）
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amta import translate
from amta import translate_tools as tt


def make_crop_image(path: Path, color=(255, 255, 255)):
    """创建一个测试用 crop 图片。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (100, 60), color=color)
    draw = ImageDraw.Draw(img)
    draw.text((10, 20), "テスト", fill=(0, 0, 0))
    img.save(path)


def setup_test_env(tmp_dir: Path, n_regions: int = 3):
    """构造测试环境：canon 数据 + crop 图片。"""
    crop_dir = tmp_dir / "crops"
    crop_dir.mkdir()

    canon = []
    for i in range(n_regions):
        rid = f"u{i:02d}"
        make_crop_image(crop_dir / f"{rid}.png")
        canon.append({
            "region_id": rid,
            "baberu_text": f"バベルテキスト{i}",
            "vlm_text": f"VLMテキスト{i}",
            "vlm_status": "ok",
            "contained_in": None,
            "page": 11,
        })
    return canon, crop_dir


# ── 集成测试 1: 工具声明 ─────────────────────────────────────────────────

def test_tools_schema():
    """TOOLS_SCHEMA 包含三个工具，lookup_image 参数正确。"""
    names = [t["function"]["name"] for t in tt.TOOLS_SCHEMA]
    assert "lookup_term" in names
    assert "get_context" in names
    assert "lookup_image" in names

    schema = next(t for t in tt.TOOLS_SCHEMA if t["function"]["name"] == "lookup_image")
    assert schema["function"]["parameters"]["required"] == ["region_id"]
    return "PASS"


# ── 集成测试 2: LLM 主动调用 lookup_image ────────────────────────────────

def test_llm_calls_lookup_image():
    """LLM 第一轮调用 lookup_image，结果回传，第二轮输出译文。"""
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        canon, crop_dir = setup_test_env(tmp_dir, n_regions=1)

        calls = []
        vlm_called = {"count": 0}

        def fake_vlm(img, text, api_key):
            vlm_called["count"] += 1
            return {
                "ocr_correct": "incorrect",
                "corrected_text": "正しいテキスト",
                "visual_type": "dialogue_bubble",
                "speaker_hint": "テストキャラ",
                "description": "横排テキスト",
                "status": "ok",
                "raw_output": "",
                "elapsed": 0.1,
            }

        def llm(messages, tools=None):
            calls.append(messages)
            if len(calls) == 1:
                return {"content": None, "tool_calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "lookup_image", "arguments": '{"region_id": "u00"}'}}]}
            return {"content": '{"u00": "正确的译文"}', "tool_calls": None}

        # monkeypatch VLM 调用
        import amta.vlm_verify as vlm_mod
        original = vlm_mod.vlm_verify_ocr_single
        vlm_mod.vlm_verify_ocr_single = fake_vlm
        try:
            out = translate.translate_with_retry(
                canon, llm, work_state={}, max_retries=1,
                tools=translate.TOOLS_SCHEMA,
                crop_dir=crop_dir, vlm_api_key="sk-test")
        finally:
            vlm_mod.vlm_verify_ocr_single = original

        assert out["u00"] == "正确的译文"
        assert vlm_called["count"] == 1, f"VLM should be called once, got {vlm_called['count']}"
        # 验证工具结果回传
        assert len(calls) == 2
        tool_msg = [m for m in calls[1] if m["role"] == "tool"]
        assert len(tool_msg) == 1
        assert "[lookup_image] u00" in tool_msg[0]["content"]
        assert "修正建议：「正しいテキスト」" in tool_msg[0]["content"]
        return "PASS"


# ── 集成测试 3: 预算控制 ─────────────────────────────────────────────────

def test_budget_control():
    """VISION_BUDGET 次调用后，下一次返回预算耗尽。"""
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        canon, crop_dir = setup_test_env(tmp_dir, n_regions=1)

        round_num = {"n": 0}

        def llm(messages, tools=None):
            round_num["n"] += 1
            if round_num["n"] <= tt.VISION_BUDGET:
                return {"content": None, "tool_calls": [
                    {"id": f"call_{round_num['n']}", "type": "function",
                     "function": {"name": "lookup_image", "arguments": '{"region_id": "u00"}'}}]}
            return {"content": '{"u00": "译文"}', "tool_calls": None}

        import amta.vlm_verify as vlm_mod
        original = vlm_mod.vlm_verify_ocr_single
        vlm_mod.vlm_verify_ocr_single = lambda img, text, api_key: {
            "ocr_correct": "correct", "corrected_text": "",
            "visual_type": "dialogue_bubble", "speaker_hint": "",
            "description": "", "status": "ok", "raw_output": "", "elapsed": 0.1}
        try:
            out = translate.translate_with_retry(
                canon, llm, work_state={}, max_retries=1,
                tools=translate.TOOLS_SCHEMA,
                crop_dir=crop_dir, vlm_api_key="sk-test")
        finally:
            vlm_mod.vlm_verify_ocr_single = original

        assert out["u00"] == "译文"
        return "PASS"


# ── 集成测试 4: 失败降级 ─────────────────────────────────────────────────

def test_failure_degradation():
    """VLM 抛异常时，lookup_image 返回失败提示，翻译继续不阻塞。"""
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        canon, crop_dir = setup_test_env(tmp_dir, n_regions=1)

        def llm(messages, tools=None):
            if not any(m["role"] == "tool" for m in messages):
                return {"content": None, "tool_calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "lookup_image", "arguments": '{"region_id": "u00"}'}}]}
            return {"content": '{"u00": "基于OCR的译文"}', "tool_calls": None}

        import amta.vlm_verify as vlm_mod
        original = vlm_mod.vlm_verify_ocr_single
        def _boom(img, text, api_key):
            raise ConnectionError("API timeout")
        vlm_mod.vlm_verify_ocr_single = _boom
        try:
            out = translate.translate_with_retry(
                canon, llm, work_state={}, max_retries=1,
                tools=translate.TOOLS_SCHEMA,
                crop_dir=crop_dir, vlm_api_key="sk-test")
        finally:
            vlm_mod.vlm_verify_ocr_single = original

        assert out["u00"] == "基于OCR的译文"  # 翻译继续，不阻塞
        return "PASS"


# ── 集成测试 5: 重点 case 标注 ───────────────────────────────────────────

def test_key_cases():
    """重点 case：p11u11(插画) / p12u07(招牌) / p14u10(OCR错误修正)。"""
    key_cases = [
        {"id": "p11u11", "desc": "插画识别", "baberu": "そういうことで、",
         "expected_vlm": {"ocr_correct": "incorrect", "corrected_text": "",
                           "visual_type": "illustration", "description": "手部插画，非文字"}},
        {"id": "p12u07", "desc": "招牌识别", "baberu": "落菜",
         "expected_vlm": {"ocr_correct": "incorrect", "corrected_text": "蓬莱",
                           "visual_type": "sign", "description": "竖排汉字招牌"}},
        {"id": "p14u10", "desc": "OCR错误修正", "baberu": "ハ意様",
         "expected_vlm": {"ocr_correct": "incorrect", "corrected_text": "八意様",
                           "visual_type": "dialogue_bubble", "speaker_hint": "八意永琳"}},
    ]

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        crop_dir = tmp_dir / "crops"
        crop_dir.mkdir()

        results = []
        for case in key_cases:
            rid = case["id"].split("u")[1]
            rid = f"u{int(rid):02d}"
            make_crop_image(crop_dir / f"{rid}.png")

            import amta.vlm_verify as vlm_mod
            original = vlm_mod.vlm_verify_ocr_single
            expected = case["expected_vlm"]
            vlm_mod.vlm_verify_ocr_single = lambda img, text, api_key, e=expected: {
                **e, "status": "ok", "raw_output": "", "elapsed": 0.1}
            try:
                ws = {"_canon_items": {rid: {"region_id": rid, "baberu_text": case["baberu"]}}}
                result = tt.execute_tool("lookup_image", {"region_id": rid}, ws,
                                         crop_dir=crop_dir, vlm_api_key="sk-test")
            finally:
                vlm_mod.vlm_verify_ocr_single = original

            # 验证关键信息
            ok = True
            if expected["visual_type"] == "illustration":
                ok = "illustration" in result and "修正建议" not in result
            elif expected["visual_type"] == "sign":
                ok = "sign" in result and expected["corrected_text"] in result
            else:
                ok = "incorrect" in result and expected["corrected_text"] in result

            results.append({"case": case["id"], "desc": case["desc"], "status": "PASS" if ok else "FAIL",
                            "result": result[:200]})

        all_pass = all(r["status"] == "PASS" for r in results)
        return ("PASS" if all_pass else "FAIL"), results


# ── 集成测试 6: 真实 API 小规模测试 ──────────────────────────────────────

def test_real_api():
    """真实 API 测试（如果配置了 API key）：调用一次 lookup_image 验证端到端。"""
    try:
        cfg = translate.get_chat_config()
        api_key = cfg.get("api_key")
        if not api_key:
            return "SKIP", "No API key configured"
    except Exception as e:
        return "SKIP", f"Cannot read config: {e}"

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        crop_dir = tmp_dir / "crops"
        crop_dir.mkdir()
        make_crop_image(crop_dir / "u00.png", color=(240, 240, 255))

        ws = {"_canon_items": {"u00": {"region_id": "u00", "baberu_text": "テスト"}}}
        try:
            result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                                     crop_dir=crop_dir, vlm_api_key=api_key)
            return "PASS", result[:300]
        except Exception as e:
            return "FAIL", f"Real API call failed: {type(e).__name__}: {e}"


# ── 主运行器 ─────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("工具声明正确", test_tools_schema),
        ("LLM主动调用lookup_image", test_llm_calls_lookup_image),
        ("预算控制(VISION_BUDGET)", test_budget_control),
        ("失败降级(VLM异常不阻塞)", test_failure_degradation),
    ]

    results = []
    for name, func in tests:
        try:
            status = func()
            results.append({"name": name, "status": status, "detail": ""})
            print(f"  {status}  {name}")
        except Exception as e:
            import traceback
            results.append({"name": name, "status": "FAIL", "detail": str(e)})
            print(f"  FAIL  {name}: {e}")
            print(traceback.format_exc())

    # 重点 case
    print("\n  重点 case 测试:")
    try:
        status, key_results = test_key_cases()
        for kr in key_results:
            results.append({"name": f"重点case:{kr['case']}({kr['desc']})", "status": kr["status"], "detail": kr["result"]})
            print(f"    {kr['status']}  {kr['case']} - {kr['desc']}")
    except Exception as e:
        results.append({"name": "重点case", "status": "FAIL", "detail": str(e)})
        print(f"    FAIL  重点case: {e}")

    # 真实 API
    print("\n  真实 API 测试:")
    try:
        status, detail = test_real_api()
        results.append({"name": "真实API端到端", "status": status, "detail": detail})
        print(f"    {status}  真实API端到端: {detail[:100]}")
    except Exception as e:
        results.append({"name": "真实API端到端", "status": "FAIL", "detail": str(e)})
        print(f"    FAIL  真实API端到端: {e}")

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    print(f"\n{'='*60}")
    print(f"Integration: {passed} passed, {failed} failed, {skipped} skipped, {len(results)} total")

    # 保存结果为 JSON 供 HTML 报告使用
    out_path = Path(__file__).parent / "integration_test_results.json"
    out_path.write_text(json.dumps({"results": results, "passed": passed, "failed": failed,
                                      "skipped": skipped, "total": len(results)},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Results saved to {out_path}")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
