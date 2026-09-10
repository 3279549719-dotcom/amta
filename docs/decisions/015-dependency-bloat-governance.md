# ADR-015：依赖膨胀治理——vibe-check 式拦截 + uv 最小化解析

**状态**：已采纳

## 背景

仓库源码实际只用 `requests` + `pillow` 两个第三方库，但此前 `pyproject.toml` 只有 lint 配置，
**没有 `[project]` 依赖清单**，`uv.lock` 是空的且未入库。结果：
- 依赖「声明」缺失 → 环境不可复现、传递依赖不可审计。
- 没有任何机制在「引入第三方依赖」这个动作上拦截 → 依赖膨胀源头未设防。

## 决策

从两条线治理依赖膨胀（对应两个参考工具）：

### 1. vibe-check-mcp 式拦截（引入前拦截）
在 AI/开发准备引入第三方库解决小任务时主动打断："能否用原生/标准库实现？"
落地两层：
- **语义层** `.dsh/skills/dependency-guard/SKILL.md`：硬性决策链（标准库优先 → 复用本地共享库 → 轻量替代 → 记理由）。
- **机械层** `scripts/depguard.py`（`npm run depcheck`）：扫 `src/scripts/tests` 第三方 import，
  拦截「未声明」和「已声明未使用（死依赖）」，接入 `fastcheck` 与 `.githooks/pre-commit` 硬门禁。

### 2. uv 最小化解析（安装期最小化）
- `pyproject.toml` 补上真实的 `[project]` + `[project].dependencies`，只声明真正用到的 `requests`、`pillow`（锁定版本）。
- `uv.lock` 入库并固化最小闭包（requests + pillow 及其传递依赖）；联网时用 `uv lock` 重建补哈希。
- 工具链（ruff/pyright/pytest）**不入 uv 管理**，走全局安装（延续 ADR-004 轻量原则）。

## 后果 / 约束

- 加任何第三方依赖前必须走 dependency-guard 决策链；`npm run depcheck` 是硬门禁（pre-commit 会拦）。
- 运行时依赖上限极小（当前 2 个直接依赖），新增需有理由记录。
- `uv.lock` 需随依赖变化同步更新；离线环境手工维护锁闭包并注释。
- 本仓零/极低运行时依赖原则由「语义 skill + 机械 depguard + pre-commit」共同强制，不再是口头约定。
