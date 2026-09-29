# 竖排列尾逗号修复 — High Effort 边缘案例验证报告

**日期**：2026-09-29
**分支**：`fix/column-end-comma-high-effort-verify`（base `02123ef`，已合并 `main` `4e3d659`）
**计划**：`docs/superpowers/plans/2026-09-29-column-end-comma-high-effort-verify.md`
**上一轮报告**：`docs/reports/2026-09-29-column-end-comma-fix.md`
**状态**：全部验证项通过；`npm run check` 通过；`pytest tests/` **634 passed, 7 skipped, 0 failed**
**建议**：可以合并到 `main`（有一条 main 侧既存缺陷建议一并修，见 §10.1）

---

## 1. 结果总览

| # | 验证项 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | 白字深底气泡 | ✅ | 3 处命中，逐像素字形回放等式 0 差异，深底无残留 |
| 2 | VLM 渲染路径 | ✅ | 4 页 VLM，2 处列末逗号消隐，元数据逐键一致 |
| 3 | 横排零影响 | ✅ | 24/24 横排区域矩形内逐像素一致；16/16 横排逗号有墨 |
| 4 | 边缘案例单元测试 | ✅ | 新增 **24** 条（要求 ≥8） |
| 5 | 与 main 合并冲突 | ✅ | 1 个文件冲突，已解；合并前后验证指标**逐项相同** |
| 6 | 全量回归 | ✅ | `pytest tests/` 0 failed；`npm run check` PASS |
| 7 | 验证报告 | ✅ | 本文件 |

整部作品（65 页，`touhou-getten-shinchi`）的端到端重渲染结论：

```
页数 65
竖排列末逗号合计   : 82   （，72 / 、10）
  白字深底         : 3
掩码确实生效       : 82/82
字形回放等式 after+replay(字形)==before : 0 像素差异（全 65 页）
改动溢出掩码字格(位移)                  : 0 像素
全图改动像素合计                        : 3992
落盘元数据 before/after 完全一致        : 65/65
横排区域 24 个（矩形内逐像素一致 24/24）｜横排逗号字格 16 个（有墨 16/16）
VLM 页 [1, 38, 42, 60]｜VLM 列末逗号 2 处
```

> **合并前 / 合并后两次全量验证的 13 项汇总指标与逐页命中数完全相同**（`verify_report_pre_merge.json`
> vs `verify_report_post_merge.json`，脚本比对输出 `identical summaries: True`）。这说明把掩码
> 从"按字符 while 循环"迁到 main 的"按行 for 循环"是**行为等价**的。

---

## 2. 本次改了什么

### 2.1 功能改动（3 个提交）

| 文件 | 改动 |
|---|---|
| `src/amta/typeset/vertical_punct.py` | `column_end_pause_mask` 增加**单列保护**（见 §9.1）|
| `tests/test_column_end_pause_edge_cases.py` | 新增 16 条边缘案例测试 |
| `tests/typeset/test_vlm_render.py` | 新增 6 条 VLM 路径测试 |
| `tests/test_column_end_pause_render.py` | 新增 2 条空译文回归测试（合并提交内）|
| `scripts/probes/verify_column_end_comma_high_effort.py` | 新增：全作品 65 页 before/after 验证探针（字形回放判据）|
| `scripts/probes/render_page_before_after.py` | 修 bug：原来只补丁 `typeset_render.column_end_pause_mask`，VLM 页的 "before" 其实仍开着掩码 |

### 2.2 合并 main（1 个提交）

| 文件 | 来源 |
|---|---|
| `src/amta/typeset/typeset_render.py` | **冲突**（唯一），手工解 |
| `docs/module-map.md`、`scripts/run_gui.py`、`src/amta/gui/*`、`src/amta/typeset/psd_jsx_export.py`、`tests/test_psd_jsx_export.py`、`tests/test_render_artifact_contract.py` | main 侧自动合并，未改 |

### 2.3 脚手架消歧（1 个提交，见 §10.5）

`scripts/run_sdk_task.py`、`scripts/_run_high_effort_verify.py`、`docs/module-map.md`、
计划文件入库 —— 让 `npm run check` 与全量 pytest 变绿。

### 2.4 明确**没有**改的东西

