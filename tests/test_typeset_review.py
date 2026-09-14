"""test_typeset_review — typeset 成品图报告的深接口 + HTML 报告铁律守卫。

2026-09-14：`scripts/gen_typeset_review.py` 等 CLI 薄壳已归档到 scripts/archive/，
HTML 生成逻辑全部在 `src/amta/report/typeset_review.py` 深接口。测试分两半：

1. 深接口行为（渲染出含内嵌图的 HTML）
2. **铁律守卫**——scripts/ 下现存的 gen_*.py 里不允许再出现 HTML 标签。
   把"铁律"变成机械可查的断言，而不是只写在宪法里靠自觉。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from amta.report.typeset_review import render_typeset_review

ROOT = Path(__file__).resolve().parent.parent


def _mk_png(path: Path, color: str = "white") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), color).save(path)
    return path


class TestRenderTypesetReview:
    def test_writes_html_with_embedded_image(self, tmp_path):
        img = _mk_png(tmp_path / "page_1_final.png")
        out = tmp_path / "review.html"
        result = render_typeset_review([img], title="成品审查", out_path=out)
        assert result == out
        html = out.read_text(encoding="utf-8")
        assert "data:image/png;base64," in html
        assert "成品审查" in html
        assert "page_1_final.png" in html

    def test_reports_image_count(self, tmp_path):
        imgs = [_mk_png(tmp_path / f"page_{i}_final.png") for i in (1, 2, 3)]
        out = tmp_path / "review.html"
        render_typeset_review(imgs, title="T", out_path=out)
        assert "共 3 张图片" in out.read_text(encoding="utf-8")

    def test_creates_parent_dir(self, tmp_path):
        img = _mk_png(tmp_path / "p.png")
        out = tmp_path / "deep" / "nested" / "r.html"
        render_typeset_review([img], title="T", out_path=out)
        assert out.exists()

    def test_empty_list_is_allowed(self, tmp_path):
        """渲染器不管"有没有图"——找图是 CLI 的事（职责分离）。"""
        out = tmp_path / "empty.html"
        render_typeset_review([], title="T", out_path=out)
        assert "共 0 张图片" in out.read_text(encoding="utf-8")


class TestHtmlReportIronLaw:
    """铁律守卫：HTML 只能是深接口的产物，scripts/ 下不许有模板。"""

    def test_deep_interface_module_exists(self):
        assert (ROOT / "src" / "amta" / "report" / "typeset_review.py").exists()

    def test_other_gen_scripts_contain_no_html(self):
        """同一条铁律对所有制图脚本生效（不只这一支）。"""
        offenders = []
        for script in sorted((ROOT / "scripts").glob("gen_*.py")):
            body = script.read_text(encoding="utf-8")
            if "<!DOCTYPE" in body or "<style" in body:
                offenders.append(script.name)
        assert offenders == [], f"以下 scripts/ 脚本内嵌了 HTML 模板：{offenders}"
