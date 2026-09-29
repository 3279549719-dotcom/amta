"""通过 deepseek-harness-sdk 启动自主任务。

用法:
    uv run python scripts/run_sdk_task.py --plan docs/superpowers/plans/2026-09-29-column-end-comma-fix.md --session-id column-end-comma-001

设计原则（The Bitter Lesson）:
    不自己写外层循环、不数轮数、不设时间预算。
    把目标和验收条件写进 prompt，让模型自己的 agent loop 决定何时停止。
    我们只在外面观测 JSONL 日志和最终结果。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 项目根目录（脚本在 scripts/ 下，根目录是上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from amta.common.encoding import force_utf8_stdio  # noqa: E402

# Windows stdout 默认 cp936，而 DSH/管道按 UTF-8 读；本脚本大量输出中文
# （任务启动信息、耗时、最终回复），必须走项目统一的 UTF-8 收口点，
# 否则 agent 侧读到的是乱码（tests/test_encoding.py 会拦）。
force_utf8_stdio()


def build_prompt(plan_path: Path) -> str:
    """根据计划文件构建给 DSH 的任务指令。"""
    plan_text = plan_path.read_text(encoding="utf-8")

    return f"""你是 AMTA 漫画翻译管线的自主开发 agent。请执行以下任务。

## 任务
修复竖排漫画中逗号/句号被断行算法推到列最底端的冗余标点问题。

## 详细计划
请先完整阅读计划文件，然后按计划中的 Task 顺序执行。

计划文件路径: {plan_path}

计划摘要:
{plan_text[:2000]}

...（完整计划请读取上述文件）

## 验收标准（必须全部满足）
1. column_end_pause_mask() 纯函数存在且有单元测试
2. 竖排渲染路径集成了列尾逗号清理，横排不受影响
3. 第4页 before/after 对比图存在，两个问题气泡的列尾逗号在 after 中消失
4. 至少另外 2 个页面验证改善
5. pytest tests/typeset/ 全部通过
6. pytest tests/ 无新增回归
7. REPORT.md 记录了根因、方案、验证结果、边界

## 严格边界（违反任何一条即视为失败）
- 不要手改最终译文或成品图冒充管线改善
- 不要修改翻译 prompt 或翻译后端
- 不要修改横排排版逻辑
- 不要处理句号/感叹号/问号的列尾问题（强终止符保留）
- 不要 git push，不要合并到 main
- 不要修改其他 worktree 或主项目目录
- 所有改动必须在当前 worktree (E:/amta-agent-loop) 内

## 工作方式
- 你可以自由读取项目代码、运行命令、写文件、跑测试
- 每完成一个 Task 就 git commit
- 遇到不确定的地方，在 REPORT.md 中诚实记录，不要猜测
- 全部验收标准满足后，写最终总结并停止
- 如果遇到无法解决的阻塞，诚实记录并停止，不要硬撑

开始执行。"""


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 SDK 启动 DSH 自主任务")
    parser.add_argument("--plan", required=True, help="计划文件路径（相对项目根目录）")
    parser.add_argument("--session-id", required=True, help="DSH session ID")
    parser.add_argument("--model", default="deepseek-v4-flash", help="模型名")
    parser.add_argument("--dsh-home", default=str(Path.home() / ".dsh"), help="DSH home 目录")
    args = parser.parse_args()

    plan_path = (PROJECT_ROOT / args.plan).resolve()
    if not plan_path.exists():
        print(f"错误: 计划文件不存在: {plan_path}", file=sys.stderr)
        return 1

    # 延迟导入，确保在 uv 环境中运行
    from deepseek_harness import DeepSeekHarness

    prompt = build_prompt(plan_path)
    print("=== 任务启动 ===")
    print(f"计划: {plan_path}")
    print(f"Session: {args.session_id}")
    print(f"模型: {args.model}")
    print(f"工作目录: {PROJECT_ROOT}")
    print(f"DSH Home: {args.dsh_home}")
    print(f"Prompt 长度: {len(prompt)} 字符")
    print()

    output_dir = PROJECT_ROOT / "workspace" / "sdk-runs" / args.session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存 prompt 供事后审计
    (output_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    start_time = time.time()

    try:
        with DeepSeekHarness(
            dsh_home=args.dsh_home,
            cwd=str(PROJECT_ROOT),
            provider="deepseek-official",
            model=args.model,
            reasoning_effort="max",
        ) as harness:
            print(">>> DSH 已启动，开始执行（harness.run() 会跑到 agent idle 才返回）...")
            print()

            result = harness.run(prompt, session_id=args.session_id)

            elapsed = time.time() - start_time
            print()
            print("=== 任务完成 ===")
            print(f"耗时: {elapsed:.1f} 秒")
            print(f"finish_reason: {result.finish_reason}")
            print(f"final_response 长度: {len(result.final_response)} 字符")
            print()
            print("--- 最终回复 ---")
            print(result.final_response)
            print()

            # 保存结果
            result_data = {
                "session_id": args.session_id,
                "plan": str(plan_path),
                "model": args.model,
                "finish_reason": result.finish_reason,
                "elapsed_seconds": elapsed,
                "final_response": result.final_response,
                "event_count": len(result.events) if hasattr(result, "events") else None,
            }
            (output_dir / "result.json").write_text(
                json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"结果已保存到: {output_dir / 'result.json'}")

            if result.finish_reason != "completed":
                print(f"\n警告: finish_reason 是 {result.finish_reason}，不是 completed")
                print("可能是触达了 max-tokens 或出错，请检查 JSONL 日志")
                return 2

            return 0

    except Exception as e:
        elapsed = time.time() - start_time
        print("\n=== 任务异常 ===")
        print(f"耗时: {elapsed:.1f} 秒")
        print(f"异常: {type(e).__name__}: {e}")
        (output_dir / "error.txt").write_text(str(e), encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(main())
