# ADR-036: 短促发声翻译采用通用可识别性边界

- 日期：2026-09-26
- 状态：采纳；最终候选基线 `96fe7350dbb8756bdab493971e64b79a09808b6d`
- 范围：`src/amta/translation/translate.py` 的系统提示词；不改变翻译及下游接口
- 开发页：`月天新地` p64；候选 1 的预注册隐藏页：p52、p43；候选 2 对后两页只做回归验证

## 根因与决策

旧提示把“拟声词、或没有实际语义的内容”整体归入无需翻译，模型因此可将可识别的人声短句留空。数组解析器允许空字符串，翻译产物按位置保存，下游仅擦除和排版非空译文；这些契约本身没有失效。空译文仍必须合法：纯标点没有可译语言内容，确实无法识别的 OCR 乱码不应强造译文。不能把“源串非空”当成机械的必译判据。

候选 1（`e0693fd`）先删除笼统的拟声排除，再枚举呻吟、喊叫、笑声、叹息、哼声等应翻译类别。p64 开发页 r08 得到非空译文并排版（运行 `fc3088129356`）；随后按当时的预注册流程，p52 r01 与 p43 r04 作为隐藏页也通过（运行 `50dd90acf644`）。这些绿色样本证明候选 1 在这三处有效，却不能证明枚举能覆盖未见的表达。用户指出这是提示词层面的软硬编码；按 Bitter Lesson 的批评继续添类别，会把模型本可做的语境判断固化成不断增长的清单。因此否决该抽象，保留已证实需要的边界。

候选 2（`96fe735`）在保留原有乱码防线和“完全是标点符号则对应位置输出空字符串”的规则后，只增加这一句：

> 其他可识别内容应结合上下文自然翻译，不因篇幅短、非词汇性或主要传达语气而省略。

它不包含页码、区域号、日文词条或发声类别清单。翻译仍是一页一批、按位置绑定的同长度 JSON 数组，代码侧零重试；合法空值仍被保存，下游只处理非空译文。源文和中文标点由模型在语境中处理，没有新增机械标点改写。

## 测试与实页证据

TDD 顺序见 `e27a6c1`、`235dc18`（先写/加严提示词断言）、`e0693fd`（候选 1 实现）及 `96fe735`（候选 2 测试与实现）。候选 1 的聚焦 RED 命令 `uv run python -m pytest tests/test_stage3_minimal.py::test_prompt_translates_narrative_vocalizations_but_allows_noise_to_stay_empty tests/test_inpaint_station.py::test_empty_translation_is_not_inpainted -q` 得到 **1 failed、1 passed（5.10 秒）**：旧提示缺少正面翻译边界，既有 inpaint 空值保护通过；实现后聚焦回归集 **23 passed**。候选 2 实现会话报告：在 `e0693fd` 上同一新通用边界测试 RED（**1 failed**，缺少通用句子；mock 的空值位置绑定通过），编辑后单测 **1 passed**、回归集 **23 passed**，复核者独立重跑通过。候选 2 的 RED 原始终端记录未保存；该失败属性也能由 `e0693fd` 的类别清单与最终测试断言直接核对，不能把会话报告冒充为留存日志。最终 mock 测试检查空字符串的数组位置绑定、纯标点/乱码例外；mock 回复只验证契约，不证明真实模型会给出好译文。实页运行承担后一项验证。

| 候选 2 运行 | 目标结果 | 管线与视觉结果 |
| --- | --- | --- |
| p64，`16b97bb40a24`，PASS | r08 `うっ...!` → `呜…！` | 检测/OCR/译文各 9 区，9/9 排版；原日文已清除，气泡内中文可读；0 overflow、0 report warnings。|
| p52、p43，`adeb9f3a8bcb`，回归 PASS | p52 r01 `ああああ` → `啊啊啊啊`；p43 r04 `ハン` → `哼` | p52 6/6、p43 5/5 译文排版；目标原日文已清除，中文可读；0 overflow、0 report warnings。|

候选 2 开始前 p52、p43 已被候选 1 使用，并非独立隐藏证据，也不能据此声称对未见页面有泛化证明。p64 的其余八区无实质视觉退步，但 r02“那个我也感冒了哦！”开头较候选 1 不够顺，核心意思保留。p43 r03“真拿你没办法呢辉夜”少了停顿及部分嗔怪语气；p43 原有的漏检/未翻译问题与本次短促发声边界无关，仍存在。本轮未评估其他版面问题。

p64 总耗时 75.03 秒：detect 3.61、OCR 34.91、translate 1.01、inpaint 31.59、typeset 3.17 秒。p52/p43 回归总耗时 149.97 秒：detect 8.90、OCR 43.75、translate 2.04、inpaint 92.65、typeset 2.14 秒。阶段和总时长分别来自运行记录，存在调度等差额，不应把分项之和当作精确总时长。

调用数仅是应用层推断：p64 一次成功 translate step，p52/p43 各一次；所审代码对每页非空 canon 调用一次 `translate_plain`，再调用一次 LLM，应用层无补救重试。没有 HTTP 请求计数器，传输层尝试次数未经独立测量。

可复核的忽略产物在 `output/short-vocalization-loop/`：候选 2 的 `round2-p64-evidence.json`、`round2-p64-report.html`、`round2-p64-final.png` 及 `round2-regression-evidence.json`、`round2-regression-report.html`、`round2-p52-final.png`、`round2-p43-final.png`；候选 1 对照为 `p64-evidence.json`、`hidden-validation-run.log`、`candidate1-hidden-*`。这些含图片的本地运行产物不进入 Git。

## 非目标与 Loop Engineering

本轮不修 p43 检测、不触碰 p62 背景保护，不加词典、额外重试、逐页规则或新后处理。循环中的关键修正是更换提示抽象：删除宽泛的负面先验后，用最小通用边界交还模型语境判断。已有测试、管线入口和报告足以暴露与复核这次问题；没有可复现的新摩擦支持再造工具、守卫或技能。

## 收尾验证

2026-09-26 在最终候选和本文档上运行 `uv run python scripts/fastcheck.py`（完整门，非 `--quick`），退出码 0：pytest **482 passed、7 skipped、3 warnings**，耗时 100.00 秒。三条 pytest 警告均为弃用提醒：Starlette testclient 中的 AnyIO `BlockingPortal` 别名 1 条，以及 Pillow `Image.getdata` 测试调用 2 条。Ruff lint、Pyright（0 errors、0 warnings、0 informations）、ROOT、环境、depguard、memory lint、memory gc dry-run、memory inject、module-map 均为 OK，最终为 `ALL PASS`。另有 Pyright 新版本提示和 memory lint 对缺失 `.remember/recent.md` 的 staleness 警告；它们未使门失败。
