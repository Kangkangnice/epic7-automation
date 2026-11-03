import dataclasses
from pathlib import Path

import cv2

from auto_game_unified.core.evidence_diagnostics import inspect_profile
from auto_game_unified.core.matcher import find_best_template, load_template
from auto_game_unified.games.epic7.evidence.common import (
    EvidenceState,
    validate_profile,
)
from auto_game_unified.games.epic7.evidence.tower import REGIONS, build_tower_evidence
from auto_game_unified.games.epic7.template_paths import resolve_template_dir


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