- 译文文本、翻译 prompt、翻译后端 —— 零改动
- 横排排版逻辑 —— 零改动
- `break_lines()` 的 `strong_break` DP 奖励 —— 未动（只消除视觉输出，不改断列策略）
- 成品图 / 最终译文 —— 未手改，before/after 全部由生产入口 `typeset_station.run()` 现场重渲染
- 上游产物（主项目 `workspace/touhou-getten-shinchi/`）—— **只读**
- 未 `git push`，未合并到 main，未动其他 worktree

---

## 3. Task 1：白字深底气泡

### 3.1 怎么找的（上一轮的误判已修正）

上一轮用"字格内主色 = 背景色"判墨，被 `page_8 r11` 打脸。本次改为按**中位亮度**判背景：

- 文字颜色接近白：`rendered_color` 亮度 > 200；
- 背景深色：**竖排墨迹矩形内像素亮度的中位数** < 110。

为什么必须用中位数：真实页的深色背景是**带噪点的纹理**，每个像素颜色都略有不同，
"出现次数最多的颜色"反而被颜色完全一致的纯白字形像素夺冠 —— `page_8 r11` 因此被
判成"白底"。中位数取的是"占多数的背景像素"，与前景/背景谁亮谁暗无关。

### 3.2 命中 3 处，全部通过

| 页 / 区域 | 列文本 | 字色 | 背景中位亮度 | 字号 / 字体 | 字形像素 | 移除像素 | 格内墨迹 before→after |
|---|---|---|---|---|---|---|---|
| `page_5 r08` | `行了，` | `#ffffff` | **3.0** | 46 / msyhbd.ttc | 80 | **80** | 71 → 0 |
| `page_8 r11` | `铃仙，` | `#ffffff` | **22.0** | 35 / msyh.ttc | 34 | **34** | 25 → 0 |
| `page_35 r00` | `啊，` | `#ffffff` | **0.0** | 52 / msyh.ttc | 75 | **75** | 65 → 0 |

"字形像素 == 被移除像素"意味着被移除的**正好**是那一个字形，不多不少。

### 3.3 无残留墨迹 + 零位移（最强断言）

判据不是"字格内没有墨"（见 §8），而是**字形回放等式**：

```
after + replay(被掩码字形)  ==  before      （整页逐像素，0 差异）
```

65 页 82 个字格全部成立，`page_5/8/35` 的 3 个白字深底字格自然包含在内。
这条等式的含义：

1. after 图里**没有该字形的任何像素** —— 否则重放会叠加出多余墨迹、等式不成立；
2. 除该字形外**全图逐像素不变** —— 任何位移/重排都会让等式不成立。

`page_8 r11` 的 ASCII 位图（`#` = 与格内背景差 > 60 的像素，空格 = 深色背景）：

```
   before                              after
   ...................................   ...................................
   ................###................   ...................................
   ...............###.................   ...................................
   ...............###.................   ...................................
   ..............###..................   ...................................
   ...................................   ...................................
```

逗号（白色笔画）消失，深色背景上没有留下任何残迹。`page_5 r08`、`page_35 r00` 位图同形。

---

## 4. Task 2：VLM 渲染路径

### 4.1 路由确认

canon 的 `ocr_engine` 分布：`hayai` 61 页、`vlm-paratext` **4 页**（`page_1/38/42/60`）、
`vlm-direct` 2 页。只有 `vlm-paratext` 走 `typeset_station` 的早期 return 分支 →
`vlm_render.render_text`；`vlm-direct` 走普通 MITS 路径（代码位置：
`src/amta/typeset/typeset_station.py:32`）。

### 4.2 验证结果

| 项 | 结果 |
|---|---|
| VLM 页列末逗号 | 2 处，全部消隐：`page_60 r01` 列3 `的物质生成量，来减轻炎症、`（simsun 28，移除 26px）、`page_60 r02` 列3 `功能障碍、肾功能障碍、`（simsun 34，移除 36px）|
| 字体 / 字号 / 颜色 / lines 元数据 | **逐键完全一致**（`meta_before == meta_after` 整字典比较，65/65 页成立）|
| 零位移 | 改动溢出字格 0 像素 |
| 掩码时机 | 见 §4.3 |

