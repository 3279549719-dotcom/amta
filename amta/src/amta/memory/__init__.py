"""amta.memory — agent 记忆机制包（ADR-025）。

两层并存、职责分立：
- 项目记忆检索 v0（原 src/amta/memory.py → project_memory）：parse_index/search/read/add/stats/main，
  索引优先 + 全文兜底，读写 docs/INDEX.md（Stage 2-d 引入）。
- 记忆机制四层闭环（ADR-025）：estate（只读解析层）/ tools（检索核心）/ lint（检查引擎），
  服务 memory_* 工具族与 SessionStart 注入包。
"""
from amta.memory.project_memory import (  # noqa: F401
    INDEX_PATH,
    add,
    main,
    parse_index,
    read,
    search,
    stats,
)
