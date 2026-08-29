# 024 — 模块边界重构:几何/区域契约/配置接缝分立 + 包导出面契约化

## Context

- 2026-08-29 重构化简任务(Patrick 指定):模块清晰、接口分明、函数可复用、抽象合理,行为等价,过项目级 hook 审核。
- 重构前 `geometry.py` 12.6KB 混装三层职责:纯几何原语(bbox/iou/union)、detection 区域契约(build_regions/flatten_regions/mark_contained)、分类规则(assign_category/assign_sub_tier)。分类与 region 契约不是几何,是 ADR-019/Front3 Stage1 的契约语义。
- `get_chat_config`(CHAT_* 配置读取)住在 translate.py,但 06_page_judge/repair_failed/translate_semantic_check 不做翻译却依赖它——配置接缝与翻译编排耦合。
- `__init__.py` 声称"对外稳定接口"但 15 个模块缺席,导出面与事实不符,无测试保护。
- 00_run_all 的"产物存在→skip / 否则 timed run→span"同构样板重复 8 处。

## Decision

1. **regions.py 独立(必须)**:`build_regions/flatten_regions/mark_contained/absorb_contained/assign_category/assign_sub_tier` 及私有 `_area/_contained_in` 唯一归属 `amta/regions.py`;`geometry.py` 只留纯几何原语(bbox_from_block/iou/union_boxes/union_blocks),保留兼容 re-export 一版(勿新增实现)。消费方(01_detect/verify_flatten_fix/eval_flatten_fix_v2/tests)全部迁移到 `amta.regions` 新接口。
2. **chat_config.py 独立(必须)**:`get_chat_config/_ENV_PATH` 唯一归属 `amta/chat_config.py`;translate.py 保留 re-export——repair_failed 深度依赖 translate 模块属性访问(`translate.get_chat_config()`),其 monkeypatch 路径不受影响;06_page_judge/translate_semantic_check 迁移到新接口,对应测试 patch 同步指向 chat_config。
3. **包导出面契约化(必须)**:`__init__.py` 补齐全部 30 个模块导出,`__all__` = 事实接口清单;`tests/test_package_api.py` 冒烟锁定(导出面漂移即红)。
4. **pytest pythonpath 兜底(必须)**:pyproject `[tool.pytest.ini_options].pythonpath = ["src", "scripts"]`。pytest 9 下 worktree 场景(.git 是文件锚点弱化)conftest 链不可靠,官方 pythonpath 选项在 collection 前生效,新测试无需 `sys.path.insert` 样板。
5. **00_run_all _step 抽象(必须)**:8 处工位样板收敛为 `_step(log, run_id, step, page, inp, out, cmd)`;skip 判定/计时/span/print 单一归属;auto_repair/judge_repair 复杂分支保留原状。
6. **workstate import 提顶(顺手)**:4 处函数体内 `from amta.paths import ...` 提到模块顶部。
7. **砍掉不跟(复查撤销)**:原计划删除 `translate.record_failure`(grep 误报为 dead code)——复查发现 `03_translate.py:143` 真实调用,**保留**。教训:grep 输出为空须二次验证,不信单次管道结果。
8. **不做**:scripts/ 一次性实验脚本归档(涉及历史实验记录归属,单独决策);SuggestionsExtractor 迁移(无 scripts 调用方,拆分收益低于文件数熵成本)。

## Consequences

- 行为等价:289→291 passed(新增 package API 2 测),ruff/pyright/depguard 全绿;4 个 commit 均通过 pre-commit hook(fastcheck 复跑)。
- 模块边界:几何数值计算 / detection 区域契约 / CHAT 配置接缝 / 翻译编排四层分立,旧 import 路径经兼容层不断。
- 已知残留(后续可选):geometry 兼容 re-export 待未来版本移除;scripts/ 一次性脚本(eval_*/gen_report_*/backfill/diag/verify_*)约 10 个待归档决策;chat_client 与 ocr_engines 的 send_chat 有进一步合并空间(本轮未动)。
- worktree 环境备忘:basetemp 父目录需预建 output/logs;audit.find_duplicate_files 排除判断已改相对 parts(worktree 内路径不再被误杀,见 L28)。