### 4.3 掩码时机：断列**之后**、按最终列序列

VLM 有独立的断列逻辑 `_vertical_columns(text, cpc)`（定宽切分，不做避头尾），
与 MITS 的 DP 断列完全不同。执行顺序是：

```
layout_text()  →  _vertical_columns()  →  断列完成，得 meta["lines"]
render_text()  →  hide = column_end_pause_mask(meta["lines"])   ← 在断列之后
               →  _render_vertical(..., [verticalize_text(s) for s in lines], hide_mask=hide)
```

`tests/typeset/test_vlm_render.py::test_vlm_mask_is_computed_on_post_split_columns`
用 spy 抓住掩码实参，断言它**恰好等于** `meta["lines"]` —— 时机正确（断列前算就不知道谁在列末）。

掩码按**横排原文**算、作用在 **verticalize 之后**的列上，靠"1:1 字符映射"对齐下标。
`test_vlm_mask_indices_survive_verticalize` 用 `（你好），世界` 钉死这一点：
`（`→`︵` 之后，列末逗号（下标 4）被隐藏、列首 `︵`（下标 0）照画 —— 下标没错位。

> **样本量诚实记录**：VLM 页只有 2 处列末逗号，且 `page_1/38/42` 一处都没有
> （VLM 的定宽切分本来就不偏好把逗号推到列末）。所以 VLM 侧的结论**主要靠 6 条单元
> 测试**支撑，真实数据只是"没有反例"。这不是遗漏，是数据本身的分布。

---

## 5. Task 3：横排零影响

### 5.1 spy 测试：横排一次都不调用掩码

- `tests/test_column_end_pause_render.py::test_horizontal_path_never_calls_column_mask`
  （MITS 横排，spy 断言调用列表为空）
- `tests/typeset/test_vlm_render.py::test_vlm_horizontal_path_never_calls_mask`
  （VLM 横排，spy 断言零调用 + 输出 `tobytes()` 与修复前逐字节相同）

### 5.2 真实页面逐像素对比

65 页共 **24 个横排区域**，用渲染器几何复算出各区域的墨迹矩形，断言矩形内
before/after 逐像素一致：

```
横排区域 24（矩形内逐像素一致 24/24）  OK
横排逗号字格 16（有墨 16/16）          OK
几何自校验：横排非空字符格 696/696 有墨
```

"几何自校验"是探针自带的反向验证：如果我对横排字格位置的复算有偏差，那些字格就会
读到 0 墨；696/696 全中说明复算无误 —— 所以"16 个逗号字格有墨"是真结论，不是空转。

横排逗号（全部为句中/句末 `，`）分布：

| 页 / 区域 | 逗号字格数 | 各格墨迹 | 区域矩形改动像素 |
|---|---|---|---|
| `page_1 r00` | 4 | 58 / 52 / 66 / 51 | 0 |
| `page_36 r00` | 4 | 30 / 30 / 30 / 30 | 0 |
| `page_38 r00` | 3 | 73 / 76 / 81 | 0 |
| `page_39 r00` | 2 | 50 / 50 | 0 |
| `page_55 r00` | 3 | 43 / 43 / 43 | 0 |

---

## 6. Task 4：边缘案例单元测试

新增 **24** 条（要求 ≥8）。原 30 条列末逗号相关测试全部保持通过，合计 **54 条**：

| 文件 | 条数 | 其中本次新增 |
|---|---|---|
| `tests/test_column_end_pause.py` | 17 | 0（既有）|
| `tests/test_column_end_pause_edge_cases.py` | 16 | **16** |
| `tests/test_column_end_pause_render.py` | 10 | **2** |
| `tests/typeset/test_vlm_render.py` | 11 | **6** |

计划要求的 8 个边缘案例逐一对应：

