# 10 — Claude Code Headless 官方机制一手调研 + ralph.ps1 优化报告

> 日期：2026-09-05　调研者：Claude Code 子代理（本机 `claude` 2.1.220）
> 范围：`claude -p` 无头模式的官方语义（help / 官方文档 / 本机实测），对照审阅 `ralph.ps1` 现有 harness，产出北极星 backlog 与信号密度分析。
> 引用约定：`claude --help (2.1.220)` = 本机 help 输出；`[docs:headless]` = https://code.claude.com/docs/en/headless.md；`[docs:cli-ref]` = https://code.claude.com/docs/en/cli-reference；`[docs:sessions]` = https://code.claude.com/docs/en/sessions.md；`[docs:permissions]` = https://code.claude.com/docs/en/permissions.md；`[docs:hooks]` = https://code.claude.com/docs/en/hooks.md；`[docs:hooks-guide]` = https://code.claude.com/docs/en/hooks-guide.md；`[docs:sdk-py]` = https://code.claude.com/docs/en/agent-sdk/python.md；`[docs:sdk-stream]` = https://code.claude.com/docs/en/agent-sdk/streaming-output.md；`[docs:sdk-ov]` = https://code.claude.com/docs/en/agent-sdk/overview.md；`[实测]` = 本机 2.1.220 实跑输出。

---

## 0) TL;DR 结论表

| # | 结论 | 裁决 | 依据 |
|---|---|---|---|
| 0.1 | **当前 spawn 用法基本正确**：`-p` + `stream-json` + `--verbose` + `--include-partial-messages` 是官方"逐事件实时"流的标准组合；`2.1.220` 下 `stream-json` **硬性要求** `--verbose`（缺了直接报错）。stdout 每行一个 JSON 对象、实时 flush → **拿它当心跳文件成立** | ✅ 用法对 | `[实测]` + `[docs:headless]` |
| 0.2 | **最大隐患 = `Stop-Job` 杀不死子进程树**（孤儿 worker 继续写文件/commit）。必须换 `Start-Process -RedirectStandardOutput` + `taskkill /PID <pid> /T /F` | ❌ 要改 | `[实测]`（孤儿实证） |
| 0.3 | transcript JSONL 是**异步批量写**（探针实测滞后 ~20s 才跳一次），不能当实时心跳；心跳该盯 stream 文件（实时逐行），transcript 只作兜底/事后诊断 | ⚠️ 现设计已对，但兜底逻辑有竞态 | `[实测]` + `[docs:hooks]` transcript_path 字段 |
| 0.4 | **transcript 定位竞态真实存在**：同 slug 目录多个 jsonl + 异步 flush 会把上一次迭代的旧文件 mtime 顶到"spawn 之后" → 抓错会话。解法：从 stream 的 `system/init` 事件解析 `session_id`（实测每行都带），或 spawn 时直接传 `--session-id <uuid>`，路径即 `<slug>/<uuid>.jsonl` | ❌ 要改 | `[实测]` |
| 0.5 | PS 5.1 `Out-File/Add-Content -Encoding utf8` **写 BOM**（EF BB BF）→ stream 文件第一行被 BOM 污染，JSONL 解析器会跳过首行；GBK 控制台更会乱码。`Start-Process -RedirectStandardOutput` 让 claude.exe 直写原始字节 → 无 BOM、无 PS 文本层 | ❌ 要改 | `[实测]` |
| 0.6 | **180s 心跳与超长工具冲突**：工具运行期间 stream 不增长（无新事件）→ 会被误杀。解法：解析"最后一个事件是 `assistant` 的 `tool_use` 且其后无 `tool_result`"= 正在执行工具 → 放宽心跳到墙钟超时 | ⚠️ 半对（现脚本只靠 mtime） | `[实测]` schema |
| 0.7 | PreToolUse **command hook** 的 block 在 2.1.220 实测会把 reason 作为 `is_error` 工具结果喂回模型、agentic loop 继续跑（有/无 `continueOnBlock` 行为无差）；"deny 默认结束整轮"只对 **prompt 型 hook** 成立（2.1.210 起）。故 ralph 的 P3 `continueOnBlock` 补丁是无害双保险，但 hook 文档串里写"不带就整轮白跑"对 command hook 不成立 | ⚠️ 注释夸大 | `[实测]` + `[docs:hooks-guide]` L852 |
| 0.8 | `result` 事件自带 `is_error` / `terminal_reason` / `total_cost_usd` / `usage` / `num_turns` / `permission_denials` → 结构化收尾可完全替代 grep `<promise>` | ✅ 北极星 1 | `[实测]` |
| 0.9 | Claude Agent SDK（Python）已成熟，事件模型与 CLI stream 同源、支持 `resume`/`max_turns`/`can_use_tool`/流式输入 → 是重写 ralph 外层的正道 | ✅ 北极星 0 | `[docs:sdk-ov]` `[docs:sdk-py]` |
| 0.10 | 本机 claude 实为**原生 claude.exe**（npm shim 转发），走 DeepSeek anthropic 兼容端点；思考型模型会把 stream 刷爆（一次 5 段话 = 760KB / 3869 事件，其中 thinking 占 ~99%）→ 解析需按事件类型过滤 | ⚠️ 环境事实 | `[实测]` |

---

## A) 现在用法对不对 —— 逐 flag / 逐问题校验

### A1. `-p` + `stream-json` + `--verbose` + `--include-partial-messages` 的官方语义

**各 flag 语义（`claude --help` (2.1.220) 原文）：**

| flag | 官方语义（本机 help） | 说明 |
|---|---|---|
| `-p, --print` | "Print response and exit (useful for pipes). Note: The workspace trust dialog is skipped when Claude is run in non-interactive mode (via -p, or when stdout is not a TTY…)" | 无头模式入口 |
| `--output-format` | "Output format (only works with --print): `text` (default), `json` (single result), or `stream-json` (realtime streaming)" | 只配 `-p` |
| `--verbose` | "Override verbose mode setting from config" | **2.1.220 实测：`stream-json` 缺 `--verbose` 直接报错退出**：`Error: When using --print, --output-format=stream-json requires --verbose`（`[实测]`） |
| `--include-partial-messages` | "Include partial message chunks as they arrive (only works with --print and --output-format=stream-json)" | 必须配 stream-json |
| `--include-hook-events` | "Include all hook lifecycle events in the output stream (only works with --output-format=stream-json)" | **SessionStart/Setup hook 事件默认就带，不需要此 flag**（见 A5） |

