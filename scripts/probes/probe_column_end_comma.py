"""复现竖排列尾冗余逗号问题（Task 1 探针）。

问题：竖排分列时，断行算法主动把逗号族标点推到列末。列边界本身已经把
"停顿"视觉化了，列末再画一个逗号是同一停顿的重复表达 → 视觉冗余。

根因：`typeset_engine.break_lines()` 对"标点后断列"给 `cost -= 50` 奖励
（strong_break），算法因此偏好让逗号落在列末。

真实样本取自 touhou-getten-shinchi 第 4 页 translation/page_4.json，
其 typeset 产物（max_chars=6）逐字复现如下。

用法：uv run python scripts/probes/probe_column_end_comma.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from amta.typeset.typeset_engine import break_lines  # noqa: E402

# 逗号家族 = "顿"（句中停顿）。句末强终止符（。！？…）不在其列，另见
# vertical_punct._COLUMN_END_REDUNDANT。
COMMA_FAMILY = set("，、,")

# 真实样本：region_id -> (译文, 第4页 typeset 产物实际用的 max_chars)
# max_chars=6 由 artifacts/typeset/page_4.json 的 lines 逐字反推确认。
REAL_SAMPLES: dict[str, tuple[str, int]] = {
    "r03": ("而且漫画家是一种职业，在幻想乡靠它谋生很难哦", 6),
    "r01": ("没关系啦！就算画不好，月都的漫画家不也有很多画得很差的嘛！", 6),
}


def column_end_comma_indices(columns: list[str]) -> list[int]:
    """返回"末字符是逗号族且不是最后一列"的列号（纯诊断，不修任何东西）。"""
    return [
        i
        for i, col in enumerate(columns[:-1])
        if col and col[-1] in COMMA_FAMILY
    ]


def main() -> int:
    print("=" * 68)
    print("探针 1：真实样本（第4页 typeset 实际参数 max_chars=6）")
    print("=" * 68)
    hits = 0
    for rid, (text, max_chars) in REAL_SAMPLES.items():
        columns = break_lines(text, max_chars)
        bad = column_end_comma_indices(columns)
        print(f"\n[{rid}] {text}")
        print(f"  max_chars={max_chars}")
        for i, col in enumerate(columns):
            mark = "  <== 列末冗余逗号" if i in bad else ""
            print(f"    列{i}: {col!r} (末字符: {col[-1]!r}){mark}")
        print(f"  列尾冗余逗号的列: {bad}")
        hits += len(bad)

    print("\n" + "=" * 68)
    print("探针 2：max_chars 扫描 —— 证明这是系统性偏好，不是个案")
    print("=" * 68)
    for rid, (text, _) in REAL_SAMPLES.items():
        found = []
        for mc in range(4, 11):
            bad = column_end_comma_indices(break_lines(text, mc))
            if bad:
                found.append(mc)
        print(f"  [{rid}] 出现列尾逗号的 max_chars: {found}")

    print()
    assert hits, "预期至少有一列以逗号结尾且不是末列"
    print(f"复现成功：{hits} 处列尾冗余逗号，断行算法把逗号推到了列底")

    print("\n" + "=" * 68)
    print("对照：列末句号（强终止符）不做处理，属预期保留")
    print("=" * 68)
    ctrl = break_lines("第一句。第二句内容", 4)
    print(f"  break_lines('第一句。第二句内容', 4) = {ctrl}")
    print("  （。！？… 是句末语义终止符，即使落列末也保留）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
