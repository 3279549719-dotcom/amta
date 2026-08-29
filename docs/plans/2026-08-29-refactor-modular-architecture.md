# 重构计划:模块边界化简(refactor/modular-architecture)

> 基线:`feature/context-semantic-transfer` @ ee907b6。等价重构(行为不变),现有 216+ 测试与 fastcheck 为安全网。

## 目标

模块清晰、接口分明、函数可复用、抽象合理。四项全部以"单一归属 + 显式接口"落地,不做行为变更。

## 范围(P0)

### R1 geometry 拆层(混合职责 → 纯几何 / 区域契约两层)

现状:`geometry.py` 12.6KB 混装三件事——纯几何原语(bbox/iou/union)、区域构建契约(build_regions/flatten_regions/mark_contained)、分类规则(assign_category/assign_sub_tier)。分类与 region 契约不是几何。

- 新建 `src/amta/regions.py`:`_area`/`_contained_in`/`absorb_contained`/`mark_contained`/`assign_category`/`assign_sub_tier`/`build_regions`/`flatten_regions`(实现唯一归属)
- `geometry.py` 保留:`bbox_from_block`/`iou`/`union_boxes`/`union_blocks` + 兼容 re-export(deprecated 注释,docstring 标注唯一归属)
- 消费方迁移到新接口:`scripts/01_detect.py`、`scripts/verify_flatten_fix.py`、`scripts/eval_flatten_fix_v2.py`、`tests/test_shared_lib.py`、`tests/test_front3_stage1.py`

### R2 00_run_all 消重(8 处复制的 step 样板 → 一个抽象)

现状:每个工位都是 "产物存在→log skipped / 否则 timed `_run_cli`→log ok" 的同构代码,重复 8 次。

- 抽 `_step(log, run_id, step, page, out, cmd)` 辅助:统一 skip 判定、计时、span 记录、print 格式
- 行为不变,`tests/test_runall_typeset.py` 兜底

### R3 chat_config 独立(配置读取 ≠ 翻译编排)

现状:`get_chat_config`(.env 手工解析)住在 `translate.py`,但 06_page_judge/repair_failed/translate_semantic_check 都不翻译却依赖它。

- 新建 `src/amta/chat_config.py`:`get_chat_config` + `_ENV_PATH`(实现唯一归属)
- `translate.py` re-export(兼容 `tests/test_repair_failed.py` 的 `repair_failed.translate.get_chat_config` monkeypatch)
- scripts 消费方迁移:`06_page_judge.py`/`repair_failed.py`/`translate_semantic_check.py`
- 同步 monkeypatch 测试路径

### R4 包接口补全(__init__ 导出面 = 事实上的公共 API)

现状:`__init__.py` 声称"对外稳定接口",但 14 个新模块(canon_schema/glossary/tickets/regions 等)缺席。

- 补全 import + `__all__`
- 新增 `tests/test_package_api.py`:遍历 `amta.__all__` 断言可访问(接口冒烟)
- `tests/conftest.py` 统一 src/scripts sys.path 兜底(存量测试文件不动)

### R5 杂味清理

- `workstate.py`:函数体内 `from amta.paths import ...` 提到模块顶部
- `translate.py`:`record_failure` 全仓无调用方(grep 实证)→ 删除 dead code
- `translate.py`:两个重复的 HTTP 代理薄壳 `text_chat`/`chat_with_tools` 若仅 re-export 价值,评估收敛(保守:保留签名,内部单行直通)

## 不做(明确出圈)

- `scripts/` 一次性实验脚本(eval_*/gen_report_*/backfill/diag/verify_*)清理与归档:涉及历史实验记录归属,单独决策
- `SuggestionsExtractor` 迁移:无 scripts 调用方,拆分收益低于文件数熵成本
- 任何行为/prompt/引擎 DAG/契约变更

## 验收标准

1. `py -3.13 scripts/fastcheck.py` 全绿(compile + ruff + pyright + pytest + depguard)
2. `git commit` 通过 pre-commit hook(项目级 hook 审核 = fastcheck 复跑)
3. 每个重构步骤独立 commit,可回溯可回滚
4. 旧 import 路径(geometry.*、translate.get_chat_config)经兼容层不断

## 风险与已知坑

- **L27 脱敏坑**:OpenClaw 工具输出把 `api_key=` 赋值脱敏为 `***`,读写代码后必须校验真实内容
- **basetemp 父目录**:worktree 需预建 `output/logs/`(已修,pytest 不自建父目录链)
- **monkeypatch 字符串路径**:改 import 时同步受影响测试,否则 patch 静默失效
