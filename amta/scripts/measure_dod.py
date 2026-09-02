"""Measure DoD metrics for stage3 minimal vs legacy (Task 10).

Wraps LLM call functions to count calls and measure latency.
"""
import json
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from amta import chat_client, translate
from _03_translate import run

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "output/data/run_11_20/canon_union_page11.json"
RAW_IMAGE = r"D:\我的汉化\汉化作品\东方\单翼停留之地\12.jpg"
STATE_DIR = ROOT / "workspace/touhou-single-wing"


class CallCounter:
    def __init__(self):
        self.calls = []
        self._orig_chat = None
        self._orig_chat_text = None
        self._orig_translate_chat = None
        self._orig_translate_chat_text = None

    def __enter__(self):
        self._orig_chat = chat_client.chat
        self._orig_chat_text = chat_client.chat_text
        self._orig_translate_chat = translate.chat
        self._orig_translate_chat_text = translate.chat_text

        counter = self

        def make_counted(fn_name, orig):
            def counted(*args, **kwargs):
                t0 = time.perf_counter()
                has_tools = bool(kwargs.get("tools"))
                try:
                    result = orig(*args, **kwargs)
                    return result
                finally:
                    dt = time.perf_counter() - t0
                    model = kwargs.get("model", args[1] if len(args) > 1 else "?")
                    counter.calls.append({
                        "fn": fn_name, "latency": dt, "model": model,
                        "has_tools": has_tools,
                    })
            return counted

        counted_chat = make_counted("chat", self._orig_chat)
        counted_chat_text = make_counted("chat_text", self._orig_chat_text)

        chat_client.chat = counted_chat
        chat_client.chat_text = counted_chat_text
        translate.chat = counted_chat
        translate.chat_text = counted_chat_text
        return self

    def __exit__(self, *args):
        chat_client.chat = self._orig_chat
        chat_client.chat_text = self._orig_chat_text
        translate.chat = self._orig_translate_chat
        translate.chat_text = self._orig_translate_chat_text

    @property
    def total_latency(self):
        return sum(c["latency"] for c in self.calls)

    @property
    def tool_calls(self):
        # chat() supports tools; chat_text doesn't. Count tool_calls from chat responses.
        return 0  # simplified: we'd need to inspect responses


def measure_mode(mode, raw_image=None):
    out_path = ROOT / f"output/data/stage3_{mode}_p11_measured.json"
    with CallCounter() as counter:
        t0 = time.perf_counter()
        run(str(CANON), str(out_path), work_id="touhou-single-wing",
            state_dir=str(STATE_DIR), mode=mode, raw_image_path=raw_image)
        wall_time = time.perf_counter() - t0

    result = json.loads(out_path.read_text(encoding="utf-8"))
    return {
        "mode": mode,
        "llm_calls": len(counter.calls),
        "call_details": counter.calls,
        "total_llm_latency": counter.total_latency,
        "wall_time": wall_time,
        "translations": result.get("translations", {}),
        "residue": result.get("residue", []),
        "glossary_violations": result.get("glossary_violations", []),
        "vlm_refine": result.get("vlm_refine"),
    }


def main():
    print("Measuring minimal mode...")
    min_result = measure_mode("minimal", raw_image=RAW_IMAGE)

    print("Measuring legacy mode...")
    leg_result = measure_mode("legacy")

    print("\n" + "=" * 70)
    print("Stage 3 Minimal vs Legacy — DoD Measurement (page_11, n=1)")
    print("=" * 70)

    # D1: LLM call count
    print("\nD1 — LLM call count (target: minimal ≤ 3)")
    print(f"  minimal: {min_result['llm_calls']}")
    print(f"  legacy:  {leg_result['llm_calls']}")
    print(f"  PASS: {min_result['llm_calls'] <= 3}")

    # D2: tool call count
    min_tools = sum(1 for c in min_result["call_details"] if c.get("has_tools"))
    leg_tools = sum(1 for c in leg_result["call_details"] if c.get("has_tools"))
    print("\nD2 — Calls with tools (target: minimal = 0)")
    print(f"  minimal: {min_tools}")
    print(f"  legacy:  {leg_tools}")
    print(f"  PASS: {min_tools == 0}")

    # D3: latency ratio
    min_lat = min_result["total_llm_latency"]
    leg_lat = leg_result["total_llm_latency"]
    ratio = min_lat / leg_lat if leg_lat > 0 else float("inf")
    print("\nD3 — LLM latency ratio (target: minimal ≤ 30% of legacy)")
    print(f"  minimal: {min_lat:.2f}s")
    print(f"  legacy:  {leg_lat:.2f}s")
    print(f"  ratio:   {ratio:.1%}")
    print(f"  PASS: {ratio <= 0.30}")

    # Wall time
    print("\nWall time (end-to-end):")
    print(f"  minimal: {min_result['wall_time']:.2f}s")
    print(f"  legacy:  {leg_result['wall_time']:.2f}s")

    # D5: translation holes
    min_holes = sum(1 for v in min_result["translations"].values() if not v.strip())
    leg_holes = sum(1 for v in leg_result["translations"].values() if not v.strip())
    print("\nD5 — Translation holes (target: minimal = 0)")
    print(f"  minimal: {min_holes}")
    print(f"  legacy:  {leg_holes}")
    print(f"  PASS: {min_holes == 0}")

    # D6: glossary violations
    min_gloss = len(min_result["glossary_violations"])
    leg_gloss = len(leg_result["glossary_violations"])
    print("\nD6 — Glossary violations (target: minimal ≤ legacy)")
    print(f"  minimal: {min_gloss}")
    print(f"  legacy:  {leg_gloss}")
    print(f"  PASS: {min_gloss <= leg_gloss}")

    # Residue
    print("\nJapanese residue:")
    print(f"  minimal: {len(min_result['residue'])}")
    print(f"  legacy:  {len(leg_result['residue'])}")

    # Call details
    print("\nCall details — minimal:")
    for i, c in enumerate(min_result["call_details"]):
        print(f"  {i}: {c['fn']} model={c['model']} latency={c['latency']:.2f}s")

    print("\nCall details — legacy:")
    for i, c in enumerate(leg_result["call_details"]):
        print(f"  {i}: {c['fn']} model={c['model']} latency={c['latency']:.2f}s")

    # Translation samples
    print("\nTranslation samples — minimal:")
    for k, v in list(min_result["translations"].items())[:4]:
        print(f"  {k}: {v[:60]}")

    print("\nTranslation samples — legacy:")
    for k, v in list(leg_result["translations"].items())[:4]:
        print(f"  {k}: {v[:60]}")

    # Save report data
    report = {
        "page": 11,
        "minimal": {k: v for k, v in min_result.items() if k != "translations"},
        "legacy": {k: v for k, v in leg_result.items() if k != "translations"},
        "d1_pass": min_result["llm_calls"] <= 3,
        "d2_pass": min_tools == 0,
        "d3_pass": ratio <= 0.30,
        "d5_pass": min_holes == 0,
        "d6_pass": min_gloss <= leg_gloss,
    }
    out = ROOT / "output/reports/stage3-minimal-dod-data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nReport data saved to {out}")


if __name__ == "__main__":
    main()
