"""在 lessons.md 末尾加 L49。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import amta  # noqa: E402,F401  # UTF-8 stdout choke point

p = Path("docs/lessons.md")
content = p.read_text(encoding="utf-8")

# 在模板前面插入 L49
l49 = """
## L49 — 假阳性治理：translate纯标点条款 + inpaint契约理顺（省略号类假阳性闭环）

- **Problem**：省略号类框被走全流程——detect 框了纯标点省略号，OCR 读出来，LLM 原样吐回，inpaint 擦掉原文，typeset 重画一遍；更严重的是，OCR 因 conf 太低过滤掉的框，inpaint 照样擦。
- **Root cause**：两个契约断裂。
  1. translate 没有"判断要不要翻"的意识——它默认"给什么翻什么"，纯标点也照样处理。
  2. inpaint 直接读 detection.json 擦所有框——上游 OCR 过滤了什么、translate 决定翻不翻，它完全不知道。
- **Durable lesson**：
  - 纯标点/无实义内容的假阳性，用 LLM 原生语言能力就能治——不用硬编码正则阈值。改 prompt 加一句"完全是标点的内容输出空"就行，LLM 自己能区分"纯省略号"和"带省略号的正常台词"。
  - 流水线契约必须理顺：下游步骤只处理上游明确说"要"的东西。inpaint 应该依赖 translate，只擦有非空译文的框——而不是依赖 detect 擦所有框。
  - 背景门牌类假阳性（如"蓬莱"）纯文本 LLM 治不了——它看不到图，不知道是台词还是背景装饰。这类问题要么加 VLM，要么重训 detect，不是靠 prompt 能解决的。
- **Prevention**：
  - translate system prompt 已加"纯标点输出空"条款（2026-09-17）。
  - inpaint consumes 从 ["detect"] 改成 ["detect", "translate"]，只擦有译文的框。
- **Regression**：月天新地单页版 p5/p10 实测：r13/r02 纯省略号框输出空译文，inpaint 不擦，typeset 不写。

"""

marker = "## 模板（新增时复制）"
assert marker in content, "模板标记没找到"
content = content.replace(marker, l49 + marker)

p.write_text(content, encoding="utf-8")
print("L49 加好了")