| 计划要求 | 测试 | 结论 |
|---|---|---|
| 单列文本列末逗号不消隐 | `test_single_column_trailing_comma_is_kept`、`test_single_column_kept_for_every_comma_family_member` | 不掩码（**本次行为改动**，见 §9.1）|
| 单字符列不消隐 | `test_single_char_comma_column_is_not_blanked` | `["，","乙丙丁"]` → 保留，避免整列空白 |
| 连续逗号 | `test_consecutive_commas_only_the_column_end_one_is_masked`、`test_triple_consecutive_commas_only_last_masked` | `"文字，，"` → 只掩末位，第一个照画 |
| 半角 / 全角逗号都掩码 | `test_halfwidth_and_fullwidth_comma_both_masked` | 两者都掩 |
| 顿号同族 | `test_ideographic_comma_same_policy_as_comma` | 掩码，不做单独特例 |
| `。！？` 不消隐 | `test_strong_terminators_kept_at_column_end` | 一律保留 |
| `…` 不消隐 | `test_ellipsis_kept_at_column_end` | 横排 `…` 与竖排 `︙` 都保留 |
| `；：` 处理 | `test_semicolon_and_colon_kept_at_column_end` | **保留**（固化当前实现，见 §9.2）|

额外补的（超出计划要求）：竖排标点组合 `！？` 落列末、空输入/空列、掩码精确下标、
`verticalize_text` 与掩码的交互、输入不被就地修改、多列时末列仍按既定策略掩码
（锁住上一轮决策）、空译文不炸。

---

## 7. Task 5：合并冲突解决

### 7.1 冲突范围

`git merge-tree` 预演 + 实跑结果一致：**只有 1 个文件冲突**
（`src/amta/typeset/typeset_render.py`）。`docs/module-map.md` 自动合并成功；
`psd_jsx_export.py` / gui / 其它测试为 main 单边改动，直接采纳。

### 7.2 冲突的本质

| | main | 本分支 HEAD |
|---|---|---|
| 行拆分 | `_count_vertical_lines` → `iter_vertical_rows` + `VerticalRow`（PNG 与 PSD 共用真源）| 未改 |
| `_render_vertical` 主循环 | **按行 for**（`for row in iter_vertical_rows(col_text)`），`y0` 提到循环外 | **按字符 while**，循环内维护 `i` |
| 掩码 | 无 | `hide_mask`，**按字符下标** `col_hide[i]` |

冲突点：同一个函数被重写，而掩码的索引维度（字符）与 main 的迭代维度（行）不一致。

### 7.3 解决方式（采纳 main 结构，把掩码挂到字符下标上）

```python
for col_idx, col_text in enumerate(lines):
    x = x_start - col_idx * col_width
    y = y0
    col_hide = hide_mask[col_idx] if hide_mask else None
    char_i = 0                      # ← 当前行首字符在本列中的字符下标
    for row in iter_vertical_rows(col_text):
        if row.kind == "punct":
            for k, pch in enumerate(group):
                if col_hide and col_hide[char_i + k]:   # ← 按字符下标查，不是行号
                    continue
                ...
        elif row.kind == "latin":
            for k, (c, f, cw) in enumerate(...):
                if col_hide and col_hide[char_i + k]:
                    gx += cw
                    continue
                ...
        else:
            if not (col_hide and col_hide[char_i]):
                _paste_glyph_centered(...)
        y += lh
        char_i += len(row.text)     # ← 行推进时同步推进字符游标
```

关键点：**被掩码的列末逗号必然是 `char` 行**（逗号既不在 `VERTICAL_COMBINE`= `！？!?` 里，
也不被 `_is_horizontal_char` 判为横向字符），所以"一行一字符"时 `char_i` 与行号相同；
但代码没有依赖这个巧合 —— `punct`/`latin` 组合行同样按 `char_i + k` 查，语义正确。

**合并前后全量验证逐项相同**（§1 末），这是"下标映射正确"的实测证明，不只是推理。

### 7.4 合并中发现并修掉的 main 侧缺陷（§10.1）

main 把 `max_col_h = max(len(iter_vertical_rows(c)) for c in lines) * lh` **提到了列循环外**。
本作品 `page_5 r13` 的译文是空串 `""`，`fit_font_size("")` 返回 `lines == []` →
`max()` 对空序列直接 `ValueError`。旧实现把 `max` 写在循环**内部**，空列表时循环体不执行，
侥幸不炸；重构后就会炸。已在合并中补 `default=0`，并加两条回归测试：

- `test_render_vertical_with_no_columns_is_a_noop`
- `test_render_item_with_empty_text_returns_empty_lines`

