# ADR-005：Benchmark 方法论 = VLM-as-oracle + 零人工全量标注 + 内容级匹配

**状态**：已采纳（勿改）

## 决策

Benchmark A/B/C 的真值（GT）与判定全部走 **VLM 当 oracle**，**零人工全量标注**；detector 评估的 recall 用**内容级匹配**而非像素 IoU。

## 理由

- 人工全量标注（每页逐框标真值）成本不可接受（用户明确拒绝）。
- 判定类工作（框是不是文字、文字内容、擦除质量）适合交给 VLM（describe_image/qwen 视觉），它是"独立判卷官"。
- **实测教训**：describe_image 看整页大图的**坐标不可靠**（裁剪验证为空白/漂移），无法做像素级 IoU 对齐 → recall 改用内容级匹配（GT 内容清单 vs detector 并集框识别内容，字符重合度≥0.6）。

## 后果 / 约束

- 候选真值 = 4 detector 并集（都漏的不计入分母，属工具能力边界）。
- 需要精确位置时用确定性 detector 的 bbox，不用 VLM 坐标。
- 人工仅抽查"detector 分歧 / VLM 低置信"子集。
- 方法细节见 `.claude/skills/benchmark/SKILL.md` 与 `docs/lessons.md` L1。
