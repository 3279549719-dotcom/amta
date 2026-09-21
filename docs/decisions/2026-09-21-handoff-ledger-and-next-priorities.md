# AMTA 质量闭环 Handoff — 2026-09-21

## 本次交付

合并到 main：`f3a3cdf`。新增页头四数 ledger：`detect N · ocr M · trans K · render L`，下一个数比上一个小就标红。

- `src/amta/report/ledger.py` — 纯函数 `compute_ledger(page)`，数文本流四站过手数
- `src/amta/report/engine.py` — `render_page_section` 页头渲染 ledger
- `tests/test_report_ledger.py` — 3 个测试
- 设计文档：`docs/decisions/2026-09-21-report-ledger.md`

**设计原则（本轮 PM 讨论定的，后续不要再走回头路）：**
- ledger 只报"文本流过手数"，不做视觉判断、不归因、不自动 retry
- 视觉问题（字小、糊、竖排英文、OCR 乱、翻译错）一律肉眼看 HTML/PSD，机器不替人看
- 不做 finding/severity/next_action 结构；不做两次 OCR；不上 VLM
- 最终交付形态：成品 PNG + PSD（未做）+ 一页 ledger 汇总
- inpaint 不进 ledger（擦筐的，不产生文本实体）

## 仓库现场

- main 在 `f3a3cdf`，已合并 ledger
- `fix/text-ink-mask` 分支仍未合并，用户认为效果一般，不要默认合
- `.playwright-cli/` 未跟踪，不要删
- 黄金页 artifact 在 `workspace/touhou-getten-shinchi/artifacts/`，原始扫描件不在本机
- 验证用：`uv run python -m pytest -q`（onnxruntime 缺失时跳过 tests/test_detect_*.py）

## 8 个已知问题 — 按 priority 重排

按"改模块就能自动修、不需要人判断"优先排。P0=纯机制问题，改了就好；P1=机制+一次用户拍板；P2=部分机制+部分肉眼。

### P0 — 纯机制，改模块代码即可，不需要人介入

**1. p64 空译文（translate 模块）**
- 现状：`うっ...!` OCR 成功但 translate 系统提示允许返回空串，原文被擦但没新字
- 修法：translate 后处理加不变量——非空 OCR 文本不许产出空译文；空了就重译一次，仍空则 ledger 标红
- 不需要人：这是确定性约束

**2. p52 fits=False 硬塞（typeset 模块）**
- 现状：所有候选字号都 `_fits=False`，typeset 仍返回最小字号+断行结果，上层只看"小于目标 40%"判断溢出，错误被静默吞掉
- 修法：typeset 返回 `{字号, fits: bool}`，`fits=False` 时要么重排行、要么压缩、要么标记 REVIEW；不许静默出图
- 不需要人：接口契约问题

**3. p59 cosplay 竖排英文（typeset 模块）**
- 现状：竖排框里逐字母绘制 ASCII，形成 c-o-s-p-l-a-y 纵列
- 修法：typeset 遇竖排框内连续拉丁字母（≥3），要么横向 inline run，要么优先译"角色扮演"
- 不需要人：排版规则

**4. p43 透明气泡漏检（detect 模块）**
- 现状：整页低阈值 0.15 仍漏；3×4 瓦片试验 0.72 找回
- 修法：启用瓦片检测→坐标还原→重叠去重→包含框消解。已有试验数据
- 不需要人：但工程量比前三个大

### P1 — 机制修，但需要用户拍板一次

**5. p44 `コマ→小町` 幻觉（translate 模块）**
- 现状：DeepSeek 受东方领域提示影响，把漫画格 `コマ` 译成角色名"小町"
- 修法 A（机制）：后处理检查——译文出现 THB 词典专名，但原文无对应实体，则标记重译
- 修法 B（词典）：`コマ→格/漫画格` 加进 master dict
- 需用户拍板：`コマ` 在这页有没有"平/小"双关？是直译"格"还是保留双关？选一次，以后不用再问

### P2 — 机制优化 + 肉眼兜底

**6. p62 inpaint 崩坏（inpaint 模块）**
- 现状：复杂背景整块矩形 mask 给 LaMa，破坏黑色纹理气泡
- 修法：细化文字 mask（text-ink mask 分支已有尝试，用户认为效果一般需重做）；或复杂背景保护策略
- 肉眼兜底：修得好不好看靠 PSD

**7. p41 OCR 乱码但置信度高（ocr 模块）**
- 现状：乱码式重复日文，平均 conf 0.79，低置信度门控抓不到
- 修法：字符串垃圾模式检测（同字符连续重复≥3、小框超长文本、字符类别异常）——便宜的正则/统计
- 肉眼兜底：真乱码靠 ledger 标红后看报告

**8. p42 字偏小（typeset 模块）**
- 现状：16 框全保留，部分字号 15-20px
- 修法：加最小字号下限，但具体值要调
- 肉眼兜底：多大算"小"是口味问题

## 下一个模块建议

**先做 typeset + translate 的契约收紧，一个模块修掉 p64/p52/p59 三个 P0：**

1. typeset 返回 `fits` 状态，`fits=False` 不静默出图（p52）
2. typeset 竖排框遇连续 ASCII 横向 inline（p59）
3. translate 后处理：非空 OCR 不许空译文，空了重译（p64）

这三个都是接口契约/排版规则，不需要用户拍板，TDD 友好。改完 ledger 跑黄金页，这三个红应该消失。

**然后：**
- p44 专名幻觉检查（跟 translate 后处理同一处，顺带做，但要先问用户 `コマ` 译法）
- p43 瓦片检测（detect 模块，独立工程，单独 worktree）
- p62 mask 细化（inpaint 模块，参考 fix/text-ink-mask 但要重做）
- p41 垃圾模式 / p42 字号下限（最后做，边际收益小）

## 不做的事

- PSD 导出（下轮）
- 自动 retry 循环（先让 ledger 标红，人工看了再决定）
- VLM 二次确认
- 两次 OCR
- finding/severity 结构
