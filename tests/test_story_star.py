# -*- coding: utf-8 -*-
"""主线补星的回归测试（真机帧驱动）。

夹具都是 2026-11-09 在 PC 客户端上实拍的整帧，覆盖三页与两个判据的正反样本：

| 夹具 | 是什么 |
|---|---|
| ``03_timeline_open.png`` | Episode 面板（Episode 3，含满星与未满卡片） |
| ``12_episode1.png`` | Episode 面板（Episode 1，5 张卡片全满） |
| ``04_chapter3_stage_list.png`` | 小节列表（10 个小节，只有 2 号有勾） |
| ``13_ep1_full_stages.png`` | 小节列表（4 个小节全有勾） |
| ``31_ch10_stages.png`` | 小节列表（4 个小节全无勾） |
| ``34_prepare2.png`` | 准备战斗页（含「战斗开始」） |
| ``22_now.png`` | Episode 3 的篇章面板（6 张卡片，2 满 4 未满） |
"""
from __future__ import annotations

from dataclasses import replace as dataclass_replace
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from auto_game_unified.games.epic7 import story_star as story_star_module
from auto_game_unified.games.epic7.evidence.story_star import chapter_is_full
from auto_game_unified.games.epic7.story_star import (
    EPISODE_ROW_POINTS,
    _RESUMABLE_STATES,
    StoryStarRunner,
    StoryStarState,
    StoryStarStateMachine,
    build_story_star_templates,
    detect_story_star_resume_point,
)
from auto_game_unified.games.epic7.template_paths import resolve_template_dir

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "epic7_story_star_pc"
TEMPLATES = Path(__file__).resolve().parents[1] / "games" / "epic7" / "templates"


def load(name: str):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None, f"夹具缺失：{name}"
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


@pytest.fixture(scope="module")
def machine() -> StoryStarStateMachine:
    return StoryStarStateMachine(
        build_story_star_templates(resolve_template_dir(TEMPLATES, "pc"))
    )


@pytest.fixture
def startup_machine() -> StoryStarStateMachine:
    """Runner 开跑那一刻的状态机：开场两步开关已打开。"""
    started = StoryStarStateMachine(
        build_story_star_templates(resolve_template_dir(TEMPLATES, "pc"))
    )
    started.begin()
    return started


# ---- 页面判定 -------------------------------------------------------------
@pytest.mark.parametrize(
    "name,expected",
    [
        ("03_timeline_open.png", StoryStarState.EPISODE),
        ("12_episode1.png", StoryStarState.EPISODE),
        ("22_now.png", StoryStarState.EPISODE),
        ("04_chapter3_stage_list.png", StoryStarState.STAGE_LIST),
        ("13_ep1_full_stages.png", StoryStarState.STAGE_LIST),
        ("31_ch10_stages.png", StoryStarState.STAGE_LIST),
        ("34_prepare2.png", StoryStarState.PREPARE),
    ],
)
def test_page_recognition(machine, name, expected):
    """三页互不误判：Episode 面板 / 小节列表 / 准备战斗。"""
    assert machine.observe_page(load(name)) is expected


# ---- 篇章满星（判据一）----------------------------------------------------
def test_all_full_page_reports_every_chapter_full(machine):
    """Episode 1 的 5 张卡片星数全满（12/12、15/15、21/21、9/9…）。"""
    screen = load("12_episode1.png")
    points = machine.star_points(screen)
    assert len(points) == 5, f"应识别到 5 张卡片，实际 {len(points)}"
    for center in points:
        full, detail = chapter_is_full(screen, center)
        assert full, f"{center} 应判满星：{detail}"


def test_mixed_page_separates_full_from_partial(machine):
    """Episode 3 的 6 张卡片里 2 张满、4 张未满 —— 正反样本在同一帧上。"""
    screen = load("22_now.png")
    results = {
        center: chapter_is_full(screen, center)[0]
        for center in machine.star_points(screen)
    }
    full = [point for point, value in results.items() if value]
    partial = [point for point, value in results.items() if not value]
    assert len(full) == 2, f"应有 2 张满星，实际 {len(full)}：{results}"
    assert len(partial) == 4, f"应有 4 张未满，实际 {len(partial)}：{results}"


