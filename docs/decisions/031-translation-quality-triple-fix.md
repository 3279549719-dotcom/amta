# 031 — 翻译质量三修复：术语表接入 + 数组契约防错位 + 字体大小第一性原理

日期：2026-09-05　状态：已采纳（前两项已实施，第三项待实施）

## 决策

### 决策 A：pre_scan 术语表自动接入 orchestrator 管线

orchestrator 的 translate adapter 在翻译前自动检查 `work_state.terms`，为空时调用 `run_pre_scan(work_id, artifacts_dir)` 扫描已有 canon 锁定术语。pre_scan 是纯机械匹配（无 LLM 调用），失败降级不阻塞翻译。逐页流水线下增量生效。

- 接入点：`amta/src/amta/orchestrator/adapters/translate.py` → `_ensure_terms()`
- 术语链路：`data/thbwiki_master_dict.json`（本地静态主词典）→ `term_dict.py` 拍平 → `pre_scan.py` 扫描全本 canon 匹配 → 写入 `work_state.terms` → `term_replace.py` 翻译前最长匹配优先替换 → LLM 收到的已是替换后文本
- 与之前手动 CLI 流程（`scripts/pre_scan.py`）机制完全一致，区别仅在自动触发

### 决策 B：翻译输出从 JSON 对象改为按位置绑定的数组契约

`translate_plain` 的 LLM 输出契约从 `{"r00": "译文", "r01": "译文", ...}` 改为 `["译文1", "译文2", ...]`，代码侧按位置绑定 region_id，严格校验 `len(output) == len(input)`，长度不符直接返回 None → 重试 → 二分拆分。

- 根因：旧契约下 LLM 可把一条输入拆成两条输出挤占后续 region_id（p14 实际故障：r01「ちょっと待て! 仮行さぼりたいだけでしょ」被拆成 r01「等一下！」+ r02「只是想偷懒不修行吧。」，后续全部偏移），而 `mechanical_guardrails` 只校验数量不校验内容对应性
- 新契约从结构上消除错位可能：LLM 无法再"拆一条塞两个 key"，因为数组长度会对不上
- 对外接口不变：`translate_plain` 仍返回 `dict[str, str]`，仅内部解析逻辑变更
- 旧函数 `parse_translation_response` 保留供外部调用/测试

### 决策 C：字体大小采用第一性原理方案——删除方向判断，双方向计算选最优

删除 `decide_direction` 函数（含 `h/w >= 2.2 and char_count <= 6` 两个人为阈值），将方向判断合并进 `fit_font_size`：同时计算横排和竖排两种方案的最大可行字号，返回字号更大的方向。

- 第一性原理：字体大小的本质是"在给定矩形内放入给定文字，使字号尽可能大且不溢出"。横竖排只是达到目标的两种排列方式，不应作为前提条件
- 旧方案的问题：`char_count <= 6` 阈值毫无物理依据，日漫大量 20-50 字竖排对白被强制横排，窄框横排每行仅 2-4 字，字号被压到 19px（p11 r00 实际故障）
- 新方案零人为阈值：窄框自动选竖排（字号大），宽框自动选横排（字号大），完全由数据驱动
- 约束方程两种方向完全一致（仅宽高互换）：
  - 竖排：每列字数 = 框高/(字号×行高系数)，列数 = ceil(总字数/每列字数)，约束：列数×字号×字宽系数 ≤ 框宽
  - 横排：每行字数 = 框宽/(字号×字宽系数)，行数 = ceil(总字数/每行字数)，约束：行数×字号×行高系数 ≤ 框高

## 理由

- **决策 A**：orchestrator 引入后丢失了 pre_scan 步骤（registry 只有 detect/ocr/translate/inpaint/typeset 五阶段），`touhou-e2e-orchestrator/state/` 下无 `work_state.json`，术语表为空，サグメ等专有名词被 LLM 乱翻。术语替换机制本身（commit 82a46b6）完好，只是没被触发
- **决策 B**：补 prompt 不治本（LLM 偶发重新组织输出），硬编码字符比例是启发式猜测语义对应性。数组契约是结构层面的强制绑定，从"相信 LLM 正确填 key"变为"用顺序和长度锁死对应关系"
- **决策 C**：`decide_direction` 的两个阈值（2.2、6）都是拍脑袋参数，为少数边缘情况牺牲了大多数长文本的正确性。第一性原理方案消除所有阈值，且代码更简洁（一个函数循环两种方向 vs 两个函数带分支逻辑）

## 后果 / 约束

- 决策 A：逐页流水线下第一页只有第一页 canon，术语表随页数增长；pre_scan 失败（主词典缺失等）降级为无术语替换，不阻塞翻译
- 决策 B：LLM 必须能稳定输出 JSON 数组（当前 DeepSeek 直调已验证）；数组长度不符时走二分拆分，极端情况下可能增加 LLM 调用次数（但比错位结果可接受）
- 决策 C：`fit_font_size` 返回值从 `int` 变为 `(int, str)` 元组（字号+方向），调用方 `typeset_engine.py` 和 `typeset_render.py` 需同步更新；`decide_direction` 删除后需检查有无其他调用方
- 相关：ADR-014（翻译工位架构）、ADR-018（管线编排）、ADR-021（typeset 工位）
