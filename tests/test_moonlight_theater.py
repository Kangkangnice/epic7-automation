"""月光剧场路线的页面、动作与循环测试（全部用当前客户端的实拍帧）。"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from auto_game_unified.games.epic7 import moonlight_theater as mt

import numpy as np

from auto_game_unified.games.epic7.evidence.moonlight_theater import (
    STORY_ARROW_EXCLUDE,
)
from auto_game_unified.games.epic7.moonlight_theater import (
    MoonlightAction,
    MoonlightCleared,
    MoonlightRunner,
    MoonlightState,
    BATTLE_ANCHOR_VOTES,
    REWARD_DOT_MIN_ORANGE_PIXELS,
    REWARD_GRACE_SECONDS,
    MoonlightStateMachine,
    build_moonlight_templates,
)
from auto_game_unified.games.epic7.template_paths import resolve_template_dir

FIXTURES = (
    Path(__file__).resolve().parent / "fixtures" / "epic7_moonlight_theater"
)
TEMPLATES = (
    Path(__file__).resolve().parents[1]
    / "games" / "epic7" / "templates" / "moonlight_theater"
)


def load(name: str) -> np.ndarray:
    import cv2

    path = FIXTURES / f"{name}.png"
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class FakeClock:
    """可控时钟：让「等橙点亮」那 8 秒在测试里一瞬间过去。

    ⚠️ 不注入时钟的话，`_at_episode` 的宽限期会拿**真实单调时钟**去算，
    而单测是毫秒级跑完的 ⇒ 永远「还没等够」⇒ 测出来的全是 `None`。
    """

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def machine(
    state: MoonlightState = MoonlightState.ENTRY,
    *,
    clock: FakeClock | None = None,
) -> MoonlightStateMachine:
    return MoonlightStateMachine(
        build_moonlight_templates(resolve_template_dir(TEMPLATES)),
        initial_state=state,
        clock=clock,
    )


class PageTests(unittest.TestCase):
    """每张夹具必须只认出一个页面 —— 页面判据的排他性。"""

    def test_each_fixture_maps_to_exactly_one_page(self) -> None:
        expected = {
            "entry_side_story": MoonlightState.ENTRY,
            "list_free": MoonlightState.LIST,
            "list_no_free": MoonlightState.LIST,
            "episode_fresh": MoonlightState.EPISODE,
            "episode_reward": MoonlightState.EPISODE,
            "episode_claimed": MoonlightState.EPISODE,
            # 2026-10-24 15:10 事故现场：这个剧场的分集页左上角是**亮蓝天**，
            # 旧返回键模板（带深黑背景）只有 0.6046。
            "episode_bright": MoonlightState.EPISODE,
            "guide": MoonlightState.GUIDE,
            "story": MoonlightState.STORY,
            "story_b": MoonlightState.STORY,
            # 2026-10-24 真机事故现场：▼ 缩到 85% + 半透明 + 背景被角色手臂压住。
            "story_dim": MoonlightState.STORY,
            "battle": MoonlightState.BATTLE,
            # 2026-10-17 真机事故现场（``timeout_clear``）存下来的那帧 CLEAR。
            "clear": MoonlightState.CLEAR,
            "purchase": MoonlightState.PURCHASE,
            # 2026-10-17 第二次实机卡死现场：这个弹窗原先**根本不在页面表里**。
            "ticket": MoonlightState.USE_TICKET,
            "reward_popup": MoonlightState.REWARD,
        }
        probe = machine()
        for name, want in expected.items():
            with self.subTest(fixture=name):
                self.assertIs(probe.observe_page(load(name)), want)

    def test_a_blank_screen_is_unknown_and_produces_no_action(self) -> None:
        blank = np.zeros((1132, 1982, 3), dtype=np.uint8)
        probe = machine()
        self.assertIsNone(probe.observe_page(blank))
        self.assertIsNone(probe.next_action(blank))


class EntryTests(unittest.TestCase):
    def test_entry_with_free_badge_opens_the_theater(self) -> None:
        probe = machine()
        action = probe.next_action(load("entry_side_story"))
        self.assertIsInstance(action, MoonlightAction)
        self.assertEqual(action.name, "open-theater")
        self.assertEqual(action.target_pages, ("剧场选择页",))

    def test_entry_without_free_badge_stops_the_route_without_clicking(self) -> None:
        """没有 F 角标 = 本周免费已领完 ⇒ 正常收工，一个动作都不发。"""
        probe = machine()
        # 把角标模板换成随机噪声 ⇒ 模拟「这一帧没有 F 角标」，但入口卡片仍在。
        # ⚠️ 不能换成全 0 / 纯色：常值模板方差为 0，``TM_CCOEFF_NORMED`` 会退化成
        # 除以 0 的分支，分数反而接近 1（实测第一次就踩了这个坑）。
        noise = np.random.default_rng(20261017).integers(
            0, 256, probe.templates.entry_free.shape, dtype=np.uint8
        )
        probe.templates = type(probe.templates)(
            **{
                **{
                    field: getattr(probe.templates, field)
                    for field in probe.templates.__dataclass_fields__
                    if field != "evidence"
                },
                "entry_free": noise,
                "evidence": probe.templates.evidence,
            }
        )
        with self.assertRaises(MoonlightCleared) as caught:
            probe.next_action(load("entry_side_story"))
        self.assertIn("免费", str(caught.exception))
        self.assertIs(probe.state, MoonlightState.FINISHED)


class TheaterListTests(unittest.TestCase):
    def test_current_theater_with_free_enters(self) -> None:
        probe = machine(MoonlightState.LIST)
        action = probe.next_action(load("list_free"))
        self.assertEqual(action.name, "enter-theater")
        # 出口写全三个：**入场本身也可能弹门票**（用户原话「进行观览和入场都通向花钱」）
        self.assertLessEqual(
            {"分集页", "购买门票弹窗", "使用剧场门票弹窗"},
            set(action.target_pages),
        )

    def test_current_theater_without_free_moves_right(self) -> None:
        probe = machine(MoonlightState.LIST)
        action = probe.next_action(load("list_no_free"))
        self.assertTrue(action.name.startswith("next-theater"), action.name)
        self.assertEqual(action.point, (1450, 550))

    def test_the_poster_fingerprint_tells_theaters_apart(self) -> None:
        """动作名带的是「现在这张海报」的指纹 ⇒ 换了一张就得换名字。

        指纹必须进名字：主循环那本「同名动作点了几次」的账靠它判定推进，
        名字不换就会被当成「点了四次都没反应」当场判死。
        """
        left = machine(MoonlightState.LIST).next_action(load("list_no_free"))
        right = machine(MoonlightState.LIST).next_action(load("list_free"))
        self.assertNotEqual(left.name, right.name)

    def test_the_same_frame_twice_means_the_right_edge_was_reached(self) -> None:
        """连点两次右边画面都没变 ⇒ 右边没有海报了 ⇒ 收工（而不是无限点）。"""
        probe = machine(MoonlightState.LIST)
        frame = load("list_no_free")
        probe.next_action(frame)
        with self.assertRaises(MoonlightCleared):
            probe.next_action(frame)
        self.assertIn("本周已结束", probe.finish_reason)

    def test_a_new_theater_is_snapshotted_once(self) -> None:
        """遇到没见过的剧场存一张样张，同一张海报只存一次。

        为什么要存：这条路线有 7 个剧场、各有各的美术，而夹具只覆盖 2 个 ——
        2026-10-24 两次事故都是「第一次撞上某个剧场」。存样是补样本的唯一途径。

        ⚠️ 存样只是附带动作：这里同时断言**动作照常发出**，不许因为它而改变决策。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            probe = machine(MoonlightState.LIST)
            probe.runtime = SimpleNamespace(  # type: ignore[attr-defined]
                diagnostic_dir=Path(tmp), log=lambda _message: None
            )
            frame = load("list_free")
            action = probe.next_action(frame)
            probe.next_action(frame)
            saved = sorted((Path(tmp) / "theater_samples").glob("list_*.png"))
            self.assertEqual(len(saved), 1, "同一张海报不该重复存")
            self.assertEqual(action.name, "enter-theater", "存样不许影响主线决策")

    def test_snapshotting_never_raises_without_a_runtime(self) -> None:
        """状态机在单元测试里是裸构造的（没有 runtime）⇒ 存样必须安静跳过。"""
        probe = machine(MoonlightState.LIST)
        action = probe.next_action(load("list_no_free"))
        self.assertTrue(action.name.startswith("next-theater"), action.name)