# ---- 小节满星（判据二）----------------------------------------------------
def test_stage_checks_one_of_ten(machine):
    """第 3 章只有 2 号小节有勾（大勾）。"""
    points = machine.stage_checks(load("04_chapter3_stage_list.png"))
    assert len(points) == 1, points


def test_stage_checks_all_full_uses_two_template_sizes(machine):
    """4 个小节全满：第 1 行是大勾、其余 3 行是小勾 —— 两张模板都要能命中。"""
    points = machine.stage_checks(load("13_ep1_full_stages.png"))
    assert len(points) == 4, points


def test_stage_checks_none(machine):
    """第 10 章的 4 个小节一个勾都没有。"""
    assert machine.stage_checks(load("31_ch10_stages.png")) == []


# ---- 决策 ----------------------------------------------------------------
def test_episode_page_opens_first_partial_chapter(machine):
    """篇章面板：第一个动作必须是「点开一张未满的卡片」，而不是滚动。"""
    machine.episode_index = 0
    machine.scroll_signature = None
    action = machine.next_action(load("22_now.png"))
    assert action is not None
    assert action.name == "open-chapter"
    assert action.target_pages == (StoryStarState.STAGE_LIST.value,)


def test_right_edge_chapter_would_be_clicked_outside_the_canvas(machine):
    """Episode 3 面板上第 3 张卡只露半张：星标 (1909,505) ⇒ 落点 (2059,595)。

    2026-11-10 12:21 实跑就是拿这个点去点，被窗口层「拒绝在 PC 游戏渲染区外点击」
    判成致命错误，整条路线连带后续路线全部没跑。这条用例把「夹具上真能复现」钉住。
    """
    screen = load("22_now.png")
    outside = [
        center
        for center in machine.star_points(screen)
        if not story_star_module.point_in_screen(
            story_star_module.chapter_click_point(center), screen
        )
    ]
    assert outside == [(1909, 505)], f"应正好有一张卡片落在画布外，实际 {outside}"


def test_partial_edge_chapter_scrolls_before_clicking(machine, monkeypatch):
    """落点越界的未满卡片先右滚；滚到头才点它露出来的那部分（不许静默跳过）。"""
    screen = load("22_now.png")
    machine.scroll_signature = None
    machine.finished = False
    monkeypatch.setattr(machine, "star_points", lambda _screen: [(1909, 505)])
    monkeypatch.setattr(
        story_star_module, "chapter_is_full", lambda _screen, _center: (False, "边缘卡片")
    )

    first = machine.next_action(screen)
    assert first is not None and first.name == "scroll-chapters", "越界落点必须先滚"
    assert "露不全" in first.reason

    # 同一帧再来一次 = 滚不动了（画面没变化）
    second = machine.next_action(screen)
    assert second is not None and second.name == "open-chapter"
    height, width = screen.shape[:2]
    x, y = second.point
    assert 0 <= x < width and 0 <= y < height, f"兜底落点仍在画布外：{second.point}"


def test_in_bounds_partial_chapter_wins_over_the_edge_one(machine, monkeypatch):
    """同一屏既有画面内的未满卡片、也有越界的：点画面内那张。"""
    screen = load("22_now.png")
    machine.scroll_signature = None
    machine.finished = False
    monkeypatch.setattr(machine, "star_points", lambda _screen: [(1909, 505), (829, 505)])
    monkeypatch.setattr(
        story_star_module, "chapter_is_full", lambda _screen, _center: (False, "未满")
    )

    action = machine.next_action(screen)
    assert action is not None and action.name == "open-chapter"
    assert action.point == (979, 595), f"应点画面内那张，实际 {action.point}"


