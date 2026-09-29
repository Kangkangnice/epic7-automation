"""骑士团捐赠路线的回归测试。

守四件事：

1. **15 个锚点在本路线 11 张夹具上真的分得开** —— 每个锚点显式声明「必须过阈」与
   「必须不过阈」的夹具集合，两集合并集必须覆盖全部 11 张，不留没表态的格子。
2. **角标（亮点）判据**：两个搜索区各有正负样本；「已领完」那帧原位的字体碎片不得误报。
   ⚠️ 骑士团主页那颗红点**不参与判据**（有没有红点都要进活动界面，用户 2026-09-24 更正）。
3. **状态机每帧重判**：11 张夹具逐帧识别到正确页面；三个弹窗/确认框排在它们盖住的页面之前。
4. **转场契约真的接上了**：12 个动作全都带得出「从哪来 + 到哪去 / 页内证据」，
   并用**真状态机 + 真 Runner** 喂整条帧序列跑完一遍，守住「每个环节都长眼睛」。

⚠️ 其中两张夹具（``support_confirm`` / ``support_page_two_buttons``）是 **2026-09-24 实跑
   当天采到的原始帧**：第一版采图没遇到「支援资源」确认框，是实跑才暴露出来的一整页；
   而「一屏两个绿按钮、上面那个吃了没反应」也是实跑实测。它们不是构造出来的。
⚠️ `activity_panel`（团员商店兜底）与「有领取按钮但没有角标」这两条分支**没有专用实拍夹具**
   —— 实拍的全屏帧里游戏每次都从「资源支援」页签打开活动界面、也没有出现过
   「没有角标但有领取按钮」的画面。这两条用 `frame_without_anchor()` **擦掉某个锚点**
   构造出来，只用来覆盖分支，不当识别准确率的证据。
"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.matcher import find_best_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.common import (
    EvidenceState,
    validate_profile,
)
from auto_game_unified.games.epic7.evidence.knights_donation import (
    DEFAULT_THRESHOLD,
    DOT_MIN_FILL_RATIO,
    DOT_ZONES,
    REFERENCE_SIZE,
    REGIONS,
    THRESHOLDS,
    build_knights_donation_evidence,
    find_dot,
    milestone_claim_point,
)
from auto_game_unified.games.epic7.knights_donation import (
    MAX_SUPPORT_SCROLLS,
    REQUEST_BUTTON_ALIVE_RATIO,
    REWARD_DISMISS_DY,
    SUPPORT_LIMIT_FULL_THRESHOLD,
    SUPPORT_ROW_SKIP_TOLERANCE,
    KnightsDonationAction,
    KnightsDonationRunner,
    KnightsDonationState,
    KnightsDonationStateMachine,
    build_knights_donation_templates,
    request_button_relative_v,
    state_label,
    support_limit_full,
)
from auto_game_unified.games.epic7.knights_support_digits import (
    HOLDINGS_DX,
    HOLDINGS_DY,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "knights_donation"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_knights_donation"

GH_DOT = "guild_home_with_dot"
GH_BARE = "guild_home_no_dot"
SUP = "support_page"
SUP_SCROLLED = "support_page_scrolled"
# 2026-09-24 实跑采到的原始帧：列表里**同时有两个**绿色「支援1个」按钮
# （上面那个要的材料我持有 0、点了不生效；下面那个能支援成功）。
SUP_TWO = "support_page_two_buttons"
# 2026-09-25 实跑采到的原始帧（**诊断帧原样**）：同样是「一屏两个绿按钮」，
# 但卡住的原因是**材料不足**（上面那行持有 1、这一格要 2）—— 当时程序把它当成
# 「没点到」连点 4 次、整条路线提前收工。「材料不足就跳过」这条判据的回归依据。
SUP_SHORT = "support_page_short_material"
# 2026-09-25 21:38 实跑的**诊断帧原样**：右上角「今日支援上限 200/200」已满，
# 而列表里的绿按钮**照样是绿的**（点它什么都不发生）。两个用途：
#   ① 「上限满了」这条**画面判据**（``support_limit_full``）的正例、模板来源；
#   ② 同页 30/200 / 90/200 那几张是它的反向对照 —— 整串匹配必须分得开，
#      否则误判成「满了」会白丢一整天的支援机会。
SUP_FULL = "support_limit_full"
WK_OK = "weekly_tasks_claimable"
WK_DONE = "weekly_tasks_claimed"
# 2026-09-26 用户现场帧（**原始帧**，不是按矩形裁的）：骑士团点数 1660，
# 500/1000 已领，**可领档位是 1500**（角标中心 (1260,286)，不是老夹具的 (1073,286)）。
# 用途：里程碑搜索区从「写死的 50×50 小方块」放宽成「整条里程碑带」的正例。
# 老判据在这一帧上返回 None ⇒ 状态机判「已经没有可领档位」直接收工，1500 的奖励白丢。
WK_1500 = "weekly_tasks_claimable_at_1500"
POP = "request_popup"
POP_SEL = "request_popup_selected"
# 2026-09-24 实跑采到的原始帧：点列表「支援1个」之后弹的「支援资源」确认框
# （第一版采图时没遇到，实跑才发现的一整页）。
SCONF = "support_confirm"
REWARD = "reward_popup"

ALL_FIXTURES = (
    GH_DOT,
    GH_BARE,
    SUP,
    SUP_SCROLLED,
    SUP_TWO,
    SUP_SHORT,
    SUP_FULL,
    WK_OK,
    WK_DONE,
    WK_1500,
    POP,
    POP_SEL,
    SCONF,
    REWARD,
)
# 「资源支援」这一页的三种样子（是否带绿按钮、按钮几个、盖没盖弹窗）。
SUPPORT_PAGES = (SUP, SUP_SCROLLED, SUP_TWO, SUP_SHORT, SUP_SHORT, SUP_FULL)
# 骑士团活动界面里的所有子页（含两个页签页）。
ACTIVITY_PAGES = (
    SUP,
    SUP_SCROLLED,
    SUP_TWO,
    SUP_SHORT,
    SUP_SHORT,
    SUP_FULL,
    WK_OK,
    WK_DONE,
    WK_1500,
)
# 除「资源支援」外都不是这一页的夹具。
NOT_SUPPORT = (GH_DOT, GH_BARE, WK_OK, WK_DONE, WK_1500, POP, POP_SEL, SCONF, REWARD)
# 弹窗类的四张（三个弹窗 + 确认框）。
POPUP_FIXTURES = (POP, POP_SEL, SCONF, REWARD)

# 锚点 -> (必须过阈的夹具, 必须不过阈的夹具)。两个集合的并集必须等于 ALL_FIXTURES。
EXPECTATIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "activity_entry": (
        (GH_DOT, GH_BARE),
        (SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_OK, WK_DONE, WK_1500, POP, POP_SEL, SCONF, REWARD),
    ),
    # panel_title 与两张页签**故意不排他**：同一段文字/标题在三个页签页上都在。
    # panel_title 只当「活动界面里页签没认出来」的兜底锚点，所以它必须命中全部活动页
    # ——**包括确认框那一帧**（确认框只盖住中间，左上角标题一点没挡）。
    "panel_title": (
        ACTIVITY_PAGES + (SCONF,),
        (GH_DOT, GH_BARE, POP, POP_SEL, REWARD),
    ),
    "tab_resource_support": (
        ACTIVITY_PAGES,
        (GH_DOT, GH_BARE, POP, POP_SEL, SCONF, REWARD),
    ),
    "tab_weekly_tasks": (
        ACTIVITY_PAGES,
        (GH_DOT, GH_BARE, POP, POP_SEL, SCONF, REWARD),
    ),
    # ⚠️ 实测：确认框**只盖中间**，右上角那个「请求支援」按钮完全没被挡 ⇒
    # 它在这一帧上仍然 0.9578（过阈）。也就是说这一帧同时满足 resource_support 的
    # 判据 —— 靠的是 `_PAGE_STATES` 里 support_confirm 排在 resource_support **前面**。
    "request_support_button": (
        SUPPORT_PAGES + (SCONF,),
        (GH_DOT, GH_BARE, WK_OK, WK_DONE, WK_1500, POP, POP_SEL, REWARD),
    ),
    # 下滑后的帧上绿色按钮已经变灰 ⇒ 它属于 must_not（状态机因此才会去下滑）；
    # 两按钮那张上必须能认出**至少一个**（多按钮的情形另有用例专门测）。
    "support_one_button": (
        (SUP, SUP_TWO, SUP_FULL, SUP_SHORT),
        (GH_DOT, GH_BARE, SUP_SCROLLED, WK_OK, WK_DONE, WK_1500, POP, POP_SEL, SCONF, REWARD),
    ),
    # 现场帧 @1500 也是每周任务页 ⇒ points_label 必须命中（实测 0.9874）。
    "points_label": (
        (WK_OK, WK_DONE, WK_1500),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, POP, POP_SEL, SCONF, REWARD),
    ),
    # 已领完那帧没有「领取」按钮 ⇒ must_not。现场帧 @1500 下面三条每周任务也都是打勾的
    # （实测 claim_button 0.4071）⇒ 同样 must_not。
    "claim_button": (
        (WK_OK,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_DONE, WK_1500, POP, POP_SEL, SCONF, REWARD),
    ),
    "popup_title": (
        (POP, POP_SEL),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_OK, WK_DONE, WK_1500, SCONF, REWARD),
    ),
    "flower_cell": (
        (POP,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_OK, WK_DONE, WK_1500, POP_SEL, SCONF, REWARD),
    ),
    "flower_cell_selected": (
        (POP_SEL,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_OK, WK_DONE, WK_1500, POP, SCONF, REWARD),
    ),
    "popup_confirm": (
        (POP, POP_SEL),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_OK, WK_DONE, WK_1500, SCONF, REWARD),
    ),
    "reward_title": (
        (REWARD,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_OK, WK_DONE, WK_1500, POP, POP_SEL, SCONF),
    ),
    # 确认框自己的两个锚点：在本路线 12 张里**只**在确认框那一帧过阈
    # （其余 11 张最高 0.2079 / 0.2166，余量都在 0.58 以上）。
    "support_confirm_title": (
        (SCONF,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_OK, WK_DONE, WK_1500, POP, POP_SEL, REWARD),
    ),
    "support_confirm_button": (
        (SCONF,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, SUP_FULL, SUP_SHORT, WK_OK, WK_DONE, WK_1500, POP, POP_SEL, REWARD),
    ),
}


def screen(name: str) -> np.ndarray:
    """夹具按 RGB 读入。

    ⚠️ 必须与 ``core.matcher.load_template`` 同口径 —— 它内部做了 BGR→RGB。
    探针里漏了这一步会拿到**假分数**（实测把页签从 1.0000 压到 0.8195，
    与真实值刚好撞上，极易误判）。
    """
    bgr = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None, f"读不到夹具 {name}"
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


# 实拍标注帧（持久证据，见 ``evidence/knights_donation.py`` 的模块 docstring）。
# 「请求支援」按钮**能点**时有两种底色：``02/07/09`` 是深蓝底，夹具 ``support_page`` 是
# 褐底（悬浮高亮）。后者在 ``tests/fixtures`` 里也有，前者只有这里存着 ——
# 想要「两种底色读数一致」这条判据，就必须读它。
MANUAL_REVIEW = ROOT / "docs" / "manual_review" / "knights_donation"


def manual_review_screen(name: str) -> np.ndarray:
    bgr = cv2.imread(str(MANUAL_REVIEW / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None, f"读不到实拍标注帧 {name}"
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def fade(image: np.ndarray, factor: float) -> np.ndarray:
    """把整幅画面乘一个亮度系数，模拟**页面淡入时的暗帧**（黑幕叠加）。

    用于证明「请求支援按钮」那条判据取的是**相对亮度**：
    绝对阈值在整屏压暗时会自己塌掉（world_boss 2026-09-23 的教训）。
    """
    return np.clip(image.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def search_zone(anchor: str) -> tuple[int, int, int, int]:
    """按名字取搜索区。

    模板锚点在 ``REGIONS``；角标（亮点）的搜索区在 ``DOT_ZONES`` 里
    （``milestone`` 只存在于后者），两边都要能取到名字。
    """
    if anchor in REGIONS:
        return REGIONS[anchor]
    if anchor in DOT_ZONES:
        return DOT_ZONES[anchor]
    raise KeyError(f"没有叫 {anchor!r} 的锚点（既不在 REGIONS 也不在 DOT_ZONES）")


def frame_without_anchor(name: str, anchor: str, *, shift: int = 220) -> np.ndarray:
    """把 ``anchor`` 的搜索区用画面别处的像素盖掉，造一张「这个锚点认不出来」的帧。

    **只用于分支覆盖**：要测的是「认不出这个锚点时状态机走哪条路」，
    不是识别准确率。用画面自己的像素（而不是纯色）盖，是为了不引入
    「零方差区域」这种 TM_CCOEFF_NORMED 的退化输入。
    """
    image = screen(name)
    x, y, width, height = search_zone(anchor)
    image[y : y + height, x : x + width] = image[
        y + shift : y + shift + height, x : x + width
    ]
    return image


def locate(image: np.ndarray, key: str):
    """按 evidence 档案里的区域/基准画面找模板（返回 ``Match``，不套阈值）。"""
    atom = build_knights_donation_evidence(TEMPLATES).atom(key)
    match = find_best_template(
        image,
        getattr(build_knights_donation_templates(TEMPLATES), key),
        region=atom.region,
        reference_size=atom.reference_size,
    )
    assert match is not None, f"{key} 的搜索区比模板还小"
    return match


def machine() -> KnightsDonationStateMachine:
    return KnightsDonationStateMachine(build_knights_donation_templates(TEMPLATES))


def machine_without_digits() -> KnightsDonationStateMachine:
    """字模没接上时的状态机（前置判据 abstain）。

    「材料不足就跳过」是 2026-09-25 才补的**前置**判据；读不出数字时它必须
    **退回 2026-09-25 之前的全部行为**（照旧点、点完没反应再靠跳过表接手）。
    这些老用例靠它继续守着那条兜底路径 —— 那条路径今天仍然活着：
    数字读不出的格子、以及**材料够但点击真丢了**的格子都走它。
    """
    return KnightsDonationStateMachine(
        replace(build_knights_donation_templates(TEMPLATES), digit_glyphs={})
    )


def frame_with_every_row_short(name: str) -> np.ndarray:
    """把第一行的「持有：N」文字带**原样搬**到第二行，造一张「每一格材料都不足」的帧。

    ⚠️ 只用于**分支覆盖**（「全部不足 ⇒ 下滑而不是反复点」），不当识别准确率的证据：
    搬的是同一张画面自己的像素（不画纯色、不贴字模），所以不引入假的纹理。
    实测那两行的「持有」文字带相对按钮中心的偏移完全一样，直接整块换即可。
    """
    image = screen(name)
    candidates = support_candidates(image)
    assert len(candidates) >= 2, f"{name} 上不止两行绿按钮才谈得上「每行都不足」"
    first, second = candidates[0].center, candidates[1].center
    for dy, dx in ((HOLDINGS_DY, HOLDINGS_DX),):
        source = image[
            first[1] + dy[0] : first[1] + dy[1], first[0] + dx[0] : first[0] + dx[1]
        ]
        image[
            second[1] + dy[0] : second[1] + dy[1], second[0] + dx[0] : second[0] + dx[1]
        ] = source
    return image


def support_candidates(image: np.ndarray):
    """整列里**所有**绿色「支援1个」按钮（与状态机同一条通道，不另配一份参数）。

    一屏可能有多个一模一样的按钮（``support_page_two_buttons.png`` 就是实拍的两按钮帧），
    所以断言不能拿 ``locate()``（只给全局最高分那一个）当全集。
    """
    return machine()._support_candidates(image)


def inside(point: tuple[int, int], region: tuple[int, int, int, int]) -> bool:
    x, y, width, height = region
    return x <= point[0] <= x + width and y <= point[1] <= y + height


class KnightsDonationEvidenceTests(unittest.TestCase):
    def test_profile_matches_the_shipped_templates(self):
        profile = build_knights_donation_evidence(TEMPLATES)

        self.assertEqual([], validate_profile(profile, TEMPLATES))
        self.assertEqual(15, len(profile.atoms))
        self.assertEqual(7, len(profile.pages))
        for atom in profile.atoms.values():
            self.assertEqual(REFERENCE_SIZE, atom.reference_size)

    def test_only_three_anchors_depart_from_the_default_threshold(self):
        """阈值不是「凑好看」调出来的：除这三个之外全是默认值。"""
        overrides = {
            key for key, value in THRESHOLDS.items() if value != DEFAULT_THRESHOLD
        }

        self.assertEqual(
            {"panel_title", "flower_cell", "flower_cell_selected"}, overrides
        )
        # 「下级精灵之花」两种状态互为最强干扰源，阈值必须夹在中间。
        self.assertGreater(THRESHOLDS["flower_cell"], 0.8279)
        self.assertGreater(THRESHOLDS["flower_cell_selected"], 0.7878)
        # panel_title 在 hero/reward_popup 上实测 0.7821，按默认 0.80 只剩 0.018。
        self.assertGreater(THRESHOLDS["panel_title"], 0.7821)

    def test_every_anchor_separates_its_fixtures(self):
        fixtures = {name: screen(name) for name in ALL_FIXTURES}

        self.assertEqual(set(REGIONS), set(EXPECTATIONS))
        for key in REGIONS:
            must, must_not = EXPECTATIONS[key]
            self.assertEqual(
                set(ALL_FIXTURES),
                set(must) | set(must_not),
                f"{key} 的期望表漏了夹具（不许留没表态的格子）",
            )
            scores = {name: locate(fixtures[name], key).score for name in ALL_FIXTURES}
            with self.subTest(anchor=key):
                self.assertLess(
                    THRESHOLDS[key],
                    min(scores[name] for name in must),
                    f"{key} 在必须命中的帧上没过阈：{scores}",
                )
                self.assertLess(
                    max(scores[name] for name in must_not),
                    THRESHOLDS[key],
                    f"{key} 在不该命中的帧上过了阈：{scores}",
                )

    def test_red_dot_shrinks_the_entry_anchor_margin(self):
        """有红点那张才是 activity_entry 余量最薄的一张（红点盖住图标左上角）。

        11×11 的角标在 75×73 的模板里占 1.4% 的像素、吃掉 7% 的分数 —— 记在这里，
        免得以后红点变大时没人知道阈值是从哪儿顶上去的。
        """
        with_dot = locate(screen(GH_DOT), "activity_entry")
        without = locate(screen(GH_BARE), "activity_entry")

        self.assertLess(with_dot.score, without.score)
        self.assertGreater(with_dot.score, THRESHOLDS["activity_entry"] + 0.10)

    def test_popups_are_evaluated_before_the_pages_they_cover(self):
        """弹窗盖在底页上，模板匹配对「压暗」不敏感 ⇒ 弹窗判据必须排在前面。

        实测奖励弹窗开着时，资源支援页的 request_support_button 掉到 0.3646、
        每周任务页的 points_label 掉到 0.6852 —— 都不会串页，但顺序上先判弹窗更稳。
        """
        profile = build_knights_donation_evidence(TEMPLATES)

        self.assertEqual("knights_donation.reward_popup", profile.pages[0].key)
        self.assertEqual("knights_donation.request_popup", profile.pages[1].key)
        self.assertEqual("knights_donation.guild_home", profile.pages[-1].key)

    def test_request_popup_needs_the_flower_cell_as_a_second_anchor(self):
        """只认标题不行：「请求支援」四个字在资源支援页的按钮上也在。"""
        page = build_knights_donation_evidence(TEMPLATES).page(
            "knights_donation.request_popup"
        )

        self.assertEqual(("popup_title",), page.required)
        self.assertEqual((("flower_cell", "flower_cell_selected"),), page.any_of)

    def test_activity_panel_is_the_unknown_tab_fallback(self):
        """团员商店那类「认不出页签」的兜底：标题在、两个页面锚点都不在。

        ⚠️ 这个分支**没有实拍证据** —— 实拍的全屏帧里游戏每次都从「资源支援」
        页签打开活动界面。这里守构造：它只依赖 panel_title，且不带 forbidden，
        否则会把正常的两个子页也判成 UNSAFE 而卡住。
        """
        profile = build_knights_donation_evidence(TEMPLATES)
        page = profile.page("knights_donation.activity_panel")

        self.assertEqual(("panel_title",), page.required)
        self.assertEqual((), page.forbidden)
        flags = {key: False for key in profile.atoms}
        flags["panel_title"] = True
        self.assertIs(EvidenceState.SAFE, page.evaluate(flags))


class KnightsDonationDotTests(unittest.TestCase):
    """角标（亮点）判据：掩膜 S≥120 & V≥190，只看「高饱和 + 高亮」，不看色相。

    本路线只用骑士团活动界面里的两处蓝角标（每周任务页签 / 骑士团点数可领档位）。
    判据不看色相是为了将来换界面时不重新标定 —— 主页那颗橙红角标只是「V 为什么卡 190」
    的由来，**已不参与决策**。
    """

    def test_weekly_tab_dot_disappears_after_claiming(self):
        self.assertIsNotNone(find_dot(screen(WK_OK), "weekly_tab"))
        self.assertIsNone(find_dot(screen(WK_DONE), "weekly_tab"))

    def test_milestone_fragments_left_behind_are_not_read_as_claimable(self):
        """领完之后原位会留下字体/宝箱碎片（面积 43/22/50/20）。

        面积下限 60 就是为了挡住它们 —— 不卡就会把「已领」读成「可领」，原地反复点。
        """
        self.assertIsNotNone(find_dot(screen(WK_OK), "milestone"))
        self.assertIsNone(find_dot(screen(WK_DONE), "milestone"))

    def test_claim_point_moves_off_the_dot_onto_the_icon(self):
        """角标在图标左上角**不重叠**（角标到 1082 就结束，图标从 1085 起）。

        直接点角标是点不到图标的 —— 必须按实测偏移挪到图标中心。
        """
        dot = find_dot(screen(WK_OK), "milestone")

        self.assertIsNotNone(dot)
        point = milestone_claim_point(dot)
        self.assertGreater(point[0], dot[0])
        self.assertGreater(point[1], dot[1])
        self.assertEqual((1107, 318), point)

    def test_a_milestone_that_moved_off_the_old_spot_is_still_found(self):
        """2026-09-26 事故回归：可领档位换到别的档之后，老判据直接漏掉。

        老搜索区是写死的 50×50 小方块 ``(1050,264,50,50)``，只罩得住角标中心 x≈1073
        （500 分档）。用户现场帧（1660 分、可领的是 **1500** 档）上角标在 x=1260，
        偏出搜索区 160px ⇒ ``find_dot`` 返回 None ⇒ 状态机判「每周任务已经没有可领的
        点数档位」**直接收工**，那档奖励白丢。现在搜索区是整条里程碑带。
        """
        dot = find_dot(screen(WK_1500), "milestone")

        self.assertEqual((1260, 286), dot)
        # 点的是那一档图标中心（角标 + 实测偏移），实测坐标正好是 1500 那个宝箱。
        self.assertEqual((1294, 318), milestone_claim_point(dot))
        # 带子必须**同时**罩得住老位置和新位置，否则只是把漏检换了个档位。
        x, _y, width, _height = DOT_ZONES["milestone"]
        self.assertLessEqual(x, 1073)
        self.assertGreaterEqual(x + width, 1260)

    def test_the_widened_band_does_not_pick_up_the_holdings_text(self):
        """放宽成整条带子之后，资源支援页的「持有: N」绿字**也落进了带子**。

        它是绿字、同样「高饱和 + 高亮」，掩膜分不开；面积/宽高也全都过筛
        （实测 21×21/85、11×21/66、12×21/67）。只有**形态**分得开：角标是实心圆点
        （填充率 0.758），文字笔画是细线（0.19~0.33）。这条用例守的就是那道形态判据 ——
        把它删掉，下面四张帧会立刻被读成「有可领档位」并去点列表里的名字。
        """
        for name in (
            SUP,
            SUP_TWO,
            SUP_SHORT,
            SUP_FULL,
        ):
            with self.subTest(fixture=name):
                self.assertIsNone(find_dot(screen(name), "milestone"))

    def test_the_fill_ratio_sits_between_the_dot_and_the_text_strokes(self):
        """填充率阈值必须夹在「实测正例」与「实测最高非角标」之间。

        - 实心角标：219 / (17×17) = 0.758（两种颜色、两张正向样本都是这个值）
        - 最高的非角标：已领绿✓ 76 / (15×9) = 0.563（本来靠「贴 ROI 底边」排除，
          这里是第二道保险）；「持有」绿字只有 0.19~0.29；可领图标亮块 0.375。
        """
        self.assertGreater(DOT_MIN_FILL_RATIO, 76 / float(15 * 9))
        self.assertLess(DOT_MIN_FILL_RATIO, 219 / float(17 * 17))

    def test_the_dot_zones_do_not_overlap(self):
        """两个搜索区必须各自独立，否则一个角标会被当两次。"""
        boxes = []
        for zone in DOT_ZONES.values():
            x, y, width, height = zone
            boxes.append((x, y, x + width, y + height))
        for index, first in enumerate(boxes):
            for second in boxes[index + 1 :]:
                self.assertFalse(
                    first[0] < second[2]
                    and second[0] < first[2]
                    and first[1] < second[3]
                    and second[1] < first[3],
                    f"搜索区重叠：{first} / {second}",
                )


class KnightsDonationStateMachineTests(unittest.TestCase):
    def test_every_fixture_is_recognised_as_its_own_page(self):
        expected = {
            GH_DOT: KnightsDonationState.GUILD_HOME,
            GH_BARE: KnightsDonationState.GUILD_HOME,
            SUP: KnightsDonationState.RESOURCE_SUPPORT,
            SUP_SCROLLED: KnightsDonationState.RESOURCE_SUPPORT,
            SUP_TWO: KnightsDonationState.RESOURCE_SUPPORT,
            SUP_SHORT: KnightsDonationState.RESOURCE_SUPPORT,
            WK_OK: KnightsDonationState.WEEKLY_TASKS,
            WK_DONE: KnightsDonationState.WEEKLY_TASKS,
            WK_1500: KnightsDonationState.WEEKLY_TASKS,
            POP: KnightsDonationState.REQUEST_POPUP,
            POP_SEL: KnightsDonationState.REQUEST_POPUP,
            SCONF: KnightsDonationState.SUPPORT_CONFIRM,
            REWARD: KnightsDonationState.REWARD_POPUP,
        }
        subject = machine()

        for name, want in expected.items():
            with self.subTest(fixture=name):
                self.assertIs(want, subject.observe_page(screen(name)))

    def test_the_confirm_dialog_wins_over_the_list_page_it_covers(self):
        """确认框那一帧**同时**满足「资源支援页」的判据（右上角按钮没被挡住）。

        实测：那一帧上 request_support_button 仍然 0.9578（过阈）。所以这一条测的是
        **判定顺序** —— `_PAGE_STATES` 里 support_confirm 必须排在 resource_support 前面，
        否则确认框会被读成资源支援页，状态机会对着被盖住的列表点来点去。
        """
        frame = screen(SCONF)

        self.assertGreaterEqual(
            locate(frame, "request_support_button").score,
            THRESHOLDS["request_support_button"],
        )
        self.assertIs(KnightsDonationState.SUPPORT_CONFIRM, machine().observe_page(frame))

    def test_the_activity_panel_fallback_is_reachable_when_the_page_anchor_is_gone(self):
        """资源支援页的右上按钮认不出来时，落点必须是 `activity_panel` 而不是「未知画面」。"""
        frame = frame_without_anchor(SUP, "request_support_button")

        self.assertLess(locate(frame, "request_support_button").score, THRESHOLDS["request_support_button"])
        self.assertIs(KnightsDonationState.ACTIVITY_PANEL, machine().observe_page(frame))

    def test_home_opens_the_activity_panel_whether_or_not_there_is_a_red_dot(self):
        """用户 2026-09-24 更正：**不看红点**，有没有红点都进活动界面。

        原先「没红点就整条路线结束」那套判据已拿掉（那会让「主页今天没亮红点」这天
        直接不进界面，也就顺带跳过「每周任务里可能还有得领」）。这里两帧用同一组断言
        钉住，免得以后有人把红点判据又加回来。
        """
        for name in (GH_DOT, GH_BARE):
            with self.subTest(fixture=name):
                subject = machine()

                action = subject.next_action(screen(name))

                self.assertEqual("open-activity", action.name)
                # 点击点是「骑士团活动」图标的匹配中心，不是红点、也不是猜的坐标。
                self.assertEqual((79, 539), action.point)
                # 活动界面上次停在哪一页，这次就还停在哪一页 ⇒ 三个落点都合法。
                self.assertEqual(
                    {
                        state_label(KnightsDonationState.RESOURCE_SUPPORT),
                        state_label(KnightsDonationState.WEEKLY_TASKS),
                        state_label(KnightsDonationState.ACTIVITY_PANEL),
                    },
                    set(action.target_pages),
                )
                # 不许在主页就收工。
                self.assertEqual(0, subject.completed_cycles)
                self.assertIsNot(KnightsDonationState.FINISHED, subject.state)

    def test_the_panel_fallback_clicks_back_to_the_resource_tab(self):
        action = machine().next_action(frame_without_anchor(SUP, "request_support_button"))

        self.assertEqual("open-resource-tab", action.name)
        self.assertEqual(locate(screen(SUP), "tab_resource_support").center, action.point)
        self.assertEqual(
            (state_label(KnightsDonationState.RESOURCE_SUPPORT),), action.target_pages
        )

    def test_resource_support_page_asks_for_help_before_giving_help(self):
        """顺序是用户定的：先请求支援、再支援别人。"""
        action = machine().next_action(screen(SUP))

        self.assertEqual("request-support", action.name)
        self.assertEqual((1654, 190), action.point)
        self.assertEqual(
            (state_label(KnightsDonationState.REQUEST_POPUP),), action.target_pages
        )

    def test_request_support_only_ever_fires_once_per_run(self):
        """请求支援一天只能发一次 ⇒ 同一次运行里 `request_done` 一置位就不再请求。"""
        subject = machine()
        subject.next_action(screen(SUP))
        subject.request_done = True

        self.assertEqual("support-one", subject.next_action(screen(SUP)).name)

    # ---- 「请求支援」今天已经用过 ⇒ 按钮变灰，不许再点 ----
    #
    #  2026-09-25 用户实跑撞上：当天第二次运行时额度已用掉、按钮变灰，但
    #  `TM_CCOEFF_NORMED` 对亮度缩放不敏感 ⇒ 灰帧上模板仍得 0.9846 ⇒ 程序照点、
    #  每次白等 42 秒转场超时 ×4，整条路线提前收工。
    #  这一组测试守「变灰就别点，直接去支援别人」。

    def test_a_greyed_request_button_is_not_clicked_and_the_route_moves_on(self):
        """灰按钮：不点它、把账记上、直接去支援列表里那个还能支援的人。"""
        subject = machine()
        subject.request_done = False

        action = subject.next_action(screen(SUP_TWO))

        self.assertEqual("support-one", action.name, "灰掉的「请求支援」又被点了")
        self.assertNotEqual((1654, 190), action.point)
        self.assertTrue(subject.request_done, "跳过一次之后不能让下一轮又来试一遍")
        self.assertIn("今天已经请求过支援", action.reason)

    def test_an_alive_request_button_is_still_clicked_first(self):
        """对照：按钮还亮着时**照旧**先请求支援（顺序是用户定的）。"""
        subject = machine()
        subject.request_done = False

        action = subject.next_action(screen(SUP))

        self.assertEqual("request-support", action.name)
        self.assertEqual((1654, 190), action.point)
        self.assertFalse(subject.request_done)

    def test_an_unmeasurable_button_area_falls_back_to_clicking(self):
        """量不出来（整幅全黑 / 区域裁不出来）⇒ 当作「还亮着」照旧点。

        宁可多点一次（退回今天的行为），也不要因为量不到就白丢当天唯一一次请求 ——
        而且「跳过请求」这件事用户从画面上很难察觉。
        """
        subject = machine()

        self.assertTrue(
            subject._request_button_still_alive(np.zeros((1132, 1982, 3), np.uint8))
        )

    def test_the_grey_reading_survives_a_page_fade(self):
        """整屏压暗（页面淡入）时**读数不变** —— 这是判据取相对亮度而不是绝对亮度的理由。

        world_boss 2026-09-23 已踩过这个坑：绝对亮度阈值在整屏压暗到 50% 时自己塌掉，
        把「还有次数」误判成「次数用完」。这里把同一帧乘亮度系数复现那个场景。
        """
        subject = machine()
        for factor in (1.0, 0.8, 0.6, 0.5, 0.4, 0.3):
            with self.subTest(factor=factor):
                self.assertTrue(
                    subject._request_button_still_alive(fade(screen(SUP), factor)),
                    f"能点的按钮被整屏压暗到 {factor} 之后误判成灰的 ⇒ 会白丢当天一次请求",
                )
                self.assertFalse(
                    subject._request_button_still_alive(fade(screen(SUP_TWO), factor)),
                    f"灰按钮在 {factor} 亮度下被当成了能点",
                )

    def test_the_threshold_sits_between_the_alive_and_grey_scores(self):
        """阈值必须坐在「能点组下界」与「灰组上界」之间，两边都留余量。

        用**真帧**把这条钉死：以后谁改区域或改统计量，先在这里看到余量还剩多少。
        """
        region = REGIONS["request_support_button"]
        alive = [
            request_button_relative_v(frame, region)
            for frame in (
                screen(SUP),
                screen(SUP_SCROLLED),
                manual_review_screen("02_resource_support"),
                manual_review_screen("09_activity_opened"),
            )
        ]
        grey = [
            request_button_relative_v(frame, region)
            for frame in (screen(SUP_TWO), screen(SUP_SHORT))
        ]

        self.assertGreater(
            min(alive), REQUEST_BUTTON_ALIVE_RATIO, f"能点的帧里有读数掉到阈值以下的：{alive}"
        )
        self.assertLess(
            max(grey), REQUEST_BUTTON_ALIVE_RATIO, f"灰的帧里有读数越过阈值的：{grey}"
        )
        # 两侧各留至少 25% 余量 —— 余量变薄就该重采样本了。
        self.assertGreater(min(alive) / REQUEST_BUTTON_ALIVE_RATIO, 1.25)
        self.assertGreater(REQUEST_BUTTON_ALIVE_RATIO / max(grey), 1.25)

    def test_the_two_button_appearances_read_the_same(self):
        """按钮「能点」时有两种底色（褐底悬浮 / 深蓝底），**读数必须接近**。

        底色变了、亮度没变 —— 这正是判据只看亮度不看颜色的理由；
        也顺手挡住「哪天换了配色就整个判据失效」。
        """
        region = REGIONS["request_support_button"]
        brown = request_button_relative_v(manual_review_screen("02_resource_support"), region)
        navy = request_button_relative_v(screen(SUP), region)

        self.assertLess(abs(brown - navy), 0.15, f"两种底色读数差太多：{brown} vs {navy}")

    def test_support_list_reorders_so_the_point_is_rematched_every_time(self):
        """列表每支援一次就重排 ⇒ 绿色按钮每轮都要重新认，不能按固定行坐标点。"""
        subject = machine()
        subject.request_done = True

        action = subject.next_action(screen(SUP))

        self.assertEqual("support-one", action.name)
        self.assertEqual(locate(screen(SUP), "support_one_button").center, action.point)

    def test_a_full_viewport_scrolls_at_most_twice_then_switches_tab(self):
        """视口内没有绿按钮 ⇒ 有界下滑；滑完还找不到就切到每周任务。"""
        subject = machine()
        subject.request_done = True

        for expected in range(1, MAX_SUPPORT_SCROLLS + 1):
            action = subject.next_action(screen(SUP_SCROLLED))
            self.assertEqual("scroll-support", action.name)
            self.assertEqual(expected, subject.support_scrolls)
            # 滑动动作的点击是**空点**：落在当前已选中的资源支援页签上，
            # 真正的手势由 Runner 的 `_after_action_click` 补发。
            self.assertEqual((255, 265), action.point)
            self.assertEqual((), action.target_pages)
            self.assertTrue(action.in_page_evidence)

        action = subject.next_action(screen(SUP_SCROLLED))

        self.assertEqual("open-weekly-tab", action.name)
        self.assertEqual(
            (state_label(KnightsDonationState.WEEKLY_TASKS),), action.target_pages
        )

    def test_a_visible_green_button_outranks_the_scroll_ledger(self):
        """账本不压业务：只要有绿按钮就先点它（列表重排会把还能支援的人排上来）。"""
        subject = machine()
        subject.request_done = True
        subject.support_scrolls = MAX_SUPPORT_SCROLLS

        self.assertEqual("support-one", subject.next_action(screen(SUP)).name)

    def test_both_green_buttons_in_one_viewport_are_visible_to_the_machine(self):
        """一屏两个绿按钮时，状态机必须**两个都看得见**（走 ``find_all_templates``）。

        只用 ``find_best_template``（永远只给最高分那一个）就永远只能点到上面那一个 ——
        而实拍那帧上**上面那个吃不下、下面那个才行**（2026-09-24 实跑实测）。
        """
        frame = screen(SUP_TWO)
        candidates = support_candidates(frame)

        self.assertEqual(2, len(candidates))
        # 分数降序；两个是**不同的行**，不是同一个按钮被沿边缘报了两次。
        self.assertGreater(candidates[0].score, candidates[1].score)
        self.assertGreater(
            abs(candidates[0].center[1] - candidates[1].center[1]),
            SUPPORT_ROW_SKIP_TOLERANCE,
        )
        # 开局挑分数最高那个（材料不足的格子会被前置判据跳过，见下面那条用例）。
        subject = machine_without_digits()
        subject.request_done = True
        self.assertEqual(candidates[0].center, subject.next_action(frame).point)

    def test_the_reward_popup_is_what_makes_a_support_count(self):
        """「点过了」不等于「支援成功」：只有看到「获得奖励」才作数。

        对照实验（2026-09-24 实跑）：团员要的材料我持有 0 时，确认框里点「支援1个」
        **什么都不发生** —— 行不消失、今日支援上限也不涨。所以判据只能是「有没有弹奖励」。
        用户当天补充确认：游戏**会**在下方闪一行小字「材料不足」，但一闪就没
        ⇒ 那行字不做判据（理由见 `games/epic7/knights_donation.py` 的模块 docstring）。

        ⚠️ 2026-09-25 起这是**兜底**判据：材料不足的格子本该在挑行时就被数字判据拦下，
        所以这条用例用 `machine_without_digits()` 跑（= 数字读不出的情形）。
        """
        subject = machine_without_digits()
        subject.request_done = True
        frame = screen(SUP_TWO)

        self.assertEqual(support_candidates(frame)[0].center, subject.next_action(frame).point)
        # 点列表那颗 ⇒ 先弹确认框；再点确认框那颗 ⇒ 这次游戏直接弹了「获得奖励」。
        subject.next_action(screen(SCONF))
        self.assertIs(KnightsDonationState.SUPPORT_CONFIRM, subject.state)
        subject.next_action(screen(REWARD))

        self.assertIsNone(subject.pending_support_y)
        self.assertEqual(set(), subject.skipped_rows)

    def test_a_row_that_shows_no_reward_is_skipped_and_the_next_button_is_tried(self):
        """回到列表却没看到「获得奖励」⇒ 这一行吃不下，下一轮挑**别的**绿按钮。

        没有这一步就会在同一个按钮上白转 4 次、然后整条路线中止（实跑第一次的现场）。
        ⚠️ 2026-09-25 起这是**兜底**路径：数字读得出时，材料不足的格子根本不会被点
        （见 `test_a_row_that_is_short_of_material_is_never_clicked`）——
        但**点击真丢了**的格子、以及数字读不出的格子仍然要靠它，所以必须留着。
        """
        subject = machine_without_digits()
        subject.request_done = True
        frame = screen(SUP_TWO)
        first, second = support_candidates(frame)

        self.assertEqual(first.center, subject.next_action(frame).point)
        self.assertEqual(first.center[1], subject.pending_support_y)

        # 又回到列表页（没弹奖励）⇒ 上一行记进跳过表，这一轮点下一个按钮。
        again = subject.next_action(frame)

        self.assertEqual({first.center[1]}, subject.skipped_rows)
        self.assertEqual("support-one", again.name)
        self.assertEqual(second.center, again.point)

    def test_a_row_that_is_short_of_material_is_never_clicked(self):
        """材料不足的格子**连点都不点**：读「持有 0 < 需求 1」直接跳过，去点下一格。

        这是 2026-09-25 补的前置判据要防的事故现场：那一格的绿按钮**不会变灰**，
        点下去毫无反应，主循环会把它当成「没点到」连点 4 次、然后把整条路线收工。
        ⚠️ 与上一条的区别就在**点没点**：那条先点、再靠跳过表回头；这条一步都不点。
        """
        subject = machine()
        subject.request_done = True
        frame = screen(SUP_TWO)
        first, second = support_candidates(frame)

        action = subject.next_action(frame)

        # 挑中的是**第二个**按钮（第一格被数字判据跳过了）。
        self.assertEqual("support-one", action.name)
        self.assertEqual(second.center, action.point)
        self.assertEqual(second.center[1], subject.pending_support_y)
        # 第一格的 y 已经记进跳过表（这一帧不会再挑到它）。
        self.assertEqual({first.center[1]}, subject.skipped_rows)
        # 理由里带上读数与「跳过了哪几格」，日志里看得见，不用猜。
        self.assertIn("持有 0 / 需求 1", action.reason)
        self.assertIn("已跳过 1 格材料不足", action.reason)

    def test_the_real_short_material_frame_skips_the_blocked_row(self):
        """实跑事故帧：上一行「持有 1 / 需求 2」不足、下一行「持有 225 / 需求 4」可以。

        这一帧就是 2026-09-25 那次中止的现场（``support_page_short_material.png``）。
        当时程序对着上面那格连点 4 次、整条路线收工；现在它应该一步跨过去，
        直接点下面那格能支援的。
        """
        subject = machine()
        subject.request_done = True
        frame = screen(SUP_SHORT)
        first, second = support_candidates(frame)

        action = subject.next_action(frame)

        self.assertEqual(second.center, action.point)
        self.assertEqual("support-one", action.name)
        self.assertIn("持有 225 / 需求 4", action.reason)
        self.assertIn("持有 1 / 需求 2", action.reason)
        self.assertEqual({first.center[1]}, subject.skipped_rows)

    def test_an_unreadable_row_falls_back_to_clicking_it(self):
        """读不出数字 ⇒ **照旧点**（退回 2026-09-25 之前的行为），绝不因此瞎跳。

        认错的代价是白丢积分，认不出只是帮不上忙 —— 所以这条兜底必须是「点」。
        """
        subject = machine_without_digits()
        subject.request_done = True
        frame = screen(SUP_SHORT)

        action = subject.next_action(frame)

        self.assertEqual(support_candidates(frame)[0].center, action.point)
        self.assertEqual(set(), subject.skipped_rows)
        self.assertIn("持有 ? / 需求 ?", action.reason)

    def test_when_every_visible_row_is_unreachable_it_scrolls_instead_of_repeating(self):
        """两个绿按钮都吃不下 ⇒ 不再重复点，改为下滑（且跳过表必须清空）。

        ⚠️ 清空是必需的：下滑会让整列位移，旧的 y 键就指到别人头上了。
        这条走的是**兜底**路径（数字读不出）；全不足走数字判据那条见下一条。
        """
        subject = machine_without_digits()
        subject.request_done = True
        frame = screen(SUP_TWO)

        self.assertEqual(2, len(support_candidates(frame)))
        subject.next_action(frame)  # 点第一行
        subject.next_action(frame)  # 吃不下 → 跳过第一行、点第二行
        action = subject.next_action(frame)  # 第二行也吃不下 → 不能重复点，下滑

        self.assertEqual("scroll-support", action.name)
        self.assertEqual(1, subject.support_scrolls)
        self.assertEqual(set(), subject.skipped_rows)

    def test_when_every_row_is_short_of_material_it_scrolls_instead_of_repeating(self):
        """**每一格**都材料不足 ⇒ 也是一个都不点，直接下滑（有界），绝不原地转圈。

        构造帧（只覆盖分支，不是识别证据）：把第一行的「持有」文字带到第二行上，
        于是两格都读成「持有 1」而不够。若不这么测，就要等真机上碰巧两格都不足。
        """
        subject = machine()
        subject.request_done = True
        frame = frame_with_every_row_short(SUP_SHORT)
        self.assertEqual(2, len(support_candidates(frame)))

        for candidate in support_candidates(frame):
            self.assertTrue(
                subject._row_numbers(frame, candidate.center).verdict is True,
                "构造帧没做对：两格都应该读成材料不足",
            )

        action = subject.next_action(frame)

        self.assertEqual("scroll-support", action.name)
        self.assertIn("已跳过 2 格材料不足", action.reason)
        self.assertEqual(set(), subject.skipped_rows)  # 下滑 ⇒ 清空

    def test_a_successful_support_invalidates_the_skip_ledger(self):
        """支援成功 ⇒ 该团员在原地变灰勾、整列**重排** ⇒ 按 y 记的跳过表全部失效。

        不失效的话，重排之后旧的 y 会指到**别人**头上，把本来能支援的人误跳过。
        """
        subject = machine()
        subject.request_done = True
        frame = screen(SUP_TWO)

        subject.next_action(frame)
        subject.skipped_rows.add(12345)  # 假装前面已经跳过一行
        subject.next_action(screen(REWARD))

        self.assertEqual(set(), subject.skipped_rows)

    def test_the_support_confirm_dialog_clicks_its_own_button(self):
        """确认框是**独立的一页**（2026-09-24 实跑才发现），它自己的按钮才是真的「支援1个」。"""
        action = machine().next_action(screen(SCONF))

        self.assertEqual("confirm-support", action.name)
        self.assertEqual(
            locate(screen(SCONF), "support_confirm_button").center, action.point
        )
        self.assertEqual(
            state_label(KnightsDonationState.SUPPORT_CONFIRM), action.source_page
        )
        # 两个落点都真实存在：生效 ⇒ 弹奖励；没生效 ⇒ 回列表（由跳过表接手）。
        self.assertEqual(
            {
                state_label(KnightsDonationState.REWARD_POPUP),
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
            },
            set(action.target_pages),
        )

    def test_popup_picks_the_lower_grade_flower_then_confirms(self):
        subject = machine()

        pick = subject.next_action(screen(POP))
        self.assertEqual("select-flower", pick.name)
        self.assertIn("flower_cell_selected", pick.in_page_evidence)
        self.assertEqual((), pick.target_pages)
        self.assertTrue(inside(pick.point, REGIONS["flower_cell"]))

        confirm = subject.next_action(screen(POP_SEL))
        self.assertEqual("confirm-request", confirm.name)
        self.assertTrue(inside(confirm.point, REGIONS["popup_confirm"]))
        self.assertIn(
            state_label(KnightsDonationState.RESOURCE_SUPPORT), confirm.target_pages
        )
        self.assertTrue(subject.request_done)

    def test_reward_popup_is_dismissed_below_its_title_and_resets_the_ledger(self):
        """支援成功一次 ⇒ 下滑账本清零，下一段还能重新往下找。"""
        subject = machine()
        subject.support_scrolls = MAX_SUPPORT_SCROLLS

        action = subject.next_action(screen(REWARD))

        self.assertEqual("dismiss-reward", action.name)
        title = locate(screen(REWARD), "reward_title")
        self.assertEqual(
            (title.center[0], title.center[1] + REWARD_DISMISS_DY), action.point
        )
        self.assertEqual(0, subject.support_scrolls)
        self.assertEqual(
            {
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
                state_label(KnightsDonationState.WEEKLY_TASKS),
            },
            set(action.target_pages),
        )

    def test_weekly_tasks_claims_the_milestone_before_the_task_rows(self):
        action = machine().next_action(screen(WK_OK))

        self.assertEqual("claim-milestone", action.name)
        # 点的是图标中心（角标中心 + 实测偏移），不是角标本身。
        self.assertEqual((1107, 318), action.point)
        self.assertTrue(action.in_page_evidence)
        self.assertEqual((), action.target_pages)

    def test_the_machine_claims_a_milestone_that_moved_off_the_old_spot(self):
        """2026-09-26 事故回归（业务后果层面）：可领档位换档之后，状态机必须照样去领。

        现场帧：骑士团点数 1660，500/1000 已领，**可领的是 1500 档**（角标中心 x=1260）。
        老搜索区（写死的 50×50 小方块，只罩得住 x≈1073 的 500 档）在这一帧上认不出角标
        ⇒ 状态机走「每周任务已经没有可领的点数档位和可领的任务了」**直接收工**
        ⇒ 1500 那档奖励白丢，而且日志上完全看不出来（收工理由看起来天经地义）。
        这条用例断言它现在真的去点那个宝箱。
        """
        action = machine().next_action(screen(WK_1500))

        self.assertEqual("claim-milestone", action.name)
        self.assertEqual((1294, 318), action.point)
        self.assertEqual((), action.target_pages)
        self.assertTrue(action.in_page_evidence)

    def test_weekly_tasks_claims_the_rows_when_no_milestone_is_left(self):
        """角标没了但还有「领取」按钮 ⇒ 去领任务行（按短窗口重试）。"""
        frame = frame_without_anchor(WK_OK, "milestone")

        self.assertIsNone(find_dot(frame, "milestone"))
        action = machine().next_action(frame)

        self.assertEqual("claim-task", action.name)
        self.assertEqual(locate(frame, "claim_button").center, action.point)
        self.assertEqual(
            (state_label(KnightsDonationState.REWARD_POPUP),), action.target_pages
        )

    def test_finished_weekly_tasks_finish_the_route(self):
        subject = machine()

        self.assertIsNone(subject.next_action(screen(WK_DONE)))
        self.assertEqual(1, subject.completed_cycles)
        self.assertIn("每周任务", subject.finish_reason)

    def test_every_reachable_action_carries_the_transition_contract(self):
        """12 个动作逐个对账：`source_page` 必须有，出口验收二选一必须有。

        同页动作**不许**用 `target_pages=(本页,)` 糊弄 —— 本页永远在集合里 ⇒
        验收永远通过 ⇒ 分不出「点了没生效」和「点了生效了」。
        """
        actions = reachable_actions()

        self.assertEqual(
            {
                "open-activity",
                "open-resource-tab",
                "request-support",
                "select-flower",
                "confirm-request",
                "support-one",
                "confirm-support",
                "scroll-support",
                "open-weekly-tab",
                "dismiss-reward",
                "claim-milestone",
                "claim-task",
            },
            set(actions),
        )
        for name, (action, observed) in actions.items():
            with self.subTest(action=name):
                self.assertEqual(state_label(observed), action.source_page)
                self.assertTrue(
                    action.target_pages or action.in_page_evidence,
                    f"{name} 既没声明 target_pages 也没声明 in_page_evidence",
                )
                self.assertNotIn(
                    action.source_page,
                    action.target_pages,
                    f"{name} 把来源页塞进了目标集合，验收会永远通过",
                )

    def test_preview_never_advances_business_progress(self):
        """主循环每帧先调 preview 做两帧稳定确认，还原不完整就会把一次点击记成两次。"""
        subject = machine()

        for _ in range(3):
            subject.preview(screen(GH_BARE))
            subject.preview(screen(WK_DONE))

        self.assertEqual(0, subject.completed_cycles)
        self.assertIsNot(KnightsDonationState.FINISHED, subject.state)
        self.assertEqual("", subject.finish_reason)

        subject.preview(screen(POP_SEL))
        subject.preview(screen(POP_SEL))
        self.assertFalse(subject.request_done)

        subject.preview(screen(SUP))
        subject.preview(screen(SUP))
        self.assertEqual(0, subject.support_scrolls)

        # ⚠️ 灰按钮那一支会在 next_action 里把 request_done 置位（「今天用过了」）——
        #    它同样必须被 preview 还原，否则两次试算确认就会把它**提前**置位，
        #    真正该请求的那次反而不请求了。
        self.assertFalse(subject.request_done)
        subject.preview(screen(SUP_TWO))
        subject.preview(screen(SUP_TWO))
        self.assertFalse(subject.request_done, "preview 把「今天已请求过」泄漏到了外面")

        # 跳过表与待结算的支援都是「这一帧试算出来的中间态」，同样不能留下痕迹。
        subject.request_done = True
        subject.preview(screen(SUP_TWO))
        subject.preview(screen(SUP_TWO))
        self.assertIsNone(subject.pending_support_y)
        self.assertEqual(set(), subject.skipped_rows)

    def test_a_missing_anchor_fails_closed_instead_of_guessing_a_point(self):
        """关键锚点拿不到就失败关闭 —— 绝不退化成固定坐标。

        构造：把「每周任务」页签在**画面上**擦掉（不是换掉模板 —— 常值模板在
        ``TM_CCOEFF_NORMED`` 下是退化输入，OpenCV 反而返回 1.0，会假命中）。
        这一帧会走到 ``_at_resource_support`` 的第 4 步：请求已发过、下滑次数
        用尽、页签又认不出来 ⇒ 必须抛错，而不是拿一个写死的坐标去点。
        """
        subject = machine()
        subject.request_done = True
        subject.support_scrolls = MAX_SUPPORT_SCROLLS
        frame = frame_without_anchor(SUP_SCROLLED, "tab_weekly_tasks")
        # 前提复核：这一帧确实仍是「资源支援」页（页签擦掉不影响页面判定），
        # 否则抛错可能来自「整页认不出」，测不到 _required 这一路。
        self.assertEqual(KnightsDonationState.RESOURCE_SUPPORT, subject.observe_page(frame))

        with self.assertRaises(UnrecognizedScreen):
            subject.next_action(frame)


def reachable_actions() -> dict[str, tuple[KnightsDonationAction, KnightsDonationState]]:
    """把 12 个动作都取到手，连同「取到时画面确认是哪一页」。

    有些动作需要先摆好业务进度标志（`request_done` / `support_scrolls`）才走得到；
    两条没有专用夹具的分支用 `frame_without_anchor()` 构造（见模块 docstring）。
    """
    actions: dict[str, tuple[KnightsDonationAction, KnightsDonationState]] = {}

    def take(name: str, frame: np.ndarray, **flags) -> None:
        subject = machine()
        for key, value in flags.items():
            setattr(subject, key, value)
        observed = subject.observe_page(frame)
        action = subject.next_action(frame)
        assert action is not None, f"{name} 这一帧本该有动作"
        actions[action.name] = (action, observed)

    take(GH_DOT, screen(GH_DOT))
    take(SUP, frame_without_anchor(SUP, "request_support_button"))
    take(SUP, screen(SUP))
    take(SUP, screen(SUP), request_done=True)
    # 两按钮那张：`support-one` 是同一个动作名，这里顺带证明它也能从实拍帧上取到。
    take(SUP_TWO, screen(SUP_TWO), request_done=True)
    take(SUP_SCROLLED, screen(SUP_SCROLLED), request_done=True)
    take(
        SUP_SCROLLED,
        screen(SUP_SCROLLED),
        request_done=True,
        support_scrolls=MAX_SUPPORT_SCROLLS,
    )
    take(POP, screen(POP))
    take(POP_SEL, screen(POP_SEL))
    take(SCONF, screen(SCONF))
    take(REWARD, screen(REWARD))
    take(WK_OK, screen(WK_OK))
    take(WK_OK, frame_without_anchor(WK_OK, "milestone"))
    return actions


class _RecordingRuntime(Runtime):
    """记录每个动作的**名字**。

    ``Runtime.click`` 只把坐标转给底层点击通道（``self._click(point)``），
    动作名只出现在日志里；而主循环的转场对账全靠动作名，所以测试要单独留一份。
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.actions: list[str] = []

    def click(self, point, action) -> None:
        self.actions.append(action)
        super().click(point, action)


