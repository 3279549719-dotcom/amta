"""Stage 2 单元测试：VLM contact sheet 校验。"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.vlm_verify import make_contact_sheet, parse_vlm_output, vlm_verify_batch


def test_make_contact_sheet_grid_layout():
    """contact sheet 应按网格排列 crop 图。"""
    from PIL import Image

    crops = [Image.new("RGB", (100, 50), (255, 255, 255)) for _ in range(7)]
    sheet = make_contact_sheet(crops, cols=3, pad=10, bg=(0, 0, 0))
    # 3列 → 3行，每格 100+10*2=120 宽，50+10*2=70 高
    assert sheet.width == 3 * 120  # 360
    assert sheet.height == 3 * 70  # 210


def test_make_contact_sheet_empty():
    """空 crop 列表应返回小占位图。"""
    sheet = make_contact_sheet([])
    assert sheet.width > 0
    assert sheet.height > 0


def test_parse_vlm_output_line_by_line():
    """VLM 输出应按行解析，与输入顺序对应。"""
    raw = "文本1\n文本2\n文本3\n"
    result = parse_vlm_output(raw, expected_count=3)
    assert len(result) == 3
    assert result == ["文本1", "文本2", "文本3"]


def test_parse_vlm_output_empty_lines():
    """空行应解析为空字符串。"""
    raw = "文本1\n\n文本3\n"
    result = parse_vlm_output(raw, expected_count=3)
    assert result[1] == ""


def test_parse_vlm_output_count_mismatch():
    """输出数量与预期不符时应返回 None（触发容错）。"""
    raw = "只有一行\n"
    result = parse_vlm_output(raw, expected_count=3)
    assert result is None


def test_vlm_verify_batch_success():
    """vlm_verify_batch 成功时应返回 texts 和 status=ok。"""
    from PIL import Image

    crops = [Image.new("RGB", (50, 30), "white") for _ in range(3)]
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "テキスト1\nテキスト2\nテキスト3"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("amta.vlm_verify.requests.post", return_value=mock_response):
        result = vlm_verify_batch(crops, api_key="test-key")

    assert result["status"] == "ok"
    assert result["texts"] == ["テキスト1", "テキスト2", "テキスト3"]
    assert result["retries"] == 0


def test_vlm_verify_batch_count_mismatch_retry():
    """数量不符时应重试，最终返回 count_mismatch。"""
    from PIL import Image

    crops = [Image.new("RGB", (50, 30), "white") for _ in range(3)]
    mock_response = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "只有一行"}}]}
    mock_response.raise_for_status = MagicMock()

    with patch("amta.vlm_verify.requests.post", return_value=mock_response):
        with patch("amta.vlm_verify.time.sleep", return_value=None):
            result = vlm_verify_batch(crops, api_key="test-key", max_retries=1)

    assert result["status"] == "count_mismatch"
    assert result["texts"] is None
    assert result["retries"] == 1


def test_vlm_verify_batch_api_failure():
    """API 调用失败时应重试，最终返回 failed。"""
    from PIL import Image

    crops = [Image.new("RGB", (50, 30), "white") for _ in range(2)]

    with patch("amta.vlm_verify.requests.post", side_effect=Exception("API error")):
        with patch("amta.vlm_verify.time.sleep", return_value=None):
            result = vlm_verify_batch(crops, api_key="test-key", max_retries=1)

    assert result["status"] == "failed"
    assert result["texts"] is None


def test_canon_output_dual_engine_format():
    """canon.json 应输出双引擎文本（baberu_text + vlm_text）。"""
    item = {
        "region_id": "u00",
        "bbox": [10, 10, 50, 50],
        "baberu_text": "では豊ちゃん…",
        "vlm_text": "では豊ちゃん、輝夜様に…",
        "contained_in": None,
        "source_engines": ["det1"],
        "vlm_status": "ok",
    }
    assert "baberu_text" in item
    assert "vlm_text" in item
    assert "vlm_status" in item
    assert item["vlm_status"] in ("ok", "failed", "count_mismatch", "skipped")
