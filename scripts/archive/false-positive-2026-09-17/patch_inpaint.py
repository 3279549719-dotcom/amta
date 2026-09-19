"""修改 inpaint_station.py：加 trans_path 参数，过滤有译文的框。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import amta  # noqa: E402,F401  # UTF-8 stdout choke point

p = Path("src/amta/inpaint/inpaint_station.py")
content = p.read_text(encoding="utf-8")

# 1. 函数签名加 trans_path 参数
old_sig = '''def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        clean_dir: Path | None = None, dry_run: bool = False,
        inpaint_engine: str = "lama-manga") -> dict:'''

new_sig = '''def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        clean_dir: Path | None = None, dry_run: bool = False,
        inpaint_engine: str = "lama-manga",
        trans_path: Path | None = None) -> dict:'''

assert old_sig in content, "函数签名没找到！"
content = content.replace(old_sig, new_sig)

# 2. 加过滤逻辑
old_filter = '''    regions = det.get("blocks") or det.get("regions") or []
    plan = plan_inpaint(regions, det.get("image_meta"))'''

new_filter = '''    regions = det.get("blocks") or det.get("regions") or []

    # 契约：只擦有译文的框——上游 translate 已经判断过哪些需要翻
    if trans_path and trans_path.exists():
        trans = read_json(trans_path)
        translations = trans.get("translations", {})
        keep_rids = {rid for rid, dst in translations.items() if dst and dst.strip()}
        regions = [r for r in regions if r.get("region_id") in keep_rids]

    plan = plan_inpaint(regions, det.get("image_meta"))'''

assert old_filter in content, "过滤位置没找到！"
content = content.replace(old_filter, new_filter)

p.write_text(content, encoding="utf-8")
print("inpaint_station.py 改完了")
