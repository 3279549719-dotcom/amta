"""Controlled Photoshop exports from frozen real-page inputs (local artifacts only).

Example: --inputs output/.../inputs.json --jsx-source output/.../baseline_psd_jsx.py
         --output output/.../baseline --repeat 5
Input manifest: [{"page": 3, "clean": "absolute path", "typeset": "absolute path"}].
Never starts translation, overwrites a run, or closes an existing Photoshop process.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.typeset.psd_export import find_photoshop_executable


def instrument(script: str, events: Path, history: bool = False) -> str:
    header = """
function benchMark(label) {
 var f = new File(EVENT_PATH);
 if (f.open('a')) { f.writeln('{"event":"' + label + '","epoch_ms":' + new Date().getTime() + '}'); f.close(); }
}
benchMark('script_start');
var benchRuler = app.preferences.rulerUnits;
var benchType = app.preferences.typeUnits;
var benchDoc = app.documents.length ? app.activeDocument : null;
""".replace("EVENT_PATH", json.dumps(events.as_posix()))
    script = script.replace("#target photoshop", "#target photoshop\n" + header)
    script = script.replace("doc = app.open(inputFile);",
                            "doc = app.open(inputFile); benchMark('open_end');")
    script = script.replace("var inputFile = new File(", "benchMark('open_start'); var inputFile = new File(")
    script = re.sub(r"(// 文字层 (\d+):[^\n]*)",
                    lambda m: m[1] + f"\nbenchMark('layer_{m[2]}_start');", script)
    script = re.sub(r"(var ti(\d+) = tl\d+.textItem;)",
                    lambda m: f"benchMark('layer_{m[2]}_created');\n" + m[1], script)
    script = re.sub(r"(ti(\d+).leading = [^;]+;)",
                    lambda m: m[1] + f"\nbenchMark('layer_{m[2]}_styled');", script)
    script = script.replace("var psdFile = new File(", "benchMark('layers_end'); var psdFile = new File(")
    script = script.replace("doc.saveAs(psdFile, psdOptions, true);",
                            "benchMark('save_start'); doc.saveAs(psdFile, psdOptions, true); benchMark('save_end');")
    script = script.replace("doc.close(SaveOptions.DONOTSAVECHANGES);",
                            "doc.close(SaveOptions.DONOTSAVECHANGES); benchMark('close_end');")
    if history:
        start = script.index("    // 文字层")
        end = script.index("benchMark('layers_end');")
        layers = script[start:end]
        script = script[:start] + "function benchLayers() {\n" + layers + "\n}\ndoc.suspendHistory('PSD export', 'benchLayers()');\n" + script[end:]
    script += """
app.preferences.rulerUnits = benchRuler;
app.preferences.typeUnits = benchType;
if (benchDoc) { try { app.activeDocument = benchDoc; } catch(e) {} }
benchMark('script_end');
"""
    return script


def summarize(events: list[dict], start_ms: float, wall: float) -> dict:
    marks = {e["event"]: e["epoch_ms"] for e in events}
    def delta(a: str, b: str) -> float | None:
        return round((marks[b] - marks[a]) / 1000, 4) if a in marks and b in marks else None
    starts = [e for e in events if re.fullmatch(r"layer_\d+_start", e["event"])]
    return {
        "wall_seconds": round(wall, 4),
        "handoff_seconds": round((marks["script_start"] - start_ms) / 1000, 4) if "script_start" in marks else None,
        "open_seconds": delta("open_start", "open_end"),
        "layers_seconds": delta(starts[0]["event"], "layers_end") if starts else None,
        "save_seconds": delta("save_start", "save_end"),
    }


def run(script: str, folder: Path, transport: str, timeout: int = 300) -> dict:
    jsx = folder / "export.jsx"
    jsx.write_text(script, encoding="utf-8-sig")
    start = time.time()
    monotonic_start = time.perf_counter()
    if transport == "cli":
        executable = find_photoshop_executable()
        if not executable:
            raise RuntimeError("Photoshop not found")
        proc = subprocess.Popen([executable, "-r", str(jsx)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        wrapper = folder / "invoke.ps1"
        wrapper.write_text("param([string]$ScriptPath)\n$ErrorActionPreference='Stop'\n"
                           "$app=New-Object -ComObject Photoshop.Application\n$app.DoJavaScriptFile($ScriptPath)\n",
                           encoding="utf-8-sig")
        proc = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(wrapper), str(jsx)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        if (folder / "error.txt").exists():
            error = (folder / "error.txt").read_text(encoding="utf-8", errors="replace")
            break
        if (folder / "complete.txt").exists():
            break
        if transport == "com" and proc.poll() is not None and proc.returncode:
            error = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
            break
        time.sleep(0.5)
    wall = time.perf_counter() - monotonic_start
    events_path = folder / "events.jsonl"
    events = [json.loads(s) for s in events_path.read_text().splitlines()] if events_path.exists() else []
    psd = folder / "output.psd"
    result = {"success": (folder / "complete.txt").exists() and psd.exists() and psd.stat().st_size > 0,
              "error": error, "start_epoch_ms": start * 1000, "events": events,
              **summarize(events, start * 1000, wall)}
    (folder / "timing.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--jsx-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--transport", choices=["cli", "com"], default="cli")
    parser.add_argument("--compare-source", type=Path, help="Alternate original and candidate for every page")
    parser.add_argument("--compare-history", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("benchmark_jsx", args.jsx_source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    variants = [("", module, args.history)]
    if args.compare_source:
        candidate_spec = importlib.util.spec_from_file_location("candidate_jsx", args.compare_source)
        assert candidate_spec and candidate_spec.loader
        candidate = importlib.util.module_from_spec(candidate_spec)
        candidate_spec.loader.exec_module(candidate)
        variants = [("original-", module, args.history), ("candidate-", candidate, args.compare_history)]
    inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
    for repeat in range(args.repeat):
        # Reverse order every second repeat to avoid a systematic warm-up/order advantage.
        jobs = [(item, variant) for item in inputs for variant in (variants if repeat % 2 == 0 else variants[::-1])]
        for item, (label, source, history) in jobs:
            folder = (args.output / f"{label}page-{item['page']}-run-{repeat + 1}").resolve()
            folder.mkdir(parents=True, exist_ok=False)
            data = json.loads(Path(item["typeset"]).read_text(encoding="utf-8"))
            script = source.build_script(item["clean"], str(folder / "output.psd"), str(folder / "error.txt"),
                                         str(folder / "complete.txt"), data)
            script = instrument(script, folder / "events.jsonl", history)
            result = run(script, folder, args.transport)
            print(json.dumps({"variant": label.rstrip('-'), "page": item["page"], "repeat": repeat + 1,
                              **{k: v for k, v in result.items() if k != "events"}}), flush=True)
            if not result["success"]:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
