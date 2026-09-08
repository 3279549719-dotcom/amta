"""生成rule_filter误伤审计HTML报告，base64嵌入图片，自包含。"""
import os, json, base64

# 9个滤除框的详细信息
BOXES = [
    {"page": 2, "rid": "t04", "rule": "pure_punct", "w": 56, "h": 247, "aspect": 4.4, "conf": 0.704, "btype": "text_free", "ocr": "...", "judgment": "真杂质", "color": "#00cc00", "desc": "量筒上的刻度线，背景装饰，非文字"},
    {"page": 6, "rid": "t08", "rule": "extreme_aspect", "w": 26, "h": 857, "aspect": 33.0, "conf": 0.789, "btype": "text_free", "ocr": "乱码", "judgment": "真杂质", "color": "#00cc00", "desc": "页面最左侧纯黑竖条，扫描边缘/装订线"},
    {"page": 13, "rid": "r01", "rule": "extreme_aspect", "w": 118, "h": 996, "aspect": 8.4, "conf": 0.921, "btype": "text_bubble", "ocr": "うおおおおおおお!", "judgment": "误伤", "color": "#ff3333", "desc": "竖排喊叫，角色大喊，完完全全的真实对话"},
    {"page": 16, "rid": "r03", "rule": "edge_box", "w": 254, "h": 368, "aspect": 1.4, "conf": 0.964, "btype": "text_bubble", "ocr": "最初は私も二人の手助けをしなければならないと思う", "judgment": "误伤", "color": "#ff3333", "desc": "竖排对话，正常气泡，左边贴边2px被误杀"},
    {"page": 20, "rid": "r00", "rule": "edge_box", "w": 824, "h": 215, "aspect": 3.8, "conf": 0.913, "btype": "text_free", "ocr": "月の民はいかにして地上から月へ移住したのか", "judgment": "误伤", "color": "#ff3333", "desc": "黑底白字横排旁白，左边贴边7px被误杀"},
    {"page": 22, "rid": "r08", "rule": "edge_box", "w": 87, "h": 324, "aspect": 3.7, "conf": 0.935, "btype": "text_bubble", "ocr": "大事なのはここから", "judgment": "误伤", "color": "#ff3333", "desc": "竖排对话，正常气泡，左边贴边5px被误杀"},
    {"page": 31, "rid": "t08", "rule": "extreme_aspect", "w": 41, "h": 619, "aspect": 15.1, "conf": 0.725, "btype": "text_free", "ocr": "美術館は、", "judgment": "边界", "color": "#ffaa00", "desc": "页面最左侧竖线，扫描边缘，OCR有文字但肉眼更像噪点"},
    {"page": 33, "rid": "r01", "rule": "extreme_aspect", "w": 137, "h": 1324, "aspect": 9.7, "conf": 0.901, "btype": "text_bubble", "ocr": "そのとき採れる手段は表向きだけでも月の世界に迎合するか", "judgment": "误伤", "color": "#ff3333", "desc": "竖排长对话，正常竖排气泡，宽高比9.7被误杀"},
    {"page": 41, "rid": "r00", "rule": "extreme_aspect", "w": 1029, "h": 125, "aspect": 8.2, "conf": 0.891, "btype": "text_free", "ocr": "東方Project Fanbook その2", "judgment": "误伤", "color": "#ff3333", "desc": "封底标题，横排文字，宽高比8.2被误杀"},
]

ANNOTATED_DIR = r"E:\manga translator agent\amta\workspace\_rule_filter_probe\annotated"
OUT_HTML = r"E:\manga translator agent\amta\output\rule_filter_audit.html"
os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)

def img_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")

# 统计
n_total = len(BOXES)
n_false = sum(1 for b in BOXES if b["judgment"] == "误伤")
n_true = sum(1 for b in BOXES if b["judgment"] == "真杂质")
n_edge = sum(1 for b in BOXES if b["judgment"] == "边界")

# 按规则统计
rule_stats = {}
for b in BOXES:
    r = b["rule"]
    if r not in rule_stats:
        rule_stats[r] = {"total": 0, "false": 0, "true": 0, "edge": 0}
    rule_stats[r]["total"] += 1
    if b["judgment"] == "误伤":
        rule_stats[r]["false"] += 1
    elif b["judgment"] == "真杂质":
        rule_stats[r]["true"] += 1
    else:
        rule_stats[r]["edge"] += 1

