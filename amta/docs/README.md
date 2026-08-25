# docs — 知识导航

> 文档的唯一入口。按"职责"组织，避免每个 AI 都重新摸一遍。
> 核心分工（与 Harness 知识模型一致）：
> - **状态** → `progress.md`（项目现在在哪）
> - **经验/坑** → `lessons.md`（我们学到什么；坑的唯一归属）
> - **决策** → `decisions/`（为什么这样选）
> - **调研** → 本目录根部的 `01-04` 调研报告（历史资料）

## 目录结构（amta/）

```
amta/
├── AGENTS.md                 # 入口指针（指向 CLAUDE.md，避免双份漂移）
├── CLAUDE.md                 # 规范本体：核心事实 + 关键规则 + 渐进式加载（精简，坑→lessons）
├── README.md                 # 架构 / 引擎 DAG / 目录
├── package.json              # 脚本入口（映射真实脚本，不包 git/gh）
├── .dsh/skills/               # 按需加载技能（DSH 原生技能根：benchmark/koharu-drive/verify/cycle-close/audit/finisher/researcher/...）
├── .githooks/                # pre-commit / pre-push（Level 2/3 护栏）
├── src/                      # Python 执行器
├── scripts/                  # 运维 / 验证 / 审计（fastcheck/audit/smoke/start/precheck/install_hooks）
├── tests/                    # 确定性单测（不依赖引擎/网络）
├── context/                  # Story Memory 种子
├── models/                   # 模型权重（gitignore）
├── output/                   # 产物（部分 gitignore，仅白名单入库）
├── testsets/                 # 测试集（原图 gitignore）
└── docs/                     # ← 本目录
    ├── README.md             # 本导航
    ├── progress.md           # 项目状态
    ├── lessons.md            # 经验库（坑的唯一归属）
    ├── decisions/            # 架构决策 ADR（001~004）
    └── 01-04 调研报告         # 历史调研（可选：移入 research/ 子目录，见下）
```

## 各文件职责速查

| 文件 | 回答 | 何时更新 |
|---|---|---|
| `progress.md` | 项目现在在哪？ | 每次收尾（/finish） |
| `lessons.md` | 踩过什么坑、学到什么？ | 出现可复用经验时 |
| `decisions/` | 为什么这样选？ | 架构/方向变更时 |
| `dependency-governance.md` | 依赖膨胀治理流程（ADR-015） | 依赖治理相关时 |
| `CLAUDE.md` | Agent 必须知道并遵守什么？ | 出现稳定规则时（保持精简） |
| `.dsh/skills/` | 怎么做某事（流程/程序/委派）？ | 出现可复用流程时（按需加载） |

## 可选重组（需要 shell，本环境未执行）

当前 4 份调研报告（`01-04`）位于 `docs/` 根部。若想进一步收敛，可移入 `docs/research/`：

```powershell
New-Item -ItemType Directory -Force docs/research | Out-Null
Move-Item docs/01-*.md docs/02-*.md docs/03-*.md docs/04-*.md docs/research/
# 然后更新 CLAUDE.md 渐进式加载表中对应行
```

> 说明：本会话环境无 shell，未实际移动文件；仅在此给出目标结构与命令。
