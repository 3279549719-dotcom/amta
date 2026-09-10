
# 2026-09-08 全链实验 p33 — 假设 H 全链实证 + 考题落盘（exp/report-anchor @ efdaa9a）

> 承接 docs/reference/2026-09-08-tool-governance-tutor-session.md（同日上半场）。
> 上半场：skill 库 113→31 / 三命运判据 / A/B/C 优先级框架。
> 下半场（本文）：假设 H 两次实证（p6 三段链 + p33 六段全链）+ 三个次生 bug + 对后续工作的启发考题。

## 假设 H 的最终陈述（Patrick 15:37 立立，15:45 重述确认）

**"把调用写进代码路径，就必然被执行。"**

证伪面（Patrick 原话）："假如说没有 HTML，那么这一切都无从谈起，之前设想的一切全都是狗屁。"
- p6 实验：run=9ab249583e7e，REPORT OK（report.html 2.4MB）→ H 在三段链尺度成立
- p33 实验：run=424c61ae90d0，六段全真跑 → H 在全链尺度成立

## p33 全链时间轴（单翼停留之地，干净 worktree）

| 时刻 | 产物 | 引擎 |
|------|------|------|
| 16:06:39 | detection/page_33.json | RT-DETR-v2 ONNX (conf 0.7) |
| 16:07:06 | canon/page_33.json | HayaiOCR-v2.1（7 框） |
| 16:09:53 | translation/page_33.json | DeepSeek（7 条全过） |
| 16:09:59 | clean/page_33_clean.png (6.8MB) | masking + inpaint（7 框 fill_white） |
| 16:10:01 | report.html (1.96MB) | gen_report 锚点自动触发 |

零人工提醒。从"AI 要人提醒才用深接口"到"报告自己出现"，结构锚点一击闭合。

## 考题（对后续工作的启发，Patrick 下次对话的起点）

**考题 1（回归 bug 优先级）**：r00/r04 译文带 `r00|` region_id 泄漏前缀（7 条中 2 条）。
LLM 把 prompt 里的 region 标记回显进译文；parse 层只验长度、guardrails 只查假名，双拦不住。
问：这是 prompt-slim 实验的回归（WIP 未合），还是主线的既有病？修在哪层最便宜——
prompt 模板（去标记）/ parse 护栏（`^r\d+\|` 判失败）/ 还是都修？判据：哪层修了之后
这个 bug **结构上不可能**而不是概率上少见？

**考题 2（lama 引擎未锻炼）**：p33 七框全 fill_white（对话气泡白底），lama-manga
推理零调用。全链通了≠全链验了。问：挑一页有拟声词/框外字的做 lama 真实测，
应该排在 pages 11-19 全量重跑之前还是之后？判据：全量重跑的验收目的是"新栈全量
数据"还是"逐引擎验证"？

**考题 3（三处 worktree 断点的系统化）**：junction models/、双位置 .env 复制、
onnxruntime 手动补装——三件事每次开 worktree 都要重做。问：按三命运判据，
"worktree 环境准备"这个动作的触发事件是什么？该 embedded（进脚本）还是
chained（进 AGENTS.md/verify skill）？现成候选：cleanup_orphan_worktrees.ps1
旁边加一个 setup_worktree.ps1？

**考题 4（onnxruntime 声明缺失）**：主 venv 有、pyproject.toml 没有，ADR-015
depguard 纪律被绕过（09-06 手动 pip install）。问：depguard 为什么没拦住？
它检查的是"声明的都在用"还是"在用的都声明了"？方向性漏洞该记 lessons 还是改工具？

## 实验环境事实（下次复现用）

- worktree：.worktrees/exp-report-anchor（分支 exp/report-anchor，efdaa9a）
- 前置三件套：junction models → 主仓 models；.env 复制到 amta/ 和 worktree 根两处；
  uv pip install onnxruntime==1.29.0
- 源图：D:\我的汉化\汉化作品\东方\单翼停留之地\33.jpg（注意是"单翼"非"单骑"）
- 命令：uv run python scripts/00_run_all.py --work-id exp-report-anchor-p33
  --src-dir "D:\我的汉化\汉化作品\东方\单翼停留之地" --start-page 33 --end-page 33
  --with-inpaint --with-report
- 断点续跑语义：产物存在即 skip——p33 若重跑会全 skip，要真跑需删对应 stage 产物

## 待 Patrick 裁决清单（从上一份文档继承 + 本次新增）

1. exp/report-anchor 合 main 时机（等 11-19 全量 or 现在合）
2. `r00|` 泄漏修复层选择（考题 1）
3. lama 锻炼页挑选时机（考题 2）
4. onnxruntime pyproject 补声明（1 行）
5. worktree setup 脚本化（考题 3）
6. CLAUDE.md 6→3 手术（等表A，本日上半场框架）
