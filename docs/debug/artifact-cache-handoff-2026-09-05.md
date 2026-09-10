# Artifact Cache 增量构建 — 交接文档

**日期**: 2026-09-05
**分支**: feat/artifact-cache-incremental-build-v2（注：因 .git 目录权限问题，代码在当前分支上，需手动创建分支并提交）

## 模块功能摘要

实现了基于内容哈希的工件缓存机制，解决"每次改代码都要从头重跑整个 pipeline"的问题。核心原理：每个 artifact 旁边存一个 `.fingerprint` 文件，记录输入文件哈希、代码文件哈希、配置参数哈希。运行前计算当前指纹，与已存指纹对比，一致则跳过。

## 新增/修改文件

| 操作 | 文件 | 说明 |
|---|---|---|
| 新增 | `src/amta/artifact_cache.py` | 核心缓存模块（236 行） |
| 新增 | `tests/test_artifact_cache.py` | 11 个单元测试 |
| 修改 | `src/amta/artifacts.py` | 新增 `fingerprint_paths()` 辅助函数 |
| 新增 | `examples/use_artifact_cache_typeset.py` | 排版阶段接入示范脚本 |
| 新增 | `docs/debug/artifact-cache-design.md` | 设计文档 |

## 核心 API

```python
from amta.artifact_cache import run_stage_if_needed

result = run_stage_if_needed(
    stage_name="typeset",
    page="page_11",
    input_files={"canon": canon_path, "translation": trans_path},
    code_files=["typeset_engine.py", "typeset_render.py"],
    config={"font_max": 52},
    output_path=typeset_path,
    generate_fn=lambda: run_typeset(...),
)
# result["cache_hit"] == True → 跳过
# result["cache_hit"] == False → 执行了
```

## 函数清单（12 个）

1. `compute_file_hash(path)` — sha256 文件哈希
2. `compute_code_hash(code_files)` — 多代码文件合并哈希（顺序无关）
3. `compute_config_hash(config)` — 配置字典哈希
4. `compute_fingerprint(input_files, code_files, config)` — 完整指纹
5. `fingerprint_path(output_path)` — .fingerprint 文件路径
6. `save_fingerprint(output_path, stage, page, fingerprint)` — 保存指纹
7. `load_fingerprint(output_path)` — 加载指纹（不存在返回 None）
8. `is_fresh(output_path, input_files, code_files, config)` — 检查是否新鲜
9. `run_stage_if_needed(...)` — 条件执行封装（主入口）
10. `invalidate_cache(output_path)` — 删除单个指纹，强制重跑
11. `invalidate_cache_for_page(art_dir, page)` — 删除某页所有指纹
12. `cache_status(art_dir)` — 统计缓存状态

## 测试结果

- **新增测试**: 11 个，全部通过
- **全量回归**: 401 passed, 3 failed（onnxruntime 相关已有环境问题）, 3 skipped
- **示范脚本验证**:
  - 第一次运行：2 CACHE MISS（执行排版）
  - 第二次运行：2 CACHE HIT（跳过排版）
  - 修改代码文件后：CACHE MISS（自动重跑）

## 示范脚本路径

`examples/use_artifact_cache_typeset.py`

运行方式：
```bash
uv run python examples/use_artifact_cache_typeset.py --pages 11 12
```

## 后续接入其他阶段的指引

### Detection 阶段
```python
run_stage_if_needed(
    stage_name="detection",
    page=page,
    input_files={"raw_image": raw_img_path},
    code_files=["detect_station.py", "detect_rtdetr.py"],
    config={"conf_threshold": 0.5},
    output_path=paths["detection"],
    generate_fn=lambda: run_detection(...),
)
```

### Translation 阶段
```python
run_stage_if_needed(
    stage_name="translation",
    page=page,
    input_files={"canon": paths["canon"]},
    code_files=["translate.py", "translate_station.py", "glossary.py"],
    config={"model": "gpt-4o", "temperature": 0.3},
    output_path=paths["translation"],
    generate_fn=lambda: run_translation(...),
)
```

### Inpaint 阶段
```python
run_stage_if_needed(
    stage_name="inpaint",
    page=page,
    input_files={"canon": paths["canon"], "raw_image": raw_img_path},
    code_files=["inpaint_station.py", "inpaint_strategy.py", "local_lama_inpainter.py"],
    config={"lama_steps": 50},
    output_path=paths["inpaint"],
    generate_fn=lambda: run_inpaint(...),
)
```

## 依赖传播机制

修改上游阶段会自动导致下游阶段缓存失效：
- 改了 `translate.py` → `translation.json` 重跑 → typeset 的输入变了 → typeset 也重跑
- 改了 `typeset_engine.py` → 只有 typeset 重跑，上游都跳过

## 遗留问题

1. **Git 权限**: `.git` 目录有系统级写入保护，无法执行 `git add/commit/checkout -b`。需要用户手动执行：
   ```bash
   git checkout -b feat/artifact-cache-incremental-build-v2
   git add src/amta/artifact_cache.py tests/test_artifact_cache.py src/amta/artifacts.py examples/use_artifact_cache_typeset.py docs/debug/artifact-cache-design.md docs/debug/artifact-cache-handoff-2026-09-05.md
   git commit -m "feat: artifact_cache增量构建模块（哈希指纹+条件执行+缓存管理）"
   ```

2. **临时文件**: 需清理 `test_results.txt`、`examples/demo_artifacts/`、`.pytest_tmp/`

3. **onnxruntime**: 3 个测试失败是已有环境问题（缺少 onnxruntime 模块），与本次改动无关
