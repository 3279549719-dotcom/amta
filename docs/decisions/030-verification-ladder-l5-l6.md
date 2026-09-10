# 030 — 验证阶梯补全：L5 端到端门 + L6 独立 model 审核

日期：2026-09-04　状态：已采纳

## 决策

验证阶梯补全后两层（前四层 L1-L4 已由 fastcheck 一条命令覆盖：compile+ruff+pyright+pytest+depguard+memory，见 ADR-007 与机械护栏三级）：

1. **L5 端到端验证 = 按改动自选，交给 agent（prompt 层），不做机械映射**：~~`fastcheck.py --with-e2e`（git diff 关键词路由 + 探测 koharu）~~ —— **已撤销**（见理由）。当前 4 个 stage（detect=本地 ONNX / ocr=hayai 本地 / translate=DeepSeek 直调 / inpaint=lama-manga 本地，ADR-029 / typeset=自研 Pillow）都**不依赖 koharu**，koharu 只剩 runner/legacy 路径；且静态 diff 路由"盲猜"（只看文件名、看不见意图），而 agent 知道 `next_action` 任务上下文、能精确选验证面。故 L5 改为：
   - Ralph `prompt.md` 第 5 步强约束：改哪个 stage 就真跑哪个 stage 的通路（detect/ocr/translate/inpaint/typeset 各自用对应工位脚本或 `run_pipeline.py --stages <X> --pages 1-1` 真跑一页）；只有真动 `koharu_client/runner` 才跑 koharu smoke（`npm start` 后跑 `smoke_test.py`）；把"验证了什么 + 为什么选它 + 结果"写进 `loop_state.last_verified`。
   - `.githooks/pre-push` 恢复"fastcheck（L1-L4）+ 可选 smoke（koharu 可达才跑）"，不再硬绑 koharu。
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
- 与项目"零依赖 stdlib"路线一致：`review.py` 零依赖，spawn 复用 ralph.ps1 已有的 `claude -p`（不引入新框架）；`--selfcheck` 用内置坏/好样例给门做可复现体检（坏样例必须被抓到、干净样例不得误报）。
- Ralph v3：迭代4 静默卡死 19 分钟（now.md 12 分钟未更新）暴露 v2 超时的"倒计时炸弹"本质；第一次 loop blocked-on-human 空转一整轮证明"写进 next_action 并继续"是错误指令。已有 `claude-agent-trace.html` 是"事后人看"的工具，缺"活的进程监控 + 自动诊断"——`trace_probe.py` 补上，零依赖 stdlib。

## 后果 / 约束

- L5 的有效性靠 **agent 的执行纪律**（prompt 层强约束 + `loop_state.last_verified` 记录），不靠死脚本——接受"agent 可能漏跑"的风险，由 L6 独立审核 + 人合入验收兜底。
- `review.py` 是人工/合入前辅助门，不进 Ralph 每轮流程（成本与 ADR-028 修订一致）；默认 `--base main`，可 `--mission` 指定验收标准；`--selfcheck` 用内置坏/好样例复检门本身（坏样例必须被抓到、干净样例不得误报），跑通才算门有效。
- pre-push 只做 L1-L4 + 可选 smoke，不再因"引擎未启动"阻断 push（引擎是否启动不由 push 钩子判断，端到端验证的选择权在 agent + 人）。
- 相关：ADR-007（验证分层）、ADR-015（依赖膨胀守卫）、ADR-025（记忆机制活性）、ADR-028（Ralph Loop）。
- 心跳对单次 >3 分钟的超长工具调用（长测试/安装）期间 JSONL 不增长可能误杀——可用 `-HeartbeatStallSeconds` 调大；`CLAUDE_CONFIG_DIR` 变更时需同步 `-TraceProjectsDir`。