class EpisodeTests(unittest.TestCase):
    def test_fresh_episode_watches(self) -> None:
        probe = machine(MoonlightState.EPISODE)
        action = probe.next_action(load("episode_fresh"))
        self.assertEqual(action.name, "watch-episode")

    def test_claimable_reward_wins_over_watching(self) -> None:
        probe = machine(MoonlightState.EPISODE)
        action = probe.next_action(load("episode_reward"))
        self.assertEqual(action.name, "claim-reward")
        self.assertTrue(probe.watched_current)

    def test_after_claiming_the_only_allowed_move_is_leaving(self) -> None:
        """「刚入场」和「领完奖励」两种分集页长得一样 ⇒ 靠业务标记走「返回」，
        绝不再点「进行观览」（那会弹购买门票）。"""
        clock = FakeClock()
        probe = machine(MoonlightState.EPISODE, clock=clock)
        probe.watched_current = True
        # 刚看完的第一帧**先等**（橙点是脉动的、奖励也可能晚一拍到账），
        # 这一帧不许下「没得领」的结论、更不许撤 —— 撤了就是漏领。
        self.assertIsNone(
            probe.next_action(load("episode_claimed")),
            "刚回到分集页就撤 = 奖励漏领",
        )
        clock.advance(REWARD_GRACE_SECONDS + 0.5)
        action = probe.next_action(load("episode_claimed"))
        self.assertEqual(action.name, "leave-theater")
        self.assertEqual(action.target_pages, ("剧场选择页",))
        self.assertEqual(probe.completed_cycles, 1)
        self.assertFalse(probe.watched_current)


class GuideAndStoryTests(unittest.TestCase):
    def test_guide_confirm(self) -> None:
        probe = machine(MoonlightState.GUIDE)
        action = probe.next_action(load("guide"))
        self.assertEqual(action.name, "confirm-guide")

    def test_story_advances_on_the_safe_point(self) -> None:
        """字幕点击点必须避开分集页的「进行观览」按钮（实测 960,1000 会误触）。"""
        probe = machine(MoonlightState.STORY)
        action = probe.next_action(load("story"))
        self.assertTrue(action.name.startswith("advance-story"), action.name)
        self.assertEqual(action.point, (760, 1000))

    def test_two_different_story_frames_advance_under_different_names(self) -> None:
        """推进了 ⇒ 指纹变 ⇒ 动作名变 ⇒ 主循环按「新动作」重新记账（不会被判死）。"""
        probe = machine(MoonlightState.STORY)
        first = probe.next_action(load("story"))
        second = probe.next_action(load("story_b"))
        self.assertNotEqual(first.name, second.name)

    def test_the_repeating_arrow_is_kept_out_of_the_progress_fingerprint(self) -> None:
        """▼ 是闪的。把它算进指纹，「每帧都在变」就恒成立，「点了没反应」永远发现不了。

        做法上的验证：把 ▼ 那一块涂成两种不同的颜色，指纹必须**不变**。
        """
        probe = machine(MoonlightState.STORY)
        frame = load("story").copy()
        x, y, w, h = STORY_ARROW_EXCLUDE
        painted = frame.copy()
        painted[y : y + h, x : x + w] = 0
        self.assertEqual(
            probe._story_fingerprint(frame), probe._story_fingerprint(painted)
        )
        # 反过来：字幕框里变一点，指纹**必须**变（同一张背景连着说话时靠它判推进）。
        subtitle = frame.copy()
        subtitle[y - 60 : y - 10, 200:1200] = 0
        self.assertNotEqual(
            probe._story_fingerprint(frame), probe._story_fingerprint(subtitle)
        )

    def test_story_page_never_issues_a_click_without_the_marker(self) -> None:
        probe = machine(MoonlightState.STORY)
        blank = np.zeros((1132, 1982, 3), dtype=np.uint8)
        self.assertIsNone(probe.next_action(blank))

    def test_a_half_faded_arrow_still_counts_as_the_story_page(self) -> None:
        """2026-10-24 事故帧（``story_dim``）：▼ 缩到 85% + 半透明 + 背景被角色手臂压住。

        这一帧上 ▼ 的位置完全正确，旧模板却只有 **0.7022** —— 因为 44×36 的模板里
        八成面积是背景，角色手臂一压过来分数就崩。判据失效的直接后果不是「点错」，
        而是「**一个动作都不发**」：画面停在这一帧不动，满 180 秒绝对超时（退出码 1）。
        模板裁到箭头本体（27×19）后实测 **0.9005**，与上面那条「没有 ▼ 不许点」
        并不冲突 —— 它验的是箭头**完全不在**（全黑帧 0.0）。
        """
        probe = machine(MoonlightState.STORY)
        frame = load("story_dim")
        self.assertIs(probe.observe_page(frame), MoonlightState.STORY)
        action = probe.next_action(frame)
        self.assertIsNotNone(action, "认成剧情页就必须发动作，干等就是 180 秒熔断")
        self.assertTrue(action.name.startswith("advance-story"), action.name)
        self.assertEqual(action.point, (760, 1000))


