# Artifact Cache 增量构建 — 设计文档

## 问题
每次修改 pipeline 任一阶段的代码，都需要从头重跑整个 pipeline（detection → OCR → translation → inpaint → typeset），即使只改了排版引擎。LLM 调用耗时且花钱。

## 解决方案
基于内容哈希的增量构建（参考 Make/Snakemake/doit）：
- 每个 artifact 旁边存一个 `.fingerprint` 文件
- 指纹记录：输入文件哈希 + 代码文件哈希 + 配置哈希
- 运行前计算当前指纹，与已存指纹对比
- 一致 → 跳过，直接用已有 artifact
- 不一致 → 重跑该阶段，保存新指纹

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

## 函数清单
| 函数 | 职责 |
|---|---|
| `compute_file_hash(path)` | sha256 文件哈希 |
| `compute_code_hash(code_files)` | 多代码文件合并哈希（顺序无关） |
| `compute_config_hash(config)` | 配置字典哈希 |
| `compute_fingerprint(input_files, code_files, config)` | 完整指纹 |
| `fingerprint_path(output_path)` | .fingerprint 文件路径 |
| `save_fingerprint(output_path, stage, page, fingerprint)` | 保存指纹 |
| `load_fingerprint(output_path)` | 加载指纹（不存在返回 None） |
| `is_fresh(output_path, input_files, code_files, config)` | 检查是否新鲜 |
| `run_stage_if_needed(...)` | 条件执行封装 |
| `invalidate_cache(output_path)` | 删除单个指纹，强制重跑 |
| `invalidate_cache_for_page(art_dir, page)` | 删除某页所有指纹 |
| `cache_status(art_dir)` | 统计缓存状态 |

## 依赖传播
修改上游阶段会自动导致下游阶段缓存失效：
- 改了 translation.py → translation.json 重跑 → typeset 的输入变了 → typeset 也重跑
- 改了 typeset_engine.py → 只有 typeset 重跑，上游都跳过

## 文件结构
```
artifacts/
├── page_11_canon.json
├── page_11_canon.json.fingerprint   ← 新增
├── page_11_translation.json
├── page_11_translation.json.fingerprint  ← 新增
├── page_11_typeset.json
└── page_11_typeset.json.fingerprint  ← 新增
```

## 管理工具
- `invalidate_cache(output_path)` — 删除单个指纹，强制重跑
- `invalidate_cache_for_page(art_dir, page)` — 删除某页所有指纹
- `cache_status(art_dir)` — 统计缓存状态

## 参考项目
- Make — 经典构建工具，基于文件修改时间
- doit (pydoit) — Python 任务自动化，基于文件哈希
- Snakemake — 生物信息学流水线，DAG + 增量构建
- DVC — ML 实验版本控制，pipeline + 数据版本
