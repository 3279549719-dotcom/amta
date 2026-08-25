# 依赖膨胀治理流程（可复用，ADR-015）

> 目标：在依赖进入仓库的**前一刻**拦截（vibe-check 式语义拦截）和**安装期**最小化（uv 严格解析），
> 让"本仓零/极低运行时依赖"从口头约定变成机械强制。
> 参考：[vibe-check-mcp](https://github.com/kesslerio/vibe-check-mcp)（拦截）、[uv](https://github.com/astral-sh/uv)（最小化解析）。

## 一、现状基线（审计结论）

- 全仓真实第三方依赖只有 2 个直接库：`requests`、`pillow`（+ 传递依赖 certifi/charset-normalizer/idna/urllib3）。
- 此前 `pyproject.toml` **没有 `[project]` 清单**、`uv.lock` 空且未入库 → 依赖声明缺失、不可复现、不可审计。
- 现状已修复：`pyproject.toml` 声明最小清单、`uv.lock` 固化最小闭包并入库、`scripts/depguard.py` 拦截。
- 工具链 `ruff/pyright/pytest` 走全局安装，不入 uv 管理（ADR-004）。

## 二、两道防线

### 防线 1：引入前拦截（vibe-check-mcp 式，语义 + 机械双层）

1. **语义层**：`.dsh/skills/dependency-guard/SKILL.md` 决策链
   加依赖前自问 → 标准库能实现？本地共享库能复用？有更轻替代？→ 确认需要才加并记理由。
2. **机械层**：`scripts/depguard.py`（`npm run depcheck`）
   自动扫 `src/scripts/tests` 的第三方 import，报：
   - **未声明**的第三方 import（要么补声明，要么改标准库）
   - **已声明但未用**的死依赖（删掉）
   已接入 `npm run fastcheck` 与 `.githooks/pre-commit` → 硬门禁，违反即拦 commit。

### 防线 2：安装期最小化（uv）

- `[project].dependencies` 只声明真实需要的库（锁定版本）。
- `uv.lock` 入库：联网 `uv lock` 重建（补哈希）、离线手写锁闭包 + 注释。
- `uv tree` 审查传递链，优先挑叶子小的库。
- `uv sync` 装进 `.venv`，与锁一致。

## 三、加依赖的完整流程（照此执行）

```bash
# 1. 走 dependency-guard 决策链（skill）—— 默认标准库，质疑一切新库
# 2. 进 pyproject.toml [project].dependencies（锁定版本）
# 3. 联网: uv lock        /  离线: 手写 uv.lock 闭包 + 注释
# 4. uv sync               # 装进 .venv
# 5. npm run depcheck      # 应通过（未声明/未使用 都会拦）
# 6. npm run fastcheck     # 全绿（compile+ruff+pyright+test+depguard）
# 7. pre-commit 自动兜底
```

## 四、日常检查命令

| 命令 | 作用 |
|---|---|
| `npm run depcheck` | 依赖膨胀守卫（未声明/未使用第三方依赖） |
| `npm run dep:tree` | 查看传递依赖树（`uv tree`），审查最小化 |
| `npm run fastcheck` | 编码期全量校验（含 depguard） |
| `npm run audit` | 周期熵审计（含依赖合理性人工检查） |

## 五、回归防护

- depguard 已进 fastcheck + pre-commit → 引入未声明/死依赖的 commit 会被拦。
- 审计（`npm run audit` + audit skill）含「新依赖是否合理」检查项。
- 新技能需登记进 `CLAUDE.md` 渐进式加载表；新 ADR 进 `docs/decisions/README.md` 索引。
