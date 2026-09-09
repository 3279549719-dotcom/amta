"""amta.inpaint — Stage 4 去文字/重绘（lama 家族落地）。

- inpaint_strategy    — 去字策略（全 box 统一 mask + inpaint）
- inpaint_station     — inpaint 工位（detection+raw → clean+inpaint 产物）
- local_lama_inpainter — 本地 LaMa inpainting 封装（big-lama / lama-manga）
- _lama_ffc / _lama_model / _lama_util — lama-manga FFC 内部实现

依赖: amta.common、amta.backends。
"""