**stream-json 事件流实测（2.1.220，一次 `"Reply PONG"`，27 行 / 20s）：**

每行一个 JSON 对象，事件类型按序：
1. `system` 子类型 `hook_started`/`hook_progress`/`hook_response`（SessionStart hook 生命周期，默认就带，实测 12 行）
2. `system` 子类型 `init` —— **首条真正会话事件**，含 `session_id` / `model` / `claude_code_version` / `cwd` / `permissionMode` / `tools` / `mcp_servers` 等
3. `system` 子类型 `status`
4. `stream_event`（仅当开 `--include-partial-messages`）—— 内层 `event.type` ∈ `message_start / content_block_start / content_block_delta / content_block_stop / message_delta / message_stop`，即 Anthropic Messages API 的原始流
5. `assistant` —— **完整 assistant 消息**，`message.content` 为 block 数组（`thinking` / `text` / `tool_use`），带 `timestamp` 与 `usage`；**有/无 partial 都会出现**（实测无 partial 时仍有 assistant 事件）
6. `result`（最后一行）—— `subtype:"success"`、`is_error`、`result`（最终文本）、`stop_reason`、`terminal_reason`、`num_turns`、`duration_ms`、`total_cost_usd`、`usage`、`permission_denials`

> 版本差异提示：`--output-format=stream-json requires --verbose` 是本机 2.1.220 的强制项。`--include-hook-events` 在 help 里写"Requires stream-json"，而 **SessionStart/Setup 的 hook 事件总是包含、无需该 flag**（`[docs:cli-ref]` include-hook-events 条目）。若主人拿到别的版本，请以 `claude --help` 为准。

**判定**：ralph 当前 spawn 组合 `claude -p <prompt> --output-format stream-json --verbose --include-partial-messages` **语义正确且是最富信号组合**。stdout 是否逐事件实时 → **是**（实测文件 20s 内逐条增长，见 B8/probe 6）。**唯一取舍**：`--include-partial-messages` 会把 token 级 deltas 也打进来，本机 DeepSeek 思考模型下会把文件刷到数百 KB~MB 级（见 0.10），纯为心跳其实可去掉 partial（assistant 完整事件已含 tool_use/文本），但会损失"逐 token 实时"粒度。建议：心跳 + 工具级信号用"无 partial"，活动仪表盘再上 partial。

### A2. 长 prompt 怎么传最稳

- **位置参数**：Windows 命令行上限 ~32767 字符（CreateProcessW），中文按 UTF-16 计 2 字节/字，超限会截断或报错。官方 SDK Python 文档也明说 system_prompt 字符串走 "CLI subprocess argv, which is subject to OS command-line length limits (~32 KB whole command line on Windows)"（`[docs:sdk-py]`）。ralph 把 prompt.md + preamble（memory_index + git log 全量）拼成单个位置参数，**迟早超限**。
- **stdin 读 prompt**：官方支持。`[docs:headless]`："Non-interactive mode reads stdin, so you can pipe data in…"，示例 `cat build-error.txt | claude -p 'concisely explain…'`；piped stdin 上限 **10MB**，超限报错非零退出。**实测**（probe 3）：`claude -p --output-format stream-json --verbose < prompt3.txt`（无位置 prompt）正确把 stdin 当 prompt 执行，exit 0。
- 附加风险：`[docs:headless]` 注明 "Before v2.1.211, an unreadable stdin on Windows crashed the session or made it exit silently"。2.1.220 已修，但 spawn 时务必保证 stdin 可读（有文件 handle）。

**推荐 spawn 写法（Start-Process 版，见 B7 组合）：** prompt 写临时文件（UTF-8 无 BOM），`-RedirectStandardInput` 指向它，不再把长 prompt 放 argv。

### A3. 退出码 / 无头权限行为 / 安全白名单组合

- **退出码**：`claude -p` exit 0 = 成功；非零 = 失败（`[docs:headless]`："exits with code 0 on success and a non-zero code when the run fails"；"invalid flag → reports the error to stderr before the run starts"）。"运行中失败（如缺 auth）→ Claude prints the failure as the result on stdout"。实测：正常完成全为 0；缺 `--verbose` 属启动错误，exit 1。`result.is_error` / `terminal_reason` 才是"这轮到底成没成"的权威字段（见 A6/C13）。SIGTERM（Unix）→ exit 143（`[docs:headless]`）。
- **无头下未批准的工具**：无交互者 → 落到 permission 流程的请求会被 **deny**（`[docs:headless]` permission-prompts 一节 + `[docs:permissions]`）。实测 probe 5：模型被 `--disallowedTools Bash` 约束后直接**不发起** Bash 调用（工具从上下文移除，`[docs:permissions]` deny 规则 "removes the tool from Claude's context entirely"）。真正触发"发起但被拒"要靠 allow 白名单之外仍可见的工具。deny 的表现：`result.permission_denials` 数组记录被拒调用（实测 probe B）。
- **flag 是否都在 2.1.220**：`--allowedTools/--allowed-tools`、`--disallowedTools/--disallowed-tools`、`--permission-mode`（choices: `acceptEdits,auto,bypassPermissions,manual,dontAsk,plan`）、`--dangerously-skip-permissions`、`--allow-dangerously-skip-permissions`、`--add-dir`、`--tools` 全部在 help 中（`claude --help` (2.1.220)）。注意 2.1.220 help 把 `--permission-mode` 列成 `manual`（官方 docs 说 manual 是 default 的别名，2.1.200+）。
- **推荐"无头自主跑安全白名单"组合**（2.1.220）：
  - 基线模式：`--permission-mode dontAsk` —— "Auto-denies tools unless pre-approved via permissions.allow rules"（`[docs:permissions]` 权限模式表），最稳、最可预测，**推荐 ralph 采用**；比现在的 defaultMode `auto`（classifier 审核）更接近"白名单确定性"。
  - 白名单：`--allowedTools "Read Edit Write Grep Glob Bash(uv run python *) Bash(py -3.13 scripts/fastcheck.py) Bash(git status *) Bash(git diff *) Bash(git add *) Bash(git commit *)"` —— 注意 `Bash(git *)` 太宽（含 push/merge），按子命令精确给（`[docs:permissions]` wildcard 规则：`*` 放子命令后）。
  - 追加目录：`--add-dir "E:\manga translator agent\amta"` 已是 cwd，通常不必；若要读原图目录 `D:\我的汉化\...` 需 `--add-dir`（read-only 命令不受工作目录限制，但 Read/Edit 文件工具受 `[docs:permissions]` working-directories 约束）。
  - 防呆：`--max-budget-usd 2.0`（print-only，2.1.217+ 子代理也算进 cap，`[docs:cli-ref]`）。
  - **不用** `--dangerously-skip-permissions`（连 `.git`/`.claude` 都放行，`[docs:permissions]` 警告），除非在 VM/容器。

