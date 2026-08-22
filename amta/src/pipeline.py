"""流水线步骤常量与引擎 DAG 知识（v0.59.1 实证，见 README）。"""

# 轮子验证过的全流水线（含翻译与渲染）
FULL_STEPS = [
    "pp-doclayout-v3",
    "comic-text-detector-seg",
    "speech-bubble-segmentation",
    "yuzumarker-font-detection",
    "manga-ocr",
    "llm",
    "lama-manga",
    "koharu-renderer",
]

# Benchmark A：四 detector 同页对比（只跑检测，出 TextBoxes）
DETECTOR_STEPS = {
    "pp-doclayout-v3": ["pp-doclayout-v3"],
    "comic-text-detector": ["comic-text-detector"],          # 漫画专用，bbox+mask
    "anime-text": ["anime-text"],                            # 漫画专用
    "comic-text-bubble-detector": ["comic-text-bubble-detector"],
}

# Benchmark B：三 OCR 同框对比（需要先有 TextBoxes）
OCR_ENGINES = ["manga-ocr", "paddle-ocr-vl-1.5", "mit48px-ocr"]
OCR_STEPS = {name: [name] for name in OCR_ENGINES}

# Benchmark C：mask + inpainting（CPU 上 lama 是唯一现实选择）
INPAINT_STEPS = ["comic-text-detector-seg", "speech-bubble-segmentation", "lama-manga"]

# 引擎依赖（v0.59.1 实证）
ENGINE_NEEDS = {
    "pp-doclayout-v3": [],
    "comic-text-detector": [],
    "anime-text": [],
    "comic-text-bubble-detector": [],
    "comic-text-detector-seg": ["TextBoxes"],
    "speech-bubble-segmentation": [],
    "manga-ocr": ["TextBoxes"],
    "paddle-ocr-vl-1.5": ["TextBoxes"],
    "mit48px-ocr": ["TextBoxes"],
    "llm": ["OcrText"],
    "lama-manga": ["SegmentMask", "BubbleMask"],
    "flux2-klein": ["SegmentMask", "BubbleMask"],
    "aot-inpainting": ["SegmentMask", "BubbleMask"],
    "yuzumarker-font-detection": ["TextBoxes"],
    "koharu-renderer": ["Inpainted", "Translations", "FontPredictions"],
}