def test_stage_list_opens_first_unmarked_stage(machine):
    """小节列表：4 个全无勾时，动作是点开第一行。"""
    machine._stage_attempts.clear()
    machine._pending_prepare = 0
    machine._pending_select = False
    machine.stage_scroll_signature = None
    action = machine.next_action(load("31_ch10_stages.png"))
    assert action is not None
    assert action.name == "open-stage"
    assert action.point[1] < 500, "应点最上面那一行"
    # 点完小节必须记住「接下来几帧先点准备战斗」，否则会接着去点下一关。
    assert machine._pending_prepare == 3


def test_stage_list_backs_out_when_everything_marked(machine):
    """小节列表全有勾且滚不动 ⇒ 退回篇章面板。"""
    screen = load("13_ep1_full_stages.png")
    machine._stage_attempts.clear()
    machine._pending_prepare = 0
    machine._pending_select = False
    machine.stage_scroll_signature = screen.copy()
    action = machine.next_action(screen)
    assert action is not None
    assert action.name == "back-to-episode"


def test_prepare_page_starts_battle(machine):
    """准备战斗页：动作是「战斗开始」，它同时是 Runner 的战斗入口。"""
    action = machine.next_action(load("34_prepare2.png"))
    assert action is not None
    assert action.name == "start-mission"


# ---- 开场顺序与接力范围（2026-11-10 用户纠正）------------------------------
def test_startup_from_stage_list_goes_to_outer_panel_before_playing(startup_machine):
    """从任何小节列表进来，第一件事是回最外层，不是找绿勾开打。"""
    screen = load("04_chapter3_stage_list.png")
    action = startup_machine.next_action(screen)
    assert action is not None
    assert action.name == "open-episode-panel"
    assert action.target_pages == (StoryStarState.EPISODE.value,)
    icon = startup_machine._locate(screen, "timeline_icon")
    assert icon is not None
    assert action.point == icon.center
    # 还没打任何一关：遍历进度仍在第一项，绿勾账本为空。
    assert startup_machine.episode_index == 0
    assert startup_machine._stage_attempts == {}


def test_startup_from_stage_list_then_selects_first_inscope_item(startup_machine):
    """外层打开后先显式选中左列第 1 项，再扫篇章（防停在第 6 章/外传直接开打）。"""
    first = startup_machine.next_action(load("04_chapter3_stage_list.png"))
    assert first.name == "open-episode-panel"

    screen = load("22_now.png")
    second = startup_machine.next_action(screen)
    assert second is not None
    assert second.name == "select-first-episode"
    assert second.point == EPISODE_ROW_POINTS[0]
    assert second.source_page == StoryStarState.EPISODE.value
    assert second.in_page_evidence

    # 开场两步只做一次；接着先归位到最左，再回到正常的「点开未满篇章」。
    third = startup_machine.next_action(screen)
    assert third is not None and third.name == "scroll-chapters-left"
    fourth = startup_machine.next_action(screen)
    assert fourth is not None and fourth.name == "open-chapter"


def test_startup_from_episode_panel_also_selects_first_item(startup_machine):
    """停在外层面板也不许直接扫当前显示的章节，先切回范围内第 1 项。"""
    action = startup_machine.next_action(load("22_now.png"))
    assert action is not None
    assert action.name == "select-first-episode"
    assert action.point == EPISODE_ROW_POINTS[0]


def test_preview_does_not_consume_the_startup_steps(startup_machine):
    """主循环先用 preview 试算；试算不能把开场开关吃掉。"""
    screen = load("22_now.png")
    preview_action, _ = startup_machine.preview(screen)
    assert preview_action is not None
    assert preview_action.name == "select-first-episode"
    # 真正提交那一帧仍应发出同一个动作。
    committed = startup_machine.next_action(screen)
    assert committed is not None
    assert committed.name == "select-first-episode"


