from pathlib import Path

import pytest

import cv2

from auto_game_unified.core.evidence_diagnostics import inspect_profile
from auto_game_unified.core.matcher import find_template, load_template
from auto_game_unified.games.epic7.arena import (
    ArenaState,
    ArenaStateMachine,
    TicketExhausted,
    build_templates,
    _VS_CONFIRM_REGION,
    _VS_CONFIRM_THRESHOLD,
)
from auto_game_unified.games.epic7.evidence.arena import (
    REFERENCE_SIZE,
    REGIONS as ARENA_REGIONS,
    THRESHOLDS as ARENA_THRESHOLDS,
    build_arena_evidence,
    classify_arena_selected_scores,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceState, validate_profile
from auto_game_unified.games.epic7.template_paths import (
    resolve_template,
    resolve_template_dir,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"


def _screen(name: str):
    bgr = cv2.imread(str(FIXTURES / name), cv2.IMREAD_COLOR)
    assert bgr is not None
    screen = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    width, height = REFERENCE_SIZE
    if screen.shape[1] >= width and screen.shape[0] >= height:
        screen = screen[:height, :width]
    return screen


def test_arena_profile_declares_existing_templates_and_current_thresholds():
    profile = build_arena_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("list_ready").threshold == 0.88
    assert profile.atom("battle_start").threshold == 0.90
    assert profile.atom("battle_start").region == (900, 930, 550, 202)
    assert profile.atom("list_ready").reference_size == REFERENCE_SIZE


def test_arena_team_page_rejects_ticket_popup_as_unsafe():
    profile = build_arena_evidence(TEMPLATES)
    page = profile.page("arena.team")

    assert page.evaluate({"battle_start": True}) is EvidenceState.SAFE
    assert (
        page.evaluate({"battle_start": True, "no_ticket": True})
        is EvidenceState.UNSAFE
    )


def test_arena_selected_page_compares_active_and_list_button_scores():
    assert classify_arena_selected_scores(1.0, 0.95) is EvidenceState.SAFE
    assert classify_arena_selected_scores(0.90, 0.95) is EvidenceState.UNKNOWN


def test_selected_fixture_matches_runtime_and_profile_page_state():
    screen = _screen("selected.png")
    profile = build_arena_evidence(TEMPLATES)
    machine = ArenaStateMachine(build_templates(TEMPLATES))

    report = inspect_profile(screen, profile, TEMPLATES)

    assert machine.is_in_state(screen, ArenaState.SELECTED)
    assert report.pages["arena.selected"] is EvidenceState.SAFE


def test_quick_battle_fixture_matches_runtime_and_profile_team_state():
    screen = _screen("quick_battle_selected_live_20260826.png")
    profile = build_arena_evidence(TEMPLATES)
    machine = ArenaStateMachine(build_templates(TEMPLATES))

    report = inspect_profile(screen, profile, TEMPLATES)

    assert machine.is_in_state(screen, ArenaState.TEAM)
    assert report.pages["arena.team"] is EvidenceState.SAFE


def test_pc_ticket_popup_uses_pc_override_templates():
    """PC 现场帧（2026-11-01 实跑）：「购买旗帜」弹窗在共享模板下认不出。

    实测共享 ``no_ticket`` 在 PC 弹窗帧上只有 0.7671（字形渲染差异），监督循环
    因此收不到「交还业务处理」信号，一直重按「开始战斗」直到 4 次熔断 ——
    而低通口径会把迷宫/商店的「购买确认」弹窗误放进来（0.91+），白掩膜救不动
    （0.684），按 PC 迁移文档 §3 走设计内动作：往 ``templates/pc/`` 补同名图。

    正例：PC 弹窗帧上，pc 口径下 ``no_ticket`` 命中（监督循环据此交还业务）、
    ``purchase_title``+``purchase_cancel`` 双锚点同时命中（收尾据此点「取消」）、
    状态机给出 ``purchase-friendship-ticket``（正文据此用友情点买旗）。
    反例：PC 结算页帧上这些锚点一律不得命中。
    模拟器侧零影响：emulator 口径解析到的仍是共享图。
    """
    popup = _screen("ticket_purchase_popup_pc_live_20261101.png")
    pc_result = _screen("result_victory_pc_live_20261101.png")

    # 解析口径：emulator 永远用共享图，pc 优先用覆盖图。
    assert resolve_template(TEMPLATES, "no_ticket.png", backend="emulator") == (
        TEMPLATES / "no_ticket.png"
    )
    assert resolve_template(TEMPLATES, "no_ticket.png", backend="pc") == (
        TEMPLATES / "pc" / "no_ticket.png"
    )

    # 反例先钉死：共享模板在 PC 弹窗帧上就是认不出（这正是补图的全部理由）。
    machine_emulator = ArenaStateMachine(build_templates(TEMPLATES))
    assert not machine_emulator._visible(popup, "no_ticket")

    machine_pc = ArenaStateMachine(
        build_templates(resolve_template_dir(TEMPLATES, "pc")),
        initial_state=ArenaState.BATTLE,
    )
    # 正例一：监督循环口径 —— no_ticket 命中 ⇒ 冻结背景的「开始战斗」。
    observation = machine_pc.observe_battle(popup, None)
    assert observation.pre_battle_business_visible
    assert observation.allowed_action is None

    # 正例二：正文口径 —— 三证据齐 ⇒ 用友情点买 5 面旗帜。
    action = machine_pc.next_action(popup)
    assert action.name == "purchase-friendship-ticket"
    assert "资源=友情点" in action.reason

    # 正例三：收尾口径 —— 双锚点同时命中才允许点「取消」。
    title = find_template(
        popup,
        load_template(str(TEMPLATES / "pc" / "arena_purchase_title.png")),
        ARENA_THRESHOLDS["purchase_title"],
        region=ARENA_REGIONS["purchase_title"],
        reference_size=REFERENCE_SIZE,
    )
    cancel = find_template(
        popup,
        load_template(str(TEMPLATES / "pc" / "arena_purchase_cancel.png")),
        ARENA_THRESHOLDS["purchase_cancel"],
        region=ARENA_REGIONS["purchase_cancel"],
        reference_size=REFERENCE_SIZE,
    )
    assert title is not None and cancel is not None

    # 反例：PC 结算页帧上，no_ticket 不得命中、双锚点不得同时命中。
    observation_result = machine_pc.observe_battle(pc_result, None)
    assert not observation_result.pre_battle_business_visible
    title_on_result = find_template(
        pc_result,
        load_template(str(TEMPLATES / "pc" / "arena_purchase_title.png")),
        ARENA_THRESHOLDS["purchase_title"],
        region=ARENA_REGIONS["purchase_title"],
        reference_size=REFERENCE_SIZE,
    )
    cancel_on_result = find_template(
        pc_result,
        load_template(str(TEMPLATES / "pc" / "arena_purchase_cancel.png")),
        ARENA_THRESHOLDS["purchase_cancel"],
        region=ARENA_REGIONS["purchase_cancel"],
        reference_size=REFERENCE_SIZE,
    )
    assert not (title_on_result is not None and cancel_on_result is not None)


def test_pc_vs_rank_confirm_page_yields_confirm_vs_action():
    """PC 实跑新截图（2026-11-02）：点完「战斗开始」后出现「段位 VS 确认」页。

    以往状态机没有登记这一页（只有 LIST/SELECTED/TEAM/BATTLE/RESULT/CONFIRMING），
    监督循环收不到任何放行/业务信号，一直等超时 —— 这正是截图里"卡住"的根因。

    修复后：监督在 ``observe_battle`` 里认出绿色「确认」按钮（只裁按钮本身、段位无关），
    交还 ``confirm-vs`` 放行动作，由监督点掉后进战斗；且不能误判成购买弹窗。
    模拟器侧零影响：emulator 口径下 ``vs_confirm`` 模板为 None，不会冒出 confirm-vs。
    """
    vs = _screen("arena_vs_confirm_pc_live_20261102.png")
    machine_pc = ArenaStateMachine(
        build_templates(resolve_template_dir(TEMPLATES, "pc")),
    )
    observation = machine_pc.observe_battle(vs, None)

    assert observation.allowed_action is not None
    assert observation.allowed_action[0] == "confirm-vs"
    # 不是购买弹窗：不能冻结背景、也不能走买旗帜流程。
    assert observation.pre_battle_business_visible is False

    # 互斥校验：同一张 VS 页不得被当成购买弹窗。
    assert not (
        machine_pc._visible(vs, "no_ticket")
        or machine_pc._visible(vs, "purchase_cancel")
    )

    # 模拟器侧零影响：emulator 口径下没有这张 PC 专属模板。
    machine_emulator = ArenaStateMachine(build_templates(TEMPLATES))
    assert machine_emulator.templates.vs_confirm is None
    obs_emu = machine_emulator.observe_battle(vs, None)
    assert obs_emu.allowed_action is None or obs_emu.allowed_action[0] != "confirm-vs"


def test_pc_ticket_popup_on_team_page_auto_buys_green_leaf_flags():
    """PC 实跑新截图（2026-11-02）：旗帜耗尽弹窗压在「队伍选择」页上（战斗开始变灰）。

    以往购买弹窗只在 ``BATTLE`` 状态处理，TEAM 状态下会去点被弹窗遮住、变灰不可用
    的「战斗开始」而卡死；更早一版 PC 因友情点报价锚点认不出只能优雅停止。

    现在 PC 补了 ``friendship_ticket_offer`` / ``ticket_purchase_button`` 两张同名图，
    与模拟器一样自动买绿叶旗帜（100 友情点 → 5 旗帜）继续刷，不再停。判定仍是
    「标题/取消 任一命中 ⇒ 弹窗在场」+「友情点报价 + 购买按钮都认得出才买」，避免误扣钻石。

    正例：TEAM 状态下这张弹窗页应给出 ``purchase-friendship-ticket``，不得抛 ``TicketExhausted``。
    反例：同一张弹窗页不得触发 VS 确认放行（绿色「购买」在顶部区域，与 VS 按钮区不重叠）。
    """
    popup = _screen("arena_purchase_popup_team_pc_live_20261102.png")
    machine_pc = ArenaStateMachine(
        build_templates(resolve_template_dir(TEMPLATES, "pc")),
        initial_state=ArenaState.TEAM,
    )
    action = machine_pc.next_action(popup)
    assert action.name == "purchase-friendship-ticket"
    # 只买廉价（友情点/绿叶）报价；原因里点名「资源=友情点」，不是钻石。
    assert "资源=友情点" in action.reason

    # 同一张弹窗页不得被当成 VS 确认页（绿色「购买」在顶部，与 VS 按钮区 y>=930 不重叠）。
    from auto_game_unified.core.matcher import find_template

    hit = find_template(
        popup,
        machine_pc.templates.vs_confirm,
        _VS_CONFIRM_THRESHOLD,
        region=_VS_CONFIRM_REGION,
        reference_size=REFERENCE_SIZE,
    )
    assert hit is None


def test_pc_ticket_popup_auto_buys_on_both_popup_variants():
    """PC 上两种渲染变体的「购买旗帜」弹窗都要能自动买绿叶旗帜继续刷。

    实测 PC 客户端对同一个弹窗有两种渲染：1101=深蓝面板（战斗前弹出）、
    1102=近黑面板（队伍页弹出），同一行「100 绿叶→5 旗帜」的面板底色差很大
    （约 22 vs 85），原样模板只能覆盖一种。

    修复：PC 的 ``friendship_ticket_offer`` 改裁「左侧绿叶报价格子内部」（绿叶图标 +
    「100」+ 格子底，刻意不裁选中描边、也不裁外面的大面板底），绿叶是稳定游戏资产，
    两种变体都过阈；``ticket_purchase_button`` 仍是绿色「购买」药丸。两张图都不许误匹配
    到钻石报价或别的画面。

    正例：PC 后端在两张弹窗上都给出 ``purchase-friendship-ticket``，且原因点名「资源=友情点」。
    反例：模拟器后端不受 pc/ 覆盖影响，仍在自己的弹窗上自动买（回归，行为不变）。
    """
    pc_dir = resolve_template_dir(TEMPLATES, "pc")
    machine_pc = ArenaStateMachine(build_templates(pc_dir), initial_state=ArenaState.TEAM)
    emu_dir = resolve_template_dir(TEMPLATES, "emulator")
    machine_emu = ArenaStateMachine(build_templates(emu_dir), initial_state=ArenaState.TEAM)

    pc_variants = [
        "arena_purchase_popup_team_pc_live_20261102.png",
        "ticket_purchase_popup_pc_live_20261101.png",
    ]
    for name in pc_variants:
        popup = _screen(name)
        action = machine_pc.next_action(popup)
        assert action.name == "purchase-friendship-ticket", name
        assert "资源=友情点" in action.reason, name

    # 模拟器后端：用共享模板，在自己的弹窗上仍自动买（回归）。
    emu_popup = _screen("friendship_ticket_offer_live_20260826.png")
    emu_action = machine_emu.next_action(emu_popup)
    assert emu_action.name == "purchase-friendship-ticket"
    assert "资源=友情点" in emu_action.reason
