# 漫画翻译开源项目 Detect/OCR 阶段调研（manga-image-translator · BallonsTranslator · comic-text-detector · PaddleOCR-VL-For-Manga）

> 核心诊断：**"框内字却没 OCR 文本"几乎不出现在成熟项目里**。原因不是"OCR 更强"，而是 **detect 宁滥勿缺 + recognition 端到端模型"有字必吐" + 空输出在流程末位被显式处理**。漏检是唯一不可逆损失通道，故行业全体押注高 Recall。

## 1. manga-image-translator（zyddnys，GPL-3.0）

- **Detect**：单选 detector（`default`=DBNet 系漫画模型 / `ctd`=comic-text-detector / `craft`/`paddle`），默认阈值 **text_threshold=0.5, box_threshold=0.7, unclip_ratio=2.3**（外扩极慷慨）、detection_size=2048、小图自动加边框、可 rotate/auto_rotate/invert/gamma 增强（[detection/common.py](https://github.com/zyddnys/manga-image-translator/blob/main/manga_translator/detection/common.py)、[config.py](https://github.com/zyddnys/manga-image-translator/blob/main/manga_translator/config.py)）。README FAQ 明说"**增加 box_threshold 可过滤 OCR 误检乱码**"、"[ctd] 可增加检测到的文本行数"——**误检是预期内的，靠后置阈值过滤**（[README_CN](https://github.com/zyddnys/manga-image-translator/blob/main/README_CN.md)）。
- **OCR**：**不是整页 OCR**，是"先 detect 再逐框"：把检测四边形按方向透视变换到 32/48px 高的规整条，批 beam-search 解码（[ocr/model_32px.py](https://github.com/zyddnys/manga-image-translator/blob/main/manga_translator/ocr/model_32px.py) `get_transformed_region`；beta-0.3 同构）。**mocr 路径例外**：`merge_bboxes` 先把同行/同气泡框合并成整个文本区，再由 manga-ocr **一次前向识别多行**——最接近"对 detect union 做 OCR"（[ocr/model_manga_ocr.py](https://github.com/zyddnys/manga-image-translator/blob/main/manga_translator/ocr/model_manga_ocr.py)）。
- **多模型 union**：历史版本有 `--detector both`（dbnet+ctd 并集合并）；现行版改为单选 + `textline_merge`（图连通分量+方向多数投票+排序，把碎片行并回 region）。
- **空输出处理**：32px/48px 有 prob 阈值（0.7/0.2），低于即跳过该框；`_run_ocr` 再 **strip 空串丢弃**，不送翻译（[manga_translator.py](https://github.com/zyddnys/manga-image-translator/blob/main/manga_translator/manga_translator.py) `_run_ocr`）。无 textline 时整页跳过（skip-no-regions）。**inpaint mask 用 detect 的 raw text mask（union），不依赖 OCR 成功**——即使 OCR 空，字也会被涂掉。

## 2. comic-text-detector（dmMaze）

两级结构：**YOLO 文本块（气泡）检测 + DBNet 文本 mask**，训练 1.3 万张漫画/合成弱监督数据（[README](https://github.com/dmMaze/comic-text-detector)）。设计取向即"**任何像字的地方先圈出来**"（Precision 低、Recall 高）；BT 中它是默认检测器，靠下游 OCR/人工消化误检。对比项 **YSGDetector 专门过滤拟声词**（Precision 取向）——反证默认是 Recall 取向（[BT README](https://github.com/dmMaze/BallonsTranslator)）。

## 3. BallonsTranslator（dmMaze）

"heavily dependent upon manga-image-translator"（README 原文）。流程 detect（CTD/YSG/星野云）→ OCR（mit*/manga-ocr/PaddleOCR-VL/Tuanzi/OneOCR 任选）→ inpaint（AOT/lama/PatchMatch）→ typeset；官方文档明确 Tuanzi 云 OCR"**逐 textblock 识别更慢且无精度提升**"，建议用其 detector 直出文本（[text-detection 文档](https://mintlify.wiki/dmMaze/BallonsTranslator/modules/text-detection)、[README](https://github.com/dmMaze/BallonsTranslator/blob/dev/README_EN.md)）。

## 4. manga-ocr / PaddleOCR-VL-For-Manga（OCR 侧）

- **manga-ocr README 原文**："**The model always attempts to recognize some text on the image, even if there is none** … might even 'dream up' realistically looking sentences"（[README](https://github.com/kha-white/manga_ocr)）——自回归解码器对"有字的图"**几乎不可能返回空**，失败模式是幻觉错字而非空串。**这就是"框内字基本都能 OCR 到"的机制核心**。
- **PaddleOCR-VL-For-Manga**：纯 OCR VLM（Manga109-s crop + 150 万合成 SFT，整句准确率 27%→70%，[README](https://github.com/jzhang533/PaddleOCR-VL-For-Manga)）。detect 靠外部；给文字 crop 必吐文本，**空输出=输入框内无字=detect 框错**，属检测层问题。

## 5. 对"框内字却没 OCR 文本"的直接解释

成熟项目里该现象的两个真因，且都不在"OCR 识别能力"：
1. **detect 漏检**——框根本不存在，整个下游（OCR/翻译/inpaint）静默丢失，最致命（本团队 ctd_seg 只细化已有框、pp-doclayout-v3 漏框即此通道）；
2. **置信度过滤**——prob 低于阈值被显式丢弃（MIT 0.2~0.7）。
"宁滥勿缺"是行业通行做法，因为**误检代价低**（OCR 出垃圾→阈值/人工过滤，成本一次推理），**漏检代价高**（文字残留未翻译未涂除，成本整条流水线）。

## 6. 本项目（逐框裁切 OCR + baberu/dashscope）可借鉴改进清单

1. **检测层召回优先**：阈值下调至 text_threshold≈0.5 / box_threshold≈0.7，unclip 放大 2 倍左右；detect_size 提到 ≥1024；小图自动加边。
2. **多检测器 union**：comic-text-detector + 现有 detector 并集后合并（对齐 MIT 历史 `--detector both`）；合并须用方向感知 merge（已踩坑：IoU>0.5 去重漏竖排碎片框）。
3. **OCR 双引擎兜底**：空输出/低置信 → 切第二引擎重试（baberu fast + dashscope/PaddleOCR-VL slow 互为 fallback，同构 MIT mocr 双引擎）；**别先丢弃**，空串 region 保留标记送 needs_review 工单（对齐 MIT 是先过滤再翻译，但本项目应更保守）。
4. **mask 独立于 OCR**：inpaint mask 用检测 raw mask（union），不依赖 OCR 成功，防"漏字残留"。
5. **行合并再 OCR**：碎片行先并回文本区再整块识别（对应 manga-ocr 多行一次过），直接修竖排碎片坑。
6. **过滤后置**：bubble/拟声词过滤放 OCR 之后，不参与 detect 硬过滤。

## 结论（一句话）

成熟项目空识别≈0 的真相 = **detect 宁滥勿缺保 Recall + 端到端 recognition 对框内文字必吐字 + 空串/低置信显式后置处理**；"框内无字"在它们那里几乎总是检测漏检，这也是本项目最该补的短板。
