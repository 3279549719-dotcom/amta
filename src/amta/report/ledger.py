"""report ledger — 页头四数对账：detect / ocr / translate / rendered。

纯函数，读 PageReport，返回 dict。不做视觉判断，不做归因，不做 retry。
数字掉了由渲染层高亮红，肉眼去 HTML/PSD 找原因。
"""
from __future__ import annotations

from .model import PageReport, StageOutput


def _find_stage(page: PageReport, key: str) -> StageOutput | None:
    return next((s for s in page.stages if s.key == key), None)


def compute_ledger(page: PageReport) -> dict[str, int | None]:
    """数文本流四站过手数。缺阶段 = None。"""
    ledger: dict[str, int | None] = {}

    detect = _find_stage(page, "detect")
    ledger["detect"] = len(detect.cells) if detect else None

    ocr = _find_stage(page, "ocr")
    if ocr:
        ledger["ocr"] = sum(
            1 for c in ocr.cells.values()
            if isinstance(c, dict) and str(c.get("text", "")).strip()
        )
    else:
        ledger["ocr"] = None

    translate = _find_stage(page, "translate")
    if translate:
        ledger["translate"] = sum(
            1 for c in translate.cells.values()
            if isinstance(c, dict) and str(c.get("translation", "")).strip()
        )
    else:
        ledger["translate"] = None

    typeset = _find_stage(page, "typeset")
    ledger["rendered"] = len(typeset.cells) if typeset else None

    return ledger
