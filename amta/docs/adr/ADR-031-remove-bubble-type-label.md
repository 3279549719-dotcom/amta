# ADR-031: 移除 bubble_type (text_bubble/text_free) 标签

**日期**: 2026-09-09
**状态**: 已合入
**影响范围**: detect / inpaint / typeset / report / geometry

## 背景

检测器（RT-DETR-v2）输出 label 1/2，被映射为 `bubble_type: text_bubble/text_free`。
这个标签最初有两个动机：

1. **涂白 vs 精修**：人做漫画翻译时，气泡内文字直接涂白，框外文字用高DPI笔刷精修。
   本能套用到 AI 执行上——text_bubble 走 fill_white，text_free 走 mask+inpaint。
2. **字体区分**：框内字和框外字字体不同，提前埋标签供 typeset 阶段用不同字体。

## 决策过程

### 动机1（涂白 vs 精修）不成立

- ADR-030 已移除 text_bubble 白底直填分支，所有框统一走 Lama inpaint。
- 假设"气泡一定是白底"被反例推翻：黑底白字、气泡内网点、灰底气泡 → 涂白产生白色方块盖背景。

### 动机2（字体区分）不成立

- 不能根据"一个字有没有被气泡包裹"判断它属于哪个字体。
- 对话用圆体、拟声用爆炸体这类高级需求，应该由内容判断（VLM/LLM），不是检测器标签。
- 字体映射表应做成独立 glossary 模块，不是散落在代码里。

### 实验验证：矩形 mask + Lama 效果可接受

**实验设计**：10 页（page_11~20），83 框（text_bubble=54, text_free=29），
只跑 inpaint 阶段（不嵌文字），用矩形 mask（不精修）+ Lama inpaint。

**数据指标**：
- 平均 mask 覆盖率：8.9%（矩形 mask 覆盖的像素比例）
- 平均像素差异率：9.7%（clean vs raw 被改变的像素比例）
- 差异率比覆盖率高 0.8%，说明 Lama 在修复区域边缘做了少量像素过渡（正常现象）
- 无异常值，所有页差异率在 4%~14% 之间，与框数量正相关

**肉眼验证**：用户确认气泡没有被破坏，text_free 用大框罩住抹掉文字融合也自然，整体能接受。

### 数据佐证：text_bubble 标签 ≠ 背景均匀纯白

对 20 页 annotated 图的 18 个 text_bubble 框计算框内灰度方差：
- 方差 < 100（背景均匀）：1 框（5.6%）
- 方差 >= 500（背景复杂）：16 框（88.9%）
- 方差中位数：2798.8，最大：9626.0

证明：检测器的 text_bubble 标签完全不能代表"背景均匀纯白"。
如果用涂白，88.9% 的 text_bubble 框会翻车（白色方块盖网点/纹理）。

### 现存消费者处理

| 消费者 | 原逻辑 | 处理方式 |
|--------|--------|----------|
| inpaint action 决策 | text_bubble→fill_white, text_free→inpaint | ADR-030 已统一 inpaint |
| inpaint mask 生成 | text_free 才精修 mask | 统一矩形 mask，删除 text_mask_refiner |
| typeset 收缩 | 只对 text_bubble 收缩 | 改为对所有框收缩（detect框比文字大时都需要） |
| geometry assign_category | bubble_type→category 映射 | 删除函数 |
| report 展示 | 显示 bubble_type 标签 | 移除展示 |
| artifacts DetectionBlock | bubble_type 字段 | 移除字段 |

## 决策

**彻底移除 bubble_type (text_bubble/text_free) 标签。**

- detect_station.py：不再生成 bubble_type 字段（det_label 保留供调试）
- typeset_station.py：收缩改为对所有框做
- inpaint_station.py：统一矩形 mask，删除 text_mask_refiner 导入
- text_mask_refiner.py：删除文件
- inpaint_strategy.py：移除 _resolve_category
- geometry.py：移除 assign_category 函数
- artifacts.py：移除 DetectionBlock.bubble_type 字段
- ocr_station.py：移除 bubble_type 传递
- orchestrator：移除 refine_mask 配置
- report：移除 bubble_type / text_free 展示
- 测试：同步更新

## 后果

### 正面
- 消除了"人先验正确输出长什么样"的错误假设（与 ADR-024 移除几何规则同类）
- inpaint 逻辑简化：所有框统一矩形 mask + Lama，不再有二分法
- typeset 收缩更合理：对所有框做，不再依赖不准确的检测器标签
- 减少了检测器越俎代庖（检测器本职是"哪里有文字"，不是"文字在不在气泡里"）

### 负面
- 失去了一个粗粒度的"气泡/非气泡"分类信号（但实验证明这个信号不准确，且下游不再需要）
- koharu 引擎路径仍输出 bubble_type（保留字段但标注 deprecated，主链路不再消费）

### 后续
- 字体区分高级需求：做成独立 glossary 模块，由内容判断而非检测器标签
- shrink=8px / pad=4px 绝对像素魔法数字：后续讨论自适应方案
- typeset overflow 判定：用"行数×行高 vs bbox高度"直接计算，替换"字号≤12"间接代理

## 参考

- ADR-024: 移除几何规则（edge_box/extreme_aspect）——同类"人先验"错误
- ADR-030: 移除 text_bubble 白底直填分支，所有框统一 Lama inpaint
- 实验数据：workspace/q2-inpaint-verify/（10页83框 inpaint 验证）
- 方差统计：scripts/probes/q2_bubble_background_variance.py（20页18框背景方差）
