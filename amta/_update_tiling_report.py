"""更新瓦片化报告：加入逐框核对表（新增绿框 12真1假 + 黄框杂质说明）。"""
from __future__ import annotations

from pathlib import Path

OUT = Path(r"E:\manga translator agent\amta\output\tiling_report.html")

AUDIT_TABLE = """
<h2>瓦片化新增 ≥0.7 框逐个人眼核对（4 页共 13 个：12 真 1 假）</h2>
<table>
<tr><th>页面</th><th>框内容</th><th>conf</th><th>判定</th></tr>
<tr><td>p14</td><td>いたい！</td><td>0.771</td><td style="color:#1a7f37;font-weight:700">真对白（漏检修复）</td></tr>
<tr><td>p14</td><td>ハ意様（八意様）</td><td>0.812</td><td style="color:#1a7f37;font-weight:700">真字</td></tr>
<tr><td>p14</td><td>ん だ ——！（含发丝纹理）</td><td>0.810</td><td style="color:#1a7f37;font-weight:700">真字（框略大）</td></tr>
<tr><td>p15</td><td>はい</td><td>0.907</td><td style="color:#1a7f37;font-weight:700">真对白（漏检修复）</td></tr>
<tr><td>p15</td><td>八意様の…えつ！？</td><td>0.940</td><td style="color:#1a7f37;font-weight:700">真对白（漏检修复）</td></tr>
<tr><td>p15</td><td>ずの子供が</td><td>0.834</td><td style="color:#1a7f37;font-weight:700">真字</td></tr>
<tr><td>p15</td><td>刺绣徽章图案</td><td>0.731</td><td style="color:#b35900;font-weight:700">❌ 杂质（OCR 可滤）</td></tr>
<tr><td>p17</td><td>おとな…</td><td>0.878</td><td style="color:#1a7f37;font-weight:700">真对白（漏检修复）</td></tr>
<tr><td>p17</td><td>にあてる</td><td>0.873</td><td style="color:#1a7f37;font-weight:700">真字</td></tr>
<tr><td>p17</td><td>ご苦労</td><td>0.872</td><td style="color:#1a7f37;font-weight:700">真对白（漏检修复）</td></tr>
<tr><td>p17</td><td>しない</td><td>0.861</td><td style="color:#1a7f37;font-weight:700">真字</td></tr>
<tr><td>p19</td><td>サグ姉</td><td>0.835</td><td style="color:#1a7f37;font-weight:700">真对白（漏检修复）</td></tr>
<tr><td>p19</td><td>そぉ～</td><td>0.738</td><td style="color:#1a7f37;font-weight:700">真对白（漏检修复）</td></tr>
</table>
<p style="color:#666;font-size:12px">
注：黄框（conf 0.3~0.7）是实验全貌显示，产线 0.7 阈值会滤掉；黄框区确实混有斜纹/网点/发丝/波浪线等杂质，
但均 <0.7 不进产线。真正需要担心的是"瓦片化是否让杂质升过 0.7"——答案：13 个新增里仅 1 个杂质，且 OCR 可滤。
</p>
<hr/>
"""

html = OUT.read_text(encoding="utf-8")
# 在第一个 <hr/> 后插入核对表（即结论块之后、Page 14 之前）
marker = '<hr/>\n\n<h2>Page 14'
if marker in html:
    html = html.replace(marker, '<hr/>\n' + AUDIT_TABLE + '\n<h2>Page 14', 1)
else:
    html = html.replace('<hr/>', '<hr/>\n' + AUDIT_TABLE, 1)
OUT.write_text(html, encoding="utf-8")
print("updated:", OUT, len(html) // 1024, "KB")
