"""test_fastcheck_guard_order — 收尾护栏**接口**的回归测试（2026-10-01）。

## 为什么要有这个文件

`fastcheck` 旧写法是 `checks: list[tuple[str, int]]`——一个"步骤枚举"。
而"谁必须排在谁前面"当时只写在代码顺序里（和一段注释里）：`module-map` 刷新
写在 pytest **之后**，于是 `test_reference_integrity` 里那条「地图必须新鲜」的
断言在**同一次 fastcheck 内**看到的是上一次刷新的结果。

后果是确定性的：**任何改动公开接口的提交，第一遍 `state.py finish` 必红，
第二遍才绿**——每次白烧一遍 6 分钟全量 pytest。实测就发生在写这个文件的那天。

修法不是"把两行代码对调"（那是把同一个隐式关系换个地方藏），而是给护栏定一个
**接口**：`repairs`（我修什么生成物）/ `depends_on`（我的判定以什么新鲜为前提）/
`action`（红项可行动）。顺序由 `order_guards()` 从这两个字段推出来。
本文件锁住这个接口的四条性质——接口没了，同一次事故会以新形状回来。
"""
from __future__ import annotations

import pytest

from scripts.fastcheck import ClosingGuard, order_guards, run_guards


def _noop() -> int:
    return 0


def _guard(name: str, *, repairs=(), depends_on=(), action="做点什么") -> ClosingGuard:
    return ClosingGuard(
        name=name, category=f"{name} 的类别", fn=_noop,
        repairs=tuple(repairs), depends_on=tuple(depends_on), action=action,
    )


class TestOrderIsDerivedNotRemembered:
    """顺序从声明里推出来——不靠人记得把刷新写在断言前面。"""

    def test_repair_moves_ahead_of_its_dependent(self):
        """**故意写反**：声明顺序是 [依赖方, 生成方]，调度必须把它掰正。

        这就是 2026-10-01 那次事故的形状：写反了，而且没人看得出来。
        """
        consumer = _guard("tests", depends_on=["docs/gen.md"])
        producer = _guard("regen", repairs=["docs/gen.md"])

        ordered = order_guards([consumer, producer])

        assert [g.name for g in ordered] == ["regen", "tests"]

    def test_independent_guards_keep_declaration_order(self):
        """没有关系的护栏保持声明顺序（稳定），别乱动。"""
        a, b, c = _guard("a"), _guard("b"), _guard("c")
        assert [g.name for g in order_guards([a, b, c])] == ["a", "b", "c"]

    def test_chain_is_ordered_end_to_end(self):
        """a 修 X → b 依赖 X 且修 Y → c 依赖 Y：链条要整体排开。"""
        a = _guard("a", repairs=["X"])
        b = _guard("b", repairs=["Y"], depends_on=["X"])
        c = _guard("c", depends_on=["Y"])
        assert [g.name for g in order_guards([c, b, a])] == ["a", "b", "c"]

    def test_cycle_does_not_hang(self):
        """真有环时保序返回，不卡死调度器。"""
        a = _guard("a", repairs=["X"], depends_on=["Y"])
        b = _guard("b", repairs=["Y"], depends_on=["X"])
        assert sorted(g.name for g in order_guards([a, b])) == ["a", "b"]


class TestOrphanPremiseIsLoud:
    """声明了前提却没人提供 → 当场抛，不许安静地永远为真（L58）。"""

    def test_unsatisfied_dependency_raises(self):
        consumer = _guard("tests", depends_on=["docs/gen.md"])
        with pytest.raises(ValueError, match="前提没人保证"):
            order_guards([consumer])

    def test_removing_the_producer_is_caught(self):
        """反向验证：把生产者摘掉（=有人删了 module-map 步骤），必须炸。"""
        producer = _guard("regen", repairs=["docs/gen.md"])
        consumer = _guard("tests", depends_on=["docs/gen.md"])
        assert order_guards([producer, consumer])
        with pytest.raises(ValueError):
            order_guards([consumer])