class ClearTests(unittest.TestCase):
    """CLEAR 过场（2026-10-17 真机 ``timeout_clear`` 事故的回归测试）。

    事故的形态不是「点错了」，而是「**一个动作都不发**」：状态机认得 CLEAR，
    却返回 ``None`` 干等，主循环于是在 CLEAR 上烧满 60 秒才报超时。
    所以这里第一条钉的就是「必须发动作」。
    """

    def test_the_real_clear_frame_is_a_true_positive_for_the_reused_template(self) -> None:
        """这一帧是真机 CLEAR（事故现场），`battle_clear` 复用支线故事的模板能认出来。

        证据档案里原先记着「本路线**没有**真 CLEAR 帧，缺口 1」—— 现在补上了：
        这一帧右下角**没有**支线故事那对「»»」继续箭头，模板照样命中（白掩膜口径）。
        """
        probe = machine()
        found = probe._locate(load("clear"), "battle_clear")
        self.assertIsNotNone(found, "真机 CLEAR 帧必须认得出 battle_clear")
        self.assertGreaterEqual(found.score, 0.95)
        self.assertIs(probe.observe_page(load("clear")), MoonlightState.CLEAR)

    def test_clear_issues_a_click_instead_of_waiting(self) -> None:
        probe = machine(MoonlightState.CLEAR)
        action = probe.next_action(load("clear"))
        self.assertIsNotNone(action, "CLEAR 上不发动作 = 干等 60 秒报 timeout_clear")
        self.assertEqual(action.name, "advance-clear")

    def test_clear_goes_on_to_the_story_or_the_episode(self) -> None:
        """CLEAR 之后不是剧情页（接着点字幕）就是分集页（领奖）—— 两者都要认。"""
        probe = machine(MoonlightState.CLEAR)
        action = probe.next_action(load("clear"))
        self.assertLessEqual({"剧情页", "分集页"}, set(action.target_pages))
        self.assertEqual(action.source_page, "CLEAR 过场")

    def test_clear_clicks_the_point_that_is_blank_on_the_episode_page(self) -> None:
        """点的是 ``STORY_CLICK_POINT``：它在分集页是空白区，不会误触「进行观览」。

        （那条教训见 ``STORY_CLICK_POINT`` 的注释：``(960,1000)`` 落在按钮上，
        实测弹出过一次购买门票。）
        """
        probe = machine(MoonlightState.CLEAR)
        self.assertEqual(probe.next_action(load("clear")).point, (760, 1000))

    def test_clear_never_fires_on_the_other_pages(self) -> None:
        """页面排他性：CLEAR 认出来的地方不能是别的页，反过来也一样。"""
        probe = machine()
        for name in ("story", "episode_fresh", "episode_claimed", "list_free", "guide"):
            with self.subTest(fixture=name):
                self.assertNotEqual(
                    probe.observe_page(load(name)), MoonlightState.CLEAR, name
                )


class TicketDialogTests(unittest.TestCase):
    """「使用剧场门票」弹窗（2026-10-17 第二次实机卡死的现场）。

    事故形态：这个弹窗**不在页面表里** ⇒ `observe_page` 返回 `None`，
    而底下的分集页元素还在 ⇒ 状态机以为自己在分集页，每 43 秒重试点一次
    「进行观览」，4 次之后本该判死（用户按了 P 才停）。

    ⚠️ 它和「购买剧场门票」是两个**相反**的弹窗：一个花金币（明令禁止，只取消），
    一个花已持有的券（用户 2026-10-17 拍板「花掉」，点确认）。所以这里两头都钉。
    """

    def test_the_dialog_is_recognized_at_all(self) -> None:
        probe = machine()
        self.assertIs(
            probe.observe_page(load("ticket")),
            MoonlightState.USE_TICKET,
            "认不出这个弹窗 = 会拿着分集页的判据继续乱点（卡死现场）",
        )

    def test_the_ticket_gets_spent(self) -> None:
        """用户拍板「花掉」⇒ 点的是**确认**（蓝色那颗，在右半边）。"""
        probe = machine(MoonlightState.USE_TICKET)
        action = probe.next_action(load("ticket"))
        self.assertEqual(action.name, "accept-ticket")
        self.assertGreater(action.point[0], 940, "确认在右半边；点成左边就是取消")
        self.assertIn("观览指南弹窗", action.target_pages)

    def test_the_gold_purchase_popup_is_a_different_thing(self) -> None:
        """花金币那个照旧只取消、点左半边 —— 两个弹窗绝不能串。"""
        probe = machine()
        self.assertIs(probe.observe_page(load("purchase")), MoonlightState.PURCHASE)
        action = probe.next_action(load("purchase"))
        self.assertEqual(action.name, "cancel-purchase")
        self.assertLess(action.point[0], 940, "取消在左半边；点成右边就是买金币票")

    def test_confirm_missing_falls_back_to_cancel_and_abandons(self) -> None:
        """确认按钮定位不到（券用光后按钮变灰）⇒ 取消 + 放弃这个剧场，绝不留在这里。"""
        probe = machine(MoonlightState.USE_TICKET)
        probe.templates = _swap_template(probe.templates, "ticket_confirm")
        action = probe.next_action(load("ticket"))
        self.assertEqual(action.name, "cancel-ticket")
        self.assertTrue(probe.must_leave)
        self.assertLessEqual(
            {"分集页", "剧场选择页"}, set(action.target_pages)
        )

    def test_abandoning_is_never_turned_back_into_spending(self) -> None:
        """已经决定放弃（取消点过但弹窗没关掉）⇒ 下一帧**仍只许取消**。

        否则「放弃」会退化成「花掉」：取消没生效的第二帧回到「确认优先」，
        正好把那张本来不打算花的券花出去 —— 方向反了，而且花的是用户的资产。
        """
        probe = machine(MoonlightState.USE_TICKET)
        probe.templates = _swap_template(probe.templates, "ticket_confirm")
        probe.next_action(load("ticket"))  # 确认定位不到 ⇒ 取消 + must_leave
        self.assertTrue(probe.must_leave)
        probe.templates = machine().templates  # 确认按钮这一帧又能定位到了
        action = probe.next_action(load("ticket"))
        self.assertEqual(
            action.name,
            "cancel-ticket",
            "must_leave 之后即使确认按钮能定位到，也不许花券",
        )
        self.assertLess(action.point[0], 940, "取消在左半边，别点到确认上")


