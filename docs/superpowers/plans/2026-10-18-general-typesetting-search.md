# 竖排通用排版搜索：kinsoku -aware 分列 + 实页视觉验证

> 本计划由 MainAgent 直接 inline 执行（不需要 subagent）。
> 前序：L54/L61/L62 修了度量口径和列数选优，但**分列算法本身**一直是朴素等分，
> 从未接 kinsoku DP。本计划补上这一环，并用 13 张实页做视觉闭环。

## Goal

修掉竖排分列时的行頭禁则违反（标点/空格开列），让 `_vertical_layout_at` 枚举列数时
用 kinsoku-aware 分列代替 `wrap_cells_to_columns` 朴素等分；然后用 book-bec83 的
13 张已译页**只重跑 typeset 阶段**，逐页人眼验收。

## 根因

`typeset_engine._vertical_layout_at` 对每个候选 `n_cols` 调 `_fill_columns` →
`wrap_cells_to_columns`，后者把 `cells` 列表**机械等分**成 n 段，完全不看首字符
是不是标点。对比横排路径 `wrap_text`：横排走 DP（`_break_units`），有行頭/行末禁则；
竖排搜索路径却绕过了同一套 DP。

实测 book-bec83（2026-10-17 跑批）：

| 页 | region | 当前 lines | 问题 |
|----|--------|-----------|------|
| 11 | r01 | `['︙︙不用','我说你也','明白吧','，笨蛋']` | 末列以 `，` 开头 |
| 11 | r02 | `['不适合你','——啦']` | 次列以 `—` 开头 |
| 12 | r02 | `['真的吗','？好开','心！']` | 次列以 `？` 开头 |
| 17 | r03 | `['我啊 一','直很憧憬',' 婚礼']` | 末列以空格开头 |

（page_25 r01 `['——真是','的︙︙']` 的 `——` 在首列句首，不算违规。）

## 修复方案

新增 `_split_cells_into_columns(cells, n_cols)`：把渲染行序列切成**正好 n_cols 列**，
遵守行頭/行末禁则。实现方式：复用 `_break_units` DP，但把 cost 从「段数最少」改成
「段数 = n_cols 为硬约束 + 段长均衡」。具体：
- 先算每列目标行数 `avg = ceil(len(cells)/n_cols)`；
- 用 DP 找 n_cols 个断点，每段 ≤ avg+1，跳过首字符 ∈ no_start 的断点、
  跳过尾字符 ∈ no_end 的断点、跳过纯标点段；
- DP 找不到合法 n_cols 分时（kinsoku 太严），返回 None → 搜索层自动放弃这个 n_cols。

`_vertical_layout_at` 改成：
```python
cols = _split_cells_into_columns(cells, n_cols)
if cols is None:
    continue  # kinsoku 不允许这么多列，试更大 n_cols
if sum(_column_width(c, char_w, font) for c in cols) > w:
    break
if _fits(cols, font, bbox, "vertical"):
    return len(cols), cols
```

`wrap_cells_to_columns` 保留（向后兼容 / 测试可能引用），但生产路径不再调它。

## Tasks

### Task 1: 建分支
```
git checkout -b fix/vertical-kinsoku-columns
```
工作区有 5 个未提交文件（discover_pages 重构，与本任务无关），保留不提交。

### Task 2: 实现 `_split_cells_into_columns` + 接线
- Modify: `src/amta/typeset/typeset_engine.py`
- 新增函数：输入 cells 列表 + n_cols，输出 list[str] | None
- 改 `_fill_columns` / `_vertical_layout_at` 调它
- 横排路径不动（已用 DP）

### Task 3: 单测
- Modify: `tests/test_typeset_cell_metrics.py`（或新建 `tests/test_typeset_kinsoku.py`）
- 用例：
  1. `真的吗？好开心！` 分 3 列 → 不得出现 `？` 开头列
  2. `……不用我说你也明白吧，笨蛋` 分 4 列 → `，` 不得开列
  3. `不适合你——啦` 分 2 列 → `—` 不得开列
  4. 首列可以以任何字符开头（句首）
  5. kinsoku 太严时返回 None（不强行分列）

### Task 4: 实页重排（typeset only，不翻译）
```
.venv\Scripts\python.exe workspace\retypeset_pages.py book-bec83a161b2f5f80 page_6 page_7 page_8 page_9 page_11 page_12 page_17 page_18 page_21 page_22 page_23 page_24 page_25
```
clean 图已 GC，脚本会自动从 final 重建（中位数底色填充，见 fix/dark-bubble 已合入 main）。

### Task 5: 视觉验收（这是补全的关键缺口）
逐页 Read `final/page_N_final.png`，对照：
- [ ] 列首不再出现 `，？！、—` 等标点
- [ ] 列首不再有空格
- [ ] 文字不溢出气泡
- [ ] 黑泡仍是黑底白字、白泡白底黑字
- [ ] 与改前对比：除分列位置外，其他像素不变
发现新问题 → 记下来，回头改代码再重跑该页。

### Task 6: 提交
只提交 typeset_engine.py + 测试，不碰 discover_pages 那 5 个文件。

## Self-Review
- [x] 根因定位到具体函数（_vertical_layout_at 绕过 DP）
- [x] 有实页证据（4 处违规列表）
- [x] 补了视觉验收闭环（Task 5）——之前计划缺的就是"改完不看成品"
- [x] 不重跑翻译（只 typeset 阶段）
