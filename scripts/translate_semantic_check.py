"""translate_semantic_check.py — 翻译工位语义护栏 ③：VLM 逐 region 评审忠实度（粗筛层）。

用法:
  python scripts/translate_semantic_check.py --canon <canon.json> --trans <translation.json> \\
      --crops <crop_dir> --out <semantic_check.json> [--limit N]

依赖: .env CHAT_*（DeepSeek），默认模型 deepseek-v4-flash-vision-exp（能读图）。
输出: {model, judged, passed, pass_rate, failed: [{region_id, source, translation, reason, suggestion}]}

定位（与 ADR-014 双层护栏一致）:
  - 机械护栏 ①② 已在 03_translate 内（结构/残留）。
  - 语义护栏 ③ = 本脚本，VLM 粗筛：抓明显错译/漏译/编造/人名乱/OCR 读错导致译错。
  - 细的语境润色（如「污秽即是心」vs「污秽源于心中」）抓不到——留导演终审。
  - ③ 的通过率是「粗筛层」的量化验收指标，不是翻译质量满分保证。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta import chat_config  # noqa: E402
from amta.ocr_engines import image_data_uri  # noqa: E402

JUDGE_PROMPT = """你是漫画翻译质量评审。请阅读图中日文原文，并判断给出的译文是否合格。
图中原文(OCR): {text}
现有译文: {translation}
检查要点：1) 是否忠实原文（错译/跑偏/编造） 2) 是否漏译/空白 3) 人名术语是否与图一致。
对四项各评 1-5 分（5=最好）：accuracy(语义准确) fluency(中文自然) consistency(术语一致) readability(漫画可读)。
输出格式：
通过
accuracy:1-5
fluency:1-5
consistency:1-5
readability:1-5
（若不合格，则第一行改为：需修订：<一句话理由>；建议译文：<译文>，并同样输出四项评分）"""


def _judge_vision(cfg: dict, crop_path: Path, text: str, translation: str,
                  model: str, retries: int = 2) -> str:
    """调 DeepSeek vision 模型评审单 region，返回评审原文；空内容重试。"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": JUDGE_PROMPT.format(text=text, translation=translation)},
            {"type": "image_url", "image_url": {"url": image_data_uri(crop_path)}},
        ]}],
        "max_tokens": 1200,
    }
    for attempt in range(retries + 1):
        r = requests.post(cfg["base_url"] + "/chat/completions",
                          headers={"Authorization": f"Bearer {cfg['api_key']}"},
                          json=payload, timeout=120)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"] or ""
        if content.strip():
            return content
    return ""


def parse_verdict(out: str) -> tuple[str, str]:
    """解析评审输出 -> (verdict, detail)。verdict ∈ {'pass','fail','inconclusive'}。"""
    out = (out or "").strip()
    if not out:
        return "inconclusive", "评审无输出"
    if "通过" in out:
        return "pass", out
    return "fail", out


def parse_verdict_with_scores(out: str) -> tuple[str, dict]:
    """解析评审输出 + 四维评分（ADR-016：全量合并同次 VLM 调用，监控/排序用）。

    返回 (verdict, {accuracy, fluency, consistency, readability})，未给出的分为 None。
    """
    import re as _re
    verdict, _ = parse_verdict(out)
    scores: dict = {}
    for key in ("accuracy", "fluency", "consistency", "readability"):
        m = _re.search(rf"{key}\s*[:：]\s*(\d)", out or "")
        scores[key] = int(m.group(1)) if m else None
    return verdict, scores


def _avg_scores(rows: list[dict]) -> dict:
    """对通过项的四维分求均值（None 忽略），无数据返回空 dict。"""
    keys = ("accuracy", "fluency", "consistency", "readability")
    out: dict = {}
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        out[k] = round(sum(vals) / len(vals), 2) if vals else None
    return out


def run(canon_path: Path, trans_path: Path, crops_dir: Path, out_path: Path,
        *, model: str = "deepseek-v4-flash-vision-exp", limit: int | None = None,
        only: list[str] | None = None) -> dict:
    canon = json.loads(Path(canon_path).read_text(encoding="utf-8"))
    trans = json.loads(Path(trans_path).read_text(encoding="utf-8")).get("translations", {})
    cfg = chat_config.get_chat_config()

    if limit:
        canon = canon[:limit]
    if only:
        only_set = set(only)
        canon = [r for r in canon if r["region_id"] in only_set]

    judged = passed = 0
    passed_scores: list[dict] = []
    failed: list[dict] = []
    inconclusive: list[dict] = []
    for i, r in enumerate(canon, 1):
        rid = r["region_id"]
        src = (r.get("text") or "").strip()
        tgt = (trans.get(rid) or "").strip()
        crop = crops_dir / f"{rid}.png"
        if not crop.exists():
            failed.append({"region_id": rid, "source": src, "translation": tgt,
                           "reason": "缺 crop 图", "suggestion": ""})
            continue
        if not tgt:
            failed.append({"region_id": rid, "source": src, "translation": "",
                           "reason": "译文为空", "suggestion": ""})
            continue
        try:
            out = _judge_vision(cfg, crop, src, tgt, model)
        except Exception as e:  # noqa: BLE001
            failed.append({"region_id": rid, "source": src, "translation": tgt,
                           "reason": f"评审调用失败: {e}", "suggestion": ""})
            continue
        verdict, scores = parse_verdict_with_scores(out)
        detail = (out or "").strip()
        if verdict == "pass":
            passed += 1
            passed_scores.append(scores)
        elif verdict == "fail":
            failed.append({"region_id": rid, "source": src, "translation": tgt,
                           "reason": detail, "suggestion": "", "scores": scores})
        else:
            inconclusive.append({"region_id": rid, "source": src, "translation": tgt,
                                 "reason": detail, "suggestion": "", "scores": scores})
        judged += 1
        print(f"[{i}/{len(canon)}] {rid}: {verdict}", flush=True)

    conclusive = passed + len(failed)
    result = {
        "model": model,
        "judged": judged,
        "passed": passed,
        "failed": failed,
        "inconclusive": inconclusive,
        "pass_rate": round(passed / conclusive, 3) if conclusive else None,
        "avg_scores": _avg_scores(passed_scores),
    }
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="翻译语义护栏③：VLM 逐 region 粗筛评审")
    ap.add_argument("--canon", required=True, type=Path)
    ap.add_argument("--trans", required=True, type=Path)
    ap.add_argument("--crops", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model", default="deepseek-v4-flash-vision-exp")
    ap.add_argument("--limit", type=int, default=None, help="只评审前 N 个 region（试跑用）")
    ap.add_argument("--only", type=str, default=None,
                    help="只评审指定 region_id（逗号分隔，补跑用）")
    args = ap.parse_args()
    only = args.only.split(",") if args.only else None
    res = run(args.canon, args.trans, args.crops, args.out,
              model=args.model, limit=args.limit, only=only)
    print(f"[semantic_check] judged={res['judged']} passed={res['passed']} "
          f"inconclusive={len(res['inconclusive'])} pass_rate={res['pass_rate']} -> {args.out}")
    for f in res["failed"][:10]:
        print("  FAILED:", f["region_id"], "|", f["reason"][:80])


if __name__ == "__main__":
    main()