html_parts = []
html_parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rule Filter 误伤审计报告 — 单翼停留之地</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #1a1a2e; color: #eee; line-height: 1.6; }
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  h1 { text-align: center; font-size: 28px; margin-bottom: 8px; color: #fff; }
  .subtitle { text-align: center; color: #888; margin-bottom: 30px; font-size: 14px; }
  .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }
  .stat-card { background: #16213e; border-radius: 10px; padding: 20px; text-align: center; border: 1px solid #0f3460; }
  .stat-card .num { font-size: 36px; font-weight: bold; }
  .stat-card .label { font-size: 13px; color: #888; margin-top: 5px; }
  .stat-false .num { color: #ff4444; }
  .stat-true .num { color: #44cc44; }
  .stat-edge .num { color: #ffaa00; }
  .stat-total .num { color: #4488ff; }
  .rule-table { width: 100%; border-collapse: collapse; margin-bottom: 30px; background: #16213e; border-radius: 10px; overflow: hidden; }
  .rule-table th, .rule-table td { padding: 12px 15px; text-align: center; border-bottom: 1px solid #0f3460; }
  .rule-table th { background: #0f3460; color: #fff; font-weight: 600; }
  .rule-table tr:last-child td { border-bottom: none; }
  .false-rate-high { color: #ff4444; font-weight: bold; }
  .false-rate-low { color: #44cc44; }
  .box-section { margin-bottom: 40px; background: #16213e; border-radius: 12px; overflow: hidden; border: 1px solid #0f3460; }
  .box-header { padding: 18px 25px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
  .box-title { font-size: 20px; font-weight: bold; }
  .box-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: bold; margin-left: 10px; }
  .badge-false { background: rgba(255,68,68,0.2); color: #ff4444; border: 1px solid #ff4444; }
  .badge-true { background: rgba(68,204,68,0.2); color: #44cc44; border: 1px solid #44cc44; }
  .badge-edge { background: rgba(255,170,0,0.2); color: #ffaa00; border: 1px solid #ffaa00; }
  .box-meta { font-size: 13px; color: #aaa; }
  .box-meta span { margin-right: 15px; }
  .box-meta .highlight { color: #ffcc00; font-weight: bold; }
  .box-image { width: 100%; display: block; }
  .box-image img { width: 100%; height: auto; display: block; }
  .box-desc { padding: 15px 25px; background: #0f1a2e; font-size: 14px; color: #ccc; }
  .box-desc .ocr-text { color: #66ccff; font-family: monospace; background: #0a1525; padding: 8px 12px; border-radius: 6px; margin-top: 8px; display: inline-block; }
  .legend { display: flex; gap: 20px; justify-content: center; margin-bottom: 20px; font-size: 14px; }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-dot { width: 14px; height: 14px; border-radius: 3px; }
  .conclusion { background: #16213e; border-radius: 12px; padding: 25px; margin-top: 30px; border-left: 4px solid #ff4444; }
  .conclusion h2 { color: #ff4444; margin-bottom: 15px; font-size: 20px; }
  .conclusion ul { padding-left: 20px; }
  .conclusion li { margin-bottom: 10px; color: #ccc; }
  .conclusion li strong { color: #fff; }
</style>
</head>
<body>
<div class="container">
""")

html_parts.append(f"""
  <h1>Rule Filter 误伤审计报告</h1>
  <p class="subtitle">作品：单翼停留之地（東方Project Fanbook） | 全40页 | 检测conf=0.7 | rule_filter已激活</p>
  
  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#ff3333"></div>红框 = 误伤</div>
    <div class="legend-item"><div class="legend-dot" style="background:#00cc00"></div>绿框 = 真杂质</div>
    <div class="legend-item"><div class="legend-dot" style="background:#ffaa00"></div>黄框 = 边界/待确认</div>
  </div>
  
  <div class="summary">
    <div class="stat-card stat-total"><div class="num">{n_total}</div><div class="label">总滤除框数</div></div>
    <div class="stat-card stat-false"><div class="num">{n_false}</div><div class="label">明确误伤</div></div>
    <div class="stat-card stat-true"><div class="num">{n_true}</div><div class="label">真杂质</div></div>
    <div class="stat-card stat-edge"><div class="num">{n_edge}</div><div class="label">边界待确认</div></div>
  </div>
  
  <table class="rule-table">
    <tr><th>规则</th><th>触发次数</th><th>误伤</th><th>真杂质</th><th>边界</th><th>误伤率</th></tr>
""")

for rule, stats in rule_stats.items():
    rate = stats["false"] / stats["total"] * 100 if stats["total"] > 0 else 0
    rate_class = "false-rate-high" if rate >= 50 else "false-rate-low"
    html_parts.append(f"""    <tr><td><strong>{rule}</strong></td><td>{stats['total']}</td><td>{stats['false']}</td><td>{stats['true']}</td><td>{stats['edge']}</td><td class="{rate_class}">{rate:.0f}%</td></tr>\n""")

html_parts.append("  </table>\n")

# 每个框的详情
for b in BOXES:
    img_path = os.path.join(ANNOTATED_DIR, f"page_{b['page']}_annotated.jpg")
    if os.path.exists(img_path):
        b64 = img_to_base64(img_path)
        img_tag = f'<img src="data:image/jpeg;base64,{b64}" alt="page_{b["page"]}">'
    else:
        img_tag = '<p style="padding:20px;color:#888">图片未找到</p>'
    
    badge_class = f"badge-{b['judgment']}"
    if b['judgment'] == '误伤':
        badge_class = 'badge-false'
    elif b['judgment'] == '真杂质':
        badge_class = 'badge-true'
    else:
        badge_class = 'badge-edge'
    
    html_parts.append(f"""
  <div class="box-section">
    <div class="box-header">
      <div class="box-title">Page {b['page']} — {b['rid']}
        <span class="box-badge {badge_class}">{b['judgment']}</span>
      </div>
      <div class="box-meta">
        <span>规则: <span class="highlight">{b['rule']}</span></span>
        <span>尺寸: {b['w']}×{b['h']}</span>
        <span>宽高比: <span class="highlight">{b['aspect']}</span></span>
        <span>conf: <span class="highlight">{b['conf']}</span></span>
        <span>类型: {b['btype']}</span>
      </div>
    </div>
    <div class="box-image">{img_tag}</div>
    <div class="box-desc">
      <strong>判断：</strong>{b['desc']}
      <br><strong>OCR文本：</strong><span class="ocr-text">{b['ocr']}</span>
    </div>
  </div>
""")

html_parts.append(f"""
  <div class="conclusion">
    <h2>核心结论</h2>
    <ul>
      <li><strong>误伤率 {n_false}/{n_total} = {n_false/n_total*100:.0f}%</strong>：9个被过滤的框中，{n_false}个是完完全全的真实对话/旁白/标题，仅{n_true}个是真杂质。</li>
      <li><strong>edge_box规则 100%误伤</strong>：触发3次，3次全是真实对话（p16、p20、p22），零真杂质过滤。</li>
      <li><strong>extreme_aspect与日漫竖排物理特性冲突</strong>：竖排对话天然高宽比大（p13=8.4、p33=9.7），横排标题天然宽高比大（p41=8.2），阈值8直接误杀。</li>
      <li><strong>真杂质conf全部&lt;0.8，误伤全部&gt;0.89</strong>：confidence本身已经能区分两类，几何规则是在已排序结果上用更粗糙的标准重筛。</li>
      <li><strong>建议</strong>：① 直接关闭edge_box规则（100%误伤零收益）；② extreme_aspect阈值从8提到15以上（仅过滤p6那种33.0的极端条），或直接关闭；③ 考虑用conf阈值（0.8）替代几何规则。</li>
    </ul>
  </div>
  
</div>
</body>
</html>
""")

with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write("".join(html_parts))

print(f"HTML报告已生成: {OUT_HTML}")
print(f"文件大小: {os.path.getsize(OUT_HTML) / 1024 / 1024:.2f} MB")
