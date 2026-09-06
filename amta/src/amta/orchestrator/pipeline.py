"""管线编排器 — run_pipeline() 唯一入口。

职责：遍历页面 → 遍历阶段 → 增量缓存判断 → 调用工位 → 日志追踪 → 错误处理。
不做的事：不关心每个工位内部做什么（那是工位的事），不关心产物内容（那是 artifacts 的事）。

增量构建（artifact_cache）：
- 每个阶段产物旁边存 .fingerprint 文件，记录输入文件+代码文件+配置的哈希
- 运行前对比指纹：一致 → 跳过（cache hit），不一致 → 重跑
- 比旧的"文件存在就跳过"更精准：改了代码/配置/输入会自动重跑，不会用陈旧产物

设计原则（codebase-design）：
- Depth（深度）：外部接口只有一个 run_pipeline(config) -> PipelineResult，内部藏着
  页面循环、阶段循环、缓存检测、上下文构建、日志、错误处理等复杂逻辑。
- Locality（局部性）：新增阶段不需要改这里，只需要在 registry 里注册 + 写工位适配器。
- Leverage（杠杆）：调用方只需要构造 PipelineConfig，不需要知道缓存怎么判断、
  上游产物怎么传递、日志怎么记录。
"""
from __future__ import annotations

import time
from pathlib import Path

from amta import artifacts
from amta.artifact_cache import compute_fingerprint, is_fresh, save_fingerprint
from amta.pipeline_log import PipelineLog
from amta.paths import ROOT
from amta.workstate import ensure_workspace

from .context import PipelineConfig, PipelineResult, StationContext, StationResult
from .registry import get_stage

# src/amta/ 目录 — code_files 都是相对于这个目录的路径
_SRC_DIR = ROOT / "src" / "amta"


def _resolve_page_list(config: PipelineConfig) -> list[tuple[int, str, Path]]:
    """把 start_page/end_page（原图序号）展开成 [(page_idx, page_key, raw_path)]。

    page_idx = 文件名 N（1 基，page_N ↔ N.jpg，与原图序号一致）
    不存在的图片跳过并打印警告。
    """
    pages = []
    for n in range(config.start_page, config.end_page + 1):
        raw_path = config.src_dir / f"{n}.jpg"
        if not raw_path.exists():
            print(f"[pipeline] WARN {raw_path} not found, skip page {n}")
            continue
        page_idx = n
        page_key = artifacts.page_key(page_idx)
        pages.append((page_idx, page_key, raw_path))
    return pages


def _build_context(
    config: PipelineConfig,
    page_idx: int,
    page_key: str,
    raw_path: Path,
    artifacts_dir: Path,
    state_dir: Path,
    stage_name: str,
    page_results: dict[str, StationResult],
) -> StationContext:
    """为某个阶段构建 StationContext。

    - inputs: 从该阶段的 consumes 声明中，查找上游阶段的 output_artifact
    - config: 合并 registry 中的 default_config 和 config.stage_configs 中的覆盖
    """
    stage = get_stage(stage_name)

    # 上游产物路径：从已完成的阶段结果中查找
    inputs = {}
    for dep_name in stage.consumes:
        dep_result = page_results.get(dep_name)
        if dep_result and dep_result.output_artifact:
            inputs[dep_name] = dep_result.output_artifact

    # 配置合并：默认配置 + 调用方覆盖
    merged_config = dict(stage.default_config)
    if stage_name in config.stage_configs:
        merged_config.update(config.stage_configs[stage_name])

    return StationContext(
        work_id=config.work_id,
        page=page_key,
        page_idx=page_idx,
        raw_image=raw_path,
        artifacts_dir=artifacts_dir,
        state_dir=state_dir,
        inputs=inputs,
        config=merged_config,
    )


def _stage_code_paths(stage_name: str) -> list[Path | str]:
    """把 StageSpec.code_files（相对路径）转成绝对路径列表。"""
    stage = get_stage(stage_name)
    return [_SRC_DIR / f for f in stage.code_files]


def _stage_input_files(ctx: StationContext) -> dict[str, Path | str]:
    """收集该阶段的所有输入文件：原始图片 + 上游产物。

    这些文件的哈希会存入 fingerprint，任何一个变了都会触发重跑。
    """
    input_files: dict[str, Path | str] = {"raw_image": ctx.raw_image}
    for dep_name, dep_path in ctx.inputs.items():
        input_files[dep_name] = dep_path
    return input_files


def _is_cache_fresh(
    stage_name: str,
    ctx: StationContext,
    output_path: Path,
) -> bool:
    """增量缓存判断：产物存在且指纹匹配（输入/代码/配置都没变）→ 可以跳过。

    比旧的 _artifact_exists（只看文件在不在）更精准：
    - 改了翻译代码 → translation 阶段自动重跑，下游 typeset 也跟着重跑
    - 改了排版代码 → typeset 自动重跑，上游不动
    - 只改了配置 → 对应阶段重跑
    """
    if not output_path.exists():
        return False
    input_files = _stage_input_files(ctx)
    code_files = _stage_code_paths(stage_name)
    config = ctx.config
    return is_fresh(output_path, input_files, code_files, config)


def _save_stage_fingerprint(
    stage_name: str,
    ctx: StationContext,
    output_path: Path,
) -> None:
    """工位执行成功后，保存当前指纹到 .fingerprint 文件。

    下次运行时对比这个指纹判断是否可以跳过。
    """
    input_files = _stage_input_files(ctx)
    code_files = _stage_code_paths(stage_name)
    config = ctx.config
    fingerprint = compute_fingerprint(input_files, code_files, config)
    save_fingerprint(output_path, stage_name, ctx.page, fingerprint)