> 这是本次合并**唯一**的行为差异（main 崩 → 我们正常渲染空列）。建议 main 也补这个 `default=0`。

### 7.5 合并后重新生成第 4 页对比图

```
uv run python scripts/probes/render_page_before_after.py --pages 4 8 12 13 16 41
uv run python scripts/probes/make_comparison.py            --pages 4 8 12 13 16 41
```

产物（`workspace/column-end-comma-fix/`，时间戳 2026-09-29 12:21，**合并后**重渲染）：

| 页 | 列末逗号 | 区域 | 全图改动 | 位移 |
|---|---|---|---|---|
| page_4 | 6 | r00 r01 r03 r06 r07 | 244px | 0 |
| page_8 | 7 | r06 r07 r09 r11 r14 r15 | 360px | 0 |
| page_12 | 5 | r01 r02 r03 r04 | 208px | 0 |
| page_13 | 5 | r01 r03 r05 r10 | 186px | 0 |
| page_16 | 4 | r00 r06 r09 r11 | 159px | 0 |
| page_41 | 4 | r00 r09 r10 | 221px | 0 |

`page_4` 的 6 处（含计划点名的 r01 / r03 两个问题气泡）逐格 `before 有墨 → after 无墨`：

```
r00 列3 '虚数之海中，'  25 → 0     r01 列1 '就算画不好，' 45 → 0
r00 列6 '那条龙现身，'  25 → 0     r03 列1 '是一种职业，' 37 → 0
r06 列0 '嘛，'          23 → 0     r07 列1 '信并努力，'  45 → 0
```

图片：`page_4_comparison.png`（整页 before|after 并排 + 红框）、`page_4_diff.png`
（移除像素高亮成红）、`page_4_zoom_{r00,r01,r03,r06,r07}.png`（逐区域放大），另 5 页同类。

---

## 8. 判据说明：为什么"字格内无墨"不是有效判据

上一轮用"字格内墨迹像素数 after == 0"作为通过标准。本次全量跑时它在 `page_60 r02` 列 3
报出 `158 → 129` 的"残留"，**逐像素查证后确认不是缺陷**：该字格顶部有一条**原作框线**
（横跨 x 260–305 的长横线），before/after 都在，与逗号无关。

同类干扰还包括：上一行字形的溢出笔画（VLM 的列宽很紧时会越界几个像素）。

所以本次改用**字形回放**：

```
after + replay(被掩码字形)  ==  before
```

`replay` 用渲染器自己的原语 `_paste_glyph_centered`，字体/颜色/描边全部取自落盘元数据
（`font_path` / `rendered_color` / `rendered_stroke` / `stroke_width`），所以它就是
"如果没被掩码会画成什么样"。等式成立 ⇔ after 里没有该字形 + 其余逐像素不变。
这条判据**天然免疫**原作线、邻字溢出、深色噪声背景 —— 那些像素在 before/after 里相同，
会被等式两边同时抵消。

---

## 9. 与计划 / 上一轮的偏差（诚实记录）

### 9.1 单列文本不再消隐（本次唯一的行为改动）

计划 Task 4 要求："单列文本（只有一列，列末逗号不应消隐，因为没有下一列承接断句）"。
上一轮实现覆盖**所有**视觉列（含末列），对 `["仙人风范，"]` 这种单列文本会隐藏逗号。

本次按计划加了**单列保护**：`len(columns) < 2` 时直接返回全 False 掩码。

理由（不是为了让测试好写）：消冗的依据是"**列边界**已经把这次停顿视觉化了"；
整条文本只有一列时，文本内部根本不存在列边界，那个逗号只是文本自己的末字符，
隐藏它等于凭空吃掉一个标点。

**实测影响为零**：全作品 82 处列末逗号**没有一处在单列文本里**（上一轮扫描同样是
"末列 0 处"），所以这条改动不改变任何一页的输出。

**多列的末列仍然掩码**（`["仙人风范", "端庄贤淑，"]` → 掩码），这是上一轮已固化的决策，
本次用 `test_multi_column_last_column_still_masked` 锁住，不允许被本次改动误伤。
两处取舍并存是刻意的：先有"列边界"这个前提，才谈得上"边界已表达停顿"。

