# 修复重排时黑气泡被刷白 + 验证竖排数字旋转渲染 Implementation Plan

> **For agentic workers:** 本计划由 MainAgent 直接 inline 执行，不需要 subagent。

**Goal:** 修复 retypeset 脚本把黑气泡（如"等一下""你也逮捕"）整个刷成白矩形的回归，只让竖排数字/英文的旋转渲染生效，其他气泡逐像素不变。

**Architecture:** 根因是 `workspace/retypeset_from_original.py` 的 `rebuild_clean_from_original()` 对每个 `fill_white` bbox 都 `draw.rectangle(fill="white")`，不区分气泡底色。原始 inpaint 流水线用 CTD 文字 mask + LaMa 只擦文字像素、保留气泡底色。修复方式：对每个 bbox 从原始成品图采样中位数底色，用该底色填充（白泡→白，黑泡→黑），并内缩 10px 避免圆角气泡的矩形角溢出。

**Tech Stack:** Python 3, PIL/Pillow, numpy, 现有 amta.typeset.typeset_station 管线。

---

## 背景诊断结论

### 对比证据
- 原图 `D:\我的汉化\汉化作品\东方\灵梦和妹红\成品\13.png`：中间"等一下"是黑色椭圆+白字，左下"你也逮捕"是黑色椭圆+白字。
- 新图 `workspace/book-a8ad0022a4f078a1/artifacts/final/page_13_final.png`：这两个黑椭圆被捅成白色矩形窟窿，字也变成了黑字。
- 重建的 clean 图 `clean/page_13_clean.png` 直接可见：黑椭圆上贴了白矩形。

### 根因链
1. 原始 inpaint（`src/amta/inpaint/inpaint_station.py`）对气泡用 **CTD 像素文字 mask + LaMa 修复**——只擦日文文字像素，气泡底色（含黑泡）完整保留。
2. `rebuild_clean_from_original()` 没有 CTD mask 可用（raw 图已 GC），退化成"把整个 bbox 刷白"。
3. `typeset_render.py` 的 `_decide_color_and_stroke()` 采样 clean 图背景亮度决定字色：白矩形→黑字，黑椭圆→白字。clean 被刷白后，黑泡上就出了黑字+白矩形。
4. 交接文档里说"typeset_engine.py 已回退"，但 `git diff` 显示它还有 1 行 docstring 改动（无行为影响）。

### 受影响 bbox（page_13, book-a8ad0022a4f078a1）
| region | bbox | 气泡类型 | 当前 rebuild 结果 |
|--------|------|----------|------------------|
| r00 | [1048,1874,1341,2459] | 白椭圆（含"100"） | 白矩形（可接受，但应填白） |
| r01 | [1320,2512,1552,3112] | 白椭圆（含"65"） | 白矩形 |
| **r02** | **[153,1975,421,2400]** | **黑椭圆"你也逮捕"** | **白矩形（BUG）** |
| **r03** | **[1137,1323,1361,1742]** | **黑椭圆"等一下"** | **白矩形（BUG）** |
| r04-r10 | 其余 7 个 | 白泡/爆泡 | 白矩形（在白底上不显眼） |

---

### Task 1: 建分支

**Files:** 无

- [ ] **Step 1: 从 main 建 fix 分支**

```powershell
cd "E:\manga translator agent"
git checkout -b fix/dark-bubble-retypeset
```

预期：分支创建成功，当前在 fix/dark-bubble-retypeset。

---

### Task 2: 修复 rebuild_clean_from_original 的刷白逻辑

**Files:**
- Modify: `workspace/retypeset_from_original.py`
- Modify: `workspace/retypeset_pages.py`（同步修复 reconstruct_clean_image）

- [ ] **Step 1: 改写 rebuild_clean_from_original，用中位数底色填充**

把 `rebuild_clean_from_original` 函数里的填充逻辑从：

```python
for action in inpaint_doc.get("actions", []):
    if action.get("action") == "fill_white":
        x1, y1, x2, y2 = action["bbox"]
        draw.rectangle([x1, y1, x2, y2], fill="white")
```

改为：

```python
import numpy as np

def _fill_bubble_bg(img: Image.Image, bbox: list, shrink: int = 10) -> None:
    """用 bbox 内中位数底色填充气泡区域，保留黑泡底色。

    原始 inpaint 用 CTD+LaMa 只擦文字像素；这里没有 raw 图，退化为整框填色。
    采样整个 bbox 的中位数颜色：文字像素占比 <5%，中位数鲁棒，白泡得白、黑泡得黑。
    shrink 内缩避免圆角气泡的矩形角溢出到画稿上。
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1 + shrink), max(0, y1 + shrink)
    x2, y2 = min(img.width, x2 - shrink), min(img.height, y2 - shrink)
    if x2 <= x1 or y2 <= y1:
        return
    arr = np.array(img.crop((x1, y1, x2, y2)))
    med = tuple(int(v) for v in np.median(arr.reshape(-1, arr.shape[-1]), axis=0))
    ImageDraw.Draw(img).rectangle([x1, y1, x2, y2], fill=med)
```

