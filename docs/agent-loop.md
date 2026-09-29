# 本机自主改进 Agent

入口：`uv run python scripts/run_agent.py`。用户提供目标和完成条件，runner 自动调用本机
harness，保存每轮证据并独立执行固定检查，最终停在 `ready_for_review` 等人验收。
首版没有 GUI 或常驻服务：进程持续运行期间无需继续发送聊天，系统重启后显式恢复。

## 配置与启动

在独立 Git worktree 开发分支运行。配置与产物放该目录下
`workspace/<work-id>/artifacts/agent/`；不要往 JSON 写 API key，认证复用 harness 本地配置。

配置示例（替换 workspace 和 launcher 为本机实际路径；launcher 是 argv 数组，不是 shell）：

```json
{
  "objective": "调查竖排列尾冗余逗号，修改可复用管线并用真实样本证明改善",
  "acceptance": "追踪译文到布局的标点来源；保留语义必要标点；提供修改前后产物及观察记录；不能手改最终译文；机械回归通过；视觉结论等待人验收",
  "workspace": "E:/amta-typeset-task",
  "launcher": ["node", "E:/deepseek harness/deepseek-harness/apps/cli/lib/bin.js", "--profile", "headless"],
  "checks": [["uv", "run", "python", "-m", "pytest", "-q"]],
  "max_rounds": 6,
  "round_seconds": 300,
  "total_seconds": 1800
}
```

```powershell
uv run python scripts/run_agent.py create --task-dir workspace/typeset/artifacts/agent --config workspace/typeset/config.json
uv run python scripts/run_agent.py run --task-dir workspace/typeset/artifacts/agent
uv run python scripts/run_agent.py status --task-dir workspace/typeset/artifacts/agent
uv run python scripts/run_agent.py resume --task-dir workspace/typeset/artifacts/agent --feedback "已确认样本位置，继续调查"
uv run python scripts/run_agent.py accept --task-dir workspace/typeset/artifacts/agent
```

`accept` 由人验收后显式运行，不自动合并或发布。若代码或证据在检查后改变，它拒绝验收。
预算耗尽后创建新任务明确新预算，不会通过反复 resume 重置额度。正常 continue 无需 resume。
失败和用户问题可附反馈恢复；若上次强杀留下子进程 PID，先核实并结束进程再清除 PID 记录。
状态文件不可手工改成成功。可写文件状态和 Git worktree 不是抵御恶意 Agent 的权限沙箱。

## 证据与边界

task.json 保存目标、固定检查、状态、历史和已使用运行时间。每轮有 request.md、result.json、
execution.json、stdout/stderr 与检查日志。nonce 拒绝旧结果；进程退出 0 而没写结果依然失败。
检查命令由提交任务的一方配置，Agent 不能改成更宽松的检查。检查应只读代码与证据；
会改生成文档的完整 fastcheck 应在交付边界运行，不作为默认轮内检查。

机械证据仅证明程序检查通过，视觉/语义质量仍需 Agent 如实观察与人的最终验收。
若视觉工具不可用、真实样本找不到，必须记录未知并停在需要人工/外部条件的位置。
人工暂停可中断运行进程；首版不提供后台服务控制 API，也不承诺机器重启后自动重启。

## 接入兼容性

Context7 官方库 `/deepseek-ai/deepseek-harness` 文档比本机安装新版，2026-09-28 查询：
https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/headless/README.md
当前本机只接受 positional task；runner 传任务文件指针，不依赖尚未安装的 stdin/json/resume。
Claude Code 可以由不同 launcher 接入同一文件协议，但没有实跑的后端不标为已验证。
DSH 的 web 和 headless 是不同 profile，web 可用不能证明 headless 已配置或可调用。