### A4. transcript：`-p` 也写 jsonl 吗？异步？能关吗？

- **写**：`-p` 默认也写。实测 probe 每次都在 `E:\claude\.claude\projects\<slug>\<session_id>.jsonl` 落了文件；文件名 == init 的 `session_id`（实测 probe 6 transcript 5f1f8606…== init session_id）。`[docs:sessions]`："Sessions are saved continuously to local transcript files… Claude Code stores transcripts as JSONL at ~/.claude/projects/<project>/<session-id>.jsonl"；-p 会话留出 picker 但可按 ID resume。
- **异步、滞后**：hook 输入字段文档直接警告 "The transcript file is **written asynchronously and may lag** the in-memory conversation…"（`[docs:hooks]` common input `transcript_path`）。**实测 probe 6**：stream 文件 09:43:41→09:44:08 从 18KB 连续长到 760KB（每 ~5s 更新），而 transcript 停在 34KB 不动约 20s、然后在 09:44:08 一次性跳到 47KB → **transcript 是批写，不能当实时心跳**。
- **能关**：`--no-session-persistence`（print-only，`claude --help` (2.1.220)）或 `CLAUDE_CODE_SKIP_PROMPT_HISTORY`（任意模式，`[docs:sessions]`）。关了就不能 `--resume`。ralph 需要 transcript 做诊断，**不要关**；心跳改盯 stream 文件即可。

### A5. hooks 在 `-p` 模式哪些事件触发？deny+continueOnBlock？超时？

- **会触发**：`SessionStart`、`PreToolUse` 实测都触发（见 probe 1/4 的 5 个 SessionStart hook 与 probe A/B 的 PreToolUse 拦截）。`-p` 从不弹信任对话框，但 settings 文件里的 hooks **照常 Used**（`[docs:permissions]` "What runs before you trust a folder" 表：Hooks in settings files → `claude -p` 列 = Used）。`Stop` 属"once per turn"（`[docs:hooks]` cadence），`-p` 下应触发；`SessionEnd` 在 SIGTERM 时运行（`[docs:headless]`）。若要把中途的 PreToolUse/Stop 生命周期事件打进 stream，需 `--include-hook-events`（SessionStart/Setup 除外，默认就带，`[docs:cli-ref]`）。
- **PreToolUse deny + continueOnBlock 官方语义（关键版本差）**：`[docs:hooks-guide]` L852 原文（prompt 型 hook 语境）：
  > "`PreToolUse`: the tool call is denied; **by default the turn ends** and the deny `reason` appears in the chat as a warning line. Set `continueOnBlock: true` … to instead return the `reason` to Claude as the tool error, so it can adjust and continue. **Before v2.1.210**, the deny `reason` was returned to Claude as the tool error and the turn continued."
  → "deny 默认结束整轮、reason 只作 chat 警告"是 **2.1.210 起 prompt 型 hook** 的语义变化。
  **但 ralph 用的是 command hook**（settings.json 里 `{"type":"command",...}`），实测 2.1.220 行为是：`{"decision":"block","reason":...}`（带/不带 `continueOnBlock`）都会把 reason 作为 `is_error` 工具结果喂回模型、**agentic loop 继续跑**（probe A/B：block 后模型照样执行了 Step 2，turns=3 success，`permission_denials` 记录被拒调用）。`[docs:hooks-guide]` L638 也写 command hook 的 `permissionDecision:"deny"` = "cancel the tool call **and send the reason to Claude**"。
  → **结论**：hook_pretooluse.py 注释"≥2.1.210 deny 默认整个回合结束、不带 continueOnBlock 本次迭代白跑"对 **command hook 不成立**（那是 prompt hook 的语义）。P3 补丁无害但非必需；真要用"整轮硬停"语义，应改用 **exit 2**（"exit 2 … even a JSON permissionDecision of allow can't override it"，`[docs:hooks]`）——但注意 exit 2 也只是 block 工具调用、未必停整轮。
- **hook 超时默认**：`command/http/mcp_tool` = **600s**；`prompt` = 30s；`agent` = 60s；`UserPromptSubmit/PreModelSwitch/PostModelSwitch` 降到 30s；`MessageDisplay` 10s；`SessionEnd` 共享 1.5s 预算（`[docs:hooks]`）。**PreToolUse 超时不 block 工具调用**（`[docs:hooks]` timeout 行）。ralph 的 PreToolUse hook 若在 600s 内不返回，commit 照跑 → 不能拿"hook 超时"当安全网，脚本自身要快。

### A6. stream-json 事件字段清单（"信号密度"原材料）

实测（probe 1/5/6）+ SDK/headless 文档交叉确认：

| 事件 | 关键字段 | 用途 |
|---|---|---|
| `system/init` | `session_id`、`model`、`claude_code_version`、`cwd`、`permissionMode`、`tools`、`mcp_servers`、`plugins` | **拿到 session_id**；确认环境 |
| `system/status` | `status` | 次要 |
| `system`（thinking_tokens） | DeepSeek 思考 token 流（本机特有，海量） | 建议忽略 |
| `stream_event` | `event.type`（message_start…）；`ttft_ms`（首个 token 延迟，message_start 上）；`event.delta`（text_delta / input_json_delta） | token 级实时文本/工具输入 |
| `assistant` | `message.content[]`（`tool_use` 带 `name`+`input`；`text`；`thinking`）；`timestamp`；`message.usage` | **工具调用信号、阶段文本** |
| `user` | `message.content[]` 里 `tool_result`（`is_error`、`content`、`tool_use_id`） | **工具结果/成败** |
| `result` | `subtype`(success)、`is_error`、`result`、`stop_reason`、`terminal_reason`、`num_turns`、`duration_ms`、`duration_api_ms`、`ttft_ms`、`total_cost_usd`、`usage`、`permission_denials` | **结构化收尾 + 成本 + 拒登** |

（`assistant`/`user`/`result` 的事件结构与 Agent SDK 的 Message 类型同源，见 `[docs:sdk-stream]`。）