def test_prepare_and_results_are_not_resumable():
    """准备 / 结算页认不出属于哪个 Episode，接着打会越过补星范围。"""
    assert StoryStarState.EPISODE in _RESUMABLE_STATES
    assert StoryStarState.STAGE_LIST in _RESUMABLE_STATES
    assert StoryStarState.PREPARE not in _RESUMABLE_STATES
    assert StoryStarState.RESULTS not in _RESUMABLE_STATES
    machine = StoryStarStateMachine(
        build_story_star_templates(resolve_template_dir(TEMPLATES, "pc"))
    )
    assert detect_story_star_resume_point(machine, load("34_prepare2.png")) is None


def test_runner_arms_the_startup_steps():
    """Runner 构造时必须打开开场开关，否则开场两步永远不会触发。"""
    runner_machine = MagicMock()
    StoryStarRunner(runner_machine, MagicMock())
    runner_machine.begin.assert_called_once_with()


# ---- 战斗观察（2026-11-10 实机失败回归）------------------------------------
# 这三张是实跑留下的真机帧：客户端把 UI 画小约 3% 时，共享战斗判据在它们上面
# 五项全假 ⇒ 监督等满 45 秒报 battle_unrecognized。夹具必须一直钉在这里。
@pytest.mark.parametrize(
    "name",
    [
        "battle_scaled_ui.png",     # 07:50 报 battle_unrecognized 的那一帧
        "battle_dark_effect.png",    # 08:20 技能演出（暗背景）帧
        "battle_after_skip.png",    # 另一档 UI 尺寸，原尺寸分数只有 0.80
    ],
)
def test_battle_frames_are_recognized(machine, name):
    """战斗观察入口必须认得这些帧，否则整场战斗会被当成「画面无法识别」。"""
    observation = machine.observe_battle(load(name), None)
    assert observation.battle_visible is True, (
        f"{name} 应判成战斗画面；共享判据在这一档 UI 尺寸上失手，"
        "需要本路线自己的 HUD 证据补正"
    )


@pytest.mark.parametrize(
    "name",
    [
        "03_timeline_open.png",
        "12_episode1.png",
        "22_now.png",
        "04_chapter3_stage_list.png",
        "13_ep1_full_stages.png",
        "31_ch10_stages.png",
        "34_prepare2.png",
    ],
)
def test_non_battle_pages_do_not_report_battle(machine, name):
    """反例：补星链路里的非战斗页面不许被新证据误判成战斗。"""
    observation = machine.observe_battle(load(name), None)
    assert observation.battle_visible is False


def test_battle_hud_template_is_what_rescues_the_frame(machine, monkeypatch):
    """反向护栏：抽掉 HUD 模板，失败帧必须回到「认不出」，不许有别处偷偷放行。"""
    # ⚠️ 不能用全黑图：白掩膜后模板成常数，TM_CCOEFF_NORMED 会把常数模板
    # 判成「处处完美匹配」。用上下翻转打乱形状，才是真的「没有这份证据」。
    scrambled = np.ascontiguousarray(np.flipud(machine.templates.battle_hud))
    monkeypatch.setattr(
        machine,
        "templates",
        dataclass_replace(machine.templates, battle_hud=scrambled),
    )
    observation = machine.observe_battle(load("battle_scaled_ui.png"), None)
    assert observation.battle_visible is False


def test_smaller_ui_frame_needs_the_scale_scan(machine):
    """反向护栏：另一档 UI 尺寸上原尺寸只有 ~0.80，尺寸扫描不能省。"""
    from auto_game_unified.core.matcher import (
        MATCH_MODE_WHITE_MASK,
        find_best_template,
    )

    atom = machine.evidence.atom("battle_hud")
    screen = load("battle_after_skip.png")
    plain = find_best_template(
        screen,
        machine.templates.battle_hud,
        atom.region,
        atom.reference_size,
        mode=MATCH_MODE_WHITE_MASK,
    )
    assert plain is not None and plain.score < atom.threshold
    assert machine._battle_hud_visible(screen) is True


# ---- 业务闭环（2026-11-10 独立审核后的补齐项）--------------------------------
# 这些用例先验「整条路线怎么把 6 个章节扫完」，再验单点判据：离线只验判据时，
# 换章 / 归位 / 收工这些设计里的步骤一条都没被跑到（见工作区根的独立审核报告）。

