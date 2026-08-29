"""lookup_image 工具单元测试 — 契约 → 反例 → 证据。

覆盖：
- 正常场景：correct / incorrect+修正 / illustration / sign / noise
- 失败降级：未配置 / crop不存在 / VLM异常 / VLM返回失败 / 参数缺失
- 重点 case 标注：p11u11(插画) / p12u07(招牌) / p14u10(OCR错误修正)
- 工具循环集成：translate_with_retry 中 LLM 调用 lookup_image，结果回传
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


# ── helpers ──────────────────────────────────────────────────────────────

def _make_canon(region_id="u00", baberu_text="テスト"):
    """构造 work_state["_canon_items"] 所需的 canon 索引。"""
    return {"_canon_items": {region_id: {"region_id": region_id, "baberu_text": baberu_text}}}


def _make_crop_file(tmp_path, region_id="u00"):
    """在 tmp_path 下创建一个假的 crop PNG 文件（1x1 像素）。"""
    from PIL import Image
    crop_dir = tmp_path / "crops"
    crop_dir.mkdir(exist_ok=True)
    img = Image.new("RGB", (10, 10), color="white")
    crop_path = crop_dir / f"{region_id}.png"
    img.save(crop_path)
    return crop_dir


def _fake_vlm_result(**kwargs):
    """构造 vlm_verify_ocr_single 的假返回值。"""
    base = {
        "ocr_correct": "correct",
        "corrected_text": "",
        "visual_type": "dialogue_bubble",
        "speaker_hint": "",
        "description": "",
        "status": "ok",
        "raw_output": "",
        "elapsed": 0.1,
    }
    base.update(kwargs)
    return base


# ── 正常场景 ─────────────────────────────────────────────────────────────

def test_lookup_image_correct(monkeypatch, tmp_path):
    """VLM 返回 correct → 输出包含 OCR 验证 correct 和区域类型。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    ws = _make_canon("u00", "こんにちは")

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            ocr_correct="correct", visual_type="dialogue_bubble",
                            description="横排平假名，对话气泡"))

    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "[lookup_image] u00" in result
    assert "OCR 验证：correct" in result
    assert "区域类型：dialogue_bubble" in result
    assert "横排平假名" in result


def test_lookup_image_incorrect_with_correction(monkeypatch, tmp_path):
    """VLM 返回 incorrect + corrected_text → 输出包含修正建议。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    ws = _make_canon("u00", "ハ意様")  # baberu 认错了

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            ocr_correct="incorrect", corrected_text="八意様",
                            visual_type="dialogue_bubble", speaker_hint="八意永琳"))

    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "OCR 验证：incorrect" in result
    assert "修正建议：「八意様」" in result
    assert "说话人提示：八意永琳" in result


def test_lookup_image_illustration(monkeypatch, tmp_path):
    """【重点 case p11u11】VLM 返回 illustration → 正确识别非文字区域。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path, "u11")
    ws = _make_canon("u11", "そういうことで、")  # baberu 把插画识别成了文字

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            ocr_correct="incorrect", corrected_text="",
                            visual_type="illustration",
                            description="手部插画，非文字区域"))

    result = tt.execute_tool("lookup_image", {"region_id": "u11"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "区域类型：illustration" in result
    assert "手部插画" in result
    # 插画区域不应有修正建议（corrected_text 为空）
    assert "修正建议" not in result


def test_lookup_image_sign(monkeypatch, tmp_path):
    """【重点 case p12u07】VLM 返回 sign + 修正 → 正确识别招牌文字。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path, "u07")
    ws = _make_canon("u07", "落菜")  # baberu 把招牌"蓬莱"认错了

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            ocr_correct="incorrect", corrected_text="蓬莱",
                            visual_type="sign",
                            description="竖排两个汉字，背景招牌"))

    result = tt.execute_tool("lookup_image", {"region_id": "u07"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "区域类型：sign" in result
    assert "修正建议：「蓬莱」" in result
    assert "背景招牌" in result


def test_lookup_image_noise(monkeypatch, tmp_path):
    """VLM 返回 noise → 识别噪点/污渍区域。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path, "u03")
    ws = _make_canon("u03", "．．．")  # baberu 把噪点识别成了省略号

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            ocr_correct="uncertain", corrected_text="",
                            visual_type="noise",
                            description="黑色污渍，非有效文字"))

    result = tt.execute_tool("lookup_image", {"region_id": "u03"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "区域类型：noise" in result
    assert "OCR 验证：uncertain" in result


def test_lookup_image_partial(monkeypatch, tmp_path):
    """VLM 返回 partial → 部分正确，给出修正建议。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    ws = _make_canon("u00", "八意様の変わり様")

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            ocr_correct="partial", corrected_text="八意様の変わりよう",
                            visual_type="dialogue_bubble"))

    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "OCR 验证：partial" in result
    assert "修正建议：「八意様の変わりよう」" in result


def test_lookup_image_uncertain(monkeypatch, tmp_path):
    """VLM 返回 uncertain → 不强迫编造，提示 LLM 自行判断。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    ws = _make_canon("u00", "模糊文字")

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            ocr_correct="uncertain", corrected_text="",
                            visual_type="other", description="文字模糊无法确认"))

    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "OCR 验证：uncertain" in result
    assert "无法确认" in result
    # uncertain 不应有修正建议
    assert "修正建议" not in result