class WatchedBookkeepingTests(unittest.TestCase):
    """「进过剧情」必须当场记账 —— 这是第二次实机连看两遍的根因。"""

    def test_entering_the_story_marks_the_episode_as_watched(self) -> None:
        probe = machine(MoonlightState.STORY)
        self.assertFalse(probe.watched_current)
        probe.next_action(load("story"))
        self.assertTrue(
            probe.watched_current,
            "看到剧情页就说明这一集的额度已经消耗掉，必须当场记账",
        )

    def test_after_the_story_the_episode_is_never_watched_again(self) -> None:
        """剧情走完回分集页，**就算没有橙点**也只许撤，绝不再点进行观览。"""
        clock = FakeClock()
        probe = machine(MoonlightState.STORY, clock=clock)
        probe._current_poster = "poster-x"
        probe.next_action(load("story"))  # 进剧情 ⇒ 记账
        # 走完回分集页、没有橙点：先等宽限期，期间一个动作都不发
        self.assertIsNone(probe.next_action(load("episode_claimed")))
        clock.advance(REWARD_GRACE_SECONDS + 0.5)
        action = probe.next_action(load("episode_claimed"))
        self.assertEqual(action.name, "leave-theater", "再点进行观览会花掉额度/弹出门票")
        self.assertEqual(probe.completed_cycles, 1)


class TransitionExitTests(unittest.TestCase):
    """每个点击动作的 ``target_pages`` 必须**写得下所有可能落点**。

    主循环的规则（``ModeRunnerBase.run``）：一个带 ``target_pages`` 的动作发出后，
    只要当前页不在目标里，那一帧的动作就会被**整个吞掉**（置 None），而且
    ``last_transition_action`` 不会清 —— 于是这条路线在目标出现之前**一个动作都发不出去**，
    最后报 ``等待动作[…]目标画面[…]超时``。实机表现就是「点了之后干等」。

    所以下面两件事必须同时成立：
    1. **来源页绝不能出现在目标里** —— 那会让「点了个寂寞」被当成「转场完成」；
    2. 所有可能落点都要列进去（这一条由下面的具体断言守着）。
    """

    #: 每个动作「至少」要认得出的落点。写窄了就是实机干等的根因。
    REQUIRED_EXITS = {
        "open-theater": {"剧场选择页"},
        "enter-theater": {"分集页", "购买门票弹窗", "使用剧场门票弹窗"},
        "watch-episode": {
            "观览指南弹窗",
            "使用剧场门票弹窗",
            "购买门票弹窗",
            "战斗中",
            "剧情页",
        },
        "confirm-guide": {"剧情页", "战斗中", "CLEAR 过场", "分集页"},
        "advance-clear": {"剧情页", "分集页", "战斗中"},
        "claim-reward": {"获得奖励弹窗"},
        "close-reward": {"分集页", "剧场选择页"},
        "leave-theater": {"剧场选择页"},
        "abandon-theater": {"剧场选择页"},
        "cancel-purchase": {"分集页", "剧场选择页"},
        "cancel-ticket": {"分集页", "剧场选择页"},
        "accept-ticket": {"观览指南弹窗", "剧情页", "战斗中"},
    }

    def _actions(self):
        """把每个动作在对应夹具上都造出来（一个动作可能有多条分支）。"""
        cases = (
            ("entry_side_story", None),
            ("list_free", None),
            ("list_no_free", None),
            ("episode_fresh", None),
            ("episode_reward", None),
            ("guide", None),
            ("story", None),
            ("clear", None),
            ("purchase", None),
            ("ticket", None),
            ("reward_popup", None),
        )
        produced = {}
        for fixture, _ in cases:
            probe = machine()
            probe._current_poster = "poster-x"
            action = probe.next_action(load(fixture))
            if action is not None:
                produced[action.name] = action
        # 分集页「看完就撤」那条分支要单独造：先看剧情、再回一张没有橙点的分集页。
        # ⚠️ 要走完「等橙点」的宽限期才会撤，所以这里得给可控时钟。
        clock = FakeClock()
        probe = machine(MoonlightState.STORY, clock=clock)
        probe._current_poster = "poster-x"
        probe.next_action(load("story"))            # 进剧情 ⇒ 记账
        probe.next_action(load("episode_claimed"))  # 回分集页第一帧：开始等
        clock.advance(REWARD_GRACE_SECONDS + 0.5)   # 等满
        action = probe.next_action(load("episode_claimed"))
        produced[action.name] = action
        # 「确认定位不到 ⇒ 取消」那条分支
        probe = machine(MoonlightState.USE_TICKET)
        probe.templates = _swap_template(probe.templates, "ticket_confirm")
        action = probe.next_action(load("ticket"))
        produced[action.name] = action
        # 「这个剧场要花门票 ⇒ 撤」那条分支（``must_leave`` 已在购买弹窗里置位）
        probe = machine(MoonlightState.EPISODE, clock=FakeClock())
        probe._current_poster = "poster-x"
        probe.must_leave = True
        action = probe.next_action(load("episode_claimed"))
        produced[action.name] = action
        return produced

    def test_every_click_action_declares_all_of_its_landing_pages(self) -> None:
        produced = self._actions()
        missing = set(self.REQUIRED_EXITS) - set(produced)
        self.assertFalse(missing, f"这些动作没造出来，护栏等于没写：{missing}")
        for name, required in self.REQUIRED_EXITS.items():
            action = produced[name]
            declared = set(action.target_pages)
            self.assertLessEqual(
                required,
                declared,
                f"动作 {name} 的出口写窄了，缺 {required - declared}："
                "目标不出现时主循环会把动作整个吞掉，实机表现为干等超时",
            )

    def test_no_action_treats_its_own_source_page_as_a_target(self) -> None:
        """来源页写进目标 = 「点了没反应」也会被判成转场完成（判据自我欺骗）。"""
        for name, action in self._actions().items():
            self.assertNotIn(
                action.source_page,
                action.target_pages,
                f"动作 {name} 把来源页当成了目标页",
            )

    def test_left_to_right_moves_are_in_page_evidence(self) -> None:
        """不换页的两条（换海报 / 点字幕）必须走 `in_page_evidence`，不能有 target_pages。"""
        episode = machine()
        episode._current_poster = "poster-x"
        next_theater = episode.next_action(load("list_no_free"))
        story = machine(MoonlightState.STORY).next_action(load("story"))
        for action in (next_theater, story):
            self.assertEqual(action.target_pages, (), f"{action.name} 不该有目标页")
            self.assertTrue(action.in_page_evidence, f"{action.name} 缺同页证据")