class _PairRecordingRuntime(_RecordingRuntime):
    """在 ``_RecordingRuntime`` 之上再记一份「（动作名, 坐标）」对。

    给它写用例的「假游戏」要看**点了什么**才决定下一帧是什么画面（点了「每周任务」
    页签之后才真的切到每周任务页）—— ``_RecordingRuntime`` 只留动作名，凑不出这一步。
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pairs: list[tuple[str, tuple[int, int]]] = []

    def click(self, point, action) -> None:
        self.pairs.append((action, point))
        super().click(point, action)


class _Clock:
    """假时钟 + 帧游标：**一次 ``sleep`` = 前进一个轮询周期**。

    ``hold={帧下标: 停留几个周期}``：主循环要看到**两帧同签名**才肯发动作，
    所以每张画面至少得停 2 个周期。必须喂假时钟 —— 用真时间的话 ``sleep``
    不推进时钟，「同页重试窗口」永远到不了，帧喂完之后主循环会原地打转
    （world_boss 2026-09-22 记过这个坑）。
    """

    def __init__(self, frames: list[np.ndarray], hold: dict[int, int]) -> None:
        self.frames = frames
        self.hold = hold
        self.now = 0.0
        self.index = 0
        self.remaining = hold.get(0, 2)

    def capture(self) -> np.ndarray:
        return self.frames[min(self.index, len(self.frames) - 1)]

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.0)
        self.remaining -= 1
        if self.remaining <= 0:
            self.index = min(self.index + 1, len(self.frames) - 1)
            self.remaining = self.hold.get(self.index, 2)


class KnightsDonationRunnerTests(unittest.TestCase):
    def test_the_transition_contract_switch_is_on(self):
        """新路线准入：本路线是第一条打开机器强制的。"""
        runner = KnightsDonationRunner(
            machine(),
            _RecordingRuntime(lambda: None, lambda point: None, emit=lambda _: None),
        )

        self.assertIs(True, runner._REQUIRE_TRANSITION_CONTRACT)

    def test_blind_actions_are_refused_before_they_are_ever_clicked(self):
        runner = KnightsDonationRunner(
            machine(),
            _RecordingRuntime(lambda: None, lambda point: None, emit=lambda _: None),
        )

        with self.assertRaisesRegex(RuntimeError, "缺少转场契约"):
            runner._require_transition_contract(
                KnightsDonationAction(name="blind", point=(1, 1))
            )
        with self.assertRaisesRegex(RuntimeError, "缺少转场契约"):
            runner._require_transition_contract(
                KnightsDonationAction(name="no-exit", point=(1, 1), source_page="某页")
            )

        runner._require_transition_contract(
            KnightsDonationAction(
                name="ok", point=(1, 1), source_page="某页", in_page_evidence="某证据"
            )
        )

    def test_the_whole_route_walks_through_without_a_single_blind_click(self):
        """真状态机 + 真 Runner 跑完一整条链路。

        守住三件事：① 动作序列就是设计的那一串，没有多余的重复点击；
        ② 每个动作都通过了转场契约（开关打开还没被拦下 = 全部长眼睛）；
        ③ 收工时轮次恰好 +1，走的是正常结束（不是资源耗尽）。

        ⚠️ 首帧刻意用**没有红点**的主页（``GH_BARE``）：用户 2026-09-24 更正后
        「有没有红点都进」，所以这一帧也必须照样开进去、把整条链路走完。
        ⚠️ 支援那一段走的是**实跑真实出现过的路径**：点列表 → 弹「支援资源」确认框 →
        点确认框 → 才弹「获得奖励」（第一版没接确认框这一页，实机直接中止）。
        """
        frames = [
            screen(GH_BARE),  # 主页**没有**红点 → 依然 open-activity
            screen(SUP),  # 资源支援 → request-support
            screen(POP),  # 弹窗未选 → select-flower
            screen(POP_SEL),  # 选中了 → confirm-request
            screen(SUP),  # 回头支援别人 → support-one
            screen(SCONF),  # 先弹「支援资源」确认框 → confirm-support
            screen(REWARD),  # 获得奖励 → dismiss-reward
            screen(WK_OK),  # 每周任务有档位 → claim-milestone
            screen(WK_DONE),  # 都没得领了 → 收工
        ]
        clock = _Clock(frames, hold={index: 3 for index in range(len(frames))})
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runtime = _RecordingRuntime(
            clock.capture,
            clicks.append,
            emit=logs.append,
            monotonic=lambda: clock.now,
        )
        runner = KnightsDonationRunner(machine(), runtime, sleep=clock.sleep)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertFalse(runner.resource_exhausted)
        self.assertEqual(
            [
                "open-activity",
                "request-support",
                "select-flower",
                "confirm-request",
                "support-one",
                "confirm-support",
                "dismiss-reward",
                "claim-milestone",
            ],
            runtime.actions,
        )
        # 每一次点击都落在基准画布内 —— 坐标不是从屏外来的。
        self.assertEqual(len(runtime.actions), len(clicks))
        for point in clicks:
            self.assertGreaterEqual(point[0], 0)
            self.assertGreaterEqual(point[1], 0)
            self.assertLess(point[0], REFERENCE_SIZE[0])
            self.assertLess(point[1], REFERENCE_SIZE[1])
        # 转场真的被验收过（不是「点了就算成功」），收工也留了结论。
        self.assertEqual(1, len([line for line in logs if "完成=open-activity" in line]))
        self.assertTrue(any("结论=" in line for line in logs))

    def test_the_greyed_request_button_is_never_clicked_by_the_real_runner(self):
        """当天第二次运行（按钮已灰）走**真 Runner**：那一下点必须**不存在**。

        与 ``test_the_short_material_row_is_never_clicked_by_the_real_runner`` 同源：
        判据只有在**主循环里**生效才算数。这里断言的是「点击列表里根本没有 (1654,190)」，
        而不是「状态机想不想点它」—— 用户 2026-09-25 那次白等 42×4 秒就发生在这一层。
        """
        frames = [
            screen(SUP_TWO),  # 今天已经请求过 ⇒ 右上「请求支援」是灰的
            screen(SCONF),  # 直接去支援列表里那个能支援的人 → 先弹确认框
            screen(REWARD),  # 确认 → 弹「获得奖励」
            screen(WK_DONE),  # 收工
        ]
        clock = _Clock(frames, hold={index: 3 for index in range(len(frames))})
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runtime = _RecordingRuntime(
            clock.capture,
            clicks.append,
            emit=logs.append,
            monotonic=lambda: clock.now,
        )
        subject = machine()
        self.assertFalse(subject.request_done)  # 开局并不知道今天请求过
        runner = KnightsDonationRunner(subject, runtime, sleep=clock.sleep)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertNotIn((1654, 190), clicks, "灰掉的「请求支援」被点了 —— 判据没接进主循环")
        self.assertEqual(
            ["support-one", "confirm-support", "dismiss-reward"], runtime.actions
        )
        # 「为什么没做请求支援」必须在日志里看得见。
        self.assertTrue(
            any("今天已经请求过支援" in line for line in logs),
            "跳过请求这一步没写进日志，用户看不出为什么没请求",
        )

    def test_the_short_material_row_is_never_clicked_by_the_real_runner(self):
        """2026-09-25 事故帧走**真 Runner**：材料不足那一格一次都不许被点。

        ⚠️ 这条是冲着「状态机测通了、主循环截胡」那类失效来的 —— 上次的 bug
        就发生在两层之间（状态机挑好了下一格，主循环的转场重试把它顶替回旧坐标）。
        所以这条必须让**真 Runner + 假时钟**跑一遍，而不是只调 ``next_action``：
        断言的是**真的点到哪儿了**，不是「状态机想点哪儿」。
        """
        incident = screen(SUP_SHORT)
        blocked, usable = [c.center for c in support_candidates(incident)[:2]]
        frames = [
            incident,  # 列表：上面那格材料不足、下面那格能支援
            screen(SCONF),  # 点了能支援的那格 → 先弹「支援资源」确认框
            screen(REWARD),  # 确认 → 弹「获得奖励」
            screen(WK_DONE),  # 收工
        ]
        clock = _Clock(frames, hold={index: 3 for index in range(len(frames))})
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runtime = _RecordingRuntime(
            clock.capture,
            clicks.append,
            emit=logs.append,
            monotonic=lambda: clock.now,
        )
        subject = machine()
        subject.request_done = True  # 事故发生在「请求支援」那一步之后
        runner = KnightsDonationRunner(subject, runtime, sleep=clock.sleep)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertFalse(runner.resource_exhausted)
        self.assertNotIn(blocked, clicks, "材料不足的那一格被点了 —— 判据又没接上")
        self.assertEqual(usable, clicks[0], "第一下应该点在能支援的那一格上")
        self.assertEqual(
            ["support-one", "confirm-support", "dismiss-reward"], runtime.actions
        )
        # 跳过这件事必须**在日志里看得见**（「为什么这次没点那一格」）。
        self.assertTrue(
            any("已跳过 1 格材料不足" in line and "持有 1 / 需求 2" in line for line in logs),
            f"日志里没有跳过记录：{logs}",
        )

    def test_the_real_runner_skips_the_support_section_on_a_capped_page(self):
        """上限已满那一帧走**真 Runner**：支援这一节整段跳过，**一次都不点支援按钮**，
        每周任务照做（绝不许整条路线提前结束）。

        现场是 2026-09-25 21:38 的事故：「今日支援上限 200/200，列表里的绿按钮却照样
        是绿的」—— 点它什么都不弹、什么都不变，旧行为在同一坐标连点 4 次后耗尽、
        就地收尾 ⇒ 那一天的每周任务领奖跟着一起丢掉。

        ⚠️ 2026-09-26 起上限由右上角那一行**数字本身**判出来（整串 200/200），
        所以掉头发生在**第一次要支援之前**：这条用例最要紧的断言因此是
        「点击列表里根本没有支援按钮」，而不是「状态机想不想点」——
        上次两个事故都发生在状态机与主循环**之间**。
        """

        frames = [
            screen(SUP_FULL),  # 上限 200/200 ⇒ 直接切每周任务，一下都不点
            screen(WK_DONE),  # 每周任务也没得领 ⇒ 这一轮正常收工
        ]
        clock = _Clock(frames, hold={index: 3 for index in range(len(frames))})
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runtime = _RecordingRuntime(
            clock.capture,
            clicks.append,
            emit=logs.append,
            monotonic=lambda: clock.now,
        )
        subject = machine()
        subject.request_done = True  # 事故发生在「请求支援」那一步之后
        runner = KnightsDonationRunner(subject, runtime, sleep=clock.sleep)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertFalse(runner.resource_exhausted)
        self.assertEqual(
            ["open-weekly-tab"],
            runtime.actions,
            f"上限满了就该直接切每周任务、别的动作一个都不许有，实际={runtime.actions}",
        )
        # 为什么整段跳过必须在日志里看得见，而且带**得分**（不是「多半是」）。
        self.assertTrue(
            any("今日支援上限" in line and "得分" in line for line in logs),
            f"日志里没有说明上限已满，用户看不出为什么没支援：{logs}",
        )

    def test_the_four_futile_clicks_end_the_support_section_in_place(self):
        """兜底防线走**真 Runner**：上限数字没读到、绿按钮点不动 ⇒ 4 次点击之后
        **原地**掉头去做每周任务，**不做第 5 次点击**，当天这一轮照常走完。

        ⚠️ 这条守的是 ``support_closed`` 那个兜底 —— 它是「路线自己换个办法」这套
        自救机制**唯一**的真实用户，而它在状态机级根本测不出来：状态机只负责把标志
        置上、返回 False，真正执行掉头的是主循环里那段自救分支。把自救整段删掉，
        **任何一条现有用例都不会变红**（这正是 2026-09-26 补它的原因）。

        ⚠️ 画面**跟着点击走**（``fake_game``）：点完「每周任务」页签才真的切过去。
        这与实机一致，也正是「掉头是不是真的落到了每周任务页」能被验收的前提。

        ⚠️ 4 次点击必须打在**同一格**上（``len(set(futile)) == 1``）：这一格才是
        事故现场那格「点了什么都不发生」的绿按钮；要是 4 次打在 4 格上，那就是
        「换着格子试」的另一样子，不是这条兜底要守的场景。
        """
        incident = screen(SUP_TWO)  # 绿按钮照样是绿的，点它什么都不发生
        weekly_ok = screen(WK_OK)  # 每周任务：还有一档点数可领
        weekly_done = screen(WK_DONE)  # 每周任务：都没得领了 ⇒ 收工
        clock = _Clock([incident], {})  # 只借它的假时间；画面由 fake_game 决定

        clicks: list[tuple[int, int]] = []
        logs: list[str] = []

        def fake_game() -> np.ndarray:
            """点了什么就换什么画面（点之前画面一动不动）。"""
            names = [name for name, _ in runtime.pairs]
            if "claim-milestone" in names:
                return weekly_done
            if "open-weekly-tab" in names:
                return weekly_ok
            return incident

        with tempfile.TemporaryDirectory() as workspace:
            runtime = _PairRecordingRuntime(
                fake_game,
                clicks.append,
                emit=logs.append,
                monotonic=lambda: clock.now,
                # 走上「没自救成功」那条错路时会保存失败诊断，给个真目录
                # 才能看到「动作 support-one 点击4次后画面未推进」这句人话。
                diagnostic_dir=Path(workspace),
            )
            subject = machine()
            subject.request_done = True  # 事故发生在「请求支援」那一步之后
            runner = KnightsDonationRunner(subject, runtime, sleep=clock.sleep)

            completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertFalse(runner.resource_exhausted)
        self.assertEqual(
            ["support-one"] * 4 + ["open-weekly-tab", "claim-milestone"],
            runtime.actions,
            f"兜底自救的动作序列不对（多点了一次 / 掉头没落到每周任务）："
            f"实际={runtime.actions}",
        )
        futile = [point for name, point in runtime.pairs if name == "support-one"]
        self.assertEqual(4, len(futile), "「4 次之后才退出来」是用户定的口径")
        self.assertEqual(
            1, len(set(futile)), "4 次重试必须打在同一格上（打不同格是另一回事）"
        )
        # 自救与掉头都必须在日志里看得见 —— 用户要能从日志看出「为什么没支援」。
        self.assertTrue(
            any("交给路线自己换个办法" in line for line in logs),
            f"日志里看不出发生过自救：{logs}",
        )
        self.assertTrue(
            any("支援=连点 4 次没能推进" in line for line in logs),
            f"日志里看不出支援这一节为什么收工：{logs}",
        )
        # 这一天没有白跑：支援那一段掉头之后，每周任务**照做**、并且收工在每周任务那一段。
        self.assertTrue(
            any("结论=" in line and "每周任务" in line for line in logs),
            f"掉头之后没走到每周任务：{logs}",
        )


class KnightsDonationClosedSupportTests(unittest.TestCase):
    """「支援这一节收工」之后的行为（``support_closed``）。"""

    def test_a_closed_support_section_goes_straight_to_the_weekly_tab(self):
        """站回资源支援页时，一个支援按钮都不点，直接切每周任务。

        ⚠️ 关键在于「站回这一页也不点」：恢复导航之后画面又会回到这一页，
        如果这里又重新挑绿按钮，就会在「上限已满」的页面上无限循环下去。
        """

        subject = machine()
        subject.support_closed = True

        action = subject.next_action(screen(SUP_TWO))

        self.assertEqual("open-weekly-tab", action.name)
        self.assertEqual(
            state_label(KnightsDonationState.RESOURCE_SUPPORT), action.source_page
        )
        self.assertEqual(
            (state_label(KnightsDonationState.WEEKLY_TASKS),), action.target_pages
        )
        self.assertIn("支援这一节收工", action.reason)

    def test_an_open_support_section_still_clicks_the_green_button(self):
        """反向守门：没收工的时候不许提前跳到每周任务（原有行为不回退）。"""

        subject = machine()
        subject.request_done = True
        self.assertFalse(subject.support_closed)

        action = subject.next_action(screen(SUP_TWO))

        self.assertEqual("support-one", action.name)


class KnightsDonationSupportLimitTests(unittest.TestCase):
    """右上角「今日支援上限 200/200」—— 2026-09-26 补的**画面判据**。

    以前「上限满了」只能靠 ``support-one`` 连点 4 次推不动**倒推**，日志里写的是
    猜测（"多半是今日支援上限已满"）。代价是：一天里第二次跑捐赠又要白点 4 次、
    再恢复导航一次才得出同一结论；而且「没推进」也可能是别的原因，却一律记成「上限满了」。
    现在直接读数字：整串 ``200/200`` 命中 = 满了。
    """

    def test_the_full_frame_is_recognised_as_capped(self):
        subject = machine()

        match = support_limit_full(screen(SUP_FULL), subject.templates.support_limit_full)

        self.assertIsNotNone(match, "200/200 那一帧必须认得出")
        self.assertGreater(match.score, SUPPORT_LIMIT_FULL_THRESHOLD)
        self.assertLessEqual(abs(match.center[0] - 1297), 3)
        self.assertLessEqual(abs(match.center[1] - 210), 3)

    def test_the_uncapped_frames_are_never_read_as_capped(self):
        """⚠️ 反向守门，这条最要紧：同页 30/200、90/200 **不许**判成「满了」。

        误判的代价是**白丢当天整个支援环节**（补不回来）；而整串与 200/200 共享
        ``0/200`` 尾巴，所以同页这几张的干扰天然就高（实测最高 0.8167）——
        阈值 0.90 正是为它们定的，改阈值前先重跑
        ``runtime_logs/_kd_limit_build_assets.py``。
        """

        subject = machine()

        for name in (SUP, SUP_SCROLLED, SUP_TWO, SUP_SHORT, SCONF):
            with self.subTest(fixture=name):
                self.assertIsNone(
                    support_limit_full(screen(name), subject.templates.support_limit_full),
                    f"{name} 的上限不是 200/200，不该判成已满",
                )

    def test_a_capped_page_goes_straight_to_the_weekly_tab(self):
        """接线：站在这张 200/200 的帧上 ⇒ 一个支援按钮都不点，直接切每周任务。

        ⚠️ 理由里必须带**得分**（不是「多半是」）—— 判据给出的数字就是这段结论的证据，
        少了它，日志又变回推测。这正是用户 2026-09-26 要求「上限判据纳入流程」的点。
        """

        subject = machine()
        subject.request_done = True

        action = subject.next_action(screen(SUP_FULL))

        self.assertEqual("open-weekly-tab", action.name)
        self.assertIn("今日支援上限", action.reason)
        self.assertIn("得分", action.reason)
        self.assertNotIn("多半", action.reason)

    def test_an_uncapped_page_still_clicks_the_green_button(self):
        """反向守门：没满的帧不许提前跳到每周任务（原有行为不回退）。"""

        subject = machine()
        subject.request_done = True

        action = subject.next_action(screen(SUP_TWO))

        self.assertEqual("support-one", action.name)

    def test_the_two_ways_of_closing_the_section_are_told_apart(self):
        """两条来路必须在日志里**分得开**：画面证据 vs 「连点推不动」这个症状。"""

        by_picture = machine()
        by_picture.request_done = True
        picture_reason = by_picture.next_action(screen(SUP_FULL)).reason

        by_symptom = machine()
        by_symptom.request_done = True
        by_symptom.support_closed = True
        symptom_reason = by_symptom.next_action(screen(SUP_TWO)).reason

        self.assertIn("得分", picture_reason)
        self.assertNotIn("连点 4 次", picture_reason)
        self.assertIn("连点 4 次", symptom_reason)
        self.assertNotIn("得分", symptom_reason)


if __name__ == "__main__":
    unittest.main()
