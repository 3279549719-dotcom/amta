import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from amta.typeset.fonts import FontNotFoundError, resolve_font


def test_dialogue_uses_msyh_no_stroke(tmp_path):
    (tmp_path / "msyh.ttc").write_bytes(b"x")
    path, stroke = resolve_font("dialogue_bubble", "普通对白", font_dir=tmp_path)
    assert path.name == "msyh.ttc"
    assert stroke == 0


def test_overlay_forces_kai_stroke(tmp_path):
    (tmp_path / "simkai.ttf").write_bytes(b"x")
    (tmp_path / "msyh.ttc").write_bytes(b"x")
    path, stroke = resolve_font("overlay_text", "压脸字", font_dir=tmp_path)
    assert path.name == "simkai.ttf"
    assert stroke == 2.5


def test_shout_uses_bold(tmp_path):
    (tmp_path / "msyhbd.ttc").write_bytes(b"x")
    path, _ = resolve_font("dialogue_bubble", "住手！！", font_dir=tmp_path)
    assert path.name == "msyhbd.ttc"


def test_sfx_uses_handwriting(tmp_path):
    (tmp_path / "FZSTK.TTF").write_bytes(b"x")
    path, stroke = resolve_font("sfx", "ドン", font_dir=tmp_path)
    assert path.name == "FZSTK.TTF"
    assert stroke == 2.5


def test_fallback_chain_and_not_found(tmp_path):
    (tmp_path / "msyh.ttc").write_bytes(b"x")
    path, _ = resolve_font("sfx", "x", font_dir=tmp_path)  # FZSTK 缺失→降级 msyh
    assert path.name == "msyh.ttc"
    with pytest.raises(FontNotFoundError):
        resolve_font("dialogue_bubble", "x", font_dir=tmp_path / "empty")
