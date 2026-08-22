# AMTA 项目进度（外部持久化记忆 / 交接文档）

> 本文件是**项目状态的唯一事实来源**，任何 AI（Claude Code / Cursor / DSH / 未来 agent）接手第一件事先读它。
> 与 hindsight（DSH 会话内记忆）互补：hindsight 是会话内快速召回，本文件是工具无关的交接文档。
> 每次完成任务后更新本节「当前状态」与「下一步」。

## 一句话

会话驱动漫画翻译自动化：**DSH 会话=导演，amta Python=确定性执行器，koharu v0.59.1 headless(:4000)=引擎**。第一里程碑：Benchmark A/B/C 定量钉死能力边界。

## 当前状态（2026-07，最后一笔：Benchmark A 预筛完成）

- 工程脚手架已就位并推送（commit `854e170`、`119df6e`、`95ab73c`，origin/main 已同步）。
- CLAUDE.md v2 = 渐进式加载模型（核心事实+坑，~2k tokens）；AGENTS.md = 薄指针（避免双份漂移）。两者 DSH 均自动注入。
- 3 个 skill 已建：`benchmark` / `koharu-drive` / `verify`（.claude/skills/，按需加载）。
- `src/koharu_client.py`（16 方法）+ `src/pipeline.py`（引擎 DAG 常量）+ smoke_test **PASS**。
- koharu headless 当前在 :4000 运行（--headless --cpu）。
- **Benchmark A 已实现**（`src/benchmark.py` 两阶段：emit crops+manifest → ingest 标注算指标；synthetic 自测 + 链路实测通过）。
- **预筛完成**：16 页原文 × 4 detector 全跑通 → **160 crops + `output/label_manifest.json`**（无缺失，16 页全覆盖，每页 2-19 框）。
- git 凭据已修：host 级 `credential.github.com.helper="!gh auth git-credential"` 绕开 GCM 弹窗（否则每次 git 操作弹账户选择框）。

## 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 脚手架 / CLAUDE.md / skills / smoke | ✅ 完成并推送 |
| 1 | Benchmark A/B/C（检测 recall / OCR CER / inpaint 评分） | 🔄 A 进行中 |
| 1a | 预筛 16 页测试集（四 detector → 160 crops + manifest） | ✅ 完成 |
| 1b | VLM oracle 标注 160 crops 归 4 类 → ingest 算 precision | 🔄 标注进行中 |
| 2 | Repair Loop / Vision QA 嵌入 pipeline | ⏳ |
| 2b | Story Memory + prompt.py + vqa() + scene 翻译 | ⏳ |
| 3 | GitHub Actions 自动触发验证循环 | ⏳ 待验证循环稳定后 |

## 已锁定决策（grill 定案，勿改）

1. 基线 = 钉 **koharu v0.59.1** headless（REST+MCP+像素 mask）；上游 0.77.5 起删 headless/HTTP/MCP，升级即失去自动化面。
2. Agent 形态 = **会话驱动**（DSH 会话=单 LLM Agent 导演；Python=确定性工具层；describe_image=Vision QA 眼睛）。
3. 第一里程碑 = **Benchmark A/B/C**（VLM 当 oracle，**零人工全量标注**——用户明确拒绝人工标注）。
4. Vision QA 通道 = **describe_image**（用户禁了 ModLens，注入 .env）。
5. 翻译通道 = koharu 内 `llm` 引擎（做法 1，systemPrompt 注入 Story Memory）。
6. 场景级翻译**不在 MVP**（Story Memory + 前页上下文优先；Benchmark D 再定）。
7. 成功标准 = **benchmark 数据 + 失败可定位到具体模块**。
8. skills = 3 个（benchmark/koharu-drive/verify）。
9. 接口全表下沉到 koharu-drive skill；CLAUDE.md 只留一行。
10. package.json 不包 git/gh（原子操作用原生；发布流程在 verify skill）。

## 验证循环设计（新锁定，来自 Claude Code 官方博客）

- 模式 = **分层**：Benchmark A/B/C=独立（我自调度，非手动跑）+ Repair Loop=嵌入 pipeline + verify=链式发布。
- 前端/playwright：**本项目永远不需要**（判卷是 describe_image 看静态图，无浏览器自动化）。
- **调度权在我**：改了 detector/OCR/prompt 后我自记 todo 跑 benchmark，用户不碰终端。
- 稳定后才上 GitHub Actions（每次 push/PR 自动跑同一验证 skill）。

## 关键坑速查（详见 CLAUDE.md）

- NO_PROXY=127.0.0.1,localhost（Clash 破坏 localhost）。
- .ps1 含中文必须 UTF-8 带 BOM。
- ctd_seg 只细化已有框；pp-doclayout-v3 是文档模型，框外字漏检嫌疑元凶（Benchmark A 同页四 detector 对比）。
- patch 后必须重跑 koharu-renderer。
- workers>1 崩（CPU/集显 Vulkan 断连）。

## 测试集现状

- 真实源图（**未翻译原文**）已在机器上：`D:\我的汉化\output\灵梦和妹红\process\NN\page.jpg`（NN=11..26，共 16 页，2243×3465）。
- 单翼停留之地 process/ 无 page.jpg（只有 rendered.png=已翻译），**不可做 benchmark 源图**。
- 原图不入库（testsets/pages/ 已 gitignore）；ground_truth/、results/ JSON 入库。

## 下一步

1. VLM oracle 标注 160 crops 归 4 类（框内对白/框外对白/SFX/背景文字 + is_text 真假判定），产出 labels JSON。
2. `npm run ingest:a` 算 Benchmark A 指标（detection_precision + 四类分布），产出 output/benchmark_a.json。
3. 结果回填本节「当前状态」并推送。