# ── 失败降级场景 ─────────────────────────────────────────────────────────

def test_lookup_image_missing_region_id(monkeypatch, tmp_path):
    """参数缺失：region_id 为空 → 返回参数缺失提示。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    result = tt.execute_tool("lookup_image", {"region_id": ""}, {},
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "参数缺失" in result


def test_lookup_image_no_crop_dir(monkeypatch):
    """未配置：crop_dir 为 None → 返回未配置提示，不抛异常。"""
    from amta import translate_tools as tt

    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, {},
                             crop_dir=None, vlm_api_key="sk-test")
    assert "未配置" in result
    assert "crop_dir" in result


def test_lookup_image_no_vlm_api_key(monkeypatch, tmp_path):
    """未配置：vlm_api_key 为 None → 返回未配置提示。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, {},
                             crop_dir=crop_dir, vlm_api_key=None)
    assert "未配置" in result
    assert "vlm_api_key" in result


def test_lookup_image_crop_not_found(monkeypatch, tmp_path):
    """crop 图片不存在 → 返回未找到提示，不抛异常。"""
    from amta import translate_tools as tt

    crop_dir = tmp_path / "crops"  # 目录存在但没有 u99.png
    crop_dir.mkdir(exist_ok=True)
    ws = _make_canon("u99", "テスト")

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)

    result = tt.execute_tool("lookup_image", {"region_id": "u99"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "未找到裁剪图" in result
    assert "u99.png" in result


def test_lookup_image_vlm_exception(monkeypatch, tmp_path):
    """VLM 调用抛异常 → 捕获并返回失败提示，不阻塞翻译。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    ws = _make_canon("u00", "テスト")

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)

    def _boom(img, text, api_key):
        raise ConnectionError("API timeout")

    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single", _boom)

    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "视觉验证调用失败" in result
    assert "ConnectionError" in result


def test_lookup_image_vlm_status_failed(monkeypatch, tmp_path):
    """VLM 返回 status != ok → 返回失败提示。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    ws = _make_canon("u00", "テスト")

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            status="failed", raw_output="500 Internal Server Error"))

    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "视觉验证返回失败" in result


