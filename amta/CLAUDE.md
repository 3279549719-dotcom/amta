# CLAUDE.md

AMTA — Automation Manga Translate Agent：会话驱动的漫画翻译自动化。DSH 会话（单 LLM Agent）= 导演（决策/翻译判断/修复决策/验收），amta Python 执行器 = 确定性工具层，koharu v0.59.1 headless（REST :4000）= 引擎。第一里程碑：Benchmark A/B/C。

## 核心事实

- **钉 koharu v0.59.1**（server 世代，REST /api/v1 + MCP /mcp + 像素 mask 机制）；上游 0.77.5 起已删 headless/HTTP/MCP，升级即失去全部自动化面。
- **翻译通道**：`03_translate` 工位脚本直调 DeepSeek API（`.env` CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY，`CHAT_MODEL=deepseek-v4-pro`，`https://api.deepseek.com`），双层护栏（机械：结构/残留/region_id 对应 + 语义：`scripts/translate_semantic_check.py` VLM 粗筛评审→FAILED 交导演）+ 分层 Loop（脚本机械重译 1 次 → FAILED 附证据交导演语义修订）；**弃 koharu 内 `llm` 引擎**（not-ready，ADR-014 修订决策 #5）。
- **Vision QA**：`vqa()` 抽象，会话内 describe_image 实现。
- **本地漫画 OCR**：`PaddleOCR-VL-For-Manga` GGUF（`models/paddle-manga/`）+ 独立 llama-server（`models/llama-cpp/llama-server.exe`，端口 8118，`--mmproj`）。koharu 内置 llama.cpp b8935 太旧，其 paddle/mit48px OCR 引擎全部不可用（MTMD 初始化失败），只 manga-ocr 可用；漫画 OCR 走独立 llama-server（OpenAI 兼容接口，prompt `OCR:`）。
- **文档查询**：`scripts/context7.py`（`npm run ctx7:search` / `ctx7:ctx`），读 `.env` 的 `CONTEXT7_API_KEY`，查最新库文档。
- **算力**：CPU-only（i5-1135G7 4C8T / 16GB），并发 workers 必须 =1；inpainter 现实选择只有 lama-manga；本地 VLM 不可行。
- **工具面**：`src/amta/koharu_client.py`（16 方法，清单见 koharu-drive skill）+ `src/amta/pipeline.py`（引擎 DAG 常量）+ `src/amta/runner.py`（单页流水线执行器）+ `src/amta/ocr_engines.py`（本地/DashScope OCR 引擎）+ `src/amta/translate.py`（翻译工位纯库：chat client + 三借鉴机制 + Context 组装 + 机械护栏 + suggestions，ADR-014）+ `src/amta/evalkit.py`（CER/EM 聚合）+ `src/amta/workstate.py`（per-work workspace + work_state，ADR-013）+ `src/amta/metrics.py`/`geometry.py`/`images.py`（共享库）。
- **技能根三路径**：`.dsh/skills`=项目维护根（git 钉版/唯一事实源，包技能一律钉此）；`~/.agents/skills`=只读下载根（`npx skills add` 落点，update 后需重复制同步钉版）；`~/.dsh/skills`=个人跨项目。包技能勿只放 `~/.agents/skills`（ADR-009）。

## 关键坑速查（完整经验见 docs/lessons.md）

> 坑/经验的**唯一归属 = `docs/lessons.md`**（Problem/Root cause/Durable lesson/Prevention/Regression），本文件只留一行指针，不重复。

