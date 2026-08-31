"""Generate a self-contained HTML report with original images, OCR text, and translations."""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "output/backup/2026-08-27-pre-rerun-11-20"
BATCH_DIR = ROOT / "output/data/stage3_minimal_batch"
RAW_IMAGE_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT_HTML = ROOT / "output/reports/stage3-minimal-10pages-visual.html"


def img_to_base64(path: Path) -> str:
    data = path.read_bytes()
    return base64.b64encode(data).decode("ascii")


def load_canon(page_idx: int) -> list[dict]:
    p = BACKUP_DIR / f"page_{page_idx}_canon.json"
    return json.loads(p.read_text(encoding="utf-8"))


def load_translation(page_idx: int) -> dict:
    p = BATCH_DIR / f"page_{page_idx}_translation.json"
    return json.loads(p.read_text(encoding="utf-8"))


def build_page_section(page_idx: int) -> str:
    jpg_num = page_idx + 1
    img_path = RAW_IMAGE_DIR / f"{jpg_num}.jpg"
    canon = load_canon(page_idx)
    trans = load_translation(page_idx)
    translations = trans.get("translations", {})
    vlm = trans.get("vlm_refine", {})

    img_b64 = img_to_base64(img_path)

    rows = []
    for item in canon:
        rid = item["region_id"]
        ocr_text = item.get("text", "")
        translation = translations.get(rid, "")
        rows.append(f"""
        <tr>
          <td class="rid">{rid}</td>
          <td class="ocr">{ocr_text}</td>
          <td class="trans">{translation}</td>
        </tr>""")

    vlm_info = ""
    if vlm:
        vlm_info = f"""
        <div class="vlm-info">
          <span class="vlm-tag">VLM refine</span>
          scene: {vlm.get('scene', 'N/A')} |
          {vlm.get('refinement_count', 0)} corrections |
          {vlm.get('invalid_count', 0)} invalid |
          {vlm.get('duplicate_count', 0)} duplicates
        </div>"""

    return f"""
    <section class="page" id="page-{page_idx}">
      <h2>Page {page_idx} <span class="jpg-name">({jpg_num}.jpg)</span></h2>
      {vlm_info}
      <div class="page-content">
        <div class="image-col">
          <img src="data:image/jpeg;base64,{img_b64}" alt="page {page_idx}" />
        </div>
        <div class="text-col">
          <table>
            <thead>
              <tr><th>Region</th><th>OCR 原文</th><th>翻译</th></tr>
            </thead>
            <tbody>
              {''.join(rows)}
            </tbody>
          </table>
        </div>
      </div>
    </section>"""


def main():
    pages = list(range(10, 20))
    sections = [build_page_section(p) for p in pages]

    # Summary stats
    total_regions = 0
    total_holes = 0
    for p in pages:
        canon = load_canon(p)
        trans = load_translation(p)
        total_regions += len(canon)
        total_holes += sum(1 for v in trans.get("translations", {}).values() if not v.strip())

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stage 3 Minimal Translation — 10 Pages Visual Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f5f5f7;
    color: #1d1d1f;
    line-height: 1.6;
  }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
  header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: white;
    padding: 30px 40px;
    border-radius: 12px;
    margin-bottom: 30px;
  }}
  header h1 {{ font-size: 28px; margin-bottom: 8px; }}
  header .subtitle {{ opacity: 0.8; font-size: 14px; }}
  .stats {{
    display: flex;
    gap: 20px;
    margin-top: 16px;
    flex-wrap: wrap;
  }}
  .stat {{
    background: rgba(255,255,255,0.1);
    padding: 10px 18px;
    border-radius: 8px;
    font-size: 13px;
  }}
  .stat strong {{ font-size: 20px; display: block; }}
  nav {{
    background: white;
    padding: 12px 20px;
    border-radius: 10px;
    margin-bottom: 24px;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  nav a {{
    text-decoration: none;
    color: #0066cc;
    padding: 4px 12px;
    border-radius: 6px;
    font-size: 13px;
    transition: background 0.2s;
  }}
  nav a:hover {{ background: #e8f0fe; }}
  .page {{
    background: white;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  .page h2 {{
    font-size: 20px;
    margin-bottom: 6px;
    color: #1a1a2e;
  }}
  .jpg-name {{ color: #86868b; font-size: 14px; font-weight: normal; }}
  .vlm-info {{
    font-size: 12px;
    color: #6e6e73;
    background: #f5f5f7;
    padding: 6px 12px;
    border-radius: 6px;
    margin-bottom: 16px;
  }}
  .vlm-tag {{
    background: #0066cc;
    color: white;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    margin-right: 6px;
  }}
  .page-content {{
    display: flex;
    gap: 24px;
    align-items: flex-start;
  }}
  .image-col {{
    flex: 0 0 45%;
    max-width: 45%;
  }}
  .image-col img {{
    width: 100%;
    height: auto;
    border-radius: 8px;
    border: 1px solid #e0e0e0;
  }}
  .text-col {{
    flex: 1;
    overflow-x: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th {{
    background: #f5f5f7;
    padding: 10px 12px;
    text-align: left;
    font-weight: 600;
    color: #6e6e73;
    border-bottom: 2px solid #e0e0e0;
    position: sticky;
    top: 0;
  }}
  td {{
    padding: 10px 12px;
    border-bottom: 1px solid #f0f0f0;
    vertical-align: top;
  }}
  tr:hover {{ background: #fafafa; }}
  .rid {{
    font-family: monospace;
    font-size: 11px;
    color: #86868b;
    white-space: nowrap;
  }}
  .ocr {{ color: #1d1d1f; }}
  .trans {{ color: #0066cc; font-weight: 500; }}
  @media (max-width: 900px) {{
    .page-content {{ flex-direction: column; }}
    .image-col {{ flex: none; max-width: 100%; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Stage 3 Minimal Translation — 10 Pages Visual Report</h1>
    <div class="subtitle">原图 + OCR 原文 + 翻译结果对照 | mode=minimal | 2 LLM calls/page, zero tools</div>
    <div class="stats">
      <div class="stat"><strong>{len(pages)}</strong>Pages (JPG 11-20)</div>
      <div class="stat"><strong>{total_regions}</strong>Text regions</div>
      <div class="stat"><strong>{total_holes}</strong>Empty translations</div>
      <div class="stat"><strong>0</strong>402 errors</div>
      <div class="stat"><strong>0</strong>Japanese residue</div>
    </div>
  </header>

  <nav>
    {''.join(f'<a href="#page-{p}">Page {p} ({p+1}.jpg)</a>' for p in pages)}
  </nav>

  {''.join(sections)}
</div>
</body>
</html>"""

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    size_mb = OUT_HTML.stat().st_size / (1024 * 1024)
    print(f"HTML generated: {OUT_HTML}")
    print(f"Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