**回答原文问题**：init **带** `session_id`；`result` **带** usage 与 `total_cost_usd`（`[docs:headless]` 亦说 "json 响应含 total_cost_usd"，本机 stream 实测 result 含）。每条 stream 行都带 `session_id`（实测 schema）。

---

## B) 现存问题清单（按严重度排序：现在错在哪 → 改成什么 → 收益）

### B1【严重】`Stop-Job` 杀不死 claude.exe 子进程树 → 孤儿 worker

**现在错在哪**：ralph.ps1 用 `Start-Job { & claude … }`，超时/心跳丢失时 `Stop-Job $job`。**实测**（test_stopjob2.ps1，Windows PowerShell 5.1）：Start-Job 内 `Start-Process` 起的子进程在 `Stop-Job + Remove-Job` 后**仍存活**（"child STILL ALIVE after Stop-Job -> ORPHAN CONFIRMED"）。即 `Stop-Job` 只杀 job 的 PowerShell 进程，不杀它拉起的 `claude.exe`（及其 Bash 工具子进程树）。孤儿 claude 会继续跑完当前回合、继续写文件/commit —— ralph 已进入下一轮，两轮 worker 同时写同一 repo → 状态错乱。

**改成什么**：放弃 Start-Job，用 `Start-Process -RedirectStandardOutput/-RedirectStandardError/-RedirectStandardInput -PassThru` 拿**真实 PID**；超时用 `taskkill /PID <pid> /T /F` 杀整棵树。注意 claude 实为 **原生 `claude.exe`**（`F:\npm-global\claude.cmd` 只是转发到 `node_modules\@anthropic-ai\claude-code\bin\claude.exe`，`[实测]` cat shim）。Start-Process 直接给 claude.exe 全路径（redirect 模式要求 `-UseShellExecute:$false`，无法跑 .cmd/.bat）。

可直接抄的核心片段（PS 5.1）：
```powershell
# 解析真实 exe 路径（npm 布局）
$claudeCmd = (Get-Command claude).Source          # ...\npm-global\claude.cmd
$claudeExe = Join-Path (Split-Path $claudeCmd) "node_modules\@anthropic-ai\claude-code\bin\claude.exe"

# prompt 写临时文件（UTF8 无 BOM），经 stdin 传入，避开 argv 长度上限
$promptFile = Join-Path $IterationLogDir "prompt-$i.txt"
[System.IO.File]::WriteAllText($promptFile, $promptWithContext, (New-Object System.Text.UTF8Encoding($false)))

$streamFile = Join-Path $IterationLogDir "iteration-$i-$ts.jsonl"
$errFile    = Join-Path $IterationLogDir "iteration-$i-$ts.stderr"
$proc = Start-Process -FilePath $claudeExe `
    -ArgumentList @('-p','--output-format','stream-json','--verbose','--include-partial-messages') `
    -RedirectStandardInput  $promptFile `
    -RedirectStandardOutput $streamFile `
    -RedirectStandardError  $errFile `
    -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden
$pid2 = $proc.Id

# 心跳轮询里：进程是否还活着是"硬存活"；stream mtime 是"软活性"（见 B3/B5）
# 超时/心跳丢失时：
taskkill /PID $pid2 /T /F 2>&1 | Out-Null   # /T = 树, /F = 强杀
```
> 注意 Windows 无 Unix SIGTERM；`taskkill /F` 是 TerminateProcess，**不会**触发 SessionEnd hook 的优雅收尾（`[docs:headless]` 的 SIGTERM→143 是 Unix 语义）。可接受：孤儿比不优雅更危险。

**改后收益**：杜绝孤儿 worker 跨迭代写文件/commit；ralph 杀即真杀。

### B2【严重】PS 5.1 `Out-File/Add-Content -Encoding utf8` 写 BOM + GBK 控制台 → stream 首行被污染、日志乱码

**现在错在哪**：`Out-File -FilePath $iterationLogFile -Encoding utf8`（ralph 内）与 `Add-Content -Encoding UTF8`（ralph + 探针）在 **Windows PowerShell 5.1**（本机无 pwsh，`[实测]` `which pwsh` 空）下写 **UTF-8 BOM**（实测 first3bytes = `EF BB BF`）。BOM 落在 stream-json 文件头 → 严格 JSONL 解析第一行必挂（trace_probe 的 read_text 会带 BOM 进 json.loads，第一行静默跳过）。GBK 控制台（`[实测]` 中文化 Windows）下 PS 传文本层还二次乱码——这正是"迭代日志 GBK 乱码 / 87B 缓冲"事故的根源之一。

**改成什么**：stream 由 `Start-Process -RedirectStandardOutput` 直写 —— claude.exe 原生句柄直写，**无 PS 文本层、无 BOM、无二次编码**（实测 Start-Process redirect 文件 first3bytes=`6C 69 6E`="lin"，即原始字节）。ralph 自己追加 KILLED 标记时改用 .NET 无 BOM 写：
```powershell
Add-RalphLog / 追加标记统一走:
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::AppendAllText($path, $text, $utf8NoBom)
```
读侧：`Get-Content -Raw -Encoding UTF8` 能正确吃 BOM，但若你自己解析 JSONL 用 python `open(..., encoding='utf-8-sig')` 更稳。

**改后收益**：stream 文件可被任何 JSONL 工具直接解析；日志不再乱码。

### B3【中高】心跳 180s vs 超长工具冲突，且没有"正在跑哪个工具"信号

**现在错在哪**：ralph 只按 stream/transcript 文件 mtime 判活，`HeartbeatStallSeconds=180`。一次全量 pytest/install 几分钟内 stream **不增长**（工具运行期间没有新事件，直到 `tool_result` 回来）→ 误杀。ralph 参数注释自己也承认这点。

**改成什么**：加"pending tool"判定 —— 解析 stream 尾部：最近一个 `assistant` 事件含 `tool_use`、且其后**没有**对应的 `user.tool_result` → 说明 Claude 正在等工具返回 → **放宽心跳到 `IterationTimeoutSeconds`**；只有"空闲（无 pending tool）且 mtime 停滞"才判卡死。因为 tool_use 与 tool_result 在 `assistant`/`user` 完整事件里都有（无需 partial），这是可靠的。

可直接抄的探针逻辑（扩充 trace_probe 或新函数）：
```python
def has_pending_tool(lines):
    saw_tool_use = False
    for line in lines:
        o = json.loads(line)
        if o.get("type") == "assistant":
            for c in (o.get("message") or {}).get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    saw_tool_use = True
        elif o.get("type") == "user":
            for c in (o.get("message") or {}).get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_result" and saw_tool_use:
                    saw_tool_use = False  # 简单近似：出现了 tool_result 即认为清空
    return saw_tool_use
