# 030 — 验证阶梯补全：L5 端到端门 + L6 独立 model 审核

日期：2026-09-04　状态：已采纳

## 决策

验证阶梯补全后两层（前四层 L1-L4 已由 fastcheck 一条命令覆盖：compile+ruff+pyright+pytest+depguard+memory，见 ADR-007 与机械护栏三级）：

1. **L5 端到端门 = `fastcheck.py --with-e2e`**：在 fastcheck 基础上追加探测 koharu :4000 ——
   - 可达 → 必跑 `scripts/smoke_test.py`（连通引擎→建项目→传图→检测→读场景→关项目），必须 PASS；
   - 不可达且本次改动涉及引擎面（`koharu_client` / `koharu_blocks` / `pipeline` / `runner` / `smoke_test`）→ **FAIL**（堵"引擎改动没验证就提交"的洞）；
   - 不可达且不涉引擎面 → SKIPPED（不算失败，但明确打印，不假装通过）。
   接线：Ralph `prompt.md` 第 5 步（改引擎面 → 额外跑 `--with-e2e`）；`.githooks/pre-push` 由"可选 smoke"统一为 `fastcheck.py --with-e2e`。
2. **L6 独立 model 审核 = `scripts/review.py`**：把 `git diff（base...HEAD + 工作区）+ 验收标准（loop_state.json 或 --mission）` 打包，spawn 一个**不知道开发者做了什么**的独立 `claude -p` 会话（只读 Read/Grep/Glob，零依赖 stdlib），按三维度审核：
   ① 达成度（是否达成验收标准，逐条对）② 风险（漏需求 / 引入 bug / 破坏契约）③ 证据（"看起来对但没证据"的断言）。
   输出 `VERDICT: PASS|FAIL|CONCERN` + 编号发现（带文件:行证据）。报告落 `output/logs/review-<ts>.md`；review 会话 JSONL 可被 trace_probe 观测。
3. **修订 ADR-028 第 7 条"不采用接第二个模型做判分"**：不逐迭代判分（Ralph 每轮仍只跑确定性 fastcheck），改为**合入 main 前 checkpoint 的一次性独立审核**（人工可选门，非默认强制），避免每轮 API 成本与迭代延迟。
4. **Ralph v3 循环可靠性（心跳 + BLOCKED + trace 复盘）**：
   - **心跳**：ralph.ps1 spawn 后每 30s 用 `scripts/trace_probe.py live` 定位本次 claude 会话 JSONL（`~/.claude/projects/<slug>/<uuid>.jsonl`）并查 mtime，连续 `HeartbeatStallSeconds`（默认 180s）无新写入即判定卡死并杀进程——把 v2 的"15 分钟倒计时炸弹"（迭代4 卡死 19 分钟靠人肉发现）提前到 3 分钟自动止损。
   - **卡死诊断**：杀前 `trace_probe.py tail` 读 JSONL 尾部（最后一次工具调用 / 最后文本 / 最后 tool_result），写进 `ralph-log.md` + `loop_state.escalation`，下轮 agent 接续不失忆。
   - **BLOCKED 暂停**：agent 在 `loop_state.json` 写 `status=BLOCKED`（`scripts/loop_state.py blocked`，三个决策点 / 死胡同时）→ ralph 检测到即 `exit 2` 停循环等人，不再空转烧迭代（第一次 loop blocked 空转一整轮）。
   - **trace 复盘**：COMPLETE 时 `trace_probe.py stats`（工具调用数 / 最大停顿 / 重复调用）追加 `ralph-log.md`——用 Trace 反查 Harness 哪里待完善。

## 理由

- 前四层已覆盖静态/lint/类型/单测；L5 能力已有（`smoke_test.py` + pre-push 可选）但**没进 Ralph 门禁**——动引擎相关代码时 Ralph 可能把"没跑过引擎通路"的改动直接 commit（verify skill 的规矩是人记得才执行的，非机器强制）。
- L6 防"自己写自己查、自我感觉良好"——单人单 agent 最容易栽在这；导演=人终审 + benchmark VLM oracle 都是"事后验收/评测"，不是"改动落地前第二个独立视角审 diff"。
- 与项目"零依赖 stdlib"路线一致：`--with-e2e` 用 stdlib socket 探测端口；`review.py` 零依赖，spawn 复用 ralph.ps1 已有的 `claude -p`（不引入新框架）。
- Ralph v3：迭代4 静默卡死 19 分钟（now.md 12 分钟未更新）暴露 v2 超时的"倒计时炸弹"本质；第一次 loop blocked-on-human 空转一整轮证明"写进 next_action 并继续"是错误指令。已有 `claude-agent-trace.html` 是"事后人看"的工具，缺"活的进程监控 + 自动诊断"——`trace_probe.py` 补上，零依赖 stdlib。

## 后果 / 约束

- `--with-e2e` 在引擎不可达且未改引擎面时打印 SKIPPED（exit 0），**不假装通过**；改引擎面 + 引擎不可达 → FAIL，必须 `npm start` 后重跑才算过。
- `review.py` 是人工/合入前辅助门，不进 Ralph 每轮流程（成本与 ADR-028 修订一致）；默认 `--base main`，可 `--mission` 指定验收标准。
- pre-push 现在会因"改引擎面但引擎未启动"而阻断 push——是刻意为之（push 应代表已验证状态）。
- 相关：ADR-007（验证分层）、ADR-015（依赖膨胀守卫）、ADR-025（记忆机制活性）、ADR-028（Ralph Loop）。
- 心跳对单次 >3 分钟的超长工具调用（长测试/安装）期间 JSONL 不增长可能误杀——可用 `-HeartbeatStallSeconds` 调大；`CLAUDE_CONFIG_DIR` 变更时需同步 `-TraceProjectsDir`。
