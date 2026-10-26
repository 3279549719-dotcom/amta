# PSD 导出优化验收收尾实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 锁定 Codex 的 PSD 导出优化成果并以可复核证据闭环 Patrick 的验收契约——**同一页翻译内容导出 PSD:结果零差异、速度更快**。

**Architecture:** 三层防线。① 生成层守卫测试(无 Photoshop):锁定"每层恰好一次 ActionDescriptor 创建 + 零 DOM 逐属性赋值 + 与 legacy 路径同语义值 + 确定性 + 300 层规模不退化"——这是"更快"唯一可自动化的结构不变量(真实提速发生在 Photoshop 桥接往返次数上)。② 真页 paired 验收:冻结输入(带 sha256)上 original vs 最终代码各跑 2 轮,Photoshop 重开产物做像素与图层属性等价对比。③ 证据落盘 + 独立复核。

**Tech Stack:** pytest(项目 venv,pythonpath=["src","."],--timeout=60)、`amta.typeset.psd_jsx.build_script`(legacy 开关保留双路径)、基准工装 `scripts/benchmark_psd.py` + `scripts/inspect_psd.py`、Photoshop CLI(`-r jsx`,工装设计为永不关闭已开实例)。

**执行方式:** Patrick 已指定"先写计划 → TDD 测试完成",本计划由主线 inline 执行(执行中不再征询选项);复核按集群规范派独立 subagent。

**工作分支:** `eirin/psd-export-optimize`(worktree `E:\manga translator agent\.worktrees\eirin-psd-relay`,基线 2012735,已含 9142e2e 快照 + 2fcd702 索引修复)。**不触碰主 checkout**(Codex 仍休眠存活)。

**已知基线(冻结证据,来自 output\psd-benchmark-20261026\):**
- Codex paired-final(22:06,真实页 5/3/19×5 轮):wall 中位 5.04→2.54 / 11.54→4.04 / 10.55→3.55;layers 中位 2.77→0.38 / 9.41→1.18 / 8.19→1.24
- 等价:3/3 页 pixels_identical=true、layer_properties_identical=true(当时候选=batch3 中间版)
- eirin 边界复测(23:19–23:40,合成 72/300 层×3 轮换序,候选=最终代码):wall 中位 88.2→34.1 / 70.6→28.6;layers 中位 64.5→11.9 / 65.4→10.0;300 层"回归"判定为单次采样被 handoff 污染(56.7s/82.8s 尖峰实测)
- 真页 paired 用**最终代码**(当前 psd_jsx.py)的验收运行此前缺失 → 本计划 Task 2 补上,这是验收契约的直接证据

---

### Task 1: 生成层验收守卫测试(TDD)

**Files:**
- Create: `tests/test_psd_acceptance.py`

**背景:** 现有测试(test_psd_progress.py)覆盖了 batch 默认值与 legacy 开关的存在性,但没有锁定**验收契约本身**:层创建往返次数有上限(速度)、语义值与 legacy 一致(等价)、大规模生成不退化。地面真值已实测(2026-10-26 探针):2 层样本下新路径 `Mk '`=2、`executeAction(`=3(2 创建 + applyTateChuYoko 定义 1 处)、`ti\d+.<attr>=` 赋值=0;legacy 路径 `Mk '`=0、`ti` 赋值=18。

- [ ] **Step 1: 写守卫测试(完整代码如下)**

```python
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
```

- [ ] **Step 2: 变异验证 RED(证明测试能抓住"退回慢路径")**

把 `src/amta/typeset/psd_jsx.py` 的 `build_script(..., legacy: bool = False)` 临时改为 `legacy: bool = True`,运行:

Run: `.venv\Scripts\python.exe -m pytest tests/test_psd_acceptance.py -v --timeout=60`(cwd=worktree)
Expected: 4 FAIL / 1 PASS——
- `test_descriptor_path_creates_one_layer_per_item_with_bounded_bridge_ops` FAIL(Mk=0≠2,ti 赋值=18≠0)
- `test_descriptor_path_uses_fewer_bridge_ops_than_legacy` FAIL(new_ops=18≠2)
- `test_descriptor_carries_same_semantic_values_as_legacy` FAIL(textKey 描述符缺失)
- `test_scale_300_layers_stays_bounded` FAIL(Mk=0≠300)
- `test_batched_generation_is_deterministic` PASS(确定性不受路径影响,非判别性断言)

- [ ] **Step 3: 还原变异,验证 GREEN**

还原 `legacy: bool = False`,重跑同命令。Expected: `5 passed`。

- [ ] **Step 4: PSD 相关回归仍绿**

Run: `.venv\Scripts\python.exe -m pytest tests/test_psd_acceptance.py tests/test_psd_progress.py tests/test_psd_export_runtime.py tests/test_gui_server.py tests/test_pipeline_cache_outputs.py tests/test_pipeline_cleanup.py -q --timeout=120`
Expected: `56 passed`(51 旧 + 5 新)。

- [ ] **Step 5: Commit**

