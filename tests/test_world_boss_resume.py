"""世界首领战开局接力：认出人停在哪一页就就地接管。

覆盖四件事：

1. **判据** —— 主页 / 选择辅助队伍 / 配置队伍 / 战斗结算 / 战斗级别奖励 / 战斗中，
   以及骑士团主页这个导航链中间站，各自认得出、且带上正确的落点状态与导航落点。
2. **判据与运行期同源** —— 抹掉该页的专属锚点就认不出，证明不是巧合命中。
3. **刻意不接的画面** —— 行动力不足弹窗（不可逆 / 弹窗）、技能演出帧（那种帧 UI 整块
   隐藏，运行期自己也认不出）、骑士团签到与「领取支援物品」弹窗、骑士团主页以外的
   骑士团画面（`lobby_with_knights`）。理由写在 ``world_boss._RESUMABLE_ENTRIES`` 上方。
4. **接线** —— ModeSpec 挂上探针；探针把状态拨进状态机（``WorldBossRunner`` 靠
   ``resumed_from`` 认出「局内接力」）；只有非空跑才把这一局交给战斗监督。

⚠️ 导航层 ``already_at`` 的行为（``worldboss_home`` 零点击 / ``knights_home`` 只走一级 /
未登记的页面报错）已经在 ``tests/test_navigation.py`` 里逐个钉过，这里不重复。
全库跨路线负例扫描单独放 ``runtime_logs/_audit_world_boss_cross_route.py``：单测只留
代表帧，免得每次跑测试都读几百张大图跟实跑抢内存。
"""