STORY_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "epic7_story"


def load_story(name: str):
    image = cv2.imread(str(STORY_FIXTURES / name))
    assert image is not None, f"夹具缺失：{name}"
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


@pytest.fixture
def fresh_machine() -> StoryStarStateMachine:
    """每个用例都拿一台干净的状态机，避免模块级 fixture 的账本串台。"""
    return StoryStarStateMachine(
        build_story_star_templates(resolve_template_dir(TEMPLATES, "pc"))
    )


def test_startup_rewinds_chapters_to_the_left_first(startup_machine):
    """开场选完第 1 项，必须先把篇章滚回最左，才允许开卡片。"""
    screen = load("22_now.png")
    first = startup_machine.next_action(screen)
    assert first is not None and first.name == "select-first-episode"
    second = startup_machine.next_action(screen)
    assert second is not None
    assert second.name == "scroll-chapters-left", (
        "切换/开局后应先把篇章归位到最左，否则左边未满的章节会被漏掉；"
        f"实际第一个动作是 {second.name}"
    )


def test_rewind_is_bounded_and_then_scanning_resumes(startup_machine):
    """归位滚到画面不动就结束，不能一直往左滚、也不能吞掉后续扫篇章。"""
    screen = load("22_now.png")
    startup_machine.next_action(screen)  # select-first-episode
    assert startup_machine.next_action(screen).name == "scroll-chapters-left"
    third = startup_machine.next_action(screen)  # 同帧 = 滚不动了
    assert third is not None
    assert third.name == "open-chapter", (
        f"归位结束后应回到正常扫篇章，实际 {third.name}"
    )


def test_checked_chapter_is_not_reopened(fresh_machine, monkeypatch):
    """一张已查过的篇章不许再点开一次，否则就是 12:21 / 18:43 那种空转。"""
    screen = load("22_now.png")
    fresh_machine.scroll_signature = None
    monkeypatch.setattr(fresh_machine, "star_points", lambda _s: [(829, 505)])
    monkeypatch.setattr(
        story_star_module, "chapter_is_full", lambda _s, _c: (False, "未满")
    )
    first = fresh_machine.next_action(screen)
    assert first is not None and first.name == "open-chapter"
    fresh_machine.scroll_signature = None  # 模拟点进去又退回篇章面板
    second = fresh_machine.next_action(screen)
    assert second is not None
    assert second.name != "open-chapter", "同一张已查过的篇章被重复点开"


def test_stage_scroll_has_its_own_notch_count(fresh_machine):
    """小节行距约 150px，不能复用横向翻篇章那 25 格（一次滚过两三行）。"""
    from auto_game_unified.games.epic7.route_action import RouteAction

    runner = StoryStarRunner(fresh_machine, MagicMock())
    runner._perform_action(RouteAction("scroll-chapters", (1100, 760)))
    runner.runtime.wheel.assert_called_once_with(
        (1100, 760), -story_star_module.SCROLL_NOTCHES, "scroll-chapters"
    )
    runner.runtime.reset_mock()
    runner._perform_action(RouteAction("scroll-stages", (200, 700)))
    notches = story_star_module.SCROLL_STAGE_NOTCHES
    assert notches < story_star_module.SCROLL_NOTCHES
    runner.runtime.wheel.assert_called_once_with(
        (200, 700), -notches, "scroll-stages"
    )


def test_six_episodes_complete_exactly_one_cycle(fresh_machine, monkeypatch):
    """一轮 = 扫完 6 个章节，不是「完成 6 轮」。"""
    screen = load("22_now.png")
    fresh_machine.episode_index = 5
    fresh_machine.scroll_signature = screen.copy()
    monkeypatch.setattr(fresh_machine, "star_points", lambda _s: [])
    action = fresh_machine.next_action(screen)
    assert action is None
    assert fresh_machine.completed_cycles == 1