NO_PROXY · .ps1 带 BOM · ctd_seg 只细化已有框 · patch 后重渲染 · workers>1 崩 · VLM 整页坐标不可靠 · 假数据落盘 · llama.cpp 版本必须 ≥b10582（旧版 MTMD 投影初始化失败） · 通用 VLM 竖排日语系统性差（需漫画微调模型） · 并集框去重漏竖排碎片框（IoU>0.5 不够） · 评测派生指标口径漂移（cer/em 随代码重算） · VLM per-crop GT 不可靠（正式 GT 用整页枚举） · 报告叠加框来源误标 · OCR 评测坐标须用 detector 对齐框（GT bbox 缩略不可靠、勿用单引擎框，页码注意 0/1 基偏移） · llama-server 多模态 cache 误命中不同图（必须 cache_prompt:false，见 L17） · 本地 OCR 默认 Q8_0（BF16 慢 ~30%，参数见 start_llama_ocr.ps1，见 L18） · baberu-OCR 快 28 倍（1s/张，对白 CER 相当，可作 fast path） · pytest Windows 尾部 PermissionError=teardown 噪音（fastcheck 已用 --basetemp 根治；手工跑看 N passed 别信 exit 1，见 L19） · 数字前缀脚本 import 需 `_NN_name.py` 桥（见 L20） · 日文残留判据只用假名（汉字 CJK 共用，见 L21） · `tests/` 一律 pytest 风格，fastcheck 用 pytest 收集（unittest discover 只收 TestCase 会漏，见 L19/L20）

## 渐进式加载

| 触发 | 读 |
|---|---|
| 不确定用哪个技能/流程（技能路由器） | `.dsh/skills/ask-matt/SKILL.md` |
| 跑 Benchmark A/B/C | `.dsh/skills/benchmark/SKILL.md` |
| VLM 标注 crop（oracle 判真假/分类/评分） | `.dsh/skills/oracle-label/SKILL.md` |
| 后台长任务自主监控（轮询/失败检测/汇报） | `.dsh/skills/background-monitoring/SKILL.md` |
| 引入第三方依赖前（依赖膨胀拦截） | `.dsh/skills/dependency-guard/SKILL.md` |
| 驱动 koharu（接口/mask/修复循环） | `.dsh/skills/koharu-drive/SKILL.md` |
| 回归/发布流程 | `.dsh/skills/verify/SKILL.md` |
| 任务收尾 / 学习落盘（/finish） | `.dsh/skills/cycle-close/SKILL.md` |
| Harness 熵审计（/audit） | `.dsh/skills/audit/SKILL.md` |
| 收尾知识归类委派（finisher subagent） | `.dsh/skills/finisher/SKILL.md` |
| 外部调研委派（researcher subagent） | `.dsh/skills/researcher/SKILL.md` |
| docs 导航（分工/目录） | `docs/README.md` |
| 可复用经验库（坑的唯一归属） | `docs/lessons.md` |
| 架构决策（为什么这样选） | `docs/decisions/README.md` |
| 架构决策背景 | `docs/01-调研报告与集成编排方案.md` |
| 可复用轮子资产 | `docs/02-本地轮子详报.md` |
| 上游能力/迁移权衡 | `docs/03-koharu上游详报.md` |
| 引擎 DAG / 目录结构 | `README.md` |

Skills 与 docs 均按需加载：先看名字/一句话，任务触发时才读全文。

## 工作协议（Finish / Audit / 知识晋升）

- **任务收尾必须走 /finish**（cycle-close skill）：复读任务 → 审查 diff → 确定性验证（`npm run fastcheck`/`finish`，动引擎则加 `smoke`）→ 修复 → 反思 → 知识晋升 → 只更新真正变化的工件 → 输出 Finish Report → git 落盘。
- **知识晋升管线**：`观察 → 可复用?No 丢弃 / Yes → 会复发?No lesson(docs/lessons.md) / Yes → 五路分流：全局规则(CLAUDE.md) · 流程(.dsh/skills/) · 架构(docs/decisions/ADR-N) · 瞬时(docs/progress.md) · 机械(test/lint/hook)`。反复犯错应逐步变成机器约束（test/lint/hook 是唯一真强制层，rules/lesson 都是 prompt 级），CLAUDE.md 保持精简（目标 <120 行）。
- **机械护栏三级**：编码期 `npm run fastcheck`（秒级）→ pre-commit（.githooks）→ pre-push（含可选 smoke）。安装：`npm run hooks:install`。
- **审计**：每 2-4 周或大里程碑后 `npm run audit` + audit skill，检测记忆膨胀/规则重复/验证缺口/仓库卫生。