class TestRepairOutcomeIsNotRed:
    """生成物类护栏：**先修再验**，刷新不是失败。"""

    def test_rewrite_is_reported_as_refreshed_not_failed(self, tmp_path, monkeypatch):
        """刷新的结果必须记为「刷新」且 ok=True——它不该制造一次红。"""
        import scripts.fastcheck as fc

        monkeypatch.setattr(fc, "ROOT", tmp_path)
        target = tmp_path / "gen.md"
        target.write_text("old\n", encoding="utf-8")

        def regenerate() -> int:
            target.write_text("new\n", encoding="utf-8")
            return 0

        guard = ClosingGuard(
            name="regen", category="生成物与代码一致", fn=regenerate,
            repairs=("gen.md",), action="生成器坏了",
        )
        (result,) = run_guards([guard])

        assert result.ok, "刷新被当成了失败——这正是那次假红"
        assert result.status == "刷新"
        assert result.refreshed == ("gen.md",)
        assert "重写: gen.md" in result.render()

    def test_no_change_is_plain_ok(self, tmp_path, monkeypatch):
        import scripts.fastcheck as fc

        monkeypatch.setattr(fc, "ROOT", tmp_path)
        (tmp_path / "gen.md").write_text("same\n", encoding="utf-8")

        guard = ClosingGuard(
            name="regen", category="生成物与代码一致", fn=_noop,
            repairs=("gen.md",), action="生成器坏了",
        )
        (result,) = run_guards([guard])

        assert result.ok and result.status == "OK"
        assert result.refreshed == ()

    def test_broken_generator_is_still_red(self, tmp_path, monkeypatch):
        """先修再验 ≠ 永远放行：生成器自己坏了必须红。"""
        import scripts.fastcheck as fc

        monkeypatch.setattr(fc, "ROOT", tmp_path)
        guard = ClosingGuard(
            name="regen", category="生成物与代码一致", fn=lambda: 1,
            repairs=("gen.md",), action="跑 peek.py --index 看报错",
        )
        (result,) = run_guards([guard])

        assert not result.ok
        assert result.status == "FAIL"


class TestRealRosterHonorsTheInterface:
    """真实名单必须满足接口契约（不然接口只是摆设）。"""

    def test_full_roster_puts_module_map_before_unit_tests(self):
        """真实名单里 `module-map` 必须排在 `unit tests` 前面（顺序是推出来的）。"""
        import scripts.fastcheck as fc

        names = [g.name for g in order_guards(fc._guard_roster(quick=False))]

        assert "module-map" in names and "unit tests" in names
        assert names.index("module-map") < names.index("unit tests"), (
            "地图刷新排到了 pytest 后面——第一遍 finish 又要白红一次"
        )

    def test_every_verify_guard_declares_an_action(self):
        """**红项必须可行动**：不会重写生成物的护栏，红了必须告诉人做什么。"""
        import scripts.fastcheck as fc

        missing = [
            g.name for g in fc._guard_roster(quick=False)
            if not g.repairs and not g.action.strip()
        ]
        assert not missing, f"这些护栏红了却没说人能做什么：{missing}"

    def test_every_guard_declares_its_category(self):
        """每条护栏检测一个**类别**——类别为空说明它还没想清楚自己在守什么。"""
        import scripts.fastcheck as fc

        for quick in (True, False):
            for g in fc._guard_roster(quick=quick):
                assert g.category.strip(), f"{g.name} 没声明它检测的类别"

    def test_quick_roster_is_read_only(self):
        """`--quick` 是 pre-commit 用的只读快检：**不许**有会重写文件的护栏。"""
        import scripts.fastcheck as fc

        writers = [g.name for g in fc._guard_roster(quick=True) if g.repairs]
        assert not writers, f"--quick 里有会写工作区的护栏：{writers}"

    def test_quick_roster_skips_the_full_only_guards(self):
        import scripts.fastcheck as fc

        quick = {g.name for g in fc._guard_roster(quick=True)}
        full = {g.name for g in fc._guard_roster(quick=False)}
        assert quick < full
        assert "unit tests" not in quick and "module-map" not in quick