```
心跳循环改为：
```powershell
$pending = uv run python scripts/trace_probe.py pending $streamFile   # 新子命令，返回 true/false
if ($pending) { $stallThreshold = $IterationTimeoutSeconds } else { $stallThreshold = $HeartbeatStallSeconds }
```
另外可把**进程存活**作为硬信号：`Get-Process -Id $pid2` 若已退出则立刻结束轮次（读 result 收尾）。

**改后收益**：长工具不再被误杀；卡死判定只在"确实空闲却无输出"时触发。

### B4【中高】transcript 定位竞态：mtime 猜文件会抓错会话

**现在错在哪**：`Get-LiveSessionJsonl` 在 `<slug>/*.jsonl` 里取 `mtime >= spawnIso` 的最新文件。同 slug 目录有**大量 jsonl**（实测 `E--manga-translator-agent-amta` 下数十个，含人类会话/历史迭代/子代理），且 transcript 异步 flush 会让**上一次迭代的旧文件**在"本次 spawn 之后"才收到最后一批写入 → mtime 被顶到 >= spawnIso → 抓错。后果：心跳兜底盯错文件、卡死诊断读到上一轮的 trace、COMPLETE 统计错会话。

**改成什么**：三选一（推荐 1+2 都做）：
1. **从 stream 文件解析 session_id**：第一行附近 `system/init.session_id`（实测每行都有 `session_id`，也可取任意行）。则 transcript 路径 = `Join-Path $TraceProjectsDir $slug "$session_id.jsonl"`，**零猜测**。
2. **spawn 时传 `--session-id <uuid>`**：`claude --help` (2.1.220) 确认存在（"Use a specific session ID … must be a valid UUID"）。ralph 每次迭代 `[guid]::NewGuid()` 生成并传参 → transcript 文件名先知。顺带可用 `--resume <uuid>` 跨迭代续上下文（见 C14）。
3. 若保留 mtime 启发式，至少把 slug 收敛到当前工作目录的 slug（`$env:CLAUDE_CONFIG_DIR\projects\E--manga-translator-agent-amta`），并过滤掉仍在增长中的人类会话（难以判断，故 1/2 更优）。

**改后收益**：诊断/stats/resume 永远指向本轮真实会话。

### B5【中】读大文件低效：`Get-Content -Raw` 每 30s 全量读 stream（已长到 MB 级）

**现在错在哪**：COMPLETE 检查用 `Get-Content $iterationLogFile -Raw` 全文读 + `-match`；DeepSeek 思考洪流下单轮 stream 可达数百 KB~MB（实测 760KB）。每 30s 全量读一次纯浪费，且 `Get-Content` 慢。

**改成什么**：只做**尾部增量扫描**：每次记住文件长度 offset，`[System.IO.File]::OpenRead` + Seek 到上次位置读新增字节，或直接让 python 探针做 `tail -c 200k` 检查 `<promise>COMPLETE</promise>` 与 last-tool。COMPLETE 信号应改从 `result` 事件解析（见 C13），grep 只作兼容兜底。

**改后收益**：心跳开销从 O(文件) 降到 O(增量)。

### B6【中】hook 配置/语义注释不准 + 真实"红 commit 门禁"应上移

**现在错在哪**：见 A5/0.7 —— hook_pretooluse.py docstring 把"deny 默认结束整轮"（prompt 型 hook 语义）当成 command hook 语义，且只靠 PreToolUse 字符串拦截 + `continueOnBlock`。PreToolUse **命令 hook 默认 600s 超时，超时不 block**（`[docs:hooks]`）；权限 deny/allow 规则优先级是 deny 先于 hook（hook `"allow"` 不能顶掉 deny 规则，`[docs:permissions]`）。

**改成什么**：把"fastcheck 未过不许 commit"的硬门禁从 PreToolUse 字符串拦截，升级为 **Stop hook exit 2**：Stop 每轮触发，exit 2 = "Prevents Claude from stopping, continues the conversation"（`[docs:hooks]` exit-2 表）。即"该收尾却 fastcheck 红 → 不让它停，逼它继续修"。这是官方机制里真正的"不让 agent 走"的旋钮，比"拦 commit 让 agent 自己决定要不要重试"更硬。可叠用：PreToolUse 拦 commit（返回 block+reason 喂回模型）+ Stop 兜底（fastcheck 红就不许停）。另外把 docstring 改成只陈述 command-hook 语义。

**改后收益**：质量门从"概率性拦一个动作"升级为"结构性卡住停止"。

### B7【中】`claude` 实为原生 exe + npm shim：spawn/杀进程的隐蔽坑

**现在错在哪**：ralph 假定 `claude` 是个普通命令。实测 `where claude` = `F:\npm-global\claude.cmd`（+ 无扩展名的 sh），内容为转发到 `node_modules\@anthropic-ai\claude-code\bin\claude.exe`（`[实测]`）。Start-Job 里 `& claude` 能跑（PS 解析 .cmd），但若改 Start-Process，`-RedirectStandardOutput` 要求 `-UseShellExecute:$false`，此时 .cmd 不能直接当 FilePath 跑 → 必须解析到 claude.exe（见 B1 代码）。另外钩子 shell 在 Windows 是 "Git Bash … or PowerShell when Git Bash isn't installed"（`[docs:hooks-guide]` L1024）——本机有 Git Bash，hook 命令经 Git Bash 跑，`py -3.13` 是否在 Git Bash PATH 里需验证（AMTA 已在用，大概率 OK）。

**改成什么**：B1 已给解析片段；写死前用 `Get-Command claude` 探测。附带：把 `-RedirectStandardError` 也独立落文件，别 `2>&1` 混进 stream（stream 必须纯净 JSONL）。

**改后收益**：spawn 层与进程模型完全确定。

### B8【中/已部分解决】Out-File 缓冲 vs mtime 心跳 —— 实证结论

- PS `2>&1 | Out-File` 是**对象管线按行**写，但 Start-Job 的 job 输出还有第二层缓冲（`Receive-Job` 才取回），这正是"日志只有 87B"的根因（job 被杀时管线缓冲未 flush）。
- **实测 probe 6**：claude 直写（stdout 重定向到文件，非 PS 管线）时文件**逐事件实时 flush**（5s 粒度看到持续增长），说明 `claude.exe` 侧每行 flush。
- `Start-Process -RedirectStandardOutput` 走 **OS 文件句柄**，完全绕过 PS 文本层 → 无乱码、无 BOM、Node/原生直写 UTF-8（实测实时可见 + 无 BOM）。**推荐**。
- 附带坑：redirect 文件被 claude 持续写时，**.NET `File.ReadAllText` 会抛共享冲突 IOException**（实测 sp_result2 连环报错），因默认 `FileShare.Read`；读侧要么用 `Get-Item .LastWriteTime`（不打开文件，最稳），要么 python `open()`（Windows 上默认共享读/写可开），要么显式 `FileShare.ReadWrite`。

### B9【低】`Get-LiveSessionJsonl` 依赖 `uv run python` 子进程，每 30s 一次 spawn 开销 + 失败静默

**现在错在哪**：`Invoke-TraceProbe` 每次起 `uv run python`（冷启动数百 ms）；失败时返回空数组被当"没找到"，吞错。若改成本地常驻 python（见 C12 SDK 版）或 PS 原生 `Get-Item` 直接看 mtime，可省这层。

**改成什么**：心跳主路径直接用 `(Get-Item $streamFile).LastWriteTime`（已有），把 trace_probe 降级为"仅在杀进程后诊断"调用一次。pending-tool 判定同样只在卡死边缘调用。

**改后收益**：心跳循环更轻、更少外部依赖。

---

## C) 北极星功能清单（backlog，标价值 / 做法 / 依赖）

### C12【北极星 0】用 Claude Agent SDK 换掉 shell 层

- **为什么值得**：官方 SDK（Python/TS）就是"把 claude 当子进程 + 给你结构化事件流"，event 模型与 CLI stream 同源（`[docs:sdk-ov]`：SDK "available as a library for Python and TypeScript only. To drive the same agent loop from another language, run the CLI as a subprocess"）。它原生给 `system/init(session_id)`、`AssistantMessage`、`ResultMessage`、`StreamEvent`、`HookEventMessage`，且支持 `resume`、`max_turns`、`can_use_tool`（权限回调）、`add_dirs`、`hooks`、`include_partial_messages`、`extra_args`（`[docs:sdk-py]` options dataclass）。ralph 现在"字符串/文件猜状态"的整层可被"官方事件流"替代。
- **大致怎么做**：`pip install claude-agent-sdk`，写 `ralph_loop.py`：`async for msg in query(prompt=..., options=ClaudeAgentOptions(allowed_tools=[...], permission_mode="dontAsk", max_turns=N, cwd=root, setting_sources=["user","project","local"]))`；按 `isinstance(msg, ResultMessage)` 拿收尾、`system/init` 拿 session_id、`AssistantMessage` 里扫 `tool_use` 做实时状态。`ClaudeSDKClient`（复用同一 session 多轮）或 `query(continue_conversation=True / resume=<id>)` 做跨轮（`[docs:sdk-py]`）。
- **成本**：中。要装 Python 包、把 ralph.ps1 外层逻辑迁进 Python；**收益**：消灭 mtime 猜心跳、BOM/编码/GDK 全部消失、直接拿 usage/cost、可做 per-tool 回调与熔断。注意：本机走 DeepSeek anthropic 端点（`ANTHROPIC_BASE_URL`），SDK 同样吃该 env，可用（`[实测]` 本机 claude 已这样路由）。
- **依赖**：官方 `claude-agent-sdk`（Python）。CLI `-p` 仍可当降级路径。

### C13【北极星 1】结构化收尾：`result` 事件替代 grep `<promise>COMPLETE</promise>`

- **为什么值得**：现在 grep 原始 stream 文本标记脆弱（模型可能把标记写进 thinking/中途、被截断、大小写变体）；而 `result` 事件是**机器可读收尾**：`is_error`、`terminal_reason`（`completed`/`aborted_*`/`max_turns`…）、`result`（最终文本）、`permission_denials`、`num_turns`、`total_cost_usd`（`[实测]` + `[docs:headless]`）。COMPLETE/BLOCKED/usage 全部结构化。
- **大致怎么做**：心跳/收尾解析器只在 stream 尾部等一个 `{"type":"result",...}`：`is_error=false && terminal_reason=="completed"` 且 `result` 内含 `<promise>COMPLETE</promise>` 才算 COMPLETE；`permission_denials` 非空 → 记 BLOCKED-by-permission；写 `ralph-log` 时把 `total_cost_usd/usage/num_turns` 一并落盘（每迭代成本核算 C17 的原料）。
- **依赖**：`-p --output-format stream-json`（2.1.220 已具）。

### C14【北极星 2】无头 session 连续性策略：每轮 fresh vs `--resume`

- **trade-off**：每轮 fresh（现状）= 无 context 污染、成本可控、状态全靠文件（符合 ADR-028 "progress lives in files"）；但每轮要重读 loop_state/重扫记忆，丢"轮内推理连续性"。`--resume <id>` 共享上下文 = 连续但会积累污染、token 上涨、且 **`claude -p --resume` 不会恢复原 permission mode**（`[docs:sessions]` permission-mode-on-resume 表：non-interactive resume 用"new -p run 的默认 mode"，需重传 `--permission-mode`）。
- **建议**：混合 —— 默认每轮 fresh；当 next_action 明确是"上一轮的子任务续作"时，用 `claude -p --resume <session_id> --output-format json "continue: <next_action>"` 省去重读文件。加 `--fork-session` 可在续作时开新 ID 防污染（`[docs:cli-ref]`）。resume 按 ID 跨项目查找需要 ≥2.1.223（`[docs:headless]`/`[docs:sessions]`；本机 2.1.220 只查当前项目目录 + worktree —— **版本差**，本机同目录 resume 可行，跨目录不行）。
- **依赖**：`--resume/--continue/--fork-session`、transcript 持久化（别开 `--no-session-persistence`）。

### C15【北极星 3】用 hooks 当"内层心跳/度量通道"

- **为什么值得**：PreToolUse/PostToolUse/Stop 每次工具调用/每步触发（`[docs:hooks]` cadence：tool 事件每工具一次；Stop 每轮一次），是"工人真实动作"的确定性信号，**比轮询 mtime 密度高几个量级**（工具级 vs 秒级文件戳），且不依赖 stream 文本。
- **大致怎么做**：在 `.claude/settings.json` 加一个**只写不拦**的 PreToolUse hook（command hook exit 0），把 `{ts, tool_name, tool_input.command/file_path, cwd}` append 到 `output/logs/worker-actions.jsonl`（用 `[System.IO.File]::AppendAllText` UTF-8 无 BOM 或 python）。ralph 心跳直接数这个文件的行增量；PostToolUse 记完成；Stop 记"整轮结束 + last_assistant_message"。hook stdin JSON 字段见 `[docs:hooks]` common input（`session_id/tool_name/tool_input/transcript_path/cwd`）。注意所有 command hook 默认 600s 超时、hook 间并行（`[docs:hooks-guide]`），写文件要快且不依赖彼此。
- **注意**：hook 是"会话内确定性侧信道"，但增加每工具一次进程 spawn 开销（`py -3.13` 冷启动 ~50-100ms）——用长驻服务或极轻脚本抵消。
- **依赖**：hooks 系统（2.1.220 已具，PreToolUse/PostToolUse 实测触发）。

### C16【北极星 4】权限/安全硬化 + "红 commit 门禁"官方做法

- **无头自主跑白名单**：推荐 `--permission-mode dontAsk` + `--allowedTools`（精确 git/uv/py 子命令）+ `--max-budget-usd` + 明确 `--disallowedTools "Bash(git push *) Bash(git merge *) Bash(rm *)"`（deny 规则优先于 allow，`[docs:permissions]`）。`dontAsk` 对不在 allow 或 read-only 集合的请求一律 deny（`[docs:permissions]` 模式表），可预测性最好。
- **红 commit 门禁官方做法**：PreToolUse 拦 commit 是"挡动作"；要让 agent **不得不继续修**，用 **Stop hook exit 2**（exit 2 on Stop = "Prevents Claude from stopping, continues the conversation"，`[docs:hooks]`）。即：fastcheck 红 → Stop hook 读 `loop_state.last_verified` 或现场跑快速 check → 红则 exit 2 + stderr 理由 → Claude 停不下来、被迫继续。配套的官方"结构化出口"是 agent hook（type:"agent" 跑工具验证，默认 60s，`[docs:hooks-guide]`），比 command hook 更能"看现场"。
- **版本差**：hook 里 permission_mode 字段 manual 到达时是 `"default"`（`[docs:hooks]`），别匹配 `"manual"`。

### C17【北极星 5】其它 backlog（一列）

1. **Live 活动仪表盘**：stream 逐 token/工具类型实时状态行。做法：解析 `assistant.tool_use.name` 与 `stream_event.content_block_start`，输出 `[Running Bash]` / `[streaming text…]`。SDK streaming-output 给了标准示例（"Build a streaming UI"，`[docs:sdk-stream]`）。价值：主人可肉眼看每轮在干嘛。
2. **每迭代 token 成本核算**：`result.total_cost_usd` + `usage`（实测字段）落 ralph-log；SDK 有专门 cost-tracking 页。价值：RALPH 跑一夜能出账单。
3. **错误工具连续 N 次熔断**：从 stream 里数 `tool_result.is_error==true` 连续次数 / 同签名工具重复调用（trace_probe stats 已算 repeated_calls）→ N 次即 kill 并 escalation。价值：防"修不好反复试同一招"空转。
4. **git diff 当进度信号**：每轮 spawn 前 `git rev-parse HEAD`，轮后 diff --stat 增量写 ralph-log；进度 = 代码树变化而非文本。价值：直接对应 ADR-028 哲学。
5. **任务计划定时触发**：Windows Task Scheduler 夜间跑 `ralph.ps1 -MaxIterations N`，配 `--max-budget-usd` + escalation 到 `ralph-log.md`。价值：夜间无人值守（ADR-028 下一步③）。
6. **`--fork-session`/`--session-id` 确定性会话**：见 B4/C14。
7. **`--output-format json` 轻量轮**：不需要实时看过程的轮（如"只跑 review 输出 VERDICT"）用 json 单结果 + `jq .result`，比 stream 省解析（`[docs:headless]`）。
8. **`--json-schema` 结构化结果**：让 agent 必须输出符合 schema 的 JSON（如完成回执），2.1.220 help 有 `--json-schema`；非法 schema 自 2.1.205 起报错（`[docs:headless]`）。

---

## D) 信号密度（第一性原理）

### D18. 工人真实状态 → 每种可观测信号 的密度对比

| 层 | 可观测信号 | 含的信息 | ralph 现状 | 实现成本 | 能早发现什么失败 |
|---|---|---|---|---|---|
| 0 | 最终文本 | 只"最终说了啥" | 抓 `<promise>COMPLETE</promise>` | 已有 | 几乎无 |
| 1 | stream_event 文本增量 | token 级"正在生成" | 开 partial 时文件里有，但没解析 | 低（tail 增量扫） | 模型卡在生成长文/死循环生成 |
| 2 | 工具调用（type+name+input） | "正准备跑什么" | 没解析（只在事后 trace stats） | 低（读 `assistant.tool_use`） | 跑偏工具、重复同一命令、工具序列异常 |
| 3 | 工具结果 `is_error` | "这步成没成" | 只在杀后诊断读 | 低中 | 连续失败/熔断、某工具系统性红 |
| 4 | usage/cost（`result`/`assistant.usage`） | "烧了多少 token/钱" | 只在 COMPLETE 后 stats | 低 | 预算失控、cache 失效导致 input 暴涨 |
| 5 | session 元数据（init/tools/mode/model/session_id） | "会话到底什么配置" | 没解析 | 低 | 配置漂移（model/mode 不对）、抓错会话 |

**结论**：ralph 现在只用到底层 0 + 事后 stats（层 0 的 grep + trace_probe stats），即**最低密度**——它只能回答"完没完/事后共调了几个工具"，回答不了"现在在干什么/是不是在空转/是不是在烧钱"。

**逐级提密度**：上到层 2（工具调用）实现成本≈"解析 stream 里 assistant.tool_use"，能早发现"agent 开始跑偏/重复同一命令"；上到层 3 能发现"某工具连续红"→ 熔断；层 4 直接给每迭代成本。**每提高一级，早失败的时间窗大约从"轮末"提前到"事件发生当下"**。当前卡死判定依赖层 1 的 mtime，改解析层 2 的 pending-tool（B3）即可消除"长工具误杀"。

### D19. 一页第一性原理重构：六个职责 vs 现状/北极星

| 职责 | 现在（ralph.ps1） | 北极星（SDK/stream 事件驱动） |
|---|---|---|
| 供应上下文 | prompt.md + memory_inject + ralph_context preamble 拼 argv | 同内容，但走 stdin 文件 / SDK `system_prompt`（无 argv 上限），session 元数据由 init 校验 |
| 观察进度 | 每 30s 轮询 stream mtime（层 1 的代理指标） | 事件驱动：每 `assistant.tool_use` 打点 + 每 `tool_result` 打点 + usage 记账（层 2/3/4） |
| 早失败 | 180s mtime 停摆 + 900s 墙钟倒计时 | pending-tool 感知（层 2）→ 长工具不误杀；连续 error N 次熔断（层 3）；`max_budget_usd` 硬顶 |
| 跨失败保状态 | kill 后 trace_probe tail 写 escalation → 下轮读文件续 | 同一目标，但用确定性 session_id + 可选 `--resume`；现场诊断用 `tail`/`--resume` 精确文件 |
| 质量门 | PreToolUse hook 拦 `git commit`（字符串拦截 + continueOnBlock） | Stop hook exit 2 结构性"不许停" + PreToolUse 拦 commit 双保险（层 0 之外的真门禁） |
| 终止 | grep `<promise>COMPLETE</promise>` / status=BLOCKED / MaxIterations | `result` 事件：`is_error`+`terminal_reason`+`permission_denials` 判定 COMPLETE/BLOCKED/FAILED；成本落账；空 commit 收尾 |

---

## E) 附录：实际查过的来源清单

**本机实测（2.1.220，claude.exe 原生，DeepSeek anthropic 端点）**
- `claude --version` → `2.1.220 (Claude Code)`；`claude --help`、`claude -p --help` 全量输出
- probe 1：`-p "Reply PONG" --output-format stream-json --verbose --include-partial-messages` → 27 事件，schema 全录
- probe 2：`stream-json` 缺 `--verbose` → `Error: … requires --verbose`（exit 1）
- probe 3：stdin 传 prompt（`< prompt3.txt`）→ 成功，exit 0
- probe 4：`stream-json --verbose`（无 partial）→ 仍见 system/init + assistant + result + thinking_tokens，无 stream_event
- probe 5：`--disallowedTools Bash` 强求跑 whoami → 模型不发起 Bash；3869 事件，thinking 占 ~99%（DeepSeek 特性）
- probe 6：长任务实时观察 → stream 文件逐事件增长（5s 粒度）；transcript 批写滞后 ~20s；transcript 名 == session_id
- probe A/B：`.claude/settings.json` PreToolUse command hook block → block+reason 喂回模型（`is_error` tool_result），loop 继续；`result.permission_denials` 记录被拒调用
- 本机事实：`where claude`→`F:\npm-global\claude.cmd`→转发 `…\claude-code\bin\claude.exe`；无 pwsh（PS 5.1）；`Out-File/Add-Content -Encoding utf8` 写 BOM（EF BB BF）；`Start-Process -RedirectStandardOutput` 无 BOM、实时、但 .NET ReadAllText 共享冲突
- Stop-Job 孤儿实证：Start-Job 内 Start-Process 子进程在 Stop-Job 后仍存活
- transcript schema：`E:\claude\.claude\projects\<slug>\<session_id>.jsonl`，逐行 JSON（user/assistant/attachment/system…）

**官方文档（WebFetch 全文/节选）**
- CLI reference：https://code.claude.com/docs/en/cli-reference （flag 语义表）
- Headless / print mode：https://code.claude.com/docs/en/headless.md （stdin、stream-json、退出码、SIGTERM、permission-prompts、10MB stdin cap、v2.1.211 Windows stdin fix）
- Hooks reference：https://code.claude.com/docs/en/hooks.md （超时默认、exit 2 语义、common input 含 transcript_path 异步警告、事件 cadence；JSON output/continueOnBlock 部分被截断，由下条补）
- Hooks guide：https://code.claude.com/docs/en/hooks-guide.md （L852 PreToolUse deny + continueOnBlock + "Before v2.1.210…"、agent/prompt/command hook 区别、hook shell 为 Git Bash）
- Sessions：https://code.claude.com/docs/en/sessions.md （transcript 存储路径、异步、--no-session-persistence、resume 语义、permission-mode-on-resume 表、v2.1.223 跨项目查找）
- Permissions：https://code.claude.com/docs/en/permissions.md （deny/allow 规则、dontAsk/auto/bypassPermissions、-p 下 hooks Used、read-only 命令集、规则优先级）
- Agent SDK overview：https://code.claude.com/docs/en/agent-sdk/overview.md （Python/TS、与 CLI 关系、能力表）
- Agent SDK Python：https://code.claude.com/docs/en/agent-sdk/python.md （query()/ClaudeSDKClient、ClaudeAgentOptions 全字段、resume/max_turns/can_use_tool、argv 长度警示、Transport）
- Agent SDK streaming-output：https://code.claude.com/docs/en/agent-sdk/streaming-output.md （StreamEvent schema、stream tool calls 示例）
- 文档索引：https://code.claude.com/docs/llms.txt

**二手（仅作线索，未当权威）**
- WebSearch 摘要：GitHub anthropics/claude-code issue #78527（v2.1.210 prompt 型 PreToolUse 回归：deny 停整轮，command hook 正常）；hooks-guide/hooks 的搜索摘要（continueOnBlock 行）
- AMTA 本地文件：`ralph.ps1`、`scripts/hook_pretooluse.py`、`scripts/trace_probe.py`、`docs/ralph-loop.md`、`docs/decisions/028-ralph-loop-autonomous-development.md`、`prompt.md`、`E:\claude\.claude\settings.json`、`E:\manga translator agent\amta\.claude\settings.json`

---

## 附：待本机实测清单（本报告拿不准/版本敏感处）

1. `--permission-mode dontAsk` 在本机 DeepSeek 端点的实际表现（本机 settings 是 `defaultMode:auto`，建议在 scratch 目录先试一轮）。
2. Stop hook 在 `-p` 2.1.220 是否每轮触发（本报告据 cadence 文档推断，未实跑）。验证：`.claude/settings.json` 加 Stop command hook 写文件，跑一轮 `-p`。
3. `--resume <session_id>` 同目录跨迭代续上下文（2.1.220 只查当前项目目录 + worktree，跨目录要 ≥2.1.223）。
4. `result.is_error` 在哪些失败下非 0 / exit code 非 0 的完整矩阵（本机只覆盖了成功与 flag 错误）。
5. command hook PreToolUse **exit 2** 是否也会把 reason 喂回模型继续（本机只实测了 exit 0 + decision JSON 路径）。