class RewardClosedLoopTests(unittest.TestCase):
    """**奖励必须真的领到**（用户 2026-10-17：漏领就是没闭环，不许当可接受风险）。

    这里的四条都是「实机漏领」的直接对策：
    1. 橙点晚一两秒才亮 ⇒ 不能拿第一帧就下「没得领」的结论；
    2. 橙点是**脉动**的，模板分会掉到阈值下 ⇒ 判据必须有颜色兜底；
    3. 领完之后别再等（否则每个剧场白等 8 秒）；
    4. 颜色兜底不许被别的页面触发（敌人和背景就是橙色的）。
    """

    def test_a_late_orange_dot_is_still_claimed(self) -> None:
        """剧情刚回来时还没橙点，等一会儿亮了 ⇒ **一定要领**，不许已经撤了。"""
        clock = FakeClock()
        probe = machine(MoonlightState.STORY, clock=clock)
        probe._current_poster = "poster-x"
        probe.next_action(load("story"))  # 进剧情 ⇒ 记账

        # 第一帧：页面回来了、橙点还没亮 ⇒ 只能等，不能撤
        self.assertIsNone(probe.next_action(load("episode_claimed")))
        # 第二帧：橙点亮了（换一帧有橙点的画面）
        action = probe.next_action(load("episode_reward"))
        self.assertEqual(
            action.name,
            "claim-reward",
            "等到了却不领 = 这一集的奖励白看",
        )
        self.assertEqual(action.target_pages, ("获得奖励弹窗",))

    def test_the_dot_is_seen_even_when_the_template_misses(self) -> None:
        """橙点脉动到模板认不出时，**颜色判据**要顶上（否则就是实机那次漏领）。"""
        probe = machine(MoonlightState.EPISODE)  # 没有橙点等着领的常态
        probe.watched_current = True
        probe.templates = _swap_template(probe.templates, "reward_dot")
        action = probe.next_action(load("episode_reward"))
        self.assertIsNotNone(action, "模板瞎了、颜色也没兜住 -> 这一集的奖励白看")
        self.assertEqual(action.name, "claim-reward")

    def test_the_orange_check_only_fires_on_the_claimable_frame(self) -> None:
        """颜色兜底的范围是那个 44×44 的小框 —— 放大到整个区域就会被橙色背景骗。"""
        probe = machine()
        for name in (
            "entry_side_story", "list_free", "list_no_free", "episode_fresh",
            "episode_claimed", "episode_bright", "guide", "story", "story_b",
            "story_dim", "clear", "reward_popup", "purchase", "ticket",
        ):
            self.assertLess(
                probe._orange_pixels(load(name)),
                REWARD_DOT_MIN_ORANGE_PIXELS,
                f"{name} 上不该有橙点像素",
            )
        self.assertGreaterEqual(
            probe._orange_pixels(load("episode_reward")),
            REWARD_DOT_MIN_ORANGE_PIXELS,
            "可领帧必须过",
        )

    def test_the_grace_is_skipped_once_the_reward_is_claimed(self) -> None:
        """领完之后别再无谓地等 8 秒。"""
        clock = FakeClock()
        probe = machine(MoonlightState.EPISODE, clock=clock)
        probe.watched_current = True
        probe.claimed_current = True
        action = probe.next_action(load("episode_claimed"))
        self.assertEqual(action.name, "leave-theater", "领过了就该直接撤")

    def test_the_bright_episode_page_still_locates_the_back_arrow(self) -> None:
        """2026-10-24 15:10 事故（``episode_bright``）：亮蓝天底图上的分集页。

        ``watch_button`` 0.9996 证明它就是分集页，但旧 ``back_button`` 模板是
        110×70 的**深黑背景**、箭头只占左下角一小块 ⇒ 0.6046 ⇒ ``_required`` 抛
        ``UnrecognizedScreen`` ⇒ ``timeout_episode``（退出码 1）。
        重裁成 47×57（只含完整箭头）+ 白掩膜后 1.0000。

        ⚠️ 第二条断言同样重要：``point=back.center`` ⇒ **模板中心就是点击坐标**。
        旧模板的中心落在箭头右上方约 40px（「月光剧场」标题上），只是碰巧也能返回。
        """
        clock = FakeClock()
        probe = machine(MoonlightState.EPISODE, clock=clock)
        probe.watched_current = True
        probe.claimed_current = True
        action = probe.next_action(load("episode_bright"))
        self.assertIsNotNone(
            action, "认得出分集页却定位不到返回键 -> timeout_episode"
        )
        self.assertEqual(action.name, "leave-theater")
        x, y = action.point
        self.assertLess(x, 100, f"点击点偏到右边了：{action.point}")
        self.assertLess(y, 130, f"点击点偏到下面了：{action.point}")

    def test_the_waiting_frames_issue_no_action_at_all(self) -> None:
        """宽限期内**不许点任何东西**（尤其不许点「进行观览」，那会花钱）。"""
        clock = FakeClock()
        probe = machine(MoonlightState.EPISODE, clock=clock)
        probe.watched_current = True
        for _ in range(5):
            self.assertIsNone(probe.next_action(load("episode_claimed")))
            clock.advance(1.0)


