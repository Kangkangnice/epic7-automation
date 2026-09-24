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

import unittest
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
    REWARD_DISMISS_DY,
    SUPPORT_ROW_SKIP_TOLERANCE,
    KnightsDonationAction,
    KnightsDonationRunner,
    KnightsDonationState,
    KnightsDonationStateMachine,
    build_knights_donation_templates,
    state_label,
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
WK_OK = "weekly_tasks_claimable"
WK_DONE = "weekly_tasks_claimed"
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
    WK_OK,
    WK_DONE,
    POP,
    POP_SEL,
    SCONF,
    REWARD,
)
# 「资源支援」这一页的三种样子（是否带绿按钮、按钮几个、盖没盖弹窗）。
SUPPORT_PAGES = (SUP, SUP_SCROLLED, SUP_TWO)
# 骑士团活动界面里的所有子页（含两个页签页）。
ACTIVITY_PAGES = (SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE)
# 除「资源支援」外都不是这一页的夹具。
NOT_SUPPORT = (GH_DOT, GH_BARE, WK_OK, WK_DONE, POP, POP_SEL, SCONF, REWARD)
# 弹窗类的四张（三个弹窗 + 确认框）。
POPUP_FIXTURES = (POP, POP_SEL, SCONF, REWARD)

# 锚点 -> (必须过阈的夹具, 必须不过阈的夹具)。两个集合的并集必须等于 ALL_FIXTURES。
EXPECTATIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "activity_entry": (
        (GH_DOT, GH_BARE),
        (SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE, POP, POP_SEL, SCONF, REWARD),
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
        (GH_DOT, GH_BARE, WK_OK, WK_DONE, POP, POP_SEL, REWARD),
    ),
    # 下滑后的帧上绿色按钮已经变灰 ⇒ 它属于 must_not（状态机因此才会去下滑）；
    # 两按钮那张上必须能认出**至少一个**（多按钮的情形另有用例专门测）。
    "support_one_button": (
        (SUP, SUP_TWO),
        (GH_DOT, GH_BARE, SUP_SCROLLED, WK_OK, WK_DONE, POP, POP_SEL, SCONF, REWARD),
    ),
    "points_label": (
        (WK_OK, WK_DONE),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, POP, POP_SEL, SCONF, REWARD),
    ),
    # 已领完那帧没有「领取」按钮 ⇒ must_not。
    "claim_button": (
        (WK_OK,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, WK_DONE, POP, POP_SEL, SCONF, REWARD),
    ),
    "popup_title": (
        (POP, POP_SEL),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE, SCONF, REWARD),
    ),
    "flower_cell": (
        (POP,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE, POP_SEL, SCONF, REWARD),
    ),
    "flower_cell_selected": (
        (POP_SEL,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE, POP, SCONF, REWARD),
    ),
    "popup_confirm": (
        (POP, POP_SEL),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE, SCONF, REWARD),
    ),
    "reward_title": (
        (REWARD,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE, POP, POP_SEL, SCONF),
    ),
    # 确认框自己的两个锚点：在本路线 11 张里**只**在确认框那一帧过阈
    # （其余 10 张最高 0.2079 / 0.2127，余量都在 0.58 以上）。
    "support_confirm_title": (
        (SCONF,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE, POP, POP_SEL, REWARD),
    ),
    "support_confirm_button": (
        (SCONF,),
        (GH_DOT, GH_BARE, SUP, SUP_SCROLLED, SUP_TWO, WK_OK, WK_DONE, POP, POP_SEL, REWARD),
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
        每周任务页的 points_label 掉到 0.4138 —— 都不会串页，但顺序上先判弹窗更稳。
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
            WK_OK: KnightsDonationState.WEEKLY_TASKS,
            WK_DONE: KnightsDonationState.WEEKLY_TASKS,
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
        # 开局挑分数最高那个（被跳过之后必须能挑到第二个，见下面的跳过用例）。
        subject = machine()
        subject.request_done = True
        self.assertEqual(candidates[0].center, subject.next_action(frame).point)

    def test_the_reward_popup_is_what_makes_a_support_count(self):
        """「点过了」不等于「支援成功」：只有看到「获得奖励」才作数。

        对照实验（2026-09-24 实跑）：团员要的材料我持有 0 时，确认框里点「支援1个」
        **毫无变化** —— 行不消失、今日支援上限也不涨。所以判据只能是「有没有弹奖励」。
        """
        subject = machine()
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
        """
        subject = machine()
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

    def test_when_every_visible_row_is_unreachable_it_scrolls_instead_of_repeating(self):
        """两个绿按钮都吃不下 ⇒ 不再重复点，改为下滑（且跳过表必须清空）。

        ⚠️ 清空是必需的：下滑会让整列位移，旧的 y 键就指到别人头上了。
        """
        subject = machine()
        subject.request_done = True
        frame = screen(SUP_TWO)

        self.assertEqual(2, len(support_candidates(frame)))
        subject.next_action(frame)  # 点第一行
        subject.next_action(frame)  # 吃不下 → 跳过第一行、点第二行
        action = subject.next_action(frame)  # 第二行也吃不下 → 不能重复点，下滑

        self.assertEqual("scroll-support", action.name)
        self.assertEqual(1, subject.support_scrolls)
        self.assertEqual(set(), subject.skipped_rows)

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

if __name__ == "__main__":
    unittest.main()
