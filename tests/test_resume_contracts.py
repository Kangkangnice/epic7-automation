"""接力契约的门槛测试 —— 三条卡点各守一条。

**转场契约**管「跑起来之后每个动作有没有出口验收」（`runner_base._require_transition_contract`）；
**接力契约**管「开局时人停在半路能不能接上」。两者互相独立，规矩见
`docs/TRANSITION_CONTRACTS.md`「接力契约」。

| 卡点 | 守在哪 |
|---|---|
| ① 表上必须表态 | 本文件（`RESUME_EXEMPT` 与 `resume_probe` 必须二选一）+ `modes.py` 的加载期自查 |
| ② 接线必须真通 | `main.py::_enter_mode` 校验 `_ResumeWatch.asked > 0`（本文件用替身 navigator 钉住「吃掉探针必须报错」） |
| ③ 判据必须真认得准（且命中后状态机真被拨对） | 本文件拿每条路线**自己的夹具**跑**注册好的探针**（`spec.resume_probe`） |

⚠️ 跨路线负例扫描（全库夹具取最高分）**不进门槛**：227 张要跑约半分钟，跟实跑抢内存。
它留在 `runtime_logs/_audit_*_cross_route.py`，结论写进 `docs/RESUME_COVERAGE.md`。
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from auto_game_unified import main as main_module
from auto_game_unified.games.epic7.modes import (
    MODE_SPECS,
    PC_ONLY_ROUTES,
    RESUME_EXEMPT,
    get_mode,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"
COVERAGE_DOC = ROOT / "docs" / "RESUME_COVERAGE.md"

REFERENCE_WIDTH, REFERENCE_HEIGHT = 1982, 1132

NAVIGATED_MODES = tuple(
    sorted(name for name, spec in MODE_SPECS.items() if spec.needs_navigation)
)
PROBE_MODES = tuple(
    sorted(name for name, spec in MODE_SPECS.items() if spec.resume_probe is not None)
)


# ---- ① 表上必须表态 ----


@pytest.mark.parametrize("name", NAVIGATED_MODES)
def test_every_navigated_route_declares_its_resume_stance(name: str):
    """有导航的路线，要么挂探针，要么在豁免名单里写明理由 —— 不许「一个字不提」。"""

    spec = MODE_SPECS[name]

    assert spec.resume_probe is not None or name in RESUME_EXEMPT, (
        f"路线 {name} 既没挂接力探针，也没在 RESUME_EXEMPT 里写明理由"
    )
    assert not (spec.resume_probe is not None and name in RESUME_EXEMPT), (
        f"路线 {name} 两边都写了：挂了探针就该从豁免名单里划掉"
    )


def test_the_exemption_list_has_no_stale_names_and_no_empty_reasons():
    for name, reason in RESUME_EXEMPT.items():
        assert name in MODE_SPECS, f"豁免名单里的 {name} 不是一条路线（改名了吧？）"
        assert reason.strip(), f"{name} 的豁免理由不能空着"


def test_routes_without_navigation_are_exempt_automatically():
    """起点本来就是人工推进到活动内部：连「回大厅」这条路径都没有，谈不上接力。

    它们**不该**出现在豁免名单里 —— 那会把「没有这条路」和「有路但没做」混成一种。
    """

    without_navigation = [
        name for name, spec in MODE_SPECS.items() if not spec.needs_navigation
    ]

    assert without_navigation, "一条 needs_navigation=False 的路线都没有，这张测试该删了"
    for name in without_navigation:
        assert MODE_SPECS[name].resume_probe is None
        assert name not in RESUME_EXEMPT


def test_at_least_one_route_actually_resumes():
    """反向护栏：别把「全都豁免」当成通过。"""

    assert PROBE_MODES, "一条挂接力探针的路线都没有 —— 接力契约被架空了"


# ---- ② 接线必须真通 ----

BLANK_FRAME = np.zeros((REFERENCE_HEIGHT, REFERENCE_WIDTH, 3), dtype=np.uint8)


def _story_machine():
    spec = get_mode("story")
    return spec, spec.build_machine(TEMPLATE_ROOT, spec.default_state)


def _legacy_home_return(navigator):
    """造一个「照旧转发给导航器」的回大厅对象。

    ``story`` 不在 ``HOME_RETURN_V2_MODES`` 里，所以 ``HomeReturn`` 走 legacy 分支、
    原样把调用转给 ``navigator.return_home`` —— 正是这两条契约想测的东西
    （它们只关心「探针有没有被传下去」，不关心回家本身怎么走）。
    """
    return main_module.HomeReturn(navigator, MagicMock(), mode="story")


def test_enter_mode_refuses_a_navigator_that_swallows_the_resume_probe():
    """探针被吃掉了就不许当没事发生。

    真 ``return_home`` 的两条正常返回路径（命中接力点 / 回到大厅）**都在问过探针之后**，
    其余路径全是 raise —— 所以「返回了却一次没问过」只可能是接线断了，
    比如 ``_enter_mode`` 忘了传 ``stop_probe``。那时候日志里一片祥和，
    人停在半路照样退回大厅重走，谁也不会发现探针白写了。
    """

    spec, machine = _story_machine()
    navigator = MagicMock()
    navigator.return_home.return_value = BLANK_FRAME

    with pytest.raises(RuntimeError, match="一次都没问过"):
        main_module._enter_mode(
            spec, machine, navigator, MagicMock(), _legacy_home_return(navigator)
        )


def test_enter_mode_falls_back_to_the_old_route_when_the_probe_misses():
    """问过了、但认不出 ⇒ 照旧「回大厅 → 按路线导航」，与接力挂上之前完全一致。"""

    spec, machine = _story_machine()
    navigator = MagicMock()

    def return_home(**kwargs):
        kwargs["stop_probe"](BLANK_FRAME)
        return BLANK_FRAME

    navigator.return_home.side_effect = return_home

    main_module._enter_mode(
        spec, machine, navigator, MagicMock(), _legacy_home_return(navigator)
    )

    navigator.navigate.assert_called_once_with("story", lobby_screen=BLANK_FRAME)


# ---- 登记表护栏 ----


def test_every_route_is_registered_in_the_coverage_doc():
    """新增路线必须去 ``docs/RESUME_COVERAGE.md`` 表态。

    这是**弱**护栏（只查名字出现过，不查写得对不对），但比什么都不查强：
    没有它，新路线的接力状况永远不会被写下来。
    """

    text = COVERAGE_DOC.read_text(encoding="utf-8")

    missing = [name for name in MODE_SPECS if name not in text]

    assert not missing, f"这些路线没在 {COVERAGE_DOC.name} 里登记：{missing}"


# ---- ③ 判据必须真认得准 ----


# 每个注册探针在旧全库回放中识别出的不同 (状态, 页面)，各留一个真机见证。
# 各路线的判据和反例仍由对应的路线测试验证。这里验接线和状态实际发生改变。
RESUME_WITNESSES = {
    'achievement': (
        ('page_sim_live_20261109.png', None, '成就页'),
        ('reward_popup_sim_live_20261109.png', None, '获得成就奖励'),
    ),
    'arena': (
        ('battle.png', 'battle', '战斗中'),
        ('failed_first_opponent.png', 'list', '对手列表'),
        ('normal_battle_ready_live_20260826.png', 'team', '队伍选择'),
        ('rank_confirm.png', 'confirming', '结果确认中'),
        ('result.png', 'result', '战斗结果'),
        ('selected.png', 'selected', '对手详情'),
    ),
    'craft_equipment': (
        ('home.png', None, '制作页（未选部位）'),
        ('qty_1.png', None, '制作页（已选部位）'),
    ),
    'expedition': (
        ('battle.png', 'battle', '战斗中'),
        ('campfire_idle.png', 'outcome', '公开招募结果'),
        ('difficulty_3_selected.png', 'difficulty_confirm', '难度确认'),
        ('empty_posters_live.png', 'posters', '通缉传单列表'),
        ('expedition_list.png', 'returning', '返回主页'),
        ('home.png', 'home', '远征主页'),
        ('public_confirm.png', 'recruit_confirm', '招募确认'),
        ('ready.png', 'ready', '准备战斗'),
        ('result.png', 'result', '战斗结果'),
        ('team.png', 'team', '队伍选择'),
    ),
    'knights_donation': (
        ('guild_home_no_dot.png', None, '骑士团主页'),
        ('support_limit_full.png', None, '骑士团活动·资源支援'),
        ('weekly_tasks_claimable.png', None, '骑士团活动·每周任务'),
    ),
    'labyrinth_stone': (
        ('battle.png', None, '迷宫内战斗（本路线不该出现）'),
        ('battle_menu.png', None, '战斗菜单·一般页'),
        ('detail_after_giveup.png', None, '迷宫详情页'),
        ('giveup_confirm.png', None, '放弃战斗确认框'),
        ('labyrinth_list.png', None, '迷宫列表'),
        ('map.png', None, '地图页'),
        ('merchant_room.png', None, '商人房'),
        ('pause_menu.png', None, '暂停菜单'),
        ('quick_menu.png', None, '右上角快捷菜单'),
        ('room.png', None, '迷宫房间'),
        ('shop.png', None, '商店页'),
        ('story.png', None, '开场剧情'),
        ('team_ready.png', None, '准备战斗页'),
        ('teleport_confirm.png', None, '传送确认弹窗'),
        ('unknown_dialog.png', None, '认不出标题的双按钮弹窗'),
    ),
    'penguin_purchase': (
        ('altar_popup.png', None, '成长祭坛'),
        ('forest_with_altar.png', None, '精灵之森'),
        ('sanctuary_home.png', None, '圣域主页'),
    ),
    'pet_adoption': (
        ('adopt_popup_free.png', None, '领养宠物'),
        ('adopt_result.png', None, '领养结果'),
        ('house.png', None, '宠物小屋'),
        ('purchase_done.png', None, '宠物商店'),
    ),
    'sanctuary': (
        ('forest_after_penguin.png', None, '精灵之森'),
        ('home.png', None, '圣域主页'),
    ),
    'shop_refresh': (
        ('covenant_purchased_row_live_20260831.png', None, '秘密商店'),
    ),
    'side_story': (
        ('battle_clear.png', 'wait_results', '通关结算'),
        ('boss_difficulty_list.png', 'team', '助手选择'),
        ('complete_popup.png', 'wait_results', '完成故事'),
        ('episode_countdown_live_20261112.png', 'stage', 'Episode详情'),
        ('exhausted_prep.png', 'team', '队伍准备'),
        ('map.png', 'stage', '关卡地图'),
        ('outpost_scene.png', 'stage', '场景页'),
        ('results.png', 'wait_results', '结算确认'),
        ('side_story.png', 'stage', '支线故事'),
        ('skip_confirm.png', 'wait_skip_confirm', '跳过确认'),
        ('story_skip.png', 'active', '剧情播放'),
    ),
    'story': (
        ('assistant.png', 'team', '助手选择'),
        ('battle.png', 'wait_battle', '战斗中'),
        ('bonus_reward.png', 'wait_next_stage', '额外奖励'),
        ('clear.png', 'wait_results', '通关结算'),
        ('complete.png', 'wait_complete', '通关提示'),
        ('friend_request_pc_live_20261101.png', 'wait_results', '结算确认'),
        ('next_stage.png', 'stage', '关卡入口'),
        ('reward.png', 'wait_results', '奖励结算'),
        ('skip_confirm.png', 'wait_skip_confirm', '跳过确认'),
        ('stamina_popup_pc_live_20261101.png', 'team', '队伍准备'),
        ('story.png', 'active', '剧情播放'),
        ('story_watch_next_ep4.png', 'stage', '剧情关卡入口'),
    ),
    'story_star': (
        ('03_timeline_open.png', None, '篇章面板'),
        ('04_chapter3_stage_list.png', None, '小节列表'),
    ),
    'tower': (
        ('battle_failed.png', 'card', '战斗失败'),
        ('battle_guide.png', 'team', '准备战斗'),
        ('battle_manual_auto_icon_dead_zone.png', 'battle', '战斗中'),
        ('card.png', 'card_confirm', '选择装置确认'),
        ('conquered.png', 'conquered', '月塔已征服'),
        ('floor_list.png', 'floor_list', '楼层列表'),
        ('home.png', 'home', '月塔主页'),
        ('result.png', 'result', '月塔结算'),
    ),
    'world_boss': (
        ('battle.png', 'battle', '战斗中'),
        ('battle_result.png', 'result', '战斗结算'),
        ('knights_home.png', None, '骑士团主页'),
        ('level_reward.png', 'level_reward', '战斗级别奖励'),
        ('team_config.png', 'team_config', '配置队伍'),
        ('team_select.png', 'team_select', '选择辅助队伍'),
        ('worldboss_home.png', 'home', '世界首领战主页'),
    ),
}


def _reference_frames(mode: str, names: tuple[str, ...]) -> Iterator[np.ndarray]:
    """Load only the nominated real frames, cropping to the existing reference canvas."""
    suffix = "_pc" if mode in PC_ONLY_ROUTES else ""
    group = FIXTURES / f"epic7_{mode}{suffix}"
    for name in names:
        path = group / name
        raw = cv2.imread(str(path), cv2.IMREAD_COLOR)
        assert raw is not None, f"无法读取接力夹具 {path}"
        height, width = raw.shape[:2]
        assert height >= REFERENCE_HEIGHT and width >= REFERENCE_WIDTH, f"夹具小于基准画布 {path}"
        frame = cv2.cvtColor(raw[:REFERENCE_HEIGHT, :REFERENCE_WIDTH], cv2.COLOR_BGR2RGB)
        del raw
        yield frame


def test_reference_frames_only_decode_the_frame_being_tested(tmp_path, monkeypatch):
    group = tmp_path / "epic7_stream"
    group.mkdir()
    for name in ("extra.png", "first.png", "second.png"):
        (group / name).touch()
    monkeypatch.setitem(_reference_frames.__globals__, "FIXTURES", tmp_path)
    decoded = []

    def read(path, flags):
        decoded.append(Path(path).name)
        return np.zeros((REFERENCE_HEIGHT, REFERENCE_WIDTH, 3), dtype=np.uint8)

    monkeypatch.setattr(cv2, "imread", read)
    frames = iter(_reference_frames("stream", ("first.png", "second.png")))
    assert not decoded
    next(frames)
    assert decoded == ["first.png"]
    next(frames)
    assert decoded == ["first.png", "second.png"]
    assert list(frames) == []


def test_every_registered_probe_has_a_real_witness():
    assert set(RESUME_WITNESSES) == set(PROBE_MODES)


@pytest.mark.parametrize("name", PROBE_MODES)
def test_the_registered_probe_adopts_each_witness_state(name: str):
    spec = MODE_SPECS[name]
    root = TemplateDir(TEMPLATE_ROOT, "pc") if name in PC_ONLY_ROUTES else TEMPLATE_ROOT
    machine = spec.build_machine(root, spec.default_state)
    witnesses = RESUME_WITNESSES[name]
    assert witnesses
    frames = _reference_frames(name, tuple(filename for filename, _, _ in witnesses))

    for (filename, expected_state, expected_page), frame in zip(witnesses, frames, strict=True):
        point = spec.resume_probe(machine, frame, None)
        assert point is not None, f"{name} 的探针认不出 {filename}"
        assert (point.state, point.page) == (expected_state, expected_page), filename
        if expected_state is not None:
            # The factory must also update the machine, so the runner can continue.
            assert machine.state.value == expected_state, (
                f"{name} 的探针报了落点状态 {expected_state}，但状态机还停在 "
                f"{machine.state.value} —— resume_from 没接上。"
            )
