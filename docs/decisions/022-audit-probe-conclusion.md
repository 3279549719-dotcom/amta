# ADR-022 — 02.5 audit VLM 探针结论与 repair 决策（2026-08-27）

> 背景：Task 0（v2 计划）——在实现 audit 工位前，用 5 页真实数据验证 deepseek-v4-flash-vision-exp 的"文字存在性判断"能力，据命中率定 repair 闭环力度。
> 探针：pages 11-15（file 11-15.jpg，canon page_10-14），每页注入 3 类已知错误（幻觉/误读/漏检），VLM 对照整页图找差异。

## 探针结果

**严格命中率：12/15 = 80.0%**（正好达到完整闭环阈值线；宽松口径 >80%）

| page | 幻觉 | 误读 | 漏检 | 备注 |
|---|---|---|---|---|
| 11 | ✓ | ✗* | ✗* | *分块后 chunk 2/3 可能空响应；全清单版曾 3/3 |
| 12 | ✓ | ✓ | ✓ | 还抓到真实漏检 ぽつん/蓬莱山 |
| 13 | ✓ | ✗* | ✓ | *被 VLM 标成 hallucination 类型（检测到但类型标错）；另抓到真实误读 ビフン→ビクッ |
| 14 | ✓ | ✓ | ✓ | 但"✓"含 1 条**假阳性**（见下） |
| 15 | ✓ | ✓ | ✓ | 含 1 条**假阳性**（见下） |

**能力结论：**
1. **误读/漏检检测强**：ハ意様→八意様、ビフン→ビクッ、ぽつん/チョキ/じゃあーーー 等真实+注入错误全部被指出，误读还带准确修正文本。
2. **幻觉检测有假阳性风险**：2/5 页把**真实小字**判成幻觉（page_14 u00 じゃ、そういうことで、/ page_15 u05 もう一人だとーーー！！，均 high confidence）——疑似窄竖排小字在降采样整页上不可读导致误判。**→ 高置信度也不能直接自动删**。
3. **误读类型标注噪声**：page_13 注入误读被标成 hallucination；且对 1-2 字符差异（お/が 助词）会刷 nitpick 级误读。
4. **漏检全部进工单**（现状设计）合理：方位框 re-OCR 可二次确认，VLM 编造的长句（如「例の姫様を除かば…」）会被空 OCR 戳穿。

## 关键工程发现：推理模型 token 螺旋

- deepseek-v4-flash-vision-exp 是**推理模型**：复杂任务（17 条清单 + JSON 指令 + 整页图）会把 max_tokens 全部耗在 reasoning_content（实测 6000/6000、12000/12000 全被吃光，finish_reason=length，content 恒空）。
- **对策：清单分块 ≤6 条/次 + max_tokens 8000** → 10s-2min 稳定出 JSON（实测 finish=stop）。"不要推理"指令无效。
- 代价：每页 2-3 次调用，~10min/页（41 页约 7h，可接受但慢；后续可考虑并发 2）。

## 决策（v2 audit/repair 落地参数）

1. **hallucination 不自动删**：一律进 needs_review；自动删需满足"For-Manga 重 OCR 为空 且 墨量 <1%"双条件才允许（机械二次确认），否则工单。
2. **misread**：重 OCR（local For-Manga 引擎）替换；但 edit distance ≤2 的差异（助词级）降级为低优先级提示，不触发重 OCR。
3. **missed**：方位框 re-OCR → 附 reocr_text 进工单（人工确认），不自动合入。
4. **audit 分块**：≤6 region/次调用，max_tokens=8000；方位词兼容中英文（top/left/…）。
5. region_id 匹配做**后缀归一**（VLM 常返回 u00 短形式而非 page_N_u00）。
6. 命中率 80% 达标 → 按完整 repair 闭环实施（带上述安全阀）。

## 探针产物

- `scripts/probe_audit.py`（一次性，已删）
- 结果落盘：`workspace/probe_audit_result.json`
- 坑入 lessons：推理模型 token 螺旋 + 分块对策（L32）
