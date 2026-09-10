"""工位适配器 — 把统一的 StationContext 桥接到现有工位函数。

每个适配器做两件事：
1. 从 StationContext 中提取参数，调用现有工位函数
2. 把现有工位的返回值（裸 dict）包装成统一的 StationResult

这是 codebase-design 里的 Adapter 模式：在 seam（统一工位接口）处，
用一个小适配器把"大实现"（现有工位函数）接进来。现有工位不需要改，
编排器也不需要知道现有工位的签名差异。
"""
