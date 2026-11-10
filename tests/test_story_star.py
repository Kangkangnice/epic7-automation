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

import cv2
import numpy as np
import pytest

from auto_game_unified.games.epic7.evidence.story_star import chapter_is_full
from auto_game_unified.games.epic7.story_star import (
    StoryStarState,
    StoryStarStateMachine,
    build_story_star_templates,
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