### 9.2 `；：` 仍然保留（与计划的逗号族不同）

计划的边缘案例条目自己写了"当前实现保留，确认这是正确的"，本次确认并固化：
`_COLUMN_END_REDUNDANT = frozenset("，、,")`，`；：` 与 `。！？…` 一起归入"列末必须保留"。
严格边界只要求保留 `。！？`，保留 `；：` 是**更保守**的一侧，不越界。

### 9.3 断列策略根因仍未修

`typeset_engine.break_lines` 的 `strong_break` DP 奖励（`typeset_engine.py` 里
`if j > 0 and text[j-1] in strong_break: cost -= 50`）**没有动**。它才是"逗号被推到列末"
的根因，但改它会影响全部页面的分列结果，风险远大于收益（与上一轮判断一致）。
本次及上一轮都只在渲染层消除视觉冗余，代价是 `lines` 元数据里仍留着列末逗号。

### 9.4 作品有 66 页而不是 65 页

`artifacts/inpaint/page_63.json` 不存在（该页没有 inpaint 产物），所以 `--pages all`
按实际存在的页扫，得到 65 页。这是探针的 `all` 语义（从磁盘发现）而不是写死 1..65 ——
写死会在 page_63 崩掉（第一次全量跑就是这样挂的）。

---

## 10. 已知限制与不确定

### 10.1 main 侧既存缺陷：空译文让竖排渲染 `ValueError`（本次已修，建议同步到 main）

见 §7.4。触发条件是 `translation` 里某条是空串。本作品实测存在（`page_5 r13`）。
**合并到 main 之前建议在 main 上也补 `default=0`**，否则 main 单独跑 `page_5` 会崩。

### 10.2 PSD 导出路径不做列末逗号消冗（已知限制，未在本次范围内）

main 的重构让 `psd_jsx_export.py` 复用 `iter_vertical_rows`，但它只用行序列算
`max_rows`（列高），文字仍然作为**整列**交给 Photoshop 文本层。
要隐藏列末逗号只能改文本内容 —— 那正是本方案刻意避免的（会破坏 `lines` 落盘契约）。

结论：**PNG 成品图已消冗，PSD 分层文件里仍带着列末逗号**。计划只点名了
`typeset_render.py` 与 `vlm_render.py` 两条渲染路径，所以这是范围外，但确实是
交付物之间的不一致，评审需知晓。若要求一致，需要在 PSD 导出层单独设计
（例如导出前按掩码逐字下标记，而不是整列文本）。

### 10.3 无图像输入：PNG 没有被模型肉眼看过

本会话模型（deepseek-v4-flash）不支持图像输入。替代证据是：

- 字号级 ASCII 位图（§3.3、`verify_report_*.json` 的 `bitmaps` 字段）；
- 逐像素的**字形回放等式**（比肉眼更强的机械断言）；
- `make_comparison.py` 产出的 PNG 对比图**存在但未经模型目视**，请人工复核。

### 10.4 本 worktree 的 pre-commit 钩子在检查**主项目**，不是这里

`core.hooksPath` 在共享配置里写的是**绝对路径**
`E:/manga translator agent/.githooks`，而 hook 脚本用 `cd "$(dirname "$0")/.."` 定位仓库根：

```
[pre-commit] ... == [fastcheck] ROOT check OK (ROOT=E:\manga translator agent) ==
```

也就是说，本分支早先几次 commit 里打印的 `QUICK PASS` 检查的是主项目目录（那里没有
agent-loop 脚手架，天然干净），**不是本 worktree 的代码**。本次最终验证是直接在
worktree 里手工跑 `npm run check` / `pytest tests/` 得到的，与钩子无关。

这正是 CLAUDE.md 反复强调的"看起来已生效、实际从未触发"那类机制的又一实例。
建议把 `core.hooksPath` 改成相对路径（`.githooks`），或在 hook 里用
`git rev-parse --show-toplevel` 定位仓库根。**本次未改**（它属于共享配置，会影响主项目）。

### 10.5 脚手架消歧（超出本任务范围，但计划要求这道门变绿）