def test_stage_attempt_book_is_not_keyed_by_screen_row(fresh_machine, monkeypatch):
    """列表滚过一屏后，同一个屏幕行坐标已经是另一关，仍应允许开打。"""
    screen = load("31_ch10_stages.png")
    monkeypatch.setattr(fresh_machine, "stage_checks", lambda _s: [])
    monkeypatch.setattr(
        story_star_module, "stage_is_full", lambda *_a, **_k: False
    )
    fresh_machine.stage_scroll_signature = None
    first = fresh_machine.next_action(screen)
    assert first is not None and first.name == "open-stage"
    fresh_machine._stage_scroll_steps = (
        getattr(fresh_machine, "_stage_scroll_steps", 0) + 1
    )
    fresh_machine._pending_prepare = 0  # 上一关已打完，回到列表重新看
    second = fresh_machine.next_action(screen)
    assert second is not None and second.name == "open-stage", (
        "滚动后同一行被旧账本拦住了，实际会漏掉没打过的小节"
    )


def test_stage_that_stays_uncleared_is_reported(fresh_machine, monkeypatch):
    """打过回来还是没满星：要报「配置可能不满足通关条件」，不能静默略过。"""
    screen = load("31_ch10_stages.png")
    monkeypatch.setattr(fresh_machine, "stage_checks", lambda _s: [])
    monkeypatch.setattr(
        story_star_module, "stage_is_full", lambda *_a, **_k: False
    )
    fresh_machine.stage_scroll_signature = screen.copy()
    opened = 0
    for _ in range(8):
        fresh_machine._pending_prepare = 0  # 每关打完回到列表重新看
        action = fresh_machine.next_action(screen)
        assert action is not None
        if action.name != "open-stage":
            break
        opened += 1
    assert opened > 0, "这一屏本来就有没满星的小节"
    assert action.name != "open-stage"
    assert "通关条件" in action.reason, (
        f"打过仍未满星的小节没有被明确提示：{action.reason}"
    )


def test_stamina_popup_is_handled_instead_of_unrecognized(fresh_machine):
    """体力不足弹窗是业务弹窗，不能判成「认不出当前页面」干等超时。"""
    screen = load_story("stamina_popup_pc_live_20261101.png")
    action = fresh_machine.next_action(screen)
    assert action is not None
    assert action.name in {"stamina-material", "stamina-confirm"}, (
        f"体力弹窗应进入两段式购买流程，实际 {action.name}"
    )


def test_sweep_moves_through_all_episodes_and_finishes(startup_machine, monkeypatch):
    """序列级：从开场一路扫到六章收工，中间不许重复开同一张篇章。"""
    screen = load("22_now.png")
    monkeypatch.setattr(startup_machine, "star_points", lambda _s: [])
    names: list[str] = []
    action = object()
    for _ in range(80):
        action = startup_machine.next_action(screen)
        if action is None:
            break
        names.append(action.name)
    assert action is None, "六章扫完应宣布收工"
    assert names.count("next-episode") == 5, f"换章次数不对：{names}"
    assert "open-chapter" not in names
    assert startup_machine.completed_cycles == 1


# ---- 连续滚动不能被「同一动作最多 4 次」误杀（19:18 实跑失败回归）----------
def test_scroll_actions_are_exempt_from_the_four_try_limit():
    """19:20:46 那轮：换到第 2 章后归位连滚 4 次，被主循环判「点击未推进」而报错。

    第一章一屏就够、滚 1 次就过；第二章卡片多，归位与往右逐屏看都要连滚
    好几次。滚动是**页内动作、页面本来就不换**，不能按「点了没换页」计数。
    """
    assert StoryStarRunner._REPEATABLE_ACTIONS == frozenset(
        {"scroll-chapters", "scroll-chapters-left", "scroll-stages"}
    ), "三个滚动动作都必须在可连续重复名单里"
    # 老路线默认仍是空名单，行为一点不变。
    from auto_game_unified.games.epic7.runner_base import ModeRunnerBase

    assert ModeRunnerBase._REPEATABLE_ACTIONS == frozenset()


