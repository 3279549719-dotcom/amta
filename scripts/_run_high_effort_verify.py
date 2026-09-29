import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.common.encoding import force_utf8_stdio  # noqa: E402

# Windows stdout 默认 cp936，DSH/管道按 UTF-8 读；本脚本大量输出中文，
# 必须走项目统一的 UTF-8 收口点，否则 agent 侧收到乱码。
force_utf8_stdio()

sys.path.insert(0, 'scripts')
from run_sdk_task import build_prompt, PROJECT_ROOT  # noqa: E402
from deepseek_harness import DeepSeekHarness  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

plan_path = PROJECT_ROOT / 'docs/superpowers/plans/2026-09-29-column-end-comma-high-effort-verify.md'
prompt = build_prompt(plan_path)
session_id = 'column-end-comma-verify-high'
output_dir = PROJECT_ROOT / 'workspace/sdk-runs' / session_id
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / 'prompt.md').write_text(prompt, encoding='utf-8')

print('=== High Effort 验证任务启动 ===')
print(f'Session: {session_id}')
print('Effort: high')
print(f'Prompt 长度: {len(prompt)} 字符')
print()

start = time.time()
with DeepSeekHarness(
    dsh_home=str(Path.home() / '.dsh'),
    cwd=str(PROJECT_ROOT),
    provider='deepseek-official',
    model='deepseek-v4-flash',
    reasoning_effort='high',
    max_tokens=49152,
) as harness:
    print('>>> DSH 已启动，high effort 执行中...')
    result = harness.run(prompt, session_id=session_id)

elapsed = time.time() - start
print()
print('=== 任务完成 ===')
print(f'耗时: {elapsed:.1f} 秒 ({elapsed/60:.1f} 分钟)')
print(f'finish_reason: {result.finish_reason}')
print()
print('--- 最终回复 ---')
print(result.final_response)

result_data = {
    'session_id': session_id,
    'effort': 'high',
    'finish_reason': result.finish_reason,
    'elapsed_seconds': elapsed,
    'final_response': result.final_response,
}
result_path = output_dir / 'result.json'
result_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'结果已保存到: {result_path}')
