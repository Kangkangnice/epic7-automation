"""接力探针共用零件的护栏（``resume_probe``）。

守的是 2026-09-30 的收敛：8 条路线原先各写一份一模一样的
``XxxResumePoint(NamedTuple)``（连字段注释都一字不差），三条页面型探针还逐字重复了
同一段控制流。现在类型只有一份、控制流只有一份。

⚠️ 这里最要紧的一条是 ``test_every_route_uses_the_shared_type`` —— 它防的是「又抄回一份
本地 NamedTuple」：抄回去不会有任何报错，只是下一次改字段时漏改一处，然后再也说不清
哪份是真的。
"""

import numpy as np

from auto_game_unified.games.epic7 import (
    arena,
    expedition,
    knights_donation,
    labyrinth_stone,
    sanctuary,
    shop_refresh,
    story,
    world_boss,
)
from auto_game_unified.games.epic7.resume_probe import (
    ResumePoint,
    observe_page_probe,
)

SCREEN = np.zeros((4, 4, 3), dtype=np.uint8)


class _FakeMachine:
    """只实现 ``observe_page`` / ``mark_entered`` 两个被用到的口子。"""

    def __init__(self, page):
        self._page = page
        self.entered = 0

    def observe_page(self, screen):
        return self._page

    def mark_entered(self):
        self.entered += 1


def test_every_route_uses_the_shared_type():
    for module in (
        arena,
        expedition,
        knights_donation,
        labyrinth_stone,
        sanctuary,
        shop_refresh,
        story,
        world_boss,
    ):
        assert module.ResumePoint is ResumePoint, module.__name__


def test_an_unrecognised_page_never_resumes():
    result = observe_page_probe(
        _FakeMachine(None), SCREEN, resumable={1, 2}, label=str
    )

    assert result is None


def test_a_page_outside_the_resumable_set_never_resumes():
    result = observe_page_probe(
        _FakeMachine(9), SCREEN, resumable={1, 2}, label=str
    )

    assert result is None


def test_a_resumable_page_gets_a_bare_point():
    result = observe_page_probe(
        _FakeMachine(2), SCREEN, resumable={1, 2}, label=lambda page: f"第{page}页"
    )

    assert result == ResumePoint(page="第2页")
    # 这三条路线都是「每帧重判页面」，所以状态恒为 None：拨了下一帧就被覆盖。
    assert result.state is None
    assert result.entry is None


def test_the_entry_page_carries_the_navigation_entry():
    result = observe_page_probe(
        _FakeMachine(1),
        SCREEN,
        resumable={1, 2},
        entry_page=1,
        entry="chain_page",
        label=str,
    )

    assert result == ResumePoint(page="1", entry="chain_page")


def test_an_entry_page_outside_the_resumable_set_is_never_reached():
    """``resumable`` 必须包含 ``entry_page`` —— 这是文档里写明的调用约束。

    先判「不在 resumable 里 -> None」，所以漏了它这一步永远走不到。
    """
    result = observe_page_probe(
        _FakeMachine(5),
        SCREEN,
        resumable={1, 2},
        entry_page=5,
        entry="chain_page",
        label=str,
    )

    assert result is None


def test_the_after_entry_hook_fires_exactly_once_for_the_listed_pages():
    machine = _FakeMachine(3)

    observe_page_probe(
        machine,
        SCREEN,
        resumable={3, 4},
        after_entry={3},
        label=str,
    )

    assert machine.entered == 1


def test_the_after_entry_hook_stays_quiet_for_other_pages():
    machine = _FakeMachine(4)

    observe_page_probe(
        machine,
        SCREEN,
        resumable={3, 4},
        after_entry={3},
        label=str,
    )

    assert machine.entered == 0