def test_rewind_is_bounded_even_if_the_picture_keeps_changing(fresh_machine, monkeypatch):
    """背景星光一直在动、判不出「滚不动」时，归位也必须自己收住。"""
    screen = load("22_now.png")
    fresh_machine._need_rewind = True
    from auto_game_unified.core import supervisor

    monkeypatch.setattr(
        supervisor,
        "meaningful_change",
        lambda _before, _after: True,  # 画面永远「有变化」
    )
    rolls = 0
    for _ in range(story_star_module.REWIND_MAX_STEPS + 2):
        action = fresh_machine._rewind_action(screen)
        if action is None:
            break
        assert action.name == "scroll-chapters-left"
        rolls += 1
    assert action is None, "到达上界必须结束归位"
    assert rolls <= story_star_module.REWIND_MAX_STEPS


# ---- 20:27 实跑：往右滚太慢 + 满星小节被点进去开打 --------------------------
def test_right_scroll_also_compares_only_the_cards_area(fresh_machine, monkeypatch):
    """往右逐屏看卡片判「滚到头」也必须只看卡片区，否则星空背景让它一直滚。"""
    from auto_game_unified.core import supervisor

    screen = load("22_now.png")
    fresh_machine.scroll_signature = screen.copy()
    seen: list[tuple[int, int]] = []

    def record(before, after):
        seen.append((before.shape[0], before.shape[1]))
        return False  # 判成「滚不动」，好走到换章分支

    monkeypatch.setattr(supervisor, "meaningful_change", record)
    monkeypatch.setattr(fresh_machine, "star_points", lambda _s: [])
    fresh_machine.next_action(screen)
    assert seen, "没有调用画面比对"
    assert seen[0][0] < screen.shape[0] and seen[0][1] < screen.shape[1], (
        "往右滚还在比整帧，背景动画会让每章多滚十几次"
    )


def test_scroll_retry_wait_is_short(fresh_machine):
    """滚动是页内动作，不该按换页那样等 6 秒。"""
    runner = StoryStarRunner(fresh_machine, MagicMock())
    assert runner._action_retry_seconds("scroll-chapters") <= 2.0
    assert runner._action_retry_seconds("scroll-stages") <= 2.0


def test_open_stage_reason_reports_the_green_checks_it_read(fresh_machine, monkeypatch):
    """日志要带上这一屏读到的绿勾位置，下次实跑不用截图也能定判据有没有漏检。"""
    screen = load("31_ch10_stages.png")
    monkeypatch.setattr(fresh_machine, "stage_checks", lambda _s: [])
    monkeypatch.setattr(
        story_star_module, "stage_is_full", lambda *_a, **_k: False
    )
    fresh_machine.stage_scroll_signature = None
    action = fresh_machine.next_action(screen)
    assert action is not None and action.name == "open-stage"
    assert "绿勾" in action.reason and "读到" in action.reason


def test_prepare_battle_is_cancelled_when_the_stage_is_actually_full(
    fresh_machine, monkeypatch,
):
    """点「准备战斗」之前复核一次：满星小节绝不能被打（20:33 实跑白打一关）。"""
    from unittest.mock import MagicMock as Mock

    screen = load("13_ep1_full_stages.png")
    fresh_machine._pending_prepare = 3
    fresh_machine._pending_stage_row = 432
    def locate(_screen, name):
        # 只让「准备战斗」出现；其余（含体力弹窗）一律没有，别把复核测试带偏。
        return Mock(center=(1740, 1051)) if name == "prepare_battle" else None

    monkeypatch.setattr(fresh_machine.story, "_locate", locate)
    monkeypatch.setattr(fresh_machine, "stage_checks", lambda _s: [(120, 432)])
    action = fresh_machine.next_action(screen)
    assert action is not None
    assert action.name != "prepare-battle", (
        "复核发现这一行已有绿勾，必须取消开打、回去重新看整页"
    )
