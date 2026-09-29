# AMTA 自主改进 Agent 实施计划

> 执行方式：本会话顺序实现并验证；用户已授权技术细节自主决策，无需再次逐项审批。

**目标：** 人提交真实问题后，本机 harness 自主完成调查、修改、实验和自检，交付可审查证据，等待人验收。

**架构：** DSH 负责每轮内的推理与工具循环；AMTA runner 负责跨进程任务状态、预算、进程生命周期和验收交接。每轮可完成一个完整实验，不限制为一次工具调用。使用文件检查点继续新会话，不假定本机支持 session resume。先单任务、单工作 Agent、单独 Git worktree，不引入常驻服务或多 Agent 调度。

**技术：** Python 标准库；DSH headless 原生 CLI；原有 pipeline/artifact/report 工具。

## 已确认需求和边界

- 改进任务优先；第一个真实问题是竖排断句和列尾冗余标点。
- 修改可复用代码或 prompt；不得人工改一张译文或成品图冒充管线改善。
- 换列不必然等于语义停顿；先定位真实样本和标点来源，不全局删标点。
- 模型决定调查路线和修改方法；runner 不硬编码排版解法。
- 每轮加载项目身份、目标、验收条件、历史结果和技能索引；技能正文按需读。
- 人最终验收；Agent 的 ready_for_review 不是 accepted。
- 自检包含固定机械检查和可追溯文件证据；机械检查不能证明视觉质量。
- 第一版用现有报告系统，runtime 文件统一放 workspace/<work-id>/artifacts/agent/。
- 不自动合并、推送、发布或修改原始页面；隔离目录不是安全沙箱，工具权限仍由 harness 控制。
- 默认至多 6 轮，每轮至多 300 秒，总执行预算 1800 秒；可在任务配置中明确调整。预算是运行时间而非 token/货币限额。
- 配置、证据缺失或后端失败会保留日志并停止，不用空输出推断成功。

## 依据

Context7 查询库 `/deepseek-ai/deepseek-harness`，2026-09-28：
https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/headless/README.md
新版文档有 stdin/json/session 参数，本机 startup.ts 仅支持 positional task；以本机源码为接入依据。
先传简短任务文件指针；结果写每轮独立 JSON，校验 round nonce，拒绝旧结果。
DSH 原生轮内工具执行不重造；goal 自动接续的启动恢复约束使文件检查点仍有必要。

## 实施清单

### 1. 状态与契约
- [ ] 创建 `src/amta/agent_loop/state.py`：原子 JSON 写入、配置校验、任务锁、Git 工作区指纹。
- [ ] 配置字段：objective、acceptance、workspace、launcher（argv）、checks（argv 列表）、max_rounds、round_seconds、total_seconds。
- [ ] 返回字段：nonce、status（continue/ready_for_review/needs_human）、summary、next_action、evidence（现有文件路径）、question。
- [ ] 拒绝空目标、非正预算、空检查、非 worktree 工作目录；不存密钥。
- [ ] 测试非法配置、并发锁、旧 nonce、证据缺失、原子恢复。

### 2. 执行后端
- [ ] 创建 `src/amta/agent_loop/backend.py`：不经过 shell 的 argv 启动、stdout/stderr 文件、超时杀进程树、Windows 隐藏窗口。
- [ ] 提示词只传任务文件路径；长上下文保存在每轮 request.md。
- [ ] 测试成功、非零退出、超时和命令参数带空格。

### 3. 持久循环
- [ ] 创建 `src/amta/agent_loop/runner.py`：先保存 running 和轮次，再调用 backend，记录返回结果。
- [ ] continue 自动下一轮；needs_human 保存具体问题并停止；空输出/损坏结果停止 failed。
- [ ] ready_for_review 后由 runner 运行固定检查、记录日志并校验证据；失败反馈下一轮。
- [ ] 检查通过记录代码和证据指纹；人工 accept 前重新校验，避免验收旧版本。
- [ ] 每个工作目录只允许一个 runner；意外中断后不自动重复上一轮，显式 resume 先读取现场。
- [ ] 测试无需聊天的两轮推进、失败反馈、预算、暂停恢复、人工验收与变更后拒绝验收。

### 4. 入口与使用
- [ ] 创建薄入口 `scripts/run_agent.py` 和 `src/amta/agent_loop/cli.py`，支持 create/run/status/resume/accept。
- [ ] 更新方向草案，标明实现边界；写运行说明和首个排版工单模板。
- [ ] 补 `docs/friction.md`：现有真实摩擦是必须人工不断发送继续指令；用两轮集成测试验证。

### 5. 验证与实跑
- [ ] `uv run python -m pytest tests/test_agent_loop.py -q`：确定性测试先跑。
- [ ] 完整项目检查，区分既有失败和本次失败。
- [ ] 真正调用本机 DSH 完成带文件证据的两轮冒烟，不能以 mock 测试充当接入完成。
- [ ] 接入成功后启动排版试点；先从 artifact 找真实样本，再由 Agent 决定修改位置。
- [ ] 若本机 DSH 接入失败，保留实跑诊断并明确报告阻塞，不声称排版已解决。

## 完成定义

计划、实现、确定性测试、真实 harness 调用证据均可查看。首个试点可以停在有证据的待人工阶段；没有视觉证据不能宣称排版质量通过。实现提交与试点修改分开，原工作目录已有 GUI 改动不进入本次提交。
