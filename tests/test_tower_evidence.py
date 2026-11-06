import dataclasses
from pathlib import Path

import cv2

from auto_game_unified.core.evidence_diagnostics import inspect_profile
from auto_game_unified.core.matcher import (
    SCALE_FALLBACK_ANCHORS,
    find_best_template,
    find_template,
    load_template,
    locate_with_fallback,
)
from auto_game_unified.games.epic7.evidence.common import (
    EvidenceState,
    validate_profile,
)
from auto_game_unified.games.epic7.evidence.arena import build_arena_evidence
from auto_game_unified.games.epic7.evidence.labyrinth_stone import (
    build_labyrinth_stone_evidence,
)
from auto_game_unified.games.epic7.evidence.moonlight_theater import (
    build_moonlight_evidence,
)
from auto_game_unified.games.epic7.evidence.story import build_story_evidence
from auto_game_unified.games.epic7.evidence.tower import REGIONS, build_tower_evidence
from auto_game_unified.games.epic7.evidence.world_boss import build_world_boss_evidence
from auto_game_unified.games.epic7.battle_controls import battle_scene_visible
from auto_game_unified.games.epic7.navigation import Epic7Navigator
from auto_game_unified.games.epic7.template_paths import resolve_template_dir
from auto_game_unified.games.epic7.tower import (
    TowerState,
    TowerStateMachine,
    build_tower_templates,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "tower"


def test_tower_profile_uses_current_templates_and_regions():
    profile = build_tower_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("home_enter").region == (1400, 950, 582, 182)
    assert profile.atom("card_decide").region == (800, 950, 700, 182)
    assert profile.page("tower.team").required == ("team_battle_start", "prepare_title")
    assert profile.page("tower.card").required == ("card_decide", "card_hint")


def test_only_the_shared_auto_off_judge_changes_its_match_mode():
    """`auto_off` 是本画像里**唯一**换比对口径的锚点，阈值也按新口径重定过。

    ⚠️ 名字与数字都独立写死，不遍历画像自己 —— 否则实现一改断言跟着改。
    """
    profile = build_tower_evidence(TEMPLATES)

    assert profile.atom("auto_off").match_mode == "white_mask"
    # 跨路线共享：三处（主线 / 远征 / 月塔）画的是同一个控件，所以复用同一张图。
    assert profile.atom("auto_off").template_path == "../story/auto_off.png"
    # 0.85 是在**新口径**上重扫全库定的，不是把旧口径的 0.80 搬过来：
    # 真阳性侧月塔三帧都是 0.9214，真阴性侧全库最高 0.6215。
    assert profile.atom("auto_off").threshold == 0.85
    for name in (
        "season_tower_title",
        "home_enter",
        "floor_select_team",
        "team_battle_start",
        "prepare_title",
        "card_decide",
        "card_hint",
        "result_clear",
    ):
        assert profile.atom(name).match_mode == "raw", name


def test_a_typo_in_the_match_mode_is_reported_not_swallowed():
    """口径写错必须进 `validate_profile` 的错误列表。

    静默退回原样比的话，阈值还是新口径的数字，判据会**变成永假** ——
    正是「判据不许静默降级」要拦的那一类。
    """
    profile = build_tower_evidence(TEMPLATES)
    broken = dataclasses.replace(
        profile,
        atoms={
            **profile.atoms,
            "auto_off": dataclasses.replace(
                profile.atom("auto_off"), match_mode="white-mask"
            ),
        },
    )

    errors = validate_profile(broken, TEMPLATES)

    assert any(
        "未知的匹配口径" in error and "auto_off" in error for error in errors
    ), errors


def test_tower_profile_reports_required_template_missing_from_empty_directory(tmp_path):
    profile = build_tower_evidence(tmp_path)

    assert "home_enter" in profile.atoms
    errors = validate_profile(profile, tmp_path)
    # 月塔的白名单是空集（一张都不许缺席），所以**每个**锚点都必须在
    # 「模板不存在」错误里被点名 —— 这也是「判据不许静默降级」的钉子：
    # 谁把某张图改成可选，这里立刻变红。
    for name in (
        "season_tower_title",
        "home_enter",
        "floor_select_team",
        "team_battle_start",
        "prepare_title",
        "card_decide",
        "card_hint",
        "result_clear",
    ):
        assert any(
            f"{name}.png" in error and "模板不存在" in error for error in errors
        ), name


# ── PC 客户端（2026-11-03 补 ``tower/pc/card_decide.png``）────────────────────
#
# ⚠️ PC 帧单独放一个目录（``tests/fixtures/epic7_tower_pc/``），**不混进**
# ``epic7_tower/``。那套夹具是**模拟器基线**，两条护栏会把「同一页的另一个平台
# 渲染」判成噪声：
#   * ``test_every_fixture_matches_exactly_one_page`` 要求每张只命中自己那页；
#   * ``test_every_judge_clears_its_threshold_with_a_wide_margin`` 要求「他页最高分
#     < 0.88 且余量 > 0.30」—— 而共享 `card_decide` 在 PC 帧上是 0.8668，
#     混进去必然逼人放宽门槛，那正是本项目最不许做的事。
PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_tower_pc"
PC_FRAME_NAMES = ("card_pc_live_20261103", "card_pc_live_20261103_b")


def _pc_frame(name: str):
    path = PC_FIXTURES / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def test_pc_card_page_is_recognized_and_nothing_else_matches():
    """正例：两张 PC 现场帧上，**只有** ``tower.card`` 是 SAFE。

    这两张就是 2026-11-03 那两次实跑的故障帧（08:08 与 23:44 各一次）。当时
    `card_decide` 只有 0.8668（阈 0.88），于是：
    ``result_visible`` 恒为 False ⇒ 战斗监督干等 45 秒 ⇒ 报 ``battle_unrecognized``；
    接着回家流程在这页上连按 ESC 也没反应 ⇒ 整条每日任务以「无法回到首页」中止。
    """
    root = resolve_template_dir(ROOT / "games" / "epic7" / "templates", "pc")
    profile = build_tower_evidence(root / "tower")

    for name in PC_FRAME_NAMES:
        result = inspect_profile(_pc_frame(name), profile, root / "tower")
        safe = sorted(
            page for page, state in result.pages.items() if state is EvidenceState.SAFE
        )
        assert safe == ["tower.card"], f"{name} 判成了 {safe}"
        assert result.atoms["card_decide"].score >= 0.99, name
        assert result.atoms["card_hint"].score >= 0.99, name


def test_the_shared_templates_cannot_recognize_the_pc_card_page():
    """反向锁：**共享（模拟器）那套图**在这两张 PC 帧上必须认不出来。

    认得出就说明 pc 覆盖图是多余的 —— 或者共享图被偷偷换成了 PC 图。

    ⚠️ ``0.8668`` 这个数字要留在断言里：它是「看着像、就是过不去」那股劲的度量，
    也是当初一眼没认出这是识别问题的原因（差了 0.0132，不是差一大截）。
    """
    profile = build_tower_evidence(TEMPLATES)
    template = load_template(str(TEMPLATES / "card_decide.png"))

    for name in PC_FRAME_NAMES:
        frame = _pc_frame(name)
        match = find_best_template(
            frame,
            template,
            region=REGIONS["card_decide"],
            reference_size=(1982, 1132),
        )
        assert 0.85 < match.score < 0.88, f"{name} 的共享图分数变了：{match.score:.4f}"

        result = inspect_profile(frame, profile, TEMPLATES)
        safe = [
            page for page, state in result.pages.items() if state is EvidenceState.SAFE
        ]
        assert safe == [], f"{name} 用共享图仍然判出了 {safe}"


# ── UI 尺寸漂移（2026-11-04 彻夜实跑踩到）────────────────────────────────────
#
# 同一个 PC 客户端，**两次启动之间**会把自己那套 UI 画得不一样大：
# `战斗开始` 实测 476x69 → 461x67（×0.9685）。`TM_CCOEFF_NORMED` 只归一化亮度、
# **不归一化尺度**，2% 的偏差就足以把 1.0000 打到 0.6448。
#
# 所以 ``core.matcher.SCALE_FALLBACK_ANCHORS`` 里的锚点在「原样不过阈」时会按
# ``SCALE_FALLBACK_STEPS`` 扫一遍模板尺寸。下面三条把这件事钉死：
#   1. 名单里的名字必须真的存在于月塔证据里（写错名字 = 兜底悄悄不生效）；
#   2. 小尺寸那档 PC 帧必须认得出来，且**原样口径确实认不出**（否则兜底是摆设）；
#   3. 兜底是「换把尺子」而不是「放宽判定」：不该命中的页面照样不许命中。
SCALE_PC_FRAMES = (
    "card_pc_live_small_20261104",
    "prepare_pc_live_20261103",
    "prepare_pc_live_small_20261104",
)


def test_the_scale_whitelist_only_names_anchors_that_exist():
    """名单里每个名字都得在**某一条**路线的证据画像里找得到。

    ⚠️ 名字是**锚点名**不是模板名，而且兜底按名字开关 —— 名字写错一个字母，
    兜底就静默不生效，症状是「明明加过白名单还是认不出」，极难查。
    名单是**跨路线共用**的（`auto_off` 就在月塔 / 竞技场 / 主线三处出现），
    所以这里逐个路线收集再比，不能只看月塔。
    """
    known = set(Epic7Navigator._REGIONS)
    for builder in (
        build_tower_evidence,
        build_arena_evidence,
        build_story_evidence,
        build_labyrinth_stone_evidence,
        build_moonlight_evidence,
        build_world_boss_evidence,
    ):
        known |= set(builder(TEMPLATES).atoms)
    for anchor in SCALE_FALLBACK_ANCHORS:
        assert anchor in known, f"缩放兜底名单里的 {anchor} 在任何路线证据里都不存在"


def test_the_small_scale_pc_card_frame_needs_the_sweep_and_gets_it():
    """00:12 那帧：原样 0.6448 认不出，扫到 ×0.98 是 0.9404。

    这是「同一页、两档尺寸」最硬的一组证据 —— 23:44 那帧在 ×1.00 才是 0.9998、
    在 ×0.98 只有 0.6661。**没有任何单一缩放能同时服务两档**，只能逐帧试。
    """
    root = resolve_template_dir(TEMPLATES.parent, "pc")
    profile = build_tower_evidence(root / "tower")
    frame = _pc_frame("card_pc_live_small_20261104")

    raw = find_best_template(
        frame,
        load_template(str(TEMPLATES / "pc" / "card_hint.png")),
        region=REGIONS["card_hint"],
        reference_size=(1982, 1132),
    )
    assert 0.60 < raw.score < 0.70, f"原样口径的分数变了：{raw.score:.4f}"

    result = inspect_profile(frame, profile, root / "tower")
    safe = sorted(
        page for page, state in result.pages.items() if state is EvidenceState.SAFE
    )
    assert safe == ["tower.card"], f"小尺寸卡页判成了 {safe}"
    assert result.atoms["card_hint"].score >= 0.94


def test_both_ui_scales_of_the_prepare_page_are_recognized():
    """准备战斗页两档尺寸（11-03 08:06 / 11-04 00:05）都要认出且**只**认出这一页。

    这两帧是同一条路线、同一台机器、同一个客户端，UI 却画得不一样大 —— 不是
    「用户换了分辨率」，所以不能靠「让用户把客户端调回来」来收场。
    """
    root = resolve_template_dir(TEMPLATES.parent, "pc")
    profile = build_tower_evidence(root / "tower")

    for name in ("prepare_pc_live_20261103", "prepare_pc_live_small_20261104"):
        result = inspect_profile(_pc_frame(name), profile, root / "tower")
        safe = sorted(
            page for page, state in result.pages.items() if state is EvidenceState.SAFE
        )
        assert safe == ["tower.team"], f"{name} 判成了 {safe}"


def test_the_scale_sweep_is_off_for_anchors_that_are_not_on_the_whitelist():
    """没登记在册的锚点：``locate_with_fallback`` 必须与 ``find_template`` 等价。

    这条守的是「模拟器零改动」：兜底只对名单里那几颗生效，别的判据一个像素都别动。
    """
    assert "result_clear" not in SCALE_FALLBACK_ANCHORS
    frame = _pc_frame("card_pc_live_small_20261104")
    template = load_template(str(TEMPLATES / "result_clear.png"))
    plain = find_template(
        frame,
        template,
        0.88,
        region=REGIONS["result_clear"],
        reference_size=(1982, 1132),
    )
    wrapped = locate_with_fallback(
        "result_clear",
        frame,
        template,
        0.88,
        region=REGIONS["result_clear"],
        reference_size=(1982, 1132),
    )
    assert plain is None and wrapped is None


# ── `TEAM --战斗开始--> CARD`：2026-11-04 01:40 真机事故（秒杀型战斗）────────────
#
# 这一队是**秒杀**：点下「战斗开始」后战斗画面只存在 1~2 秒，紧接着弹出三选一
# 装置页并**稳定停在那里**。而转场要「目标连续=2」，轮询间隔 1~2 秒 ⇒ 永远抓不到
# 那一两帧战斗 ⇒ 57 秒后报
# ``动作[battle-start]未稳定进入[战斗中/准备战斗]``，整条每日任务接着中止。
#
# ⚠️ 判定这**不是识别问题**：超时那一帧的 ``evidence.json`` 里
# ``card_hint``=0.9404（×0.98）、``card_decide``=0.8973，**两枚都过阈**；
# 而同帧 ``result_clear``=0.3557 / ``conquer_title``=0.2347 / ``battle_failed``=0.0000
# / ``team_battle_start``=0.3414 / ``prepare_title``=0.3771。
# ⇒ 缺的是「这一下可以落到 CARD」这句**合同**，不是阈值、不是『目标连续』。
# 那两条都是全项目判据的根，为了一个落点去动它们不划算。


def _pc_tower_machine(state):
    """用 **PC 那套模板** 起状态机（夹具是 PC 帧 ⇒ 必须走同一个分辨率来源）。"""
    root = resolve_template_dir(TEMPLATES.parent, "pc")
    machine = TowerStateMachine(build_tower_templates(root / "tower"))
    machine.state = state
    return machine


def test_the_instant_clear_lands_on_the_device_page_which_is_a_legal_target():
    """`TEAM --战斗开始--> CARD` 必须成立，且**只**成立这一条。

    两条一起断言才叫判据：
    - 正方向：``action_target_state`` 必须返回 ``CARD``（否则 57 秒超时）；
    - 反方向：同一帧必须**不是** TEAM / BATTLE / RESULT（否则这条边等于
      「什么页都收」，等于没有判据）。
    """
    machine = _pc_tower_machine(TowerState.TEAM)
    frame = _pc_frame("card_after_instant_battle_pc")
    action = machine.next_action(_pc_frame("prepare_pc_live_20261103"))
    assert action.name == "battle-start"
    assert TowerState.CARD in action.target_states

    assert not machine.is_in_state(frame, TowerState.TEAM)
    assert not machine.is_in_state(frame, TowerState.BATTLE)
    assert not machine.is_in_state(frame, TowerState.RESULT)
    assert machine.is_in_state(frame, TowerState.CARD)

    assert machine.action_target_state(frame, action) is TowerState.CARD

    # 落进 CARD 之后必须**立刻有活可干**：先选中间卡，不许干等。
    machine.commit(action, TowerState.CARD)
    assert machine.next_action(frame).name == "pick-middle-card"


def test_the_instant_clear_frame_is_never_mistaken_for_a_battle_scene():
    """反向锁：这一帧**不许**被 ``battle_scene_visible`` 认成战斗画面。

    真机探针（60 秒 × 1.5 秒采样）里它整段都是 False，而 1.5 秒那一帧确实是
    ``AUTO_CONTROLS`` —— 说明「战斗发生了、但快得抓不住」，不是「没打」。
    ⇒ 想靠「战斗中」这一页来接住秒杀，方向就是错的。
    """
    frame = _pc_frame("card_after_instant_battle_pc")

    assert battle_scene_visible(frame) is False