class BattleRecognitionTests(unittest.TestCase):
    """战斗必须**认得出**（用户 2026-10-17：认不出来的都是有问题）。

    2026-10-17 两次实跑的日志里一个 ``阶段=战斗`` 都没有 —— 复用的
    ``battle_scene_visible`` 在本路线认不出（行动列是彩色头像，白占比只有 0.037）。
    这里钉两件事：自有锚点能独立认出来；且它们不会在任何别的页面上误报。
    """

    def test_a_battle_frame_is_recognized_without_the_shared_check(self) -> None:
        """把复用的判据强行打哑，本路线仍要靠自有锚点认出战斗。"""
        probe = machine()
        with mock.patch.object(mt, "battle_scene_visible", lambda _s: False):
            self.assertIs(
                probe.observe_page(load("battle")),
                MoonlightState.BATTLE,
                "共享判据哑了就认不出战斗 = 战斗监督永远接管不了",
            )

    def test_the_shared_check_alone_is_not_trusted(self) -> None:
        """反过来：共享判据说是战斗、但自有锚点说不是 ⇒ 不认（防误报剧情/立绘帧）。"""
        probe = machine()
        with mock.patch.object(mt, "battle_scene_visible", lambda _s: True):
            self.assertIs(
                probe.observe_page(load("story")),
                MoonlightState.STORY,
                "剧情页必须先被页面表认出来",
            )

    def test_the_anchors_never_fire_on_other_pages(self) -> None:
        """三枚锚点在其他 15 张夹具上**命中数必须 < 2**（误报就是乱交控制权）。"""
        probe = machine()
        for name in (
            "entry_side_story", "list_free", "list_no_free", "episode_fresh",
            "episode_reward", "episode_claimed", "episode_bright", "guide",
            "story", "story_b", "story_dim", "clear", "reward_popup",
            "purchase", "ticket",
        ):
            votes = probe._battle_anchor_votes(load(name))
            self.assertLess(votes, BATTLE_ANCHOR_VOTES, f"{name} 被误判成战斗")
        self.assertGreaterEqual(
            probe._battle_anchor_votes(load("battle")),
            BATTLE_ANCHOR_VOTES,
            "战斗帧必须过",
        )


class PurchaseSafetyTests(unittest.TestCase):
    def test_purchase_popup_only_ever_cancels(self) -> None:
        """出现购买门票弹窗时，动作必须是「取消」，而且点不在「购买」上。"""
        probe = machine()
        action = probe.next_action(load("purchase"))
        self.assertEqual(probe.state, MoonlightState.PURCHASE)
        self.assertEqual(action.name, "cancel-purchase")
        self.assertLess(action.point[0], 900, "取消按钮在左侧，绝不能落到购买上")
        # 从选择页「入场」弹出来时，取消之后回的是**选择页**，不是分集页
        self.assertLessEqual({"分集页", "剧场选择页"}, set(action.target_pages))

    def test_claim_reward_never_targets_the_watch_button(self) -> None:
        """领奖点必须落在下载图标上，而不是压在旁边的「进行观览」。"""
        probe = machine(MoonlightState.EPISODE)
        action = probe.next_action(load("episode_reward"))
        self.assertEqual(action.name, "claim-reward")
        # 「进行观览」按钮在 y≈1050..1125；领奖图标在它左边、更靠上。
        self.assertLess(action.point[1], 1000, "领奖点不能落到「进行观览」那一行")
        self.assertEqual(action.target_pages, ("获得奖励弹窗",))


class RewardPopupTests(unittest.TestCase):
    def test_reward_popup_closes_and_returns_to_the_episode(self) -> None:
        probe = machine(MoonlightState.REWARD)
        action = probe.next_action(load("reward_popup"))
        self.assertEqual(action.name, "close-reward")
        self.assertIn("分集页", action.target_pages)


class PurchaseFallbackTests(unittest.TestCase):
    """购买弹窗之后**不能**再回到「入场 → 又点进行观览」的循环。

    这是真机上会遇到的一条：进程跑到一半退出（或这一集的免费额度早就在上一次
    跑掉了），重来时列表上的 Free 角标还在 ⇒ 入场 ⇒ 点「进行观览」⇒ 弹购买。
    如果取消之后只是退回去重新判，就会「取消 → 又入场 → 又弹购买」死循环；
    而点「进行观览」这一步是**会真花钱**的，所以这条必须钉死。
    """

    def test_the_theater_is_abandoned_and_never_entered_again(self) -> None:
        probe = machine(MoonlightState.LIST)
        self.assertEqual(probe.next_action(load("list_free")).name, "enter-theater")

        cancel = probe.next_action(load("purchase"))
        self.assertEqual(cancel.name, "cancel-purchase")
        self.assertTrue(probe.must_leave)

        leave = probe.next_action(load("episode_fresh"))
        self.assertEqual(leave.name, "abandon-theater", "取消之后绝不能再点进行观览")
        self.assertEqual(leave.target_pages, ("剧场选择页",))
        self.assertEqual(probe.completed_cycles, 0, "没看完的一幕不算完成")
        self.assertFalse(probe.must_leave)

        # 退回列表：这张海报的 Free 角标**还在**，但已经处理过 ⇒ 只许往右。
        again = probe.next_action(load("list_free"))
        self.assertTrue(again.name.startswith("next-theater"), again.name)
        # 右边再点一下画面没变 ⇒ 最右端 ⇒ 收工。
        with self.assertRaises(MoonlightCleared):
            probe.next_action(load("list_free"))

    def test_a_watched_theater_is_not_entered_again_either(self) -> None:
        """看完一幕、领完奖退回列表 ⇒ 同一个剧场不再入场（用户口径：一幕一剧场）。"""
        clock = FakeClock()
        probe = machine(MoonlightState.LIST, clock=clock)
        probe.next_action(load("list_free"))
        probe.watched_current = True
        probe.completed_cycles = 0
        self.assertIsNone(probe.next_action(load("episode_claimed")))  # 等橙点的宽限期
        clock.advance(REWARD_GRACE_SECONDS + 0.5)
        self.assertEqual(probe.next_action(load("episode_claimed")).name, "leave-theater")
        self.assertEqual(probe.completed_cycles, 1)
        again = probe.next_action(load("list_free"))
        self.assertTrue(again.name.startswith("next-theater"), again.name)


class BattleTests(unittest.TestCase):
    def test_battle_hands_control_to_the_supervisor(self) -> None:
        probe = machine()
        self.assertIs(probe.observe_page(load("battle")), MoonlightState.BATTLE)
        self.assertIsNone(probe.next_action(load("battle")))

    def test_battle_observation_marks_the_battle_and_the_result(self) -> None:
        probe = machine()
        battle = load("battle")
        observed = probe.observe_battle(battle, None)
        self.assertTrue(observed.battle_visible)
        self.assertFalse(observed.result_visible)
        episode = load("episode_fresh")
        self.assertTrue(probe.observe_battle(episode, None).result_visible)


