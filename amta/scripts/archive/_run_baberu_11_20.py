"""baberu 本地 OCR 跑 page_11-20 -> output/data/baberu_canon/。"""
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent          # scripts/
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(SCRIPT_DIR))
from _02_ocr import run as ocr_run  # noqa: E402

DET = ROOT / 'output/data/detect_contract'
RAW = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
OUT = ROOT / 'output/data/baberu_canon'
OUT.mkdir(parents=True, exist_ok=True)

for det_page in range(11, 21):
    out = OUT / f'page_{det_page}_canon.json'
    if out.exists():
        print(f'[SKIP] page_{det_page}'); continue
    t0 = time.perf_counter()
    try:
        doc = ocr_run(work_id='touhou-single-wing', det_path=DET / f'p{det_page}.json',
                      raw_page=RAW / f'{det_page}.jpg', out_path=out,
                      page_idx=det_page, engine='baberu', vlm_enabled=False)
        n = len(doc.get('items', []))
        filled = sum(1 for it in doc['items'] if it.get('baberu_text'))
        print(f'[OK] page_{det_page}: {n} regions, filled {filled}/{n}, {time.perf_counter()-t0:.1f}s')
    except Exception as e:
        print(f'[FAIL] page_{det_page}: {type(e).__name__}: {e} ({time.perf_counter()-t0:.1f}s)')
print('DONE baberu 10 pages')
