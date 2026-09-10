---
name: dependency-guard
description: 依赖膨胀守卫（ADR-015）。当任务可能引入第三方依赖、或代码中出现新的 import 时加载——在动手加依赖前先自问"能否用原生/标准库实现"，拦截依赖膨胀源头。配合 scripts/depguard.py 机械扫描（npm run depcheck / fastcheck / pre-commit）。
---

# Dependency Guard（依赖膨胀守卫）

> 灵感：kesslerio/vibe-check-mcp —— 在 AI 准备引入一个第三方库解决很小任务时主动打断：
> "是否可以用原生代码实现，避免新增依赖？"。本项目用「skill 语义拦截 + depguard.py 机械门禁」落地。

## 触发时机

- 你要给 `src/`、`scripts/`、`tests/` 新增任何第三方 import 之前。
- 你准备在 `pyproject.toml` 的 `[project].dependencies` 里加东西。
- 你发现代码里 import 了某个库但不确定它是否必要。
- 任何"这个功能要不要引个库？"的念头出现时。

## 硬性决策链（每次加依赖前走一遍）

1. **能否用标准库实现？** 先答这个。Python 标准库覆盖面很大：`json/os/re/pathlib/difflib/urllib/csv/zipfile/xml/statistics/math/itertools`。
   - 小任务（解析、格式化、简单计算、HTTP GET）→ 默认标准库，**不要**引库。
   - 本项目当前唯一被认可的直接依赖：`requests`（HTTP）、`pillow`（图像）。其余一律先质疑。
2. **这个库是不是重复轮子？** 仓库里 `src/amta/` 已有共享库（metrics/geometry/images/evalkit...），先复用。
3. **真需要 → 再问三个子问题：**
   - 有没有更轻量的替代（树更小、纯 Python、无重依赖）？
   - 能否只在局部用（不提升为全局运行时依赖）？
   - 传递依赖有多重？（用 `uv tree` 看，尽量挑叶子小的）
4. **最终决策：** 只有标准库确实无法承担、且替代方案都更重时，才允许新增，且：
   - 进 `[project].dependencies` 并锁定（`uv add <pkg>` 或手写 + `uv lock`）。
   - 在 `docs/decisions/` 记一句为什么（防复发）。
   - 跑 `npm run depcheck` 确认通过。

## 机械层（自动拦截，无需你记）

- `npm run depcheck`（scripts/depguard.py）：扫 `src/scripts/tests` 的第三方 import，
  - **未声明**的第三方 import → 报错（要么补声明并审视，要么改标准库）。
  - **已声明但没用**的死依赖 → 报错（删掉）。
  - 已接进 `fastcheck` 与 `.githooks/pre-commit`，是硬门禁。

## 加依赖的标准动作

```
# 1. 走上面的决策链
# 2. 进 pyproject.toml [project].dependencies（锁定版本）
# 3. uv lock（联网）重建 uv.lock；离线则手写锁 + 注释
# 4. uv sync 装进 .venv
# 5. npm run depcheck   # 应通过
# 6. npm run fastcheck  # 全绿
```

## 反模式（直接拒绝）

- 为「转置一个字符串」「读一行文件」「求个百分比」这种小事引库。
- 为了「少写 3 行」引一个带 50 个传递依赖的重库。
- 把 `pytest`/`ruff`/`pyright` 这类工具链混进运行时 `dependencies`（走全局安装，ADR-004）。