```bash
git add tests/test_psd_acceptance.py
git commit -m "test(psd): acceptance guards — descriptor round-trip bound + legacy-semantic parity"
```

### Task 2: 真页 paired 验收运行(Photoshop,最终代码)

**Files:**
- 产物(gitignored,不进 git): `output/acceptance-final/`(worktree 下)
- 证据摘要: `output/acceptance-final/summary.md` + `acceptance-equivalence.json`

**输入:** 主仓冻结输入 `E:\manga translator agent\output\psd-benchmark-20261026\inputs.json`(真实页 5/3/19,clean.png+typeset.json 带 sha256:页5 clean `d919b1bf…`、页3 `0e094ca6…`、页19 `d5138aa9…` 见 inputs.json 全值)。

- [ ] **Step 1: 预检**——Photoshop 可执行(`find_photoshop_executable()` 非 None)、无并行基准在跑(Codex 休眠,仓库 22:13 后零写入已确认)。
- [ ] **Step 2: paired 运行**(original=frozen baseline 生成器,candidate=当前分支 psd_jsx.py):

```
.venv\Scripts\python.exe scripts\benchmark_psd.py --inputs "E:\manga translator agent\output\psd-benchmark-20261026\inputs.json" --jsx-source "E:\manga translator agent\output\psd-benchmark-20261026\baseline_psd_jsx.py" --compare-source "E:\manga translator agent\.worktrees\eirin-psd-relay\src\amta\typeset\psd_jsx.py" --output "E:\manga translator agent\.worktrees\eirin-psd-relay\output\acceptance-final" --repeat 2
```
Expected: 12/12 行 success=true(2 变体×3 页×2 轮),exit 0。

- [ ] **Step 3: 聚合中位数**——解析 acceptance-final\*.log(JSONL)按 page×variant 求 wall/layers 中位数,写 `summary.md`(判定阈值见 Step 6)。
- [ ] **Step 4: 等价检查**——`scripts\inspect_psd.py` 重开 12 个 output.psd(每页 original/candidate 同轮配对),产出 metadata.json + preview.png。
- [ ] **Step 5: 等价对比**——一次性证据工具 `output/acceptance-final/compare_equivalence.py`(仿 diff-descriptors.py 递归 diff):对每页每轮对比 (a) preview.png 像素数据(PIL,非字节),(b) 文字层标量属性 contents/font/size/leading/direction/justification/position/color,(c) text_descriptor 深度差异仅记录。写 `acceptance-equivalence.json`。
- [ ] **Step 6: 验收判定(硬阈值)**——① 每页每轮 pixels_identical=true;② 文字层标量属性 100% 相等;③ 每页 wall 中位数 candidate < original。三条全满足 → 验收 PASS;任一不满足 → 按失败证据修复(TDD:先加失败测试)后重跑。

### Task 3: 独立复核(集群 S4)

- [ ] **Step 1:** 派 1 个复核 subagent:对照验收契约审 计划文档、守卫测试、benchmark 原始日志、equivalence JSON;结论写 `.cluster/psd-relay-tdd/review.md`(置信分级)。
- [ ] **Step 2:** 复核发现问题 → 修复一次并复验;仍不过 → 带瑕疵交付并列明。

### Task 4: 收口提交与交付

- [ ] **Step 1:** commit 计划文档:`git add docs/superpowers/plans/2026-10-26-psd-export-optimization-acceptance.md && git commit -m "docs(plans): PSD export optimization acceptance plan + evidence"`
- [ ] **Step 2:** 更新交付 HTML 报告(追加"验收"节:守卫测试 + 真页验收数字)。
- [ ] **Step 3:** 终态汇报:完整 plan 全 done + 交付物清单。

---

## Self-Review(写计划后自查)

1. **Spec coverage:** 验收契约三要素——同页翻译内容(Task 2 冻结输入=真实翻译页)、结果零差异(Task 1 语义等价守卫 + Task 2 像素/属性对比)、更快(Task 1 往返上限守卫 + Task 2 wall 中位数阈值)。✔
2. **Placeholder scan:** 所有代码块为完整可运行代码(地面真值实测过字符串精确形态);所有命令含绝对路径与预期输出。✔
3. **Type consistency:** `build_script(clean, output, error, completion, data, *, progress_path="", cancel_path="", legacy=False)` 与测试调用一致;`MK_CREATE/TI_ASSIGN` 正则与生成产物实测一致(24.0 浮点格式、`#Pnt`、`'Mk  '` 双空格)。✔

## 风险与边界

- Task 2 依赖 Photoshop 本机可用;若 PS 忙/模态阻塞导致 dispatch 延迟(已观测过 56–83s 尖峰),以中位数与 layers 相位为准判读,单轮 handoff 尖峰不构成失败。
- `ti0.position = [300.0, 284.8]` 断言钉住当前 iter_vertical_rows 行为;若排版引擎行高逻辑变化,该守卫按新真值更新(属预期维护)。
- 分支不推送 origin(需 Clash);合回 main 由 Patrick 拍板,避免与休眠 Codex 的 checkout 冲突。
