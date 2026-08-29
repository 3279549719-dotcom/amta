"""语义护栏③脚本（scripts/translate_semantic_check.py）的机械逻辑测试。

覆盖：评审输出解析（pass/fail/inconclusive）与 run() 聚合/过滤逻辑。
VLM 调用本身不可测（外部 API），由 _judge_vision 的 mock 隔离。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from translate_semantic_check import parse_verdict, parse_verdict_with_scores, run  # noqa: E402


def test_parse_verdict_pass():
    assert parse_verdict("通过") == ("pass", "通过")
    # 带说明也算通过
    assert parse_verdict("通过。译文忠实，无漏译。")[0] == "pass"


def test_parse_verdict_fail():
    v, d = parse_verdict("需修订：主语错位；建议译文：下次我帮你拿过来吧")
    assert v == "fail"
    assert "主语错位" in d


def test_parse_verdict_inconclusive_on_empty():
    assert parse_verdict("") == ("inconclusive", "评审无输出")
    assert parse_verdict("   ") == ("inconclusive", "评审无输出")


def _write_fixtures(tmp_path):
    canon = [
        {"region_id": "r1", "text": "月の都", "page": 0},
        {"region_id": "r2", "text": "カチャ", "page": 0},
        {"region_id": "r3", "text": "八意様だ", "page": 1},
    ]
    canon_p = tmp_path / "canon.json"
    canon_p.write_text(json.dumps(canon, ensure_ascii=False), encoding="utf-8")
    trans_p = tmp_path / "translation.json"
    trans_p.write_text(json.dumps(
        {"translations": {"r1": "月之都", "r2": "咔嗒", "r3": "是八意大人"}},
        ensure_ascii=False), encoding="utf-8")
    for rid in ("r1", "r2", "r3"):
        (tmp_path / f"{rid}.png").write_bytes(b"x")
    return canon_p, trans_p


def test_run_aggregates_pass_fail_inconclusive(tmp_path, monkeypatch):
    from amta import chat_config
    monkeypatch.setattr(chat_config, "get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})

    canon_p, trans_p = _write_fixtures(tmp_path)
    verdicts = iter(["通过", "", "需修订：x"])

    def fake_judge(cfg, crop, text, translation, model):
        return next(verdicts)

    monkeypatch.setattr("translate_semantic_check._judge_vision", fake_judge)
    out_p = tmp_path / "out.json"
    res = run(canon_p, trans_p, tmp_path, out_p)
    # r1 pass / r2 空输出→inconclusive / r3 fail
    assert res["passed"] == 1
    assert len(res["failed"]) == 1 and res["failed"][0]["region_id"] == "r3"
    assert len(res["inconclusive"]) == 1 and res["inconclusive"][0]["region_id"] == "r2"
    assert res["pass_rate"] == 0.5  # 1 pass / (1 pass + 1 fail) 结论数


def test_run_only_filters_regions(tmp_path, monkeypatch):
    from amta import chat_config
    monkeypatch.setattr(chat_config, "get_chat_config",
                        lambda: {"base_url": "x", "model": "m", "api_key": "k"})

    canon_p, trans_p = _write_fixtures(tmp_path)
    monkeypatch.setattr("translate_semantic_check._judge_vision",
                        lambda cfg, crop, text, translation, model: "通过")
    res = run(canon_p, trans_p, tmp_path, tmp_path / "out.json", only=["r1"])
    assert res["judged"] == 1
    assert res["passed"] == 1


def test_parse_pass_with_scores():
    out = "通过\naccuracy:4\nfluency:3\nconsistency:4\nreadability:5"
    verdict, scores = parse_verdict_with_scores(out)
    assert verdict == "pass"
    assert scores["accuracy"] == 4
    assert scores["fluency"] == 3
    assert scores["consistency"] == 4
    assert scores["readability"] == 5


def test_parse_fail_with_scores():
    out = "需修订：主语错；建议译文：xx\naccuracy:2\nfluency:3\nconsistency:5\nreadability:4"
    verdict, scores = parse_verdict_with_scores(out)
    assert verdict == "fail"
    assert scores["accuracy"] == 2


def test_parse_no_scores_defaults_none():
    verdict, scores = parse_verdict_with_scores("通过")
    assert verdict == "pass"
    assert scores["accuracy"] is None
def test_judge_prompt_format_safe():
    """回归（L24）：JUDGE_PROMPT 必须能被 .format() 安全调用——禁止字面花括号占位符。"""
    from translate_semantic_check import JUDGE_PROMPT
    out = JUDGE_PROMPT.format(text="原文です", translation="译文")
    assert "原文です" in out
    assert "译文" in out