def test_lookup_image_dependency_not_installed(monkeypatch, tmp_path):
    """视觉依赖未安装（PIL/vlm_verify import 失败）→ 返回未安装提示。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    ws = _make_canon("u00", "テスト")

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: False)

    result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                             crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "视觉依赖未安装" in result


# ── 工具循环集成 ─────────────────────────────────────────────────────────

def test_translate_with_retry_lookup_image_loop(monkeypatch, tmp_path):
    """集成：LLM 第一轮调用 lookup_image，结果回传，第二轮输出译文。"""
    from amta import translate

    crop_dir = _make_crop_file(tmp_path, "u00")
    calls = []

    def llm(messages, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "lookup_image", "arguments": '{"region_id": "u00"}'}}]}
        return {"content": '{"u00": "八意永琳"}', "tool_calls": None}

    # mock VLM 调用
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(
                            ocr_correct="incorrect", corrected_text="八意様",
                            visual_type="dialogue_bubble", speaker_hint="八意永琳"))

    canon = [{"region_id": "u00", "baberu_text": "ハ意様", "page": 0}]
    ws = {}
    out = translate.translate_with_retry(canon, llm, work_state=ws, max_retries=1,
                                          tools=translate.TOOLS_SCHEMA,
                                          crop_dir=crop_dir, vlm_api_key="sk-test")
    assert out["u00"] == "八意永琳"
    # 验证工具结果回传
    roles = [m["role"] for m in calls[1]]
    assert roles == ["system", "user", "assistant", "tool"]
    tool_content = calls[1][-1]["content"]
    assert "[lookup_image] u00" in tool_content
    assert "修正建议：「八意様」" in tool_content


def test_lookup_image_budget_enforced(monkeypatch, tmp_path):
    """预算真拦截：VISION_BUDGET 次调用后，下一次返回预算耗尽提示。"""
    from amta import translate_tools as tt

    crop_dir = _make_crop_file(tmp_path)
    ws = _make_canon("u00", "テスト")

    monkeypatch.setattr(tt, "_lookup_image_available", lambda: True)
    monkeypatch.setattr("amta.vlm_verify.vlm_verify_ocr_single",
                        lambda img, text, api_key: _fake_vlm_result(ocr_correct="correct"))

    budgets = {"lookup_image": tt.VISION_BUDGET}

    # 前 VISION_BUDGET 次正常执行
    for i in range(tt.VISION_BUDGET):
        if budgets["lookup_image"] <= 0:
            result = "预算已耗尽"
        else:
            budgets["lookup_image"] -= 1
            result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                                     crop_dir=crop_dir, vlm_api_key="sk-test")
        assert "OCR 验证：correct" in result

    # 第 VISION_BUDGET+1 次被拦截
    if budgets["lookup_image"] <= 0:
        result = "工具「lookup_image」本次调用预算已耗尽，请基于现有信息继续翻译"
    else:
        budgets["lookup_image"] -= 1
        result = tt.execute_tool("lookup_image", {"region_id": "u00"}, ws,
                                 crop_dir=crop_dir, vlm_api_key="sk-test")
    assert "预算已耗尽" in result


def test_tools_schema_contains_lookup_image():
    """TOOLS_SCHEMA 注册了 lookup_image，且参数 schema 正确。"""
    from amta import translate_tools as tt

    names = [t["function"]["name"] for t in tt.TOOLS_SCHEMA]
    assert "lookup_image" in names
    assert "lookup_term" in names
    assert "get_context" in names

    # 找到 lookup_image 的 schema
    schema = next(t for t in tt.TOOLS_SCHEMA if t["function"]["name"] == "lookup_image")
    params = schema["function"]["parameters"]
    assert "region_id" in params["properties"]
    assert params["required"] == ["region_id"]
    # description 应包含调用时机提示
    assert "OCR" in schema["function"]["description"] or "原图" in schema["function"]["description"]


def test_canon_items_injected_into_work_state(monkeypatch, tmp_path):
    """translate_with_retry 自动把 canon 索引注入 work_state["_canon_items"]。"""
    from amta import translate

    captured_ws = {}

    def llm(messages, tools=None):
        return {"content": '{"u00": "译文"}', "tool_calls": None}

    canon = [{"region_id": "u00", "baberu_text": "テスト", "page": 0}]
    ws = {"terms": {}}

    # 用 monkeypatch 拦截 execute_tool 来捕获 work_state
    original_execute = translate.execute_tool

    def _capture_execute(name, args, work_state, *a, **kw):
        captured_ws.update(work_state)
        return original_execute(name, args, work_state, *a, **kw)

    monkeypatch.setattr(translate, "execute_tool", _capture_execute)

    out = translate.translate_with_retry(canon, llm, work_state=ws, max_retries=1)
    assert out["u00"] == "译文"
    # _canon_items 应被注入
    assert "_canon_items" in ws
    assert "u00" in ws["_canon_items"]
    assert ws["_canon_items"]["u00"]["baberu_text"] == "テスト"
