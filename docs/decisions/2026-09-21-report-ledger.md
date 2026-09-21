# Plan: 报告页头四数对账（ledger）

## 目标

在 gen_report 每页页头加一行数字对账：`detect N · ocr M · translate K · rendered L`。
数字掉了（下一个比上一个少）高亮红。不引入新 stage、新模型、新 finding 结构。

## 产品判断（为什么是这四个数）

文本流是一筐橘子在传：detect 摘了 N 个，ocr 捡出 M 个能吃的，translate 把 K 个榨成汁，rendered 把 L 杯倒进杯子。
每过一手数量可能变少，所以"手上有几个"对得有意义——数量跳了，就是这一手丢的。

inpaint 不进 ledger：它不碰橘子，只擦筐，不产生文本实体；擦得好不好看是美学，肉眼看 PSD。
视觉问题（字小、糊、竖排英文、漏检、OCR 乱码、翻译错）一律不进 ledger，肉眼看 HTML/PSD。

## 做什么

1. **新建 `src/amta/report/ledger.py`** — 纯函数
   - `compute_ledger(page: PageReport) -> dict`
   - `detect = len(detect.cells)`
   - `ocr = 非空 text 的 cells 数`
   - `translate = 非空 translation 的 cells 数`
   - `rendered = len(typeset.cells)`
   - 缺阶段 = 该值为 None（不算异常，跟 quality_audit 的"未跑 ≠ 异常"一致）

2. **修改 `src/amta/report/engine.py`**
   - `render_page_section` 里调用 `compute_ledger`
   - 在 page-header 渲染一行 ledger HTML
   - 下一个数 < 上一个数时，那个数标红

3. **新建 `tests/test_report_ledger.py`** — TDD 先行

## 不做什么（明确后置/删除）

- inpaint 不进 ledger
- 不做 PSD 导出（后置，现有 HTML 报告已够肉眼看）
- 不做自动 retry
- 不做 finding/severity/next_action 结构
- 不做两次 OCR / 字符串垃圾模式 checker
- 不做竖排 ASCII / 字号比 / 死灰方差 / mask 面积比等视觉 checker
- 不重构 quality_audit.py（它继续给 AI 看红榜，互不干扰）
- 不动 pipeline 主体、不动任何 stage 产物格式

## TDD 步骤

1. RED: 写 `test_compute_ledger_counts` — 构造假 PageReport（detect 5, ocr 4[一个空 text], translate 3[一个空译文], rendered 3），断言四数
2. 跑测试，看它因 ImportError 失败
3. GREEN: 写 `ledger.py` 的 `compute_ledger`
4. 跑测试，看通过
5. REFACTOR: 接入 `engine.py` 的 `render_page_section`
6. RED: 写 `test_ledger_html_rendered` — 断言 HTML 里出现 ledger 行且掉数标红
7. GREEN: 改 `engine.py` 渲染
8. 验证: `uv run python -m pytest -q`
9. 验证: 对黄金页 p41,42,43,44,52,59,62,64 跑 gen_report，肉眼确认数字