from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.games.epic7.evidence.world_boss import REGIONS as WORLD_BOSS_REGIONS
from auto_game_unified.games.epic7.knights_donation import KNIGHTS_GUILD_HOME_PAGE
from auto_game_unified.games.epic7.modes import (
    _probe_world_boss_resume,
    get_mode,
)
from auto_game_unified.games.epic7.world_boss import (
    CLICK_POINTS,
    WORLD_BOSS_ENTRY_PAGE,
    WorldBossRunner,
    WorldBossState,
    WorldBossStateMachine,
    detect_resume_point,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "world_boss"

REFERENCE_WIDTH, REFERENCE_HEIGHT = 1982, 1132

# 能落脚的画面 -> （中文页面名, 要拨过去的状态）。
RESUMABLE_FIXTURES: dict[str, tuple[str, WorldBossState]] = {
    "worldboss_home": ("世界首领战主页", WorldBossState.HOME),
    "worldboss_home_chest_claimable": ("世界首领战主页", WorldBossState.HOME),
    "worldboss_home_chest_claimed": ("世界首领战主页", WorldBossState.HOME),
    # 2026-09-25 实跑那帧：同一个「绿勾」态、整幅偏暗，对可领模板误得 0.8069 越阈。
    # 页面身份不变，所以照样是主页。
    "worldboss_home_chest_claimed_dark": ("世界首领战主页", WorldBossState.HOME),
    "worldboss_home_exhausted": ("世界首领战主页", WorldBossState.HOME),
    # 2026-09-25 实跑那帧：同一个主页、#1 已领（亮度比 1.011）、#2 还亮着（3.197）。
    # 落地宝箱 #2 那道判据的回归依据 —— 只认 #1 会把这一屏当成「没有可领」。
    "worldboss_home_chest2_claimable": ("世界首领战主页", WorldBossState.HOME),
    "team_select": ("选择辅助队伍", WorldBossState.TEAM_SELECT),
    "team_config": ("配置队伍", WorldBossState.TEAM_CONFIG),
    "team_config_configured": ("配置队伍", WorldBossState.TEAM_CONFIG),
    "battle": ("战斗中", WorldBossState.BATTLE),
    "battle_live_skip": ("战斗中", WorldBossState.BATTLE),
    "battle_result": ("战斗结算", WorldBossState.RESULT),
    "level_reward": ("战斗级别奖励", WorldBossState.LEVEL_REWARD),
}

# 骑士团主页（导航链中间站）：不拨状态，只带 ``entry``。
KNIGHTS_HOME_FIXTURES = ("knights_home", "knights_home_after_popup")

# 刻意不接：理由是三类完全不同的东西（见模块 docstring）。
REFUSED_FIXTURES = (
    "battle_skill_anim",
    "gift_support_popup",
    "knights_signin_popup",
    "lobby_with_knights",
    "stamina_popup",
)

ALL_FIXTURES = tuple(RESUMABLE_FIXTURES) + KNIGHTS_HOME_FIXTURES + REFUSED_FIXTURES


def _screen(group: str, name: str) -> np.ndarray:
    """夹具读成 RGB，并裁到基准尺寸。

    - **RGB**：模板是 ``load_template`` 解出来的 RGB，色序必须一致。
    - **裁到基准**：宽高比必须与 1982×1132 一致，否则匹配层直接抛
      「画面宽高比与模板基准不一致」。本路线的 18 张夹具本来就都是基准尺寸，
      这里统一裁只是不给自己留坑。
    """
    bgr = cv2.imread(str(FIXTURES / group / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None, f"夹具不存在：{group}/{name}.png"
    bgr = bgr[:REFERENCE_HEIGHT, :REFERENCE_WIDTH]
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _wb(name: str) -> np.ndarray:
    return _screen("epic7_world_boss", name)


def _machine() -> WorldBossStateMachine:
    return WorldBossStateMachine(TEMPLATES)


def _runner(
    machine: WorldBossStateMachine,
    *,
    dry_run: bool,
    outcome: BattleOutcome = BattleOutcome.RESULT_REACHED,
) -> tuple[WorldBossRunner, MagicMock]:
    runtime = MagicMock()
    runtime.dry_run = dry_run
    runtime.capture.return_value = _wb("worldboss_home")
    supervisor = MagicMock()
    supervisor.run.return_value = outcome
    runner = WorldBossRunner(
        machine, runtime, sleep=lambda _seconds: None, battle_supervisor=supervisor
    )
    return runner, supervisor


# ---- 1. 判据 ----


@pytest.mark.parametrize(
    ("name", "expected_page", "expected_state"),
    tuple(
        (name, page, state) for name, (page, state) in RESUMABLE_FIXTURES.items()
    ),
)
def test_every_business_page_is_a_resume_point(
    name: str, expected_page: str, expected_state: WorldBossState
):
    found = detect_resume_point(_machine(), _wb(name))

    assert found is not None, f"{name} 认不出是哪一页"
    assert found.page == expected_page
    assert found.state is expected_state


def test_the_fixture_lists_cover_every_file_on_disk():
    """18 张夹具一张不落 —— 新增图必须在这里表态（接 / 不接）。

    少了这条，以后往夹具目录里丢一张图不会有人发现「它根本没被考虑过」，
    而「没被考虑过」正是这一轮要根治的那类问题。
    """

    on_disk = {path.stem for path in (FIXTURES / "epic7_world_boss").glob("*.png")}

    assert on_disk == set(ALL_FIXTURES)


def test_only_the_navigation_and_home_pages_carry_an_entry():
    """只有「已经在导航链上」的落点才带 ``entry``。

    主页（``worldboss_home``）与骑士团主页（``knights_home``）各带一个；业务链里的页面
    已经在导航终点之后，再让导航走一趟纯属多余，也会把 Back 发到业务画面上。
    """

    for name in RESUMABLE_FIXTURES:
        found = detect_resume_point(_machine(), _wb(name))

        assert found is not None
        expected = WORLD_BOSS_ENTRY_PAGE if found.state is WorldBossState.HOME else None
        assert found.entry == expected, f"{name} 的导航落点不对"

    for name in KNIGHTS_HOME_FIXTURES:
        found = detect_resume_point(_machine(), _wb(name))

        assert found is not None
        assert found.entry == KNIGHTS_GUILD_HOME_PAGE
        # 还没进入世界首领战，状态机不该被拨到任何一页。
        assert found.state is None


# ---- 2. 刻意不接的画面 ----


@pytest.mark.parametrize("name", REFUSED_FIXTURES)
def test_these_screens_are_deliberately_not_resume_points(name: str):
    """理由分三类，**都不接**：

    - ``stamina_popup``：点「确认购买」要消耗生命之叶（不可逆）。而且它盖在底页上，
      回大厅的那一下 Back 会先把弹窗关掉，下一帧探针就在底页接管了 —— 效果一样更安全。
    - ``battle_skill_anim``：技能演出帧把 UI 整块隐藏，运行期自己的两条战斗判据都不命中
      （``world_boss_battle_visible`` 的注释里写明了这是预期行为），接力没有更神的判据。
    - ``knights_signin_popup`` / ``gift_support_popup``：骑士团的两个弹窗 —— 盖在骑士团
      主页上，回大厅那一下 Back 先关掉它，下一帧就在骑士团主页接管。
    - ``lobby_with_knights``：大厅（只是背景里有骑士团元素），本来就不该接。
    """

    assert detect_resume_point(_machine(), _wb(name)) is None


def test_the_result_page_takes_the_conservative_unclaimed_reward_branch():
    """结算页有歧义，接力**保守取「奖励还没领」那一支**。

    ``next_action`` 靠 ``state is LEVEL_REWARD`` 分岔，而接力只看到一帧、拿不到这个
    上下文。取 ``RESULT`` 就是选「点确认弹奖励」。
    """

    machine = _machine()
    point = detect_resume_point(machine, _wb("battle_result"))

    assert point is not None
    assert point.state is WorldBossState.RESULT

    machine.resume_from(point.state)
    action = machine.next_action(_wb("battle_result"))

    assert action is not None
    assert action.name == "open-level-reward"
    assert action.target_pages == ("战斗级别奖励",)


def test_both_result_branches_click_the_same_button():
    """猜错也不会误触别的功能 —— 两支点的是**同一个按钮**。

    这是「保守取一支」能成立的前提。按钮一旦分开，这条就不成立，
    那时候必须换判据（而不是继续猜）。
    """

    assert CLICK_POINTS["open-level-reward"] == CLICK_POINTS["confirm-result"]

    machine = _machine()
    machine.resume_from(WorldBossState.LEVEL_REWARD)
    action = machine.next_action(_wb("battle_result"))

    assert action is not None
    assert action.name == "confirm-result"
    assert action.point == CLICK_POINTS["open-level-reward"]


# ---- 3. 判据与运行期同源 ----


@pytest.mark.parametrize(
    ("name", "atom"),
    (
        ("worldboss_home", "select_team_button"),
        ("team_select", "team_select_title"),
        ("team_config", "team_config_auto"),
        ("battle_result", "result_title"),
        ("level_reward", "level_reward_title"),
        ("knights_home", "knights_title"),
    ),
)
def test_the_judgement_is_the_same_anchors_the_runtime_uses(name: str, atom: str):
    """抹掉该页的专属锚点就认不出 —— 证明接力点不是巧合命中。

    夹具都是基准尺寸（1982×1132），``REGIONS`` 的坐标可以直接用、不需要换算。
    """

    screen = _wb(name)
    assert detect_resume_point(_machine(), screen) is not None, name

    x, y, width, height = WORLD_BOSS_REGIONS[atom]
    broken = screen.copy()
    broken[y : y + height, x : x + width] = 0

    assert detect_resume_point(_machine(), broken) is None, (
        f"抹掉 {atom} 后仍被判成接力点，说明判据不是这个锚点决定的"
    )


# ---- 4. 接线 ----


def test_world_boss_exposes_a_resume_probe():
    """从「一律回大厅」改成「先看停在世界首领战哪一页」。"""

    assert get_mode("world_boss").resume_probe is _probe_world_boss_resume


def test_the_probe_reports_the_point_in_the_modes_shape():
    point = _probe_world_boss_resume(_machine(), _wb("team_config"), None)

    assert point is not None
    assert point.page == "配置队伍"
    assert point.state == WorldBossState.TEAM_CONFIG.value
    assert point.entry is None


def test_the_probe_puts_the_point_state_into_the_machine():
    """拨状态不是为了判页面（``next_action`` 每页都现判），而是为了留下
    ``resumed_from`` —— ``WorldBossRunner`` 靠它认出「局内接力」。"""

    machine = _machine()

    _probe_world_boss_resume(machine, _wb("battle"), None)

    assert machine.state is WorldBossState.BATTLE
    assert machine.resumed_from is WorldBossState.BATTLE


def test_the_probe_leaves_the_machine_unmarked_when_landing_on_the_navigation_chain():
    """落在骑士团主页说明**还没进**世界首领战，这时候留下「局内接力」的记号会让
    Runner 凭空去监督一场不存在的战斗。"""

    machine = _machine()

    _probe_world_boss_resume(machine, _wb("knights_home"), None)

    assert machine.resumed_from is None


def test_the_probe_misses_on_a_foreign_page():
    assert (
        _probe_world_boss_resume(
            _machine(),
            _screen("epic7_navigation", "lobby"),
            None,
        )
        is None
    )


def test_the_runner_hands_a_resumed_battle_to_the_supervisor():
    """接力落在局内：进主循环之前先把这一局监督完，绝不按 Back 回大厅。"""

    machine = _machine()
    machine.resume_from(WorldBossState.BATTLE)
    runner, supervisor = _runner(machine, dry_run=False)
    runtime = runner.runtime

    completed = runner.run(max_cycles=0)

    assert completed == 0
    supervisor.run.assert_called_once()
    assert machine.state is WorldBossState.RESULT
    assert any(
        "交由战斗监督等待结算" in str(call)
        for call in runtime.log.call_args_list
    )


def test_the_runner_does_not_touch_the_supervisor_for_a_normal_start():
    runner, supervisor = _runner(_machine(), dry_run=False)

    runner.run(max_cycles=0)

    supervisor.run.assert_not_called()


def test_dry_run_never_runs_the_battle_supervisor():
    """空跑只观察：就算状态机带着「局内接力」的标记，也不许真的去监督战斗。"""

    machine = _machine()
    machine.resume_from(WorldBossState.BATTLE)
    runner, supervisor = _runner(machine, dry_run=True)

    runner.run(max_cycles=0)

    supervisor.run.assert_not_called()