class FakeRuntime:
    """按顺序吐真夹具帧的假 Runtime。

    ⚠️ 每抓一帧走 10 秒：主循环对「同名动作」有一条重试窗口，而战斗监督那边
    `no_activity_seconds=180` / `absolute_seconds=900` 的看门狗是按 ``now()`` 走的
    —— 步子太小会走不到结算、步子太大又会撞超时，10 秒/帧是两头都安全的值。
    """

    diagnostic_dir = None
    dry_run = False

    def __init__(self, frames: list[np.ndarray], step: float = 10.0) -> None:
        self._frames = frames
        self._index = 0
        self._step = step
        self.now_value = 0.0
        self.clicks: list[tuple[tuple[int, int], str]] = []
        self.messages: list[str] = []

    def now(self) -> float:
        return self.now_value

    def capture(self) -> np.ndarray:
        index = min(self._index, len(self._frames) - 1)
        self._index += 1
        self.now_value += self._step
        return self._frames[index]

    def click(self, point, name) -> None:
        self.clicks.append((point, name))

    def log(self, message: str) -> None:
        self.messages.append(message)

    def save_diagnostic(self, label, screen):
        from pathlib import Path as _Path

        return _Path(label)


def _script(*fixtures: str, repeat: int = 2) -> list[np.ndarray]:
    """每一帧重复 ``repeat`` 次：主循环要**两帧稳定**才肯发动作。"""
    frames: list[np.ndarray] = []
    for name in fixtures:
        frames.extend([load(name)] * repeat)
    return frames


def _runner(runtime: FakeRuntime) -> MoonlightRunner:
    return MoonlightRunner(
        MoonlightStateMachine(machine().templates, initial_state=MoonlightState.ENTRY),
        runtime,
        sleep=lambda _: None,
        poll_seconds=0.0,
    )


def test_runner_walks_a_whole_theater_and_stops_at_the_right_edge():
    """真主循环跑完一整幕，一路往右，最后按「海报没换」收工。

    ⚠️ 只调 ``next_action`` 测不出「判据没接上主循环」这类事故（骑士团捐赠
    2026-09-25 连出两次，都发生在状态机与主循环**之间**）。这里额外守住三件事：
    战斗能交出去又接得回来、「进行观览」只点一次、购买弹窗一次都没出现。
    """
    runtime = FakeRuntime(
        _script(
            "entry_side_story",
            "list_free",
            "episode_fresh",
            "guide",
            "story",
            "story_b",
            "battle",
            # 战斗监督会吃掉「战斗」剩下的帧 + 两帧「剧情页」来确认结算，
            # 所以这里多留一帧剧情：跑完回来还得能接着点字幕。
            "story",
            "story",
            # 战斗打完（或剧情走完）→ CLEAR 过场。**它不会自己消失**：不发动作就会
            # 在这里干等到 ``_TIMEOUT_SECONDS[CLEAR]``（2026-10-17 真机就是这样死的）。
            "clear",
            "episode_reward",
            "reward_popup",
            "episode_claimed",
            "list_no_free",
            # 往右点一下，画面一点没变 ⇒ 右边没有海报了 ⇒ 收工（结论要连续两帧）
            "list_no_free",
            "list_no_free",
            "list_no_free",
        )
    )

    completed = _runner(runtime).run(max_cycles=None)

    names = [name.split("#", 1)[0] for _, name in runtime.clicks]
    assert completed == 1
    assert names == [
        "open-theater",
        "enter-theater",
        "watch-episode",
        "confirm-guide",
        "advance-story",
        "advance-story",
        "advance-story",   # 战斗打完回到剧情页，接着点字幕
        "advance-clear",   # CLEAR 过场点一下就过（干等的那版会死在这里）
        "claim-reward",
        "close-reward",
        "leave-theater",
        "next-theater",
    ]
    assert "cancel-purchase" not in names
    assert any("本周已结束" in message for message in runtime.messages)


def test_runner_never_watches_the_same_episode_twice():
    """第二次实机卡死的那个形态：剧情走完回分集页、**没有橙点**。

    旧逻辑在这里判「没看过」⇒ 再点「进行观览」⇒ 白看第二遍、把免费额度烧光
    ⇒ 第三次弹出「使用剧场门票」⇒ 连点 4 次卡死（14:47~14:50 那次）。
    修好之后：这一幕只点**一次**观览，走完直接返回。
    """
    runtime = FakeRuntime(
        _script(
            "entry_side_story",
            "list_free",
            "episode_fresh",
            "guide",
            "story",
            "story_b",
            # 剧情走完回到分集页，橙点没亮。⚠️ 要给**三帧**：回来的第一帧是
            # 「开始等橙点」（不发动作），等满 REWARD_GRACE_SECONDS 之后才允许撤。
            "episode_claimed",
            "episode_claimed",
            "list_no_free",
            "list_no_free",
            "list_no_free",
            "list_no_free",
        )
    )

    completed = _runner(runtime).run(max_cycles=None)

    names = [name.split("#", 1)[0] for _, name in runtime.clicks]
    assert names.count("watch-episode") == 1, names
    assert names.count("advance-story") == 2, names
    assert "leave-theater" in names, names
    assert "accept-ticket" not in names
    assert "cancel-ticket" not in names
    assert completed == 1


def test_runner_spends_the_ticket_when_the_free_quota_is_gone():
    """免费额度用光 ⇒ 弹「使用剧场门票」⇒ 按用户拍板点确认花掉，继续观览。"""
    runtime = FakeRuntime(
        _script(
            "entry_side_story",
            "list_free",
            "episode_fresh",
            "ticket",            # 点进行观览之后弹出的是花券确认，不是观览指南
            "guide",
            "story",
            "episode_reward",
            "reward_popup",
            "episode_claimed",
            "list_no_free",
            "list_no_free",
            "list_no_free",
            "list_no_free",
        )
    )

    completed = _runner(runtime).run(max_cycles=None)

    names = [name.split("#", 1)[0] for _, name in runtime.clicks]
    assert "accept-ticket" in names, names
    assert names.index("accept-ticket") > names.index("watch-episode")
    assert "cancel-ticket" not in names
    assert "claim-reward" in names
    assert completed == 1