Task 6 要求 `npm run check` 通过。实测它在本分支上是红的，且**与本任务无关**：
4 条 ruff 报错全在 agent-loop 脚手架 `scripts/run_sdk_task.py`（本分支 `02123ef` 引入），
另有 2 个脚本输出中文却没到 UTF-8 收口点，被 `tests/test_encoding.py` 拦。

全部是机械修复，单独成一个 commit：

- `scripts/run_sdk_task.py`：`ruff --fix`（删未用 `os`、去掉 3 个无占位符 f 前缀）+ 补 `force_utf8_stdio()`
- `scripts/_run_high_effort_verify.py`：补 `force_utf8_stdio()`，并**纳入版本管理**
  （它一直在 `scripts/` 下且被 `docs/module-map.md` 收录，不跟踪就会让地图指向一个
  "存在但不在库里"的模块）
- `docs/module-map.md`：重新生成。合并 main 时它被自动合并成 main 的旧版本
  （`_split_vertical_punct_runs`），而合并后的 `psd_jsx_export.py` 里是 `_has_conjoined_punct`
  —— **main 自己那份地图本来就已经过期**（main 干净检出也过不了这条测试）
- 计划文件入库（与既有计划文件同一惯例）

副作用（正面）：全量 pytest 由"1 failed"变成 **0 failed**。

### 10.6 其它不确定

1. **数字与上一轮不可比**：上一轮报告的"52 处 / 6 页 31 处"读的是主项目 main 的
   2026-09-16 产物；本次是 65 页现场重渲染的 **82 处**。两组数字都对，但描述的是
   不同代码状态 + 不同产物，不要混用。
2. **`page_4` 的命中区域与上一轮不同**（上一轮 5 个区域，本轮 6 处含 `r00` 两处）。
   原因同样是代码状态不同（本轮含 main 的 `iter_vertical_rows` 重构）。
3. **探针的几何复算依赖渲染器公式**。已内置反向自校验（横排非空字符格 696/696 有墨；
   竖排靠字形回放等式），但如果渲染器换了几何公式而探针没跟着改，探针会先报错而不是
   静默放过（`char_idx 越界` / 回放差异）。
4. **`_ink_dev` 是信息量指标，不是判据**：它按"与格内中位亮度差 > 60"数像素，
   会把原作线、邻字溢出也算进去。通过/不通过一律以字形回放等式为准。

---

## 11. Task 6：全量回归

```
$ uv run python -m pytest tests/ -q
634 passed, 7 skipped, 3 warnings in 105.33s

$ uv run python -m pytest tests/typeset/ -q
11 passed

$ npm run check
== [fastcheck] ROOT check OK (ROOT=E:\amta-agent-loop) ==
== [fastcheck] QUICK PASS ==
```

- 全量 0 failed（本次之前本分支是 `1 failed, 621 passed`；失败项是 agent-loop 脚手架的
  UTF-8 收口点，已在 §10.5 修掉）。
- `npm run check` = `uv run python scripts/fastcheck.py --quick`（compile + ruff + pyright）。

### 修改文件清单（本会话，`02123ef..HEAD`）

**功能（3 个提交）**

```
src/amta/typeset/vertical_punct.py                          |   6 +
tests/test_column_end_pause_edge_cases.py                   | 169 +++++  (新)
tests/typeset/test_vlm_render.py                            | 129 +++++
tests/test_column_end_pause_render.py                       |  33 ++ (其中 2 条在合并提交内)
scripts/probes/verify_column_end_comma_high_effort.py       | 610 +++++  (新)
scripts/probes/render_page_before_after.py                  |  32 +-
```

**合并 main（1 个提交）**

```
src/amta/typeset/typeset_render.py      （唯一冲突，手工解）
docs/module-map.md, scripts/run_gui.py, src/amta/gui/*,
src/amta/typeset/psd_jsx_export.py, tests/test_psd_jsx_export.py,
tests/test_render_artifact_contract.py  （main 侧自动合并）
```

**脚手架消歧（1 个提交，见 §10.5）**

```
scripts/run_sdk_task.py                                     |  15 +-
scripts/_run_high_effort_verify.py                          |  60 ++ (新，纳入版本管理)
docs/module-map.md                                          （重新生成）
docs/superpowers/plans/2026-09-29-column-end-comma-high-effort-verify.md  (新)
```

