from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.evidence_diagnostics import inspect_profile
from auto_game_unified.games.epic7.evidence.common import (
    EvidenceState,
    validate_profile,
)
from auto_game_unified.games.epic7.evidence.survivor import (
    BATTLE_SCORE_THRESHOLD,
    CONFIRM_BUTTON_BOX,
    LEVEL_UP_REDRAW_BOX,
    LEVEL_UP_THRESHOLD,
    RESULT_RESTART_BOX,
    RESULT_RESTART_THRESHOLD,
    RESULT_TITLE_THRESHOLD,
    WEAPON_CARD_BOX,
    WEAPON_CARD_THRESHOLD,
    build_survivor_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures"
SURVIVOR_FIXTURE_DIR = FIXTURES / "epic7_survivor"

# 循环里四个页面各自对应的 fixture，同一页可以有多张，顺序就是一轮的运行顺序。
# 三选一三张：静态夹具，以及 2026-09-16 两次实跑留下的实时帧。
# 实时帧才是关键证据——2026-09-16 先暴露出「副标题锚点在实时帧上只有 0.7101」，
# 同一天晚上 21:29 的第二次失败又暴露出「标题锚点被半透明面板拖到 0.8662」，
# 两次都是静态夹具上看不出来的（同一位置在夹具上都是 1.0000）。
SURVIVOR_FIXTURES = (
    ("survivor.weapon_card", "first_card_select.png"),
    ("survivor.battle", "battle_live_probe.png"),
    ("survivor.level_up", "level_up.png"),
    ("survivor.level_up", "level_up_live_20260916.png"),
    ("survivor.level_up", "level_up_live_20260916_2129.png"),
    ("survivor.result", "result.png"),
)

SURVIVOR_PAGES = tuple(dict.fromkeys(page for page, _ in SURVIVOR_FIXTURES))

# 明确排除（UNSAFE）而不是「认不出来」的组合：三选一弹窗左卡的分类标签和首卡页
# 一模一样，所以弹窗上 weapon_card 的必要锚点是真命中的，只能靠 forbidden 排掉。
EXPLICIT_REJECTIONS = {("survivor.weapon_card", "survivor.level_up")}

# 其它路线的页面，全部取基准尺寸 1982x1132；旧基准 3200x2000 的截图不适用。
OTHER_ROUTE_PAGES = (
    ("epic7_expedition", "result"),
    ("epic7_fodder", "results"),
    ("epic7_navigation", "lobby"),
    ("epic7_hero", "reward_popup"),
    ("epic7_hero", "transmit_select"),
    ("epic7_shop_refresh", "shop_top_live"),
)


def _screen(group: str, name: str) -> np.ndarray:
    bgr = cv2.imread(str(FIXTURES / group / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None, f"缺少 fixture: {group}/{name}"
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _survivor_screen(name: str) -> np.ndarray:
    bgr = cv2.imread(str(SURVIVOR_FIXTURE_DIR / name), cv2.IMREAD_COLOR)
    assert bgr is not None, f"缺少 fixture: {name}"
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def test_profile_declares_existing_current_client_templates():
    profile = build_survivor_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("weapon_card_label").reference_size == (1982, 1132)
    assert profile.atom("weapon_card_label").threshold == WEAPON_CARD_THRESHOLD
    assert profile.atom("result_title").threshold == RESULT_TITLE_THRESHOLD
    assert profile.atom("result_restart").threshold == RESULT_RESTART_THRESHOLD
    assert profile.atom("level_up_title").threshold == LEVEL_UP_THRESHOLD
    assert profile.atom("level_up_redraw").threshold == LEVEL_UP_THRESHOLD
    assert profile.atom("battle_score_label").threshold == BATTLE_SCORE_THRESHOLD


def test_level_up_page_never_uses_the_translucent_subtitle_as_an_anchor():
    """副标题压在半透明面板上，实时帧只有 0.7101，不能再当锚点。"""

    profile = build_survivor_evidence(TEMPLATES)

    assert "level_up_prompt" not in profile.atoms
    assert "level_up_prompt" not in {
        key
        for page in profile.pages
        for key in (*page.required, *page.forbidden)
        + tuple(key for group in page.any_of for key in group)
    }


def test_level_up_page_accepts_either_of_its_two_anchors():
    """两个锚点各自都会失效（标题怕半透明面板透底，按钮怕抽完次数后变灰）。

    所以升级页必须写成「任一命中即可」；只写一个的话，另一个失效时整页就认不出来，
    2026-09-16 21:29 就是这么卡的：标题 0.8662、按钮 0.9134，两个都压在 0.90 门槛下。
    """

    profile = build_survivor_evidence(TEMPLATES)

    page = profile.page("survivor.level_up")
    assert page.required == ()
    assert page.any_of == (("level_up_title", "level_up_redraw"),)
    # 任一命中即 SAFE，两个都不命中才 UNKNOWN
    assert page.evaluate({"level_up_title": False, "level_up_redraw": True}) is EvidenceState.SAFE
    assert page.evaluate({"level_up_title": True, "level_up_redraw": False}) is EvidenceState.SAFE
    assert page.evaluate({"level_up_title": False, "level_up_redraw": False}) is EvidenceState.UNKNOWN


def test_every_level_up_fixture_keeps_both_anchors_above_the_threshold_alone():
    """实时帧上两个锚点各自都要能单独认出升级页，不能只靠另一个兜底。"""

    profile = build_survivor_evidence(TEMPLATES)

    for page, name in SURVIVOR_FIXTURES:
        if page != "survivor.level_up":
            continue
        inspection = inspect_profile(_survivor_screen(name), profile, TEMPLATES)
        for key in ("level_up_title", "level_up_redraw"):
            atom = inspection.atoms[key]
            assert atom.score is not None and atom.score >= LEVEL_UP_THRESHOLD, (
                f"{name} 上 {key} 只有 {atom.score}"
            )


def test_level_up_redraw_anchor_lands_inside_the_banned_redraw_button():
    """判别三选一页的锚点，正好落在永远不许点的那颗按钮上。"""

    profile = build_survivor_evidence(TEMPLATES)

    for name in ("level_up.png", "level_up_live_20260916.png"):
        inspection = inspect_profile(_survivor_screen(name), profile, TEMPLATES)
        center = inspection.atoms["level_up_redraw"].center
        assert center is not None
        x, y, width, height = LEVEL_UP_REDRAW_BOX
        assert x <= center[0] <= x + width
        assert y <= center[1] <= y + height


def test_live_level_up_popup_is_explicitly_rejected_as_the_first_card_page():
    """三选一弹窗左卡标签也是「攻击武器」，实时帧上首卡页锚点会以 0.9994 真命中。

    所以光靠「升级页排在首卡页前面」不够，必须用 forbidden 显式排除。
    （静态夹具上这个锚点只有 0.7932，看不出问题，只有实时帧能暴露。）
    """

    profile = build_survivor_evidence(TEMPLATES)
    inspection = inspect_profile(
        _survivor_screen("level_up_live_20260916.png"), profile, TEMPLATES
    )

    assert inspection.atoms["weapon_card_label"].observed
    assert inspection.atoms["weapon_card_label"].score >= WEAPON_CARD_THRESHOLD
    assert inspection.atoms["level_up_redraw"].observed
    assert inspection.pages["survivor.weapon_card"] is EvidenceState.UNSAFE
    assert inspection.pages["survivor.level_up"] is EvidenceState.SAFE


def test_anchor_center_lands_inside_the_clickable_weapon_card():
    """点击点直接用锚点命中中心，因此锚点必须落在卡片可点范围内。"""

    profile = build_survivor_evidence(TEMPLATES)
    inspection = inspect_profile(
        _screen("epic7_survivor", "first_card_select"),
        profile,
        TEMPLATES,
    )

    center = inspection.atoms["weapon_card_label"].center
    assert center is not None
    x, y, width, height = WEAPON_CARD_BOX
    assert x <= center[0] <= x + width
    assert y <= center[1] <= y + height


def test_every_survivor_page_is_safe_on_its_own_fixture():
    profile = build_survivor_evidence(TEMPLATES)

    for page, name in SURVIVOR_FIXTURES:
        inspection = inspect_profile(_survivor_screen(name), profile, TEMPLATES)
        assert inspection.pages[page] is EvidenceState.SAFE, (
            f"{page} 在 {name} 上没有识别出来"
        )


def test_survivor_pages_do_not_match_each_other():
    """四个页面必须互相排斥，否则状态机会把循环的某一环认成另一环。"""

    profile = build_survivor_evidence(TEMPLATES)

    for page, name in SURVIVOR_FIXTURES:
        inspection = inspect_profile(_survivor_screen(name), profile, TEMPLATES)
        for other in SURVIVOR_PAGES:
            if other == page:
                continue
            expected = (
                EvidenceState.UNSAFE
                if (other, page) in EXPLICIT_REJECTIONS
                else EvidenceState.UNKNOWN
            )
            assert inspection.pages[other] is expected, (
                f"{name} 上的 {other} 状态为 {inspection.pages[other].value}，"
                f"期望 {expected.value}"
            )


def test_other_route_pages_stay_unknown():
    """武器名、奖励数量、游玩时间每次都随机，能用的只有固定文案锚点。

    所以要在别的路线页面上验证「一个都认不出来」，包括另外三条路线的结算页与弹窗。
    """

    profile = build_survivor_evidence(TEMPLATES)

    for group, name in OTHER_ROUTE_PAGES:
        inspection = inspect_profile(_screen(group, name), profile, TEMPLATES)
        for page in SURVIVOR_PAGES:
            assert inspection.pages[page] is EvidenceState.UNKNOWN, (
                f"{group}/{name} 被误判为 {page}"
            )


def test_restart_anchor_center_lands_inside_the_restart_button():
    """点击点直接用锚点命中中心，因此锚点必须落在「重新进行」按钮范围内。"""

    profile = build_survivor_evidence(TEMPLATES)
    inspection = inspect_profile(
        _screen("epic7_survivor", "result"),
        profile,
        TEMPLATES,
    )

    center = inspection.atoms["result_restart"].center
    assert center is not None
    x, y, width, height = RESULT_RESTART_BOX
    assert x <= center[0] <= x + width
    assert y <= center[1] <= y + height


def test_restart_anchor_never_lands_on_the_confirm_button():
    """结算页底部并排两个尺寸几乎相同的按钮，「确认」在右、只差 346 像素。

    误点「确认」会离开结算流程，所以必须守住「只可能命中左边那个」。这条同时验证
    搜索区域已经收紧到左半边，排除掉孪生按钮。
    """

    profile = build_survivor_evidence(TEMPLATES)
    inspection = inspect_profile(
        _screen("epic7_survivor", "result"),
        profile,
        TEMPLATES,
    )

    center = inspection.atoms["result_restart"].center
    assert center is not None
    x, y, width, height = CONFIRM_BUTTON_BOX
    inside_confirm = x <= center[0] <= x + width and y <= center[1] <= y + height
    assert not inside_confirm, f"命中中心 {center} 落在了「确认」按钮上"
