import sys
sys.path.insert(0, r"E:\manga translator agent\amta\.worktrees\report-tool\src")

from amta.ocr_engines import ocr_batch, ENGINES
print("Engines:", ENGINES)

import glob
crops = sorted(glob.glob(r"E:\manga translator agent\amta\.worktrees\report-tool\workspace\ocr-compare\artifacts\crops\page_0\*.png"))[:2]
print(f"Test crops: {len(crops)}")

r = ocr_batch(crops, engine="baberu")
for item in r:
    print(f"  baberu: {item['ocr'][:60]}")
print("baberu OK")