**没有意外改动**：`git status` 干净；除上述文件外无其它变更；主项目目录与其他 worktree 未动。

---

## 12. 结论与合并建议

### 12.1 结论

- 列末逗号消冗在**两条渲染路径**（MITS `typeset_render` + VLM `vlm_render`）上都正确工作：
  全作品 65 页 82 处命中，**82/82** 被消除。
- 消隐是"只跳过绘制"：**零位移**（改动溢出掩码字格 0 像素）、**落盘元数据逐字节不变**（65/65）。
- **白字深底**（3 处，背景中位亮度 0–22）与**深色噪声底**上无残留墨迹 —— 由字形回放等式证明。
- **横排完全不受影响**：24/24 区域逐像素一致，16/16 横排逗号照画，两条 spy 测试断言零调用。
- 与 main 的合并冲突（`_render_vertical`：按行重构 vs 按字符掩码）已解，
  **合并前后全量验证逐项相同**。
- 全量 `pytest tests/` **0 failed**，`npm run check` **PASS**。

### 12.2 建议

**可以合并到 `main`**，附两条前置建议：

1. 把 §7.4 的 `default=0`（空译文保护）同步到 main —— main 现在跑 `page_5` 会
   `ValueError`，这是合并引入的**唯一**行为差异，且是修 bug 而不是引入风险。
2. 明确 §10.2 的 PSD 不一致是否可接受（PNG 消冗、PSD 不消冗）；若不可接受，
   另开一个任务在 PSD 导出层做，不要塞进本次改动。

评审时可重点复核（本会话模型看不到图，这几处只有机械证据）：

- `workspace/column-end-comma-fix/page_4_comparison.png` 及 `_zoom_*.png`（**人工目视**）；
- §9.1 的"单列不消隐 / 多列末列仍消隐"取舍是否认可；
- §10.2 的 PSD 范围外结论是否认可。

---

## 13. 复现命令

```powershell
# 全作品 65 页 before/after 验证（字形回放判据，约 8 分钟）
uv run python scripts/probes/verify_column_end_comma_high_effort.py --pages all --bitmaps

# 6 页 before/after 图 + 对比图（生产入口现场重渲染）
uv run python scripts/probes/render_page_before_after.py --pages 4 8 12 13 16 41
uv run python scripts/probes/make_comparison.py          --pages 4 8 12 13 16 41

# 根因复现 / 全作品扫描（上一轮工具）
uv run python scripts/probes/probe_column_end_comma.py
uv run python scripts/probes/scan_column_end_comma.py

# 回归
uv run python -m pytest tests/ -q
npm run check
```

`render_*` / `make_comparison` / `verify_*` 只**读**主项目
`workspace/touhou-getten-shinchi/`（`--src-root` 可覆盖），所有输出写在本 worktree 内，
未修改主项目目录或其他 worktree。

## 14. 证据文件（`workspace/`，被 `.gitignore` 整目录忽略，不入库）

| 文件 | 说明 |
|---|---|
| `column-end-comma-high-effort-verify/verify_report_pre_merge.json` | 合并前 65 页全量验证明细（含字形像素、回放差异、位图）|
| `column-end-comma-high-effort-verify/verify_report_post_merge.json` | 合并后同上；两者汇总指标逐项相同 |
| `column-end-comma-high-effort-verify/{before,after}/page_*_final.png` | 65 页 × 2 现场重渲染图 |
| `pre_merge_verify.log` / `post_merge_verify.log` | 两次全量验证的控制台输出 |
| `column-end-comma-fix/page_4_comparison.png` 等 37 张 | **合并后**重生成的 before/after 对比图 |
| `column-end-comma-fix/render_report.json` | 6 页逐格墨迹/改动/位移数据 |
| `full_pytest.log` | 全量回归输出（634 passed）|

---

> 本报告与上一轮 `docs/reports/2026-09-29-column-end-comma-fix.md` 是**互补**关系：
> 上一轮记录"问题是什么、方案怎么选、6 页 31 处基础验证"；本报告记录
> "边缘案例（白字深底 / VLM / 横排 / 退化输入）的严格验证 + 与 main 的合并"。
> 两份报告里的数字属于不同代码状态，不要混用（见 §10.6.1）。
