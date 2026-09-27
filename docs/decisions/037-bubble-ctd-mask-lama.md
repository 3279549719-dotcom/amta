# ADR-037: 气泡擦除从矩形涂白改为 CTD 像素 mask + LaMa

- 日期：2026-09-27
- 状态：已合入 main
- 分支：`feat/bubble-ctd-lama`
- Commit：`df14a9a`

## 背景

气泡内文字擦除经历了反复横跳：

1. **最初**：气泡 → PIL 画白矩形（shrink=8）；框外字 → LaMa。
2. **ADR-030/033**：废掉涂白，全走 LaMa 矩形 mask。起因是 88.9% 气泡框背景不是纯白，白方块突兀。
3. **21fc2f4**：text-ink mask（中值差分找墨像素），但磨掉纯黑发。
4. **60717a6**：std 均匀度分流，但矩形 bbox 四角吃进气泡外灰底，std 被抬高，白泡被误送 LaMa → 每页残影。
5. **ADR-035 (p62)**：试 CTD 像素 mask 三轮，全部否证（复杂背景下文字压人物画，CTD 分不清黑字和黑发）。
6. **5274f37**：撤回，气泡回到 shrink 涂白。理由："残影每页都有 > 灰泡少见"。

实测 page 7（姬兔合同本）发现涂白的两个残留问题：

- **形状**：白矩形硬边嵌在椭圆泡里，shrink=8 在弧线收窄处对不齐。
- **颜色**：气泡原生色是 RGB(245,251,249) 冷灰白，写死 (255,255,255) 死白，差 10 个灰阶，肉眼可见硬边。
- **误伤**：作者名（"作：真菜"）的白矩形盖在黑头发上。

## 决策

气泡类（det_label=1 / dialogue_bubble）不再走 `_apply_fill_white` 矩形涂白，改为：

1. **CTD DBNet**（`models/CTD/comictextdetector.pt.onnx`）出整页文字像素 mask（`seg` 输出阈值化 + 9×9 椭圆膨胀 ×3）。
2. 按气泡 bbox 裁剪 mask——只保留气泡内的文字像素。
3. 和框外复杂矩形 mask 合并，一次送 **LaMa-manga** 重建。

框外字路径不变（均匀背景 median 填色，复杂背景矩形 mask + LaMa）。

## 为什么这次能成

ADR-035 在 p62 试 CTD 失败，是因为 p62 是文字压在人物画上的复杂场景，CTD 分不清黑字和黑发。但**白泡内部**是简单场景：白底黑字，没有歧义。CTD 在白泡上的任务比 p62 简单得多。

之前 5274f37 撤回涂白是因为 LaMa 矩形 mask 在白泡上留残影——那是因为 mask 是大矩形，LaMa 要重建一大块空白。现在 mask 是紧贴文字笔画的细 mask，LaMa 只补笔画周围几像素，不会幻觉出条纹。

## 代价

- CPU 上单页 inpaint 从 ~0.4s 涨到 ~105s（CTD ~76s + LaMa ~25s）。
- GPU 上预计 ~5-15s（CTD 需改 provider 为 CUDA，收尾时做）。
- CTD 模型已在本地（94MB），无新增依赖。

## 遗留

- `_apply_fill_white()` 成为死代码，待决定删除或留作 fallback。
- CTD provider 写死 CPU，待加 CUDA 自动选择。
- `inpaint_strategy.py` docstring 和输出 JSON 的 `filled` 字段名语义待更新。

## 参考

- ADR-030：统一 LaMa
- ADR-033：移除 bubble_type
- ADR-035：p62 CTD 三轮否证
- 5274f37：撤回涂白