def test_cancelling_a_popup_opened_from_the_list_goes_back_to_the_list():
    """「入场」也会弹购买门票；取消之后回的是**剧场选择页**，不是分集页。

    这是落点写窄最阴的一种：`cancel-purchase` 原来只写了「分集页」，于是取消之后
    主循环认为目标一直没来，把之后每一帧的动作全吞掉 ⇒ 干等 45 秒报
    `等待动作[cancel-purchase]目标画面[分集页]超时`。**真机上看起来就是点了没反应。**
    """
    runtime = FakeRuntime(
        _script(
            "entry_side_story",
            "list_free",
            "purchase",   # 点「入场」弹出了花金币的购买确认
            "list_free",  # 取消 ⇒ 回到选择页（同一个剧场，已进跳过集）
            "list_no_free",  # 往右换一个
            "list_no_free",
            "list_no_free",
        )
    )

    completed = _runner(runtime).run(max_cycles=None)

    names = [name.split("#", 1)[0] for _, name in runtime.clicks]
    # ⚠️ **必须是四步**。只断言前三个「取消」是抓不到这个坑的（实测两种写法都能过）：
    # 落点写窄时，取消之后那一帧的动作被吞掉，路线会**提前**得出「本周已结束」——
    # 少掉的正是这一下 `next-theater`（换下个剧场），也就是后面那些剧场的奖励。
    assert names == [
        "open-theater",
        "enter-theater",
        "cancel-purchase",
        "next-theater",
    ], names
    assert "watch-episode" not in names, "取消之后必须换剧场，不许再点观览"
    assert completed == 0, "这一幕根本没看成，不许记成完成一幕"


def test_cancelling_the_ticket_dialog_from_the_list_goes_back_to_the_list():
    """同一个坑的「花券」版：`cancel-ticket` 也要认得出「回到选择页」。

    确认按钮定位不到时才会走取消（否则按用户拍板就花掉了），所以这里把
    ``ticket_confirm`` 换成噪声 —— 正好也是「券用光了按钮变灰」那种真机形态。
    """
    runtime = FakeRuntime(
        _script(
            "entry_side_story",
            "list_free",
            "ticket",     # 点「入场」弹出了花券确认
            "list_no_free",
            "list_no_free",
            "list_no_free",
        )
    )

    probe = machine()
    probe.templates = _swap_template(probe.templates, "ticket_confirm")
    runner = MoonlightRunner(
        probe, runtime, sleep=lambda _: None, poll_seconds=0.0
    )
    completed = runner.run(max_cycles=None)

    names = [name.split("#", 1)[0] for _, name in runtime.clicks]
    # 同 `cancel-purchase`：少掉末尾的 `next-theater` 就说明取消之后被吞了一帧
    assert names == [
        "open-theater",
        "enter-theater",
        "cancel-ticket",
        "next-theater",
    ], names
    assert "accept-ticket" not in names
    assert completed == 0


def test_clear_retry_window_is_short_but_not_a_wild_tap():
    """CLEAR 的同名重试窗口：2.5 秒。

    默认 45 秒太晚（CLEAR 会一直挂着，等 45 秒才补第二下）；0.5 秒太急
    （过场动画还没走完就点满 4 下，反而被当成「点不动」判死）。
    """
    runner = MoonlightRunner(
        MoonlightStateMachine(machine().templates),
        FakeRuntime([]),
        sleep=lambda _: None,
        poll_seconds=0.5,
    )
    assert runner._action_retry_seconds("advance-clear") == 2.5
    assert runner._action_retry_seconds("open-theater") == 45
    assert runner._action_retry_seconds("advance-story#0a1b2c") == 0.5


def test_runner_stops_immediately_when_the_entry_has_no_free_badge():
    """入口没有绿 F ⇒ 一个点击都不发，直接以「本周已领完」收工。"""
    runtime = FakeRuntime(_script("entry_side_story", repeat=4))
    runner = _runner(runtime)
    runner.machine.templates = _without_free_badge(runner.machine.templates)

    completed = runner.run(max_cycles=None)

    assert completed == 0
    assert runtime.clicks == []


def _swap_template(templates, field: str):
    """把某一枚模板换成随机噪声，用来模拟「这一帧认不出这个锚点」。

    ⚠️ 不能换成全 0 / 纯色：常值模板方差为 0，``TM_CCOEFF_NORMED`` 会退化成
    除以 0 的分支，分数反而接近 1（2026-10-17 第一次写这条测试就踩了）。
    """
    noise = np.random.default_rng(20261017).integers(
        0, 256, getattr(templates, field).shape, dtype=np.uint8
    )
    return type(templates)(
        **{
            **{
                name: getattr(templates, name)
                for name in templates.__dataclass_fields__
                if name != "evidence"
            },
            field: noise,
            "evidence": templates.evidence,
        }
    )


def _without_free_badge(templates):
    """把入口角标换成随机噪声（常值模板方差为 0，相关系数会退化成接近 1）。"""
    return _swap_template(templates, "entry_free")


class CloseOutStoryTests(unittest.TestCase):
    """收尾前「把剧情推完」—— 剧情页不吃 ESC，不推完就回不了大厅。

    2026-10-24 三次实跑全都栽在这儿：剧情页右上角**没有「跳过」**（观览指南原话
    「月光剧场的故事情无法跳过」），而收尾只会按 ESC ⇒ 连按两次无效 ⇒ 报
    ``return_home_v2_esc_no_effect``。
    """

    @staticmethod
    def _runner_at(state: MoonlightState, runtime: FakeRuntime) -> MoonlightRunner:
        return MoonlightRunner(
            MoonlightStateMachine(machine().templates, initial_state=state),
            runtime,
            sleep=lambda _seconds: None,
            poll_seconds=0.0,
        )

    def test_it_clicks_the_story_until_the_page_stops_being_story(self) -> None:
        runtime = FakeRuntime([load("story"), load("story_b"), load("episode_fresh")])
        self._runner_at(MoonlightState.STORY, runtime)._close_out()

        names = [name for _point, name in runtime.clicks]
        self.assertEqual(len(names), 2, f"离开剧情页就该停，实际点了 {names}")
        self.assertTrue(
            all(name.startswith("advance-story") for name in names),
            f"收尾阶段只许点字幕：{names}",
        )

    def test_it_never_touches_the_screen_when_not_on_the_story_page(self) -> None:
        """正常跑完（停在分集页）时不该多任何一次点击。"""
        runtime = FakeRuntime([load("episode_fresh")])
        self._runner_at(MoonlightState.EPISODE, runtime)._close_out()
        self.assertEqual(runtime.clicks, [])


if __name__ == "__main__":
    unittest.main()