def run_pipeline(config: PipelineConfig) -> PipelineResult:
    """编排器唯一入口 — 跑完整条管线。

    用法：
        result = run_pipeline(PipelineConfig(
            work_id="touhou-single-wing",
            src_dir=Path("D:/.../单翼停留之地"),
            start_page=11, end_page=20,
            stages=["detect", "ocr", "translate"],
            stage_configs={"ocr": {"engine": "hayai", "rule_filter": True}},
        ))

    增量构建：每个阶段产物旁边存 .fingerprint，输入/代码/配置没变就跳过。
    force_rerun=True 时忽略缓存全部重跑。

    后续加 inpaint/typeset：只需在 stages 列表里加名字，不需要改这个函数。
    """
    t_total = time.perf_counter()

    # 1. 初始化工作区
    ws_root = ensure_workspace(config.work_id)
    artifacts_dir = ws_root / "artifacts"
    state_dir = ws_root / "state"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    # 2. 初始化日志
    log = PipelineLog(state_dir / "pipeline_log.json")
    stages_str = ",".join(config.stages)
    run_id = log.start_run(
        trigger=f"pages {config.start_page}-{config.end_page} stages=[{stages_str}]"
    )

    # 3. 展开页面列表
    pages = _resolve_page_list(config)
    if not pages:
        log.fail_run(run_id, step="pipeline", page="?", reason="no valid pages found")
        return PipelineResult(
            run_id=run_id, work_id=config.work_id,
            pages=[], stages=config.stages,
            total_duration_s=round(time.perf_counter() - t_total, 2),
            failed_step={"page": "?", "stage": "pipeline", "reason": "no valid pages found"},
        )

    # 4. 主循环：页面 → 阶段
    all_results: dict[str, dict[str, StationResult]] = {}
    failed_pages: list[str] = []
    first_failure: dict | None = None

    for page_idx, page_key, raw_path in pages:
        page_results: dict[str, StationResult] = {}
        page_failed = False

        for stage_name in config.stages:
            stage = get_stage(stage_name)
            out_path = artifacts.artifact_paths(artifacts_dir, page_key).get(stage.produces)

            # 4a. 构建上下文（需要先有 ctx 才能做缓存判断，因为缓存需要 inputs/config）
            ctx = _build_context(
                config, page_idx, page_key, raw_path,
                artifacts_dir, state_dir, stage_name, page_results,
            )

            # 4b. 上游依赖检查：consumes 声明的阶段必须有成功产物
            missing_deps = [d for d in stage.consumes if d not in ctx.inputs]
            if missing_deps:
                result = StationResult(
                    page=page_key, stage=stage_name, status="failed",
                    error=f"上游阶段缺失: {missing_deps}（前序阶段可能失败或被跳过）",
                )
                page_results[stage_name] = result
                log.add_span(run_id, step=stage_name, page=page_key, status="failed",
                             detail={"error": result.error})
                print(f"[pipeline] {page_key} {stage_name} FAILED — {result.error}")
                page_failed = True
                if first_failure is None:
                    first_failure = {"page": page_key, "stage": stage_name, "reason": result.error}
                break

            # 4c. 增量缓存判断：不强制重跑 + 产物存在 + 指纹匹配 → 跳过
            if not config.force_rerun and out_path is not None and _is_cache_fresh(stage_name, ctx, out_path):
                result = StationResult(
                    page=page_key, stage=stage_name, status="skipped",
                    output_artifact=out_path, duration_s=0.0,
                    stats={"cache_hit": True},
                )
                page_results[stage_name] = result
                log.add_span(run_id, step=stage_name, page=page_key, status="skipped",
                             output=str(out_path), detail={"cache_hit": True})
                print(f"[pipeline] {page_key} {stage_name} cache hit (skipped)")
                continue

            # 4d. 调用工位
            print(f"[pipeline] {page_key} {stage_name} running...")
            result = stage.station(ctx)
            page_results[stage_name] = result

            # 4e. 执行成功 → 保存指纹（供下次增量判断用）
            if result.status == "ok" and out_path is not None and out_path.exists():
                _save_stage_fingerprint(stage_name, ctx, out_path)

            # 4f. 记录日志
            log.add_span(
                run_id, step=stage_name, page=page_key, status=result.status,
                input=str(ctx.inputs), output=str(result.output_artifact),
                detail=result.stats, duration_s=result.duration_s,
            )

            if result.status == "failed":
                print(f"[pipeline] {page_key} {stage_name} FAILED — {result.error}")
                page_failed = True
                if first_failure is None:
                    first_failure = {"page": page_key, "stage": stage_name, "reason": result.error}
                break
            else:
                print(f"[pipeline] {page_key} {stage_name} ok ({result.duration_s}s)")

        all_results[page_key] = page_results
        if page_failed:
            failed_pages.append(page_key)
            if not config.continue_on_error:
                log.fail_run(run_id, step=first_failure["stage"] if first_failure else "?",
                             page=page_key, reason=first_failure["reason"] if first_failure else "?")
                break

    # 5. 收尾
    if first_failure is None:
        log.end_run(run_id)

    total_duration = round(time.perf_counter() - t_total, 2)
    print(f"\n[pipeline] DONE run={run_id} pages={len(pages)} failed={len(failed_pages)} "
          f"duration={total_duration}s")

    return PipelineResult(
        run_id=run_id,
        work_id=config.work_id,
        pages=[p[1] for p in pages],
        stages=config.stages,
        results=all_results,
        total_duration_s=total_duration,
        failed_pages=failed_pages,
        failed_step=first_failure,
    )
