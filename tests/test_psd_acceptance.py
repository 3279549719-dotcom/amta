"""PSD 导出优化验收守卫(2026-10-26 验收契约)。

契约:同一页翻译内容导出 PSD —— 结果零差异、速度更快。
生成层(本文件,无 Photoshop)锁两点:
  - 速度不变量:每层恰好一次 'Mk ' 描述符创建、零 DOM 逐属性赋值
    (真实开销在 Photoshop 桥接往返,往返数由脚本结构决定);
  - 等价不变量:新路径与 legacy DOM 路径对同一输入产出同语义值
    (文本/字体家族/字号缩放/锚点/颜色)。
PSD 层等价由真页 paired 验收运行证明,见
docs/superpowers/plans/2026-10-26-psd-export-optimization-acceptance.md Task 2。
"""
import re
import time

from amta.typeset.psd_jsx import build_script

MK_CREATE = r"executeAction\(charIDToTypeID\('Mk  '\)"
TI_ASSIGN = r"ti\d+\.(?:contents|font|size|color|leading|position|direction|justification|useAutoLeading)\s*="

SAMPLE_ITEMS = [
    {"region_id": "r0", "lines": ["测试 Hello!?第二行"], "font_size": 24.0,
     "anchor_pos": [300.0, 400.0], "rendered_color": "#1A1A1A",
     "layout_direction": "vertical"},
    {"region_id": "r1", "lines": ["plain"], "font_size": 20.0,
     "anchor_pos": [100.0, 200.0], "layout_direction": "horizontal",
     "align": "center"},
]


def test_descriptor_path_creates_one_layer_per_item_with_bounded_bridge_ops():
    script = build_script("clean.png", "out.psd", "err.txt", "done.txt",
                          {"rendered_items": SAMPLE_ITEMS})
    assert len(re.findall(MK_CREATE, script)) == 2  # 每层一次 'Mk '
    # executeAction 只允许出现在 applyTateChuYoko 定义(1)+ 每层创建(N)
    assert script.count("executeAction(") == len(re.findall(MK_CREATE, script)) + 1
    assert len(re.findall(TI_ASSIGN, script)) == 0  # 无 DOM 逐属性赋值


def test_descriptor_path_uses_fewer_bridge_ops_than_legacy():
    data = {"rendered_items": SAMPLE_ITEMS}
    new = build_script("clean.png", "out.psd", "err.txt", "done.txt", data)
    old = build_script("clean.png", "out.psd", "err.txt", "done.txt", data, legacy=True)
    new_ops = len(re.findall(MK_CREATE, new)) + len(re.findall(TI_ASSIGN, new))
    old_ops = len(re.findall(MK_CREATE, old)) + len(re.findall(TI_ASSIGN, old))
    assert new_ops == 2            # 每层 ≤1 次创建
    assert old_ops >= 16           # legacy 每层 ≥8 次属性往返
    assert new_ops < old_ops


def test_descriptor_carries_same_semantic_values_as_legacy():
    data = {"rendered_items": SAMPLE_ITEMS}
    new = build_script("clean.png", "out.psd", "err.txt", "done.txt", data)
    old = build_script("clean.png", "out.psd", "err.txt", "done.txt", data, legacy=True)
    # 文本:竖排标点归一后两边一致
    assert "textKey'), '测试 Hello！？第二行')" in new
    assert "ti0.contents = '测试 Hello！？第二行'" in old
    # 字体解析同一家族名
    assert "findFontPostScriptName('Microsoft YaHei')" in new
    assert "findFontPostScriptName('Microsoft YaHei')" in old
    # 字号 × dpi 缩放同一表达式
    assert "putUnitDouble(stringIDToTypeID('size'), charIDToTypeID('#Pnt'), 24.0 * dpiScale0)" in new
    assert "new UnitValue(24.0 * dpiScale0, 'pt')" in old
    # 定位同一锚点(新路径用文档百分比表达同一像素位)
    assert "300.0 / doc.width.as('px') * 100" in new
    assert "ti0.position = [300.0, 284.8]" in old
    # 颜色同一 RGB(#1A1A1A → 26,26,26)
    for channel in ("red", "green", "blue"):
        assert f"putDouble(stringIDToTypeID('{channel}'), 26)" in new
    assert "tc0.rgb.red = 26" in old


def test_batched_generation_is_deterministic():
    data = {"rendered_items": SAMPLE_ITEMS}
    first = build_script("clean.png", "out.psd", "err.txt", "done.txt", data)
    second = build_script("clean.png", "out.psd", "err.txt", "done.txt", data)
    assert first == second


def test_scale_300_layers_stays_bounded():
    data = {"rendered_items": [
        {"region_id": f"r{i}", "lines": ["字"], "font_size": 20.0,
         "anchor_pos": [10.0, 10.0]} for i in range(300)
    ]}
    start = time.perf_counter()
    script = build_script("clean.png", "out.psd", "err.txt", "done.txt", data)
    elapsed = time.perf_counter() - start
    assert len(re.findall(MK_CREATE, script)) == 300       # 每层一次创建
    assert script.count("executeAction(") == 301           # 300 创建 + tcy 定义
    assert len(re.findall(TI_ASSIGN, script)) == 0
    assert elapsed < 1.0                                    # 纯字符串生成不得退化
