# 2026-09-09 DSH 仪表盘读图指南（给"不会看"的自己）

> 配套 2026-09-09-harness-inventory-tracing.md。本文只解决一件事：
> **打开 DSH 后，点哪里、看什么，才能回答"AI 干了啥 / 用了哪个 skill / hook 生效没"。**
> 已核实环境：dsh 0.1.0-rc.7 全局已装、Node v22、Web UI = http://127.0.0.1:3080（`dsh web`）。

## 0. 先把三层搅在一起的东西分开（认知减负）

比喻：AI 是你雇的员工。
- **生产层**＝员工干的活（detect→ocr→translate→clean→report）。已跑通，先不动。
- **观测层**＝办公室监控（DSH 仪表盘 / trace）。**你现在只装、只看这一层。**
- **治理层**＝员工手册与工具架（CLAUDE.md、skill、hook、memory）。前两天盘点的是这层。
- **自动化层**＝把规矩改成不用盯也必然做（embedded/chained）。那是看完监控之后的事。

顺序铁律：**先点亮观测层 → 才看得出治理层哪些是摆设 → 最后做自动化。**
没监控就评估"员工守没守规矩"，必然越想越乱（前两天的沮丧来源）。

## 1. 关键前提：你在哪个 harness 派活，记录就进哪个仪表盘（互不连通）

| harness | 记录位置 | 谁在读 |
|---|---|---|
| DSH（dsh web，:3080） | `C:\Users\asus\.dsh\sessions\<工作区>\<id>\session.jsonl.zstd` | DSH 仪表盘 |
| Claude Code | `C:\Users\asus\.claude\projects\**\*.jsonl` | trace_probe.py |
| 豆包（当前对话） | 各自云端 | — |

**所以：要在 DSH 仪表盘看到 amta 的干活过程，必须在 DSH 里派活。**
现在 DSH 最新会话停在 2026-08-31，是因为那之后没用 DSH 跑过——不是仪表盘坏了。

## 2. 回到电脑前的 10 分钟最小动作（只做这一件，别扩散）

1. 浏览器开 http://127.0.0.1:3080（若没起：amta 目录下终端敲 `dsh web`）
2. 设置里填模型 API key；工作区选 `E:\manga translator agent\amta`
3. 派一个**低风险小任务**，例如：「读 CLAUDE.md，告诉我里面引用了多少个 skill」
4. **全程只盯中间的工具调用树（Trajectory）**，看它一步步怎么完成，先不记术语
5. 跑完再做下面 A–D 的对照查找

## 3. 问题 → 点哪里 → 看什么（读图对照表）

### A. AI 整体在干嘛 / 卡没卡（先只学这个）
- **哪看**：会话主区的「工具调用树 / Trajectory」。AI 每动一步多一个节点
  （Think=想、Pwsh/Bash=跑命令、Read=读文件、Edit=改文件…），点节点展开看输入参数+返回结果。
- **底部统计条**：轮数 / 步数 / 思考耗时 / 执行耗时 / 缓存命中率 / Token。
- 卡住判断：树长时间不长新节点、底部时间在走 = 卡在当前步；点开最后一个节点看它在等什么。

### B. 某个 skill 有没有被调用
- DSH 插件 `skill-badge` 已确认在插件树里：AI 加载 skill 时轨迹上会出现**技能徽章节点**。
- 铁证判据：skill 的本质是 AI 去读一份 `SKILL.md`。轨迹里出现
  `Read .dsh/skills/<名字>/SKILL.md` 的动作 = 这个 skill 真被用了；全程没出现 = 没用。
- 一周后要"命中次数排行榜"再写脚本解析 session.jsonl.zstd（事件流已全量落盘，不着急）。

### C. hook / 插件到底挂上没有（治"看起来有其实没有"）
- 不在会话界面，在**终端**：`dsh --profile web --dump-config`
- 输出里搜得到插件 id = 已挂载；搜不到 = 没生效。
- 已核实存在的关键插件：agent-instructions（记忆注入）、skill / skill-filesystem / skill-badge、
  session-stats、token-meter、repeat-tool-reminder（重复调用提醒）、session-log-download。
- 注意：Claude Code 的 SessionStart / UserPromptSubmit 是 CC 专有事件，DSH 里默认没有，
  要改成 DSH 的 Cordis 生命周期插件——**现在先不做，看熟仪表盘再说。**

### D. memory 到底注入了什么（验证早上的疑问）
- 插件 agent-instructions 每次把 CLAUDE.local.md 塞进上下文，这个动作在轨迹里是
  一个「上下文注入 / context injection」来源记录；按来源筛选即可看到它注了什么，
  不用再靠读代码猜。

### E. 事后翻旧账
- UI 内可对会话搜索 / 回放 / 分叉；原始事件流在第 1 节路径（zstd 压缩，UI 直接读，无需手动解压）。

## 4. 明确"现在不做"（防止又一次认知过载）
- 不迁移 Claude Code hook 到 DSH（等会看仪表盘之后）
- 不删任何 skill / 脚本（等一周真实命中数据）
- 不装 OTLP/外部遥测（session-telemetry-otel 默认 DISABLED，本地仪表盘已够，先不开）
- 不手动解 zstd、不改造 trace_probe（DSH 原生视图先够用）

## 5. 看完第一次后要回答自己的一个问题
> 盯着工具调用树看完一个完整小任务后：哪一步是它"自己会做"的，哪一步是"本该自动却要我提醒"的？
> 把后者记下来——那就是下一个该 embedded 的候选，且这次有轨迹为证，不再凭感觉。