然后循环体改为：

```python
for action in inpaint_doc.get("actions", []):
    if action.get("action") == "fill_white":
        _fill_bubble_bg(img, action["bbox"])
```

- [ ] **Step 2: 同步改 retypeset_pages.py 的 reconstruct_clean_image**

同样把 `draw.rectangle([x1, y1, x2, y2], fill="white")` 换成 `_fill_bubble_bg(img, action["bbox"])`，并在文件顶部 import numpy + 复制 `_fill_bubble_bg` 函数。

- [ ] **Step 3: 快速自测——重建 page_13 clean 并检查黑泡**

```powershell
cd "E:\manga translator agent"
.venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, 'src')
from pathlib import Path
from workspace.retypeset_from_original import rebuild_clean_from_original
art = Path(r'workspace/book-a8ad0022a4f078a1/artifacts')
p = rebuild_clean_from_original(art, 'page_13', Path(r'D:\我的汉化\汉化作品\东方\灵梦和妹红\成品\13.png'))
print('clean saved:', p)
"
```

预期：clean/page_13_clean.png 里 r02/r03 位置不再是白矩形，而是黑底（与周围黑椭圆融合）。

- [ ] **Step 4: 视觉检查 clean 图**

用 Read 工具打开 `workspace/book-a8ad0022a4f078a1/artifacts/clean/page_13_clean.png`，确认：
  - r03"等一下"位置：黑椭圆内部是黑的，没有白矩形窟窿
  - r02"你也逮捕"位置：黑椭圆内部是黑的
  - 其他白泡位置：是白的

---

### Task 3: 重排 page_13（book-a8ad）

**Files:** 无代码改动，运行脚本

- [ ] **Step 1: 运行 retypeset_from_original.py**

```powershell
cd "E:\manga translator agent"
.venv\Scripts\python.exe workspace\retypeset_from_original.py book-a8ad0022a4f078a1 page_13 "D:\我的汉化\汉化作品\东方\灵梦和妹红\成品\13.png"
```

预期：rendered=N overflow=0，无报错。

- [ ] **Step 2: 视觉检查最终成品**

用 Read 打开 `workspace/book-a8ad0022a4f078a1/artifacts/final/page_13_final.png`，与原图 `D:\...\13.png` 并排对比：
  - ✅ r03"等一下"：黑椭圆+白字（与原图一致）
  - ✅ r02"你也逮捕"：黑椭圆+白字（与原图一致）
  - ✅ 其他白泡：位置、字色、排版与原图一致
  - ⚠️ r00"罚金100万日"：数字"100"应是旋转90°竖过来的效果（这是预期改动）
  - ⚠️ r01"道交法第65条第2项"："65"和"2"应是旋转效果

---

### Task 4: 重排 page_59（touhou-getten-shinchi）

**Files:** 无代码改动

说明：这本书的 clean 图全部还在（没被 GC），不需要 rebuild，直接用 retypeset_pages.py 重跑 typeset 阶段即可。

- [ ] **Step 1: 运行 retypeset_pages.py**

```powershell
cd "E:\manga translator agent"
.venv\Scripts\python.exe workspace\retypeset_pages.py touhou-getten-shinchi page_59
```

预期：rendered=N overflow=0。

- [ ] **Step 2: 视觉检查**

用 Read 打开 `workspace/touhou-getten-shinchi/artifacts/final/page_59_final.png`，与原图 `D:\...\59.png` 对比：
  - ✅ 黑泡"鸣哇 可疑人物："（右下）保持黑底白字
  - ✅ 其他纯中文气泡不变
  - ⚠️ 含英文字母的气泡（顶部"那不穿了吗"附近、中部"什么啊！是"附近）：英文应作为整体旋转竖排，不再散乱

---

### Task 5: 最终确认 + 提交

- [ ] **Step 1: 终检两页**

再次 Read 两张 final 图，确认：
  1. 只有数字/英文字母的渲染变了
  2. 所有气泡形状/底色/位置与原图一致
  3. 没有白矩形窟窿

- [ ] **Step 2: 提交**

```powershell
cd "E:\manga translator agent"
git add workspace/retypeset_from_original.py workspace/retypeset_pages.py
git commit -m "fix(workspace): retypeset rebuild 用中位数底色填充，不再把黑泡刷成白矩形"
```

---

## Self-Review 记录

- **Spec 覆盖**：用户要求①诊断 masking 被改 ②建分支修复 ③只改数字、其他不变 ④重排 page_13 和 59 ⑤视觉校验。全部覆盖。
- **占位符扫描**：无 TBD/TODO，所有代码块完整。
- **类型一致**：`_fill_bubble_bg` 在两个脚本里签名一致。
