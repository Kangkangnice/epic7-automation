"""P0 护栏：会花资源 / 不可逆的路线，在「画面认不出」时不得给出点击。

为什么单独一个文件而不住在各路线自己的测试里
------------------------------------------
这条约束是**跨路线**的：它的依据不是某条路线的业务逻辑，而是「花出去就回不来」
这件事本身。放在这里，新增路线只要往 ``RESOURCE_ROUTES`` 里加个名字，就自动被问一次
「你认不出画面时会不会照样点」—— 而住在各自的测试里，新路线很容易漏掉这一问。

判据口径（2026-11-09 定）
------------------------
「全黑帧」= 窗口被遮挡 / 抓帧失败 / 游戏还在加载，三种现场都会在 production 里出现。
此时只允许两种结果：

* 返回 ``None`` —— 主循环等超时后安全停止；
* 抛 ``UnrecognizedScreen`` —— 连状态都不推进。

**不许**返回一个带坐标的动作让主循环照着点。注意不是「一律不许返回动作」：
项目里确实有合法的「点一下唤醒」例外（月塔的唤醒器），所以只钉「黑帧」这一种输入，
不越界去规定正常页面上的行为。

⚠️ 这组用例只覆盖「UNKNOWN」这一维。TODO 里另外两维（关键模板缺失 / 判据冲突）
分别由 ``test_missing_templates_fail_at_build_time`` 和各路线自己的页面互斥用例守。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from auto_game_unified.games.epic7.modes import MODE_SPECS
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"

# 动作会消耗资源、或结果不可逆的路线。加新路线时先问一句：它的动作花不花东西？
RESOURCE_ROUTES = (
    # 英雄材料 + 传送（传送不可逆）
    "hero_synthesis",
    # 挑战券 / 刷新对手
    "arena",
    # 体力
    "expedition",
    "story",
    "fodder",
    "tower",
    # 领奖励本身不可逆（领了就没了）
    "achievement",
    "sanctuary",
    # 捐赠次数 / 首领战次数 / 入场次数
    "knights_donation",
    "world_boss",
    "labyrinth_stone",
)

BLACK = np.zeros((1132, 1982, 3), dtype=np.uint8)


@pytest.mark.parametrize("mode", RESOURCE_ROUTES)
def test_an_unrecognised_screen_never_yields_a_click(mode: str) -> None:
    """全黑帧上：要么不给动作，要么直接抛「认不出」。"""
    spec = MODE_SPECS[mode]
    machine = spec.build_machine(TEMPLATES, spec.default_state)

    try:
        action = machine.next_action(BLACK)
    except UnrecognizedScreen:
        return

    assert action is None, (
        f"{mode} 在全黑帧上给出了动作 {action.name!r} @ {getattr(action, 'point', None)}"
        " —— 认不出画面还敢点，这条路线会花资源或不可逆"
    )


@pytest.mark.parametrize("mode", RESOURCE_ROUTES)
def test_missing_templates_fail_at_build_time(mode: str, tmp_path: Path) -> None:
    """模板根是空的时候，装配阶段就该炸，而不是带着半套判据跑到真机上。

    这是「关键模板缺失」那一维：装配期 fail-closed 比运行期少一次误点机会。
    """
    spec = MODE_SPECS[mode]

    with pytest.raises(FileNotFoundError):
        spec.build_machine(tmp_path, spec.default_state)
