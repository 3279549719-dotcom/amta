"""amta.common — 跨阶段共享叶子库（纯通用，不依赖其他域）。

单一事实共享工具，供 stores/backends/guards/translation/typeset/inpaint/stations
及各 stage 使用：路径/几何/图片/指标(含评测聚合 evalkit)/配置/流水线日志/
分词对齐/工作态/工单。
"""
