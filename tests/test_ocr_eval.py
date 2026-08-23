"""ocr_eval.py 评测聚合测试：按 GT 内容算 CER/EM，分 4 类 + ALL。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_eval_computes_cer_em_by_gt():
    from ocr_eval import eval_rows
    # meta 用相对路径、preds 用绝对路径（basename 匹配）
    meta = [{"crop": "output/data/crops/page_1_gt00.png", "content": "月の都", "type": "bg_text"}]
    preds = [{"crop": "E:/x/output/data/crops/page_1_gt00.png", "ocr": "月の都"}]
    rows, summary = eval_rows(meta, preds)
    assert rows[0]["cer"] == 0.0
    assert rows[0]["em"] == 1.0
    assert summary["ALL"]["n"] == 1
    assert summary["ALL"]["cer"] == 0.0
    assert summary["ALL"]["em"] == 1.0


def test_eval_misses_empty_pred():
    from ocr_eval import eval_rows
    meta = [{"crop": "page_1_gt00.png", "content": "月の都", "type": "bg_text"}]
    preds = [{"crop": "page_1_gt00.png", "ocr": ""}]
    rows, summary = eval_rows(meta, preds)
    assert rows[0]["em"] == 0.0
    assert summary["ALL"]["cer"] > 0.0


def test_eval_groups_by_type():
    from ocr_eval import eval_rows
    meta = [
        {"crop": "a.png", "content": "甲", "type": "dialogue_in"},
        {"crop": "b.png", "content": "乙", "type": "sfx"},
    ]
    preds = [{"crop": "a.png", "ocr": "甲"}, {"crop": "b.png", "ocr": "错"}]
    rows, summary = eval_rows(meta, preds)
    assert summary["dialogue_in"]["n"] == 1
    assert summary["sfx"]["n"] == 1
    assert summary["ALL"]["n"] == 2
