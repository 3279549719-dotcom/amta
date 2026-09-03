from PIL import Image, ImageDraw
from pathlib import Path
import json

OUT = Path('output/tmp/inpaint_compare')
ART = Path('workspace/touhou-single-wing-fresh/artifacts')

for page_name in ['page_11', 'page_12']:
    with open(ART / f'{page_name}_detection.json') as f:
        det = json.load(f)
    free = [b for b in det['blocks'] if b['bubble_type'] == 'text_free']
    print(f'{page_name}: {len(free)} free boxes')

    for fi, fb in enumerate(free):
        bb = fb['bbox']
        x1, y1, x2, y2 = [int(v) for v in bb]
        pad = 60
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(2243, x2 + pad), min(3465, y2 + pad)

        variants = ['lama-manga_pad0', 'lama-manga_pad4', 'aot-inpainting_pad0', 'aot-inpainting_pad4']
        crops = []
        for v in variants:
            p = OUT / f'{page_name}_{v}.png'
            if p.exists():
                im = Image.open(p).convert('RGB')
                crop = im.crop((x1, y1, x2, y2))
                crops.append((v, crop))

        if not crops:
            continue

        w = crops[0][1].width
        h = crops[0][1].height
        cols = 2
        rows = 2
        canvas = Image.new('RGB', (w * cols + 10, (h + 28) * rows), (240, 240, 240))
        d = ImageDraw.Draw(canvas)
        for i, (label, crop) in enumerate(crops):
            r, c = divmod(i, cols)
            x = c * (w + 10)
            y = r * (h + 28)
            d.text((x + 5, y + 3), label, fill=(0, 0, 0))
            canvas.paste(crop, (x, y + 25))
        out_path = OUT / f'{page_name}_free{fi}_zoom.png'
        canvas.save(out_path)
        print(f'  saved {out_path.name}')
