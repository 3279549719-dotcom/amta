"""amta.typeset — Stage 5/6 排版（自研 Pillow 引擎，ADR-019/020/021）。

- typeset_engine  — 排版本体（方向/折行/字号两分选择）
- typeset_render  — 渲染器（逐字排布/描边/多级字体 → PIL Image）
- typeset_station — typeset 工位（clean+canon+translation+detection → final）
- fonts           — 4 级字体映射 + 探测

依赖: amta.common、amta.stores。
"""
