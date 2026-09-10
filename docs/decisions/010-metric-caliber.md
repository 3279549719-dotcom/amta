# 010 — 评测指标口径：统一 norm 去全部标点 + 派生指标重算 + 双轨（nCER/lCER）展望

## Context

- /simplify 后 metrics.norm 为「去全部标点、保留假名/汉字/字母/数字」，但 benchmark_b_paddle_manga.json 的 cer/em 仍是「只去空白」旧口径缓存 → 出现「GT=OCR 却 EM=0」假 bug（实测 32 行 0→1，无 1→0；EM 0.516→0.770、CER 0.316→0.121）。
- researcher 调研（jzhang533/PaddleOCR-VL-For-Manga 代码、OmniDocBench）：主流评测**不删符号**；〜(U+301C) vs ー(U+30FC) 有真实语气差异（如 も〜わがまま）；促音っ 是 OCR 共同弱点；Baberu 用双轨（nCER 严格 + lCER 宽松）。

## Decision

1. 现行统一口径 = metrics.norm（去全部标点）；派生指标（cer/em）不入库缓存，或入库必须随代码重算 + 一致性测试兜底（L14）。
2. 双轨（nCER 严格保留符号 / lCER 宽松去符号）为**未来方向**：落地时 U+FF5E/U+301C 需显式映射，且须保留 〜 vs ー 的语气差异，不盲目归一。
3. 报告/QA 中 unmatched 行必须先归因（GT 噪声 / 误检框 / 口径差异）再引用数字。

## Consequences

- ✅ 数字口径与代码一致，GT=OCR 却 EM=0 类假 bug 被测试兜住。
- ✅ norm 敏感性已验证：是否保留 〜〜ー 只影响 3/126 行，双轨切换代价小。
- ⚠️ 双轨落地前，含 〜/ー 差异的行可能被现行 norm 判为不匹配（3/126 行量级）。
