"""基准工装 COM 传输的启动契约。

COM 派发(进程内,无 spawn 噪声)由 invoke.ps1 包装脚本承载;默认执行策略下
`-File` 运行未签名脚本会被 UnauthorizedAccess 拦截(2026-10-27 验收运行实测),
因此包装命令必须显式携带 -ExecutionPolicy Bypass。
"""
import importlib.util
from pathlib import Path


def _load_benchmark():
    spec = importlib.util.spec_from_file_location(
        "benchmark_psd",
        Path(__file__).resolve().parents[1] / "scripts" / "benchmark_psd.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_com_wrapper_launches_with_execution_policy_bypass(tmp_path, monkeypatch):
    benchmark = _load_benchmark()
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)

        class Proc:
            stderr = None

            def poll(self):
                return None

        return Proc()

    monkeypatch.setattr(benchmark.subprocess, "Popen", fake_popen)
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "complete.txt").write_text("complete")  # run() 轮询第一圈即完成

    benchmark.run("#target photoshop\n", folder, "com")

    assert captured["args"][0] == "powershell.exe"
    assert "-ExecutionPolicy" in captured["args"]
    assert "Bypass" in captured["args"]
    assert "-File" in captured["args"]
