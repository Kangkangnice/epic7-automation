"""社区签到路线状态机的离线验收。

覆盖：页面 → 动作的映射、兑换清单的决策、底部绿按钮的逐帧定位、
三条每日任务的脚本与对账、签到两态的读数，以及**发送层**那两条
（滑动必须走 ``runtime.swipe``；换向那一两秒取不到图必须**有界等待**、
不许秒失败收尾）。后者是主循环「取图 / 发动作」那两行没有兜底的地方，
只能靠 Runner 覆写 —— 所以要在离线就把「脚本 → 动作 → 真的走对通道」整条链钉住，
不能只断言动作字段（2026-10-07：动作字段写着 ``swipe_end``，发出去的却是点击）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import unittest
import unittest.mock

import cv2
import numpy as np

from auto_game_unified.core.portrait import OrientationError
from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.games.epic7 import community as cm
from auto_game_unified.games.epic7 import community_pages as cp


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_community"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "community"


def fixture(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    if image is None:
        raise AssertionError(f"缺夹具 {name}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class CommunityRedeemPlanTests(unittest.TestCase):
    """兑换清单的决策 —— 这块是真机数据最全、最该先钉死的。"""

    @classmethod
    def setUpClass(cls):
        cls.templates, cls.glyphs = cm.build_screen_reader(TEMPLATES)

    def test_reads_the_real_exchange_page(self):
        readout = cm.read_exchange(fixture("exchange_after_redeem_live_20261006"), self.glyphs)
        self.assertEqual(readout.balance, 880)
        self.assertEqual(readout.limits[1], (1, 2))
        self.assertEqual(readout.limits[2], (1, 1))
        self.assertEqual(readout.limits[3], (0, 1))
        self.assertEqual(readout.limits[4], (1, 1))

    def test_picks_the_card_that_is_still_short_of_its_daily_limit(self):
        """兑换后那一帧：两件强化石已满，**行动力还差一次** ⇒ 必须挑卡 1。"""
        readout = cm.read_exchange(fixture("exchange_after_redeem_live_20261006"), self.glyphs)
        step = cm.plan_redeem(readout)
        self.assertEqual(step.kind, "open_card")
        self.assertEqual(step.card, 1)
        self.assertEqual(step.point, cm.CARD_POINTS[1])

    def test_stops_when_the_plan_is_full(self):
        full = cm.ExchangeReadout(
            balance=999,
            balance_score=1.0,
            limits={1: (2, 2), 2: (1, 1), 3: (0, 1), 4: (1, 1)},
        )
        self.assertEqual(cm.plan_redeem(full).kind, "done")

    def test_stops_cleanly_when_points_are_short(self):
        """余额不够下一件 ⇒ 停（不是故障，是正常业务退出）。"""
        poor = cm.ExchangeReadout(
            balance=10,
            balance_score=1.0,
            limits={1: (1, 2), 2: (1, 1), 3: (0, 1), 4: (1, 1)},
        )
        step = cm.plan_redeem(poor)
        self.assertEqual(step.kind, "insufficient")
        self.assertTrue(step.is_terminal)

    def test_refuses_to_decide_when_a_limit_is_unreadable(self):
        """限购读不出来 ⇒ 报 blocked。**不许默认成 0**（会重复兑换）。"""
        blind = cm.ExchangeReadout(
            balance=999,
            balance_score=1.0,
            limits={1: None, 2: (1, 1), 3: (0, 1), 4: (1, 1)},
        )
        step = cm.plan_redeem(blind)
        self.assertEqual(step.kind, "blocked")
        self.assertEqual(step.card, 1)

    def test_refuses_to_decide_when_the_balance_is_unreadable(self):
        blind = cm.ExchangeReadout(
            balance=None,
            balance_score=0.0,
            limits={1: (0, 2), 2: (0, 1), 3: (0, 1), 4: (0, 1)},
        )
        self.assertEqual(cm.plan_redeem(blind).kind, "blocked")

    def test_empty_shelf_asks_for_a_retry(self):
        self.assertEqual(cm.plan_redeem(None).kind, "retry_empty")

    def test_flags_a_plan_that_disagrees_with_the_game(self):
        """游戏限购比清单目标还小 ⇒ 两边对不上，必须报出来而不是硬点。"""
        mismatch = cm.ExchangeReadout(
            balance=999,
            balance_score=1.0,
            limits={1: (1, 1), 2: (1, 1), 3: (0, 1), 4: (1, 1)},
        )
        step = cm.plan_redeem(mismatch)
        self.assertEqual(step.kind, "blocked")
        self.assertIn("对不上", step.reason)

    def test_plan_targets_are_daily_limits_not_one_each(self):
        """清单的目标是**每日限购上限**：行动力要 2 次。这是用户纠正过的口径。"""
        by_card = {target.card: target for target in cm.REDEMPTION_PLAN}
        self.assertEqual(by_card[1].daily_limit, 2)
        self.assertEqual(by_card[2].daily_limit, 1)
        self.assertEqual(by_card[4].daily_limit, 1)
        # 金币卡刻意不在清单里
        self.assertNotIn(3, by_card)


class GreenButtonLocatorTests(unittest.TestCase):
    """底部绿按钮**必须每帧现量** —— 它在两个页面上差 49px。"""

    def test_finds_the_button_on_item_detail(self):
        point = cm.locate_green_button(fixture("item_detail_live_20261006"))
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 520, delta=8)
        self.assertAlmostEqual(point[1], 1795, delta=8)

    def test_finds_the_button_on_order_confirm_at_a_different_height(self):
        """订单确认页上按钮**重排**过 —— 沿用商品详情页的位置就会点空。

        实测两页差 49px（1795 vs 1746），这正是「量到 1795、点下去落空、白等 40 秒」
        那个坑的根因。
        """
        point = cm.locate_green_button(fixture("order_confirm_live_20261006"))
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 520, delta=8)
        self.assertAlmostEqual(point[1], 1746, delta=8)
        self.assertNotAlmostEqual(point[1], 1795, delta=20)

    def test_finds_nothing_once_the_button_is_disabled(self):
        """点过之后按钮变禁用暗绿 ⇒ 找不到。这是**特性**：不许再点第二次。"""
        self.assertIsNone(cm.locate_green_button(fixture("redeem_success_live_20261006")))


class CommunityStateMachineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates, cls.glyphs = cm.build_screen_reader(TEMPLATES)

    def machine(self, **kwargs) -> cm.CommunityStateMachine:
        return cm.CommunityStateMachine(self.templates, self.glyphs, **kwargs)

    # ---- 入口（横屏） ----

    def test_enters_the_community_from_the_landscape_page(self):
        """入口那一下发生在**横屏**链路上，不能因为「不是竖屏」就不动。"""
        landscape = np.zeros((1132, 1982, 3), np.uint8)
        action = self.machine().next_action(landscape)
        self.assertIsNotNone(action)
        self.assertEqual(action.name, "enter_community")
        self.assertEqual(action.point, cm.WEB_COMMUNITY_ENTRY)

    def test_waits_on_an_unexpected_landscape_frame_after_entry(self):
        """已经进过社区之后再来一帧横屏（转屏途中）⇒ 等，不点。"""
        landscape = np.zeros((1132, 1982, 3), np.uint8)
        machine = self.machine(state=cm.CommunityState.FEED)
        self.assertIsNone(machine.next_action(landscape))

    # ---- 兑换流程 ----

    def test_opens_the_card_that_still_has_room(self):
        machine = self.machine(state=cm.CommunityState.EXCHANGE)
        action = machine.next_action(fixture("exchange_after_redeem_live_20261006"))
        self.assertEqual(action.name, "open_item")
        self.assertEqual(action.point, cm.CARD_POINTS[1])
        self.assertEqual(action.source_page, "exchange_center")
        self.assertEqual(action.target_pages, ("item_detail",))

    def test_leaves_the_empty_shelf_instead_of_poking_at_it(self):
        machine = self.machine(state=cm.CommunityState.EXCHANGE)
        action = machine.next_action(fixture("exchange_center_live_20261006"))
        self.assertEqual(action.name, "leave_empty_exchange")
        self.assertEqual(action.point, cm.EXCHANGE_BACK)

    def test_item_detail_clicks_the_button_it_just_located(self):
        machine = self.machine(state=cm.CommunityState.EXCHANGE)
        action = machine.next_action(fixture("item_detail_live_20261006"))
        self.assertEqual(action.name, "open_order_confirm")
        self.assertAlmostEqual(action.point[1], 1795, delta=8)

    def test_order_confirm_clicks_the_button_at_the_current_height(self):
        machine = self.machine(state=cm.CommunityState.ITEM_DETAIL)
        action = machine.next_action(fixture("order_confirm_live_20261006"))
        self.assertEqual(action.name, "confirm_redeem")
        self.assertAlmostEqual(action.point[1], 1746, delta=8)
        self.assertEqual(action.target_pages, ("redeem_done", "item_detail"))

    def test_success_dialog_is_acknowledged(self):
        machine = self.machine(state=cm.CommunityState.ORDER_CONFIRM)
        action = machine.next_action(fixture("redeem_success_live_20261006"))
        self.assertEqual(action.name, "ack_redeem_done")
        self.assertEqual(action.point, cm.REDEEM_CONFIRM)

    def test_raises_a_business_stop_when_points_run_out(self):
        """余额不够 ⇒ 走「资源耗尽」通道（退出码 2），**不是故障**。

        用替换读数的方式测：真机夹具余额是 880（够），要构造「不够」得把读数换掉。

        ⚠️ 这条用例钉的是**时序**，不是「抛不抛」：余额不够时人还停在社区的竖屏
        页面里，当场抛出去，收尾那步就会拿横屏通道去取竖屏画面（直接抛
        「render size changed」），而且模拟器会被留在竖屏。所以正确次序是
        **先按正常出口退出社区 → 等转回横屏 → 才抛**。
        """
        machine = self.machine(state=cm.CommunityState.EXCHANGE)
        poor = cm.ExchangeReadout(
            balance=5,
            balance_score=1.0,
            limits={1: (1, 2), 2: (1, 1), 3: (0, 1), 4: (1, 1)},
        )
        with unittest.mock.patch.object(cm, "read_exchange", return_value=poor):
            # ① 兑换中心：不抛，退回信息流（并记下停止原因）
            action = machine.next_action(fixture("exchange_after_redeem_live_20261006"))
            self.assertEqual(action.name, "leave_exchange")
            self.assertIn("不够", machine.stop_reason)
            # ② 信息流：关掉社区（照样不抛）
            closing = machine.next_action(fixture("feed_list_live_20261006"))
            self.assertEqual(closing.name, "close_community")
            self.assertEqual(closing.point, cm.FEED_CLOSE)
            # ③ 画面转回横屏那一帧：这时才抛，且必须是「资源耗尽」家族
            landscape = np.zeros((1132, 1982, 3), np.uint8)
            with self.assertRaises(cm.RedeemBudgetExhausted) as ctx:
                machine.next_action(landscape)
        self.assertIn("不够", str(ctx.exception))
        self.assertEqual(cm.RedeemBudgetExhausted.stop_label, "积分不足")
        # 退出码 2 靠的是**继承关系**：挂在 RuntimeError 下会被当成「画面认不出」，
        # 白等一轮超时再报退出码 1（故障）。
        self.assertIsInstance(ctx.exception, cm.ResourceExhausted)

    # ---- 任务枢纽 ----

    def test_tasks_all_done_goes_to_the_exchange(self):
        machine = self.machine(state=cm.CommunityState.FEED)
        action = machine.next_action(fixture("tasks_all_done_live_20261006"))
        self.assertEqual(action.name, "goto_exchange")
        self.assertEqual(action.point, cm.TASKS_GOTO_EXCHANGE)
        self.assertTrue(machine.progress.tasks_all_done())

    def test_pending_task_starts_the_right_row(self):
        """三条任务的脚本齐了 ⇒ 点**那一行**的「去完成」，并把脚本从头排上。"""
        machine = self.machine(state=cm.CommunityState.FEED)
        action = machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        self.assertEqual(action.name, "start_task")
        self.assertEqual(action.point, (cm.TASKS_BUTTON_X, cm.TASK_BUTTON_Y["browse"]))
        self.assertEqual(machine.active_task, "browse")
        self.assertEqual(machine.task_step, 0)

    def test_task_script_walks_the_pages_then_returns_to_reconcile(self):
        """脚本按**页**推进：信息流点开帖子 → 帖子详情返回 → 经兑换中心回我的任务。

        ⚠️ 最后一步必须是「回我的任务对账」而不是「再排一遍」：任务成败只有页面上那个
        ``x/3`` 说得准，脚本跑完不等于计数涨了。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        opened = machine.next_action(fixture("feed_before_signin_live_20261007"))
        self.assertEqual(opened.name, "task_browse_1")
        self.assertEqual(opened.point, cm.FEED_FIRST_POST)
        back = machine.next_action(fixture("post_detail_live_20261006"))
        self.assertEqual(back.name, "task_browse_2")
        self.assertEqual(back.point, cm.POST_BACK)
        home = machine.next_action(fixture("feed_before_signin_live_20261007"))
        self.assertEqual(home.name, "back_to_tasks_via_exchange")
        self.assertTrue(machine.via_exchange)
        # 脚本跑完但**还没对账** ⇒ active_task 必须还在，否则对账就认不出是哪一条
        self.assertEqual(machine.active_task, "browse")
        detour = machine.next_action(fixture("exchange_before_redeem_live_20261007"))
        self.assertEqual(detour.name, "goto_tasks_card")
        self.assertEqual(detour.point, cm.EXCHANGE_GAIN_POINTS_CARD)
        machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        self.assertEqual(machine.active_task, "browse")

    def test_the_return_step_does_not_accept_its_own_page_as_an_exit(self):
        """出口验收集合里**不许含来源页** —— 含了就等于「点空了也算完成」（2026-10-07 修）。

        实跑形态：任务「看完退回信息流」那一步把本页 ``post_detail`` 写进目标集合 ⇒
        **点空了也判完成**（白等 33 秒）；而真退回信息流时又因为集合里没有
        ``feed_home``，被判「转场超时」⇒ **任务明明做成了、整条路线却失败**。
        成熟路线（sanctuary / hero_synthesis）的 ``target_pages`` 一律只写
        「点了之后会到哪」，从不包含来源页。
        """
        machine = self.machine(state=cm.CommunityState.POST_DETAIL)
        machine.active_task = "browse"
        machine.task_step = 1  # 「看完退回信息流」那一步（POST_BACK）
        action = machine._drive_task(
            fixture("post_detail_live_20261006"),
            cp.PageJudgement("post_detail", 1.0, ()),
        )
        self.assertEqual(action.name, "task_browse_2")
        self.assertNotIn(
            "post_detail",
            tuple(action.target_pages),
            "出口集合含来源页：点空了也判完成，分不出「点了没生效」与「点了生效了」",
        )
        self.assertIn("feed_home", tuple(action.target_pages))

    def test_task_retries_are_bounded_then_declared_impossible(self):
        """这一行没变成「已完成」就重来；连试 ``TASK_ATTEMPT_LIMIT`` 遍 ⇒ 记一笔「今天做不成」并往下走。

        ⚠️ 必须**有上限**：判据失灵时「试到成功为止」会无声转到状态超时，
        日志里只剩一句「页面识别超时」，看不出是哪条任务在磨。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        tasks = fixture("tasks_one_browse_done_live_20261006")
        feed = fixture("feed_before_signin_live_20261007")
        post = fixture("post_detail_live_20261006")
        exchange = fixture("exchange_before_redeem_live_20261007")

        def run_one_round() -> str:
            """跑完一轮：脚本两步 → 经兑换中心回我的任务 → 返回对账那一帧的动作名。"""
            machine.next_action(feed)      # 脚本第 1 步（点开帖子）
            machine.next_action(post)      # 脚本第 2 步（返回）
            machine.next_action(feed)      # 脚本跑完 ⇒ 回兑换中心
            machine.next_action(exchange)  # 路过兑换中心 ⇒ 点「获取积分卡」
            return machine.next_action(tasks).name

        machine.next_action(tasks)  # 排上「浏览帖子」
        for _ in range(cm.TASK_ATTEMPT_LIMIT - 1):
            self.assertEqual(run_one_round(), "start_task")   # 这一行还没变成「已完成」⇒ 原地再来
            self.assertIn("再来一遍", machine.last_reason)
        # 最后一轮：到上限 ⇒ 记一笔「今天做不成」，挑下一条待办（这一帧里是「分享帖子」）
        self.assertEqual(run_one_round(), "start_task")
        self.assertIn("browse", machine.stuck_tasks)
        self.assertIn("做不成", machine.last_reason)
        self.assertEqual(machine.active_task, "share")
        self.assertEqual(
            machine.task_attempts["browse"], cm.TASK_ATTEMPT_LIMIT
        )

    def test_stuck_task_still_lets_the_route_finish(self):
        """有一条今天做不成 ⇒ 路线照样要能收工（否则会永远在信息流/任务页之间打转）。"""
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.progress.tasks = {"browse": "todo", "like": "done", "share": "done"}
        machine.progress.redeemed = {1: 2, 2: 1, 4: 1}
        self.assertFalse(machine._finishing())
        machine.stuck_tasks.add("browse")
        self.assertTrue(machine._finishing())

    def test_task_step_that_lands_on_the_wrong_page_does_not_click_blind(self):
        """脚本要求停在 A 页、实际在 B 页 ⇒ 先回信息流，**不许拿错页的坐标硬点**。"""
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        # 本应在信息流点帖子，却停在帖子详情（上一下没点中/多点了一下）
        action = machine.next_action(fixture("post_detail_live_20261006"))
        self.assertEqual(action.name, "back_to_tasks_from_post")
        self.assertEqual(action.point, cm.POST_BACK)

    def test_like_button_is_a_toggle_and_is_read_before_clicking(self):
        """卡片那颗 👍 是**开关**：已绿再点会取消点赞 ⇒ 开点前必须先读颜色。

        2026-10-07 真机实测：`act01` 就是把一张已绿的卡片点灰了，计数白掉一次。
        """
        before = fixture("feed_before_signin_live_20261007")
        self.assertIsInstance(cm.card_like_is_on(before), bool)
        # 裁掉画面 ⇒ 读不出，必须给 None 而不是 False（False 会被当成「灰色的，可以点」）
        self.assertIsNone(cm.card_like_is_on(before[:100, :100]))

    # ---- 点赞脚本的点前预检（2026-10-07 加）----
    #
    # ⚠️ 上面那条只验了 ``card_like_is_on`` **这个纯函数**，没验「脚本真的会调它」——
    #    事实上它当时**一个调用点都没有**，纯函数测得再绿也保护不了任何东西。
    #    下面这三条把「脚本真的先读颜色」钉住。

    @staticmethod
    def _painted_liked_card() -> np.ndarray:
        """一张「那颗 👍 已经绿了」的信息流帧（把按钮那块涂成点赞态的绿色）。"""
        frame = fixture("feed_before_signin_live_20261007").copy()
        x, y, w, h = cm.FEED_CARD_LIKE_BOX
        frame[y : y + h, x : x + w] = (40, 190, 90)
        return frame

    def _like_machine_at_the_button(self) -> cm.CommunityStateMachine:
        """把状态机直接摆到「正在跑点赞、脚本第 1 步（该点 👍 了）」。

        ⚠️ 为什么不走 ``next_action(tasks_page)`` 去排上它：竖屏口径下**没有一张
        「点赞未完成」的任务页夹具**（``tasks_fresh`` 是另一种口径，见
        ``test_community_pages`` 里的口径守卫），而 ``tasks_one_browse_done``
        那一帧的点赞行读出来**已经是「已完成」**。所以这里直接摆状态 ——
        被测的是 ``_drive_task`` 的点前预检，不是「挑哪条任务」那一步。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.active_task = "like"
        machine.task_step = 1  # 第 0 步是「往下滑一次」，第 1 步才是那颗 👍
        return machine

    def test_like_script_swipes_again_when_the_button_is_already_green(self):
        """已经是绿的 ⇒ **不许点**，改滑一次换一张卡片。

        断言的是「依据」：动作名是再滑一次、``task_step`` **没有**推进
        （推进了就等于把这遍脚本当成点过了）。
        """
        machine = self._like_machine_at_the_button()

        action = machine.next_action(self._painted_liked_card())

        self.assertEqual(action.name, "task_like_reswipe")
        # ⚠️ 这一步是**滑动**，不是「在终点点一下」：point 是起点、swipe_end 是终点。
        # 旧断言是 ``point == FEED_TASK_SCROLL_END``——它保护的是「滑动被当点击发出」
        # 这个错误行为（点在信息流中部会点开一张帖子，于是下一步对不上页、本遍作废）。
        self.assertEqual(action.point, cm.FEED_TASK_SCROLL_START)
        self.assertEqual(action.swipe_end, cm.FEED_TASK_SCROLL_END)
        self.assertEqual(machine.task_step, 1, "还没点下去，不该算完成这一步")
        self.assertEqual(machine.like_reswipes, 1)

    def test_like_script_never_taps_when_the_colour_is_unreadable(self):
        """读不出颜色 ⇒ **不许盲点**（认不出就说认不出，别拿「也许没点过」当答案）。"""
        machine = self._like_machine_at_the_button()

        with unittest.mock.patch.object(cm, "card_like_is_on", return_value=None):
            action = machine.next_action(fixture("feed_before_signin_live_20261007"))

        self.assertNotEqual(action.name, "task_like_2")
        self.assertEqual(action.name, "back_to_tasks_via_exchange")
        self.assertIn("不敢盲点", action.reason)
        self.assertEqual(machine.task_step, 1)

    def test_like_script_gives_up_instead_of_swiping_forever(self):
        """一路都是已点过的卡片 ⇒ 滑够 ``LIKE_RESWIPE_LIMIT`` 次就收手（本遍作废）。

        ⚠️ 必须有上限：否则「全是已点过的卡片」会把主循环卡在信息流里空转到超时。
        """
        machine = self._like_machine_at_the_button()

        names = [
            machine.next_action(self._painted_liked_card()).name
            for _ in range(cm.LIKE_RESWIPE_LIMIT + 1)
        ]

        self.assertEqual(
            names[: cm.LIKE_RESWIPE_LIMIT],
            ["task_like_reswipe"] * cm.LIKE_RESWIPE_LIMIT,
        )
        self.assertEqual(names[cm.LIKE_RESWIPE_LIMIT], "back_to_tasks_via_exchange")
        self.assertEqual(machine.like_reswipes, cm.LIKE_RESWIPE_LIMIT)

    def test_task_retry_budget_leaves_room_for_a_missed_tap(self):
        """上限必须**大于**「任务要求的次数」，否则点空一次就等于判死。

        浏览 / 点赞一天各要 3 次，而对账只在「这一行还没变成『已完成』」时才记一遍
        ⇒ 上限等于 3 时**恰好要求每遍都成功**：中间点空一次（点歪、或者那颗 👍
        本来就是绿的、点赞被取消），第 3 次对账就撞上限 ⇒ 记「今天做不成」，
        **哪怕计数已经 2/3、再来一次就成了**（2026-10-07 修）。

        这里用「第 4 遍才成」来钉住「有容错」这件事：
        前 3 遍都读到「未完成」，第 4 遍读到「已完成」⇒ 必须判成、**不许**判死。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        not_done = fixture("tasks_one_browse_done_live_20261006")
        all_done = fixture("tasks_all_done_live_20261006")
        feed = fixture("feed_before_signin_live_20261007")
        post = fixture("post_detail_live_20261006")
        exchange = fixture("exchange_before_redeem_live_20261007")

        def run_one_round(tasks_frame) -> str:
            machine.next_action(feed)
            machine.next_action(post)
            machine.next_action(feed)
            machine.next_action(exchange)
            return machine.next_action(tasks_frame).name

        machine.next_action(not_done)  # 排上「浏览帖子」
        for _ in range(3):
            self.assertEqual(run_one_round(not_done), "start_task")
            self.assertNotIn("browse", machine.stuck_tasks, "第 4 遍之前不许判死")
        # 第 4 遍：这一行终于变成「已完成」⇒ 成了。
        self.assertNotEqual(run_one_round(all_done), "start_task")
        self.assertNotIn("browse", machine.stuck_tasks)
        self.assertIn("做成了", machine.last_reason)

    def test_retry_log_does_not_claim_the_counter_did_not_move(self):
        """日志别写「计数没动」—— 对账读的是**按钮**，3 次制的计数每遍都在动。

        照这句话排错会被带偏（2026-10-07 修正措辞）。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        machine.next_action(fixture("feed_before_signin_live_20261007"))
        machine.next_action(fixture("post_detail_live_20261006"))
        machine.next_action(fixture("feed_before_signin_live_20261007"))
        machine.next_action(fixture("exchange_before_redeem_live_20261007"))
        machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        self.assertNotIn("计数没动", machine.last_reason)
        self.assertIn("还没变成", machine.last_reason)

    # ---- 信息流 / 签到 ----

    def test_signin_state_reads_colour_not_shape(self):
        """「今天签没签」只看那块的**饱和度**：未签到 ≈49、已签到 =0，中间没有灰带。"""
        self.assertEqual(
            cm.feed_signin_state(fixture("feed_before_signin_live_20261007")), "todo"
        )
        self.assertEqual(
            cm.feed_signin_state(fixture("feed_after_signin_live_20261007")), "done"
        )
        self.assertEqual(
            cm.feed_signin_state(fixture("feed_list_live_20261006")), "done"
        )

    def test_signin_state_is_unknown_when_the_patch_is_dimmed(self):
        """弹窗的压暗背板会把彩色图标也压成 0 饱和度 ⇒ 必须报「不知道」，不许读成「已签」。

        少这道亮度闸门，签到成功弹窗一出现就会被读成「今天已签」——**当天直接漏签**。
        """
        popup = fixture("signin_success_live_20261007")
        self.assertEqual(cm.feed_signin_state(popup), "unknown")
        self.assertEqual(cm.feed_signin_state(popup[:50, :50]), "unknown")

    def test_feed_clicks_signin_when_the_icon_is_colourful(self):
        """未签到 ⇒ 点「每日签到」图标；点完只等（弹窗实测最慢 74 秒才出）。"""
        machine = self.machine(state=cm.CommunityState.FEED)
        action = machine.next_action(fixture("feed_before_signin_live_20261007"))
        self.assertEqual(action.name, "tap_signin")
        self.assertEqual(action.point, cm.FEED_SIGNIN_CLICK)
        self.assertTrue(machine.signin_clicked)
        # 点了之后还停在信息流（弹窗还没出）⇒ **不许再点一次**，只等
        self.assertIsNone(machine.next_action(fixture("feed_before_signin_live_20261007")))

    def test_signin_popup_is_acknowledged_before_anything_else(self):
        """弹窗是模态的：不先关掉，后面点的每一处都会被它吃掉。"""
        machine = self.machine(state=cm.CommunityState.FEED)
        action = machine.next_action(fixture("signin_success_live_20261007"))
        self.assertEqual(action.name, "ack_signin_done")
        self.assertEqual(action.point, cm.SIGNIN_POPUP_CLOSE)

    def test_signed_in_feed_goes_to_tasks_through_the_exchange(self):
        """已签到 ⇒ 去我的任务。⚠️ 路线是「兑换图标 → 兑换中心 → 获取积分卡」。

        底栏那个「我的」**不是**我的任务，是社区个人主页（2026-10-07 实测点过去
        得到一张认不出的页面），所以这一步绝不能再用 ``FEED_TAB_MINE``。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        action = machine.next_action(fixture("feed_after_signin_live_20261007"))
        self.assertEqual(action.name, "goto_tasks_via_exchange")
        self.assertEqual(action.point, cm.FEED_ICON_EXCHANGE)
        self.assertNotEqual(action.point, cm.FEED_TAB_MINE)
        self.assertTrue(machine.via_exchange)

    # ---- 网络异常 ----

    def test_network_error_leaves_the_community_to_reenter(self):
        """H5 死了（不会自愈）⇒ 关掉社区、重进一次。

        状态必须回到 ``WEB_ENTRY``（而不是停在 BLOCKED）：那一帧之后模拟器转回横屏，
        状态机要能**自动重进**；停在 BLOCKED 会一直等到超时。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        action = machine.next_action(fixture("network_error_live_20261006"))
        self.assertEqual(action.name, "logout_community")
        self.assertEqual(action.point, cm.FEED_CLOSE)
        self.assertEqual(machine.state, cm.CommunityState.WEB_ENTRY)

    def test_network_error_does_not_ping_pong_forever(self):
        """退出去重进之后还是网络异常 ⇒ 那是在乒乓，转两次就停。

        ⚠️ 主循环那本「同一动作 4 次」的账**记不到它**：来回是
        `logout_community` / `enter_community` 两个动作名，每次都是新动作。
        所以必须自己记一笔账，否则会一直转下去（真断网时就是这样）。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        frame = fixture("network_error_live_20261006")
        for _ in range(cm.NETWORK_RETRY_LIMIT):
            self.assertEqual(machine.next_action(frame).name, "logout_community")
        with self.assertRaises(RuntimeError) as ctx:
            machine.next_action(frame)
        self.assertIn("网络异常", str(ctx.exception))
        self.assertEqual(machine.state, cm.CommunityState.BLOCKED)

    # ---- 认不出就不动 ----

    def test_unrecognized_screen_raises_instead_of_clicking(self):
        blank = np.full((1920, 1080, 3), 128, np.uint8)
        machine = self.machine(state=cm.CommunityState.FEED)
        with self.assertRaises(cm.UnrecognizedCommunityScreen):
            machine.next_action(blank)

    # ---- 预览不许改状态 ----

    def test_preview_restores_state(self):
        machine = self.machine(state=cm.CommunityState.EXCHANGE)
        before = (machine.state, dict(machine.progress.redeemed))
        machine.preview(fixture("exchange_after_redeem_live_20261006"))
        self.assertEqual((machine.state, dict(machine.progress.redeemed)), before)

    # ---- 动作契约 ----

    def test_every_action_carries_an_exit_check(self):
        """新路线准入：每个动作都要有「去处」或「页内依据」。"""
        frames = [
            ("exchange_after_redeem_live_20261006", cm.CommunityState.EXCHANGE),
            ("exchange_center_live_20261006", cm.CommunityState.EXCHANGE),
            ("item_detail_live_20261006", cm.CommunityState.EXCHANGE),
            ("order_confirm_live_20261006", cm.CommunityState.ITEM_DETAIL),
            ("redeem_success_live_20261006", cm.CommunityState.ORDER_CONFIRM),
            ("tasks_all_done_live_20261006", cm.CommunityState.FEED),
            ("network_error_live_20261006", cm.CommunityState.FEED),
        ]
        for frame_name, state in frames:
            with self.subTest(frame=frame_name):
                machine = self.machine(state=state)
                action = machine.next_action(fixture(frame_name))
                self.assertTrue(action.source_page, "动作缺 source_page")
                self.assertTrue(
                    action.target_pages or action.in_page_evidence,
                    "动作既没写 target_pages 也没写 in_page_evidence",
                )

    def test_action_points_stay_inside_the_portrait_canvas(self):
        frames = [
            ("exchange_after_redeem_live_20261006", cm.CommunityState.EXCHANGE),
            ("exchange_center_live_20261006", cm.CommunityState.EXCHANGE),
            ("item_detail_live_20261006", cm.CommunityState.EXCHANGE),
            ("order_confirm_live_20261006", cm.CommunityState.ITEM_DETAIL),
            ("redeem_success_live_20261006", cm.CommunityState.ORDER_CONFIRM),
            ("tasks_all_done_live_20261006", cm.CommunityState.FEED),
            ("network_error_live_20261006", cm.CommunityState.FEED),
        ]
        width, height = cp.PORTRAIT_CANVAS
        for frame_name, state in frames:
            with self.subTest(frame=frame_name):
                machine = self.machine(state=state)
                action = machine.next_action(fixture(frame_name))
                x, y = action.point
                self.assertTrue(0 <= x < width and 0 <= y < height, f"{action.name} {action.point} 越界")


class CommunityEntryAndCloseTests(unittest.TestCase):
    """进社区 / 出社区这两下的**时序**：两下都必须等画面真的转过去。

    这两下是整条路线里唯一会改变屏幕方向的动作 —— 方向一变，取图与点击的坐标系
    整个换掉（横屏 1982x1132 vs 竖屏 1080x1920）。所以「什么时候算这一下做完了」
    必须以**画面转过去**为准，不能以「点过了」为准。
    """

    LANDSCAPE = np.zeros((1132, 1982, 3), np.uint8)
    PORTRAIT = np.zeros((1920, 1080, 3), np.uint8)

    @classmethod
    def setUpClass(cls):
        cls.templates, cls.glyphs = cm.build_screen_reader(TEMPLATES)

    def machine(self, **kwargs) -> cm.CommunityStateMachine:
        return cm.CommunityStateMachine(self.templates, self.glyphs, **kwargs)

    def test_entry_click_repeats_until_the_screen_turns(self):
        """点了入口却还是横屏 ⇒ 那一下没点中，再点一次（上限由主循环给）。"""
        machine = self.machine()
        first = machine.next_action(self.LANDSCAPE)
        self.assertEqual(first.name, "enter_community")
        self.assertEqual(first.point, cm.WEB_COMMUNITY_ENTRY)
        self.assertEqual(machine.state, cm.CommunityState.ENTERING)
        again = machine.next_action(self.LANDSCAPE)
        self.assertEqual(again.name, "enter_community")

    def test_a_portrait_frame_mid_entry_goes_back_to_page_decisions(self):
        """转过去之后的帧照常按页面判：不能因为「还在 ENTERING」就发呆。"""
        machine = self.machine(state=cm.CommunityState.ENTERING)
        action = machine.next_action(fixture("tasks_all_done_live_20261006"))
        self.assertEqual(action.name, "goto_exchange")

    def test_a_blank_portrait_frame_mid_entry_waits_instead_of_failing(self):
        """**转成竖屏了、但社区页面还没加载出来** ⇒ 只等，不判失败。

        ⚠️ 这是 2026-10-07 补的第三个缺口，也是「点完游戏社区就出事」那条的
        真正机制。刚进竖屏的一两秒里 H5 还在加载（实测网页活动列表那个 H5
        要 29 秒），画面是 1080x1920 但内容一片白 —— 判不出 ``feed_home``。
        旧代码在这里直接抛「认不出画面」⇒ 主循环按**失败**收尾 ⇒
        **一次正常的加载被判成「点坏了」**。

        规范里那一档叫「来源已离开、目标未稳 ⇒ 只等」。这里断言它真的只等。
        """
        machine = self.machine(state=cm.CommunityState.ENTERING)
        blank = np.full((1920, 1080, 3), 255, np.uint8)
        self.assertIsNone(
            machine.next_action(blank),
            "转场中认不出页面应当只等；抛异常会被主循环当成失败收尾",
        )
        self.assertIn("还没加载", machine.last_reason)
        # ⚠️ 关键：状态**不许**被这一帧推进 —— 否则下一步就会当成已经进社区，
        #    拿着一个还没加载出来的页面开始点东西。
        self.assertEqual(machine.state, cm.CommunityState.ENTERING)
        self.assertEqual(machine.completed_cycles, 0)

    def test_the_entry_only_counts_as_done_once_the_feed_is_recognised(self):
        """入口的出口标志 = **方向 + 画幅 + feed_home**，少一样都不算走通。

        断言的是「走到 feed_home 之后状态才推进」这条因果，而不是某个返回值 ——
        因为出口标志是 ``target_pages=("feed_home",)`` 这个契约字段在起作用。
        """
        machine = self.machine(state=cm.CommunityState.ENTERING)
        action = machine.next_action(fixture("feed_list_live_20261006"))
        self.assertEqual(machine.state, cm.CommunityState.FEED)
        self.assertIsNotNone(action)
        # 契约字段本身也要钉住：出口只认 feed_home，不认「方向变了」这种非页面证据。
        from auto_game_unified.games.epic7 import community as community_module

        entry_actions = []
        probe = self.machine()
        for _ in range(2):
            got = probe.next_action(self.LANDSCAPE)
            if got is not None:
                entry_actions.append(got)
        self.assertTrue(entry_actions)
        for got in entry_actions:
            self.assertEqual(("feed_home",), tuple(got.target_pages))
        self.assertIs(community_module, cm)

    def test_closing_finishes_only_after_the_screen_turned_back(self):
        """转回横屏之前不许收工 —— 提前收工会让「回大厅」拿横屏通道取竖屏画面。"""
        machine = self.machine(state=cm.CommunityState.CLOSING)
        self.assertIsNone(machine.next_action(self.PORTRAIT))
        self.assertEqual(machine.completed_cycles, 0)
        self.assertIsNone(machine.next_action(self.LANDSCAPE))
        self.assertEqual(machine.completed_cycles, 1)
        self.assertEqual(machine.state, cm.CommunityState.DONE)
        self.assertIn("横屏", machine.last_reason)

    def test_order_confirm_waits_instead_of_failing_when_the_button_is_disabled(self):
        """按钮禁用（点过了、结果还没出）是**正常等待**，不是故障。

        实测结果要 3~40 秒才弹；这段期间按钮是暗的、颜色定位找不到。
        报错会被主循环当成「画面认不出」去重试 —— 白等一轮，还容易误判方向。
        """
        machine = self.machine(state=cm.CommunityState.ITEM_DETAIL)
        frame = fixture("order_confirm_live_20261006").copy()
        x, y, width, height = cm.GREEN_BUTTON_BAND
        frame[y : y + height, x : x + width] = 0
        self.assertIsNone(machine.next_action(frame))
        self.assertIn("等兑换结果", machine.last_reason)
        self.assertEqual(machine.state, cm.CommunityState.ORDER_CONFIRM)

    def test_finished_route_leaves_the_community_before_finishing(self):
        """任务与兑换都做完 ⇒ 先退信息流、再关社区，**在竖屏段不许收官**。

        如果这一帧直接收官，主循环会在竖屏下执行「回大厅」，拿到的是横屏通道 ——
        直接抛「render size changed」。任务明明做完了，却报一个看不懂的失败。
        """
        machine = self.machine(state=cm.CommunityState.TASKS)
        machine.progress.tasks = {"browse": "done", "like": "done", "share": "done"}
        machine.progress.redeemed = {1: 2, 2: 1, 4: 1}
        action = machine.next_action(fixture("tasks_all_done_live_20261006"))
        self.assertEqual(action.name, "leave_tasks")
        self.assertEqual(machine.completed_cycles, 0)
        closing = machine.next_action(fixture("feed_list_live_20261006"))
        self.assertEqual(closing.name, "close_community")
        self.assertEqual(machine.completed_cycles, 0)


class _FakePortrait:
    """竖屏通道替身：只记「被调了什么」，方向由测试拨。

    ⚠️ 2026-10-07 补了 ``wait_for_landscape`` / ``wait_for_portrait``：
    之前收尾那一步**只点不等**（点完 X 与返回键就 return），所以替身没有等待
    方法也照样全绿 —— 这就是「跑不到的分支」的典型形态。补上之后，那条
    「必须等转回横屏再交棒」才有得测。
    """

    def __init__(self, portrait: bool = True) -> None:
        self.portrait = portrait
        self.calls: list[str] = []
        self.probes = 0
        self.capture_error: Optional[Exception] = None
        # 连续失败几次。``None`` = 一直失败（老行为）；``0`` 起 = 递减到 0 就不失败。
        # ⚠️ 需要它是因为「窗口已是竖屏 ⇒ 不退回横屏、留在竖屏再取一帧」这条新逻辑
        # 会**再取一次**：第一次失败、第二次成功才是它设计的那条路。
        self.capture_failures_left: Optional[int] = None
        # 等方向时调用方给的动作：``"turn"`` = 等的过程中方向会转过来；
        # ``"stay"`` = 一直不变（模拟「等不到」）；``None`` = 不记这个。
        self.turns_while_waiting: Optional[bool] = None
        self.wait_error: Optional[Exception] = None

    def is_portrait(self) -> bool:
        self.probes += 1
        return self.portrait

    def _wait(self, target_portrait: bool, label: str) -> None:
        self.calls.append(f"wait_{label}")
        if self.turns_while_waiting:
            self.portrait = target_portrait
        if self.wait_error is not None:
            raise self.wait_error

    def wait_for_portrait(self, timeout: Optional[float] = None) -> None:
        self._wait(True, "portrait")

    def wait_for_landscape(self, timeout: Optional[float] = None) -> None:
        self._wait(False, "landscape")

    def capture(self) -> np.ndarray:
        failing = self.capture_error is not None and (
            self.capture_failures_left is None or self.capture_failures_left > 0
        )
        if failing:
            if self.capture_failures_left is not None:
                self.capture_failures_left -= 1
            raise self.capture_error
        self.calls.append("capture")
        return np.full((1920, 1080, 3), 7, np.uint8)

    def click(self, point) -> None:
        self.calls.append(f"click{point}")

    def swipe(self, start, end, duration_ms) -> None:
        self.calls.append(f"swipe{start}->{end}")

    def back(self) -> None:
        self.calls.append("back")


class _Clock:
    """可注入的假时钟：``sleep`` 推进它、``now`` 读它。

    ⚠️ 为什么必须有：Runner 里跑的是**有界等待**循环（``_capture_frame``），
    用 ``sleep=lambda _: None`` 而 ``now`` 是真时钟，循环条件永远不成立 ⇒
    测试要么真等 30 秒，要么死转。项目里同款的做法见 ``Runtime`` 的
    ``monotonic`` 注入（``runner_base`` 的 ``self.now = runtime.now``）。
    """

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class ChannelSwitchTests(unittest.TestCase):
    """方向开关：只在**换向的那几秒**里问窗口方向。

    每问一次要跑 `ldconsole list2`（约 100ms 的子进程），每帧都问等于给主循环
    白加一份开销 —— 所以「**锁定竖屏**之后不再问」是一条要有用例钉住的省时约定。

    ⚠️⚠️ 但「锁定**横屏**」不一样：**必须核对真实方向**（2026-10-07 修，用户点 2）。
    原来两个方向都无条件信任记录，于是「记录说横屏、窗口真的竖屏」这个错位
    一路带到取图那一步 ⇒ ``render size changed`` ⇒ 失败收尾**把社区关掉**。
    核对成本是一次 ``GetClientRect``（微秒级），远比事后崩一条路线便宜。
    """

    def test_landscape_by_default_and_asks_nothing(self):
        """默认横屏、窗口**确实**是横屏 ⇒ 判定横屏（问一次以核对）。"""
        fake = _FakePortrait(portrait=False)
        switch = cm.ChannelSwitch(fake)
        self.assertFalse(switch.use_portrait())
        self.assertEqual(fake.probes, 1, "锁定横屏也要核对一次真实方向")

    def test_portrait_lock_never_asks_again(self):
        """锁定竖屏后不再问（省时约定仍然成立）。"""
        fake = _FakePortrait(portrait=True)
        switch = cm.ChannelSwitch(fake)
        switch.expect("portrait")
        self.assertTrue(switch.use_portrait())
        self.assertEqual(fake.probes, 1)
        self.assertTrue(switch.use_portrait())
        self.assertEqual(fake.probes, 1, "锁定竖屏之后不该再问方向")
        self.assertEqual(switch.state, cm.ChannelSwitch.PORTRAIT)

    def test_landscape_record_with_a_portrait_window_switches_back(self):
        """⚠️⚠️ 用户点 2 的正样：记录说横屏、**窗口实际已是竖屏** ⇒ 必须改走竖屏。

        实测错位：``switch.state=landscape`` 而 ``is_portrait()=True``
        ⇒ 继续按横屏取图 ⇒ ``RuntimeError: LDPlayer render size changed:
        1023x1820; expected 1920x1080`` ⇒ 失败收尾**把刚打开的社区关掉**。

        错位怎么来的：收尾把开关拨成「等横屏」，可人还在竖屏里；
        而 ``ChannelSwitch`` **只被那两次拨动更新**，从不核对现实。
        """
        fake = _FakePortrait(portrait=True)
        lines: list[str] = []
        switch = cm.ChannelSwitch(fake, log=lines.append)
        self.assertEqual(switch.state, cm.ChannelSwitch.LANDSCAPE)
        self.assertTrue(
            switch.use_portrait(),
            "窗口已经是竖屏了，还按横屏取图必然撞 render size changed",
        )
        self.assertEqual(
            switch.state,
            cm.ChannelSwitch.PENDING_PORTRAIT,
            "纠正后应进入「等竖屏」，下一帧锁上",
        )
        self.assertTrue(lines, "纠正必须出声：这是记录与现实脱节的唯一证据")
        self.assertIn("实际已是竖屏", lines[0])

    def test_a_landscape_record_with_a_landscape_window_stays_quiet(self):
        """窗口**确实**是横屏 ⇒ 老老实实走横屏，且**不啰嗦**（没有纠正就不出声）。"""
        fake = _FakePortrait(portrait=False)
        lines: list[str] = []
        switch = cm.ChannelSwitch(fake, log=lines.append)
        self.assertFalse(switch.use_portrait())
        self.assertEqual(switch.state, cm.ChannelSwitch.LANDSCAPE)
        self.assertEqual(lines, [], "没有错位就不该有纠正日志")

    def test_locks_after_the_screen_turned(self):
        fake = _FakePortrait(portrait=True)
        switch = cm.ChannelSwitch(fake)
        switch.expect("portrait")
        self.assertTrue(switch.use_portrait())
        self.assertEqual(fake.probes, 1)
        self.assertTrue(switch.use_portrait())
        self.assertEqual(fake.probes, 1, "锁定之后不该再问方向")
        self.assertEqual(switch.state, cm.ChannelSwitch.PORTRAIT)

    def test_keeps_using_the_portrait_channel_until_the_screen_really_turns_back(self):
        """转屏动画期间**不能**回横屏：那会儿横屏取图会因为渲染尺寸在变而报错。"""
        fake = _FakePortrait(portrait=True)
        switch = cm.ChannelSwitch(fake)
        switch.expect("landscape")
        self.assertTrue(switch.use_portrait(), "还没转回来，仍该走竖屏通道")
        fake.portrait = False
        self.assertFalse(switch.use_portrait())
        self.assertEqual(switch.state, cm.ChannelSwitch.LANDSCAPE)

    def test_demote_sends_us_back_to_landscape(self):
        fake = _FakePortrait(portrait=False)
        switch = cm.ChannelSwitch(fake)
        switch.expect("portrait")
        self.assertTrue(switch.use_portrait())
        switch.demote_to_landscape()
        self.assertFalse(switch.use_portrait())


class DualChannelTests(unittest.TestCase):
    """把竖屏通道接进 Runtime 的那一层。"""

    def make_runtime(self, *, dry_run: bool = False):
        calls: list[str] = []

        def capture() -> np.ndarray:
            calls.append("landscape-capture")
            return np.full((1132, 1982, 3), 3, np.uint8)

        def click(point) -> None:
            calls.append(f"landscape-click{point}")

        runtime = Runtime(
            capture=capture, click=click, dry_run=dry_run, emit=lambda _: None
        )
        runtime._swipe = lambda start, end, ms: calls.append("landscape-swipe")
        runtime._back = lambda: calls.append("landscape-back")
        return runtime, calls

    def test_landscape_segment_forwards_to_the_window_chain(self):
        """横屏段（窗口**确实**是横屏）⇒ 原样转发给窗口链路。

        ⚠️2026-10-07：替身必须给 ``portrait=False``。默认是 ``True``（竖屏），
        而 ``ChannelSwitch`` 现在会**核对真实方向**（用户点 2 的修复）——
        窗口真是竖屏时它就纠正成竖屏、不再走横屏，那是正确行为、不是这条要测的。
        """
        runtime, calls = self.make_runtime()
        cm.attach_dual_channel(runtime, _FakePortrait(portrait=False))
        runtime.capture()
        runtime.click((10, 20), "x")
        self.assertEqual(calls, ["landscape-capture", "landscape-click(10, 20)"])

    def test_portrait_segment_uses_the_adb_channel(self):
        runtime, calls = self.make_runtime()
        portrait = _FakePortrait(portrait=True)
        switch = cm.attach_dual_channel(runtime, portrait)
        switch.expect("portrait")
        frame = runtime.capture()
        self.assertIn("capture", portrait.calls)
        self.assertEqual(tuple(frame.shape[:2]), (1920, 1080))
        runtime.click((10, 20), "x")
        self.assertIn("click(10, 20)", portrait.calls)
        runtime.back("back")
        self.assertIn("back", portrait.calls)
        runtime.swipe((1, 2), (3, 4), 300, "s")
        self.assertIn("swipe(1, 2)->(3, 4)", portrait.calls)
        self.assertEqual(calls, [], "竖屏段不该再走窗口链路")

    def test_dry_run_never_touches_the_adb_channel(self):
        """干跑不碰 adb、也不该让模拟器转屏（干跑时连方向都不问）。"""
        runtime, calls = self.make_runtime(dry_run=True)
        portrait = _FakePortrait(portrait=True)
        switch = cm.attach_dual_channel(runtime, portrait)
        switch.expect("portrait")
        runtime.capture()
        self.assertEqual(portrait.calls, [])
        self.assertEqual(portrait.probes, 0)
        self.assertEqual(calls, ["landscape-capture"])

    def test_orientation_timeout_falls_back_to_landscape_and_says_so(self):
        """等转屏超时 ⇒ 那一下入口没点中：退回横屏重试，并在日志里说清楚。"""
        runtime, calls = self.make_runtime()
        portrait = _FakePortrait(portrait=False)
        portrait.capture_error = OrientationError("等竖屏超时（假的）")
        lines: list[str] = []
        runtime._emit = lines.append
        switch = cm.attach_dual_channel(runtime, portrait)
        switch.expect("portrait")
        frame = runtime.capture()
        self.assertEqual(tuple(frame.shape[:2]), (1132, 1982))
        self.assertEqual(switch.state, cm.ChannelSwitch.LANDSCAPE)
        self.assertTrue(any("退回横屏" in line for line in lines), lines)

    def test_wrong_canvas_size_also_falls_back_instead_of_crashing(self):
        """截图尺寸不对**且窗口确实还在横屏** ⇒ 退回横屏，不许崩掉整条路线。

        ⚠️ 2026-10-07 10:51 那次实跑崩溃的**原样复现**：
        ``portrait.capture()`` 在截图不是 1080x1920 时抛的是**裸
        ``RuntimeError``**，而 ``attach_dual_channel.capture`` 只 ``except
        OrientationError`` ⇒ 漏过 ⇒ 一路冒到主循环 ⇒ 整条路线崩掉。

        ⚠️⚠️ **窗口方向是这条的前置条件**（2026-10-07 第二次修）。
        这条测试原来写成 ``_FakePortrait(portrait=True)``（窗口**已是竖屏**）
        却断言「退回横屏」—— 那正是用户点 2 的病根：
        窗口已是竖屏时退回横屏 ⇒ 拿竖屏画面撞横屏模板 ⇒ 失败收尾**把刚打开的
        社区又关掉**。所以这里的替身必须是 ``portrait=False``：
        **只有窗口还在横屏**，「社区没打开、回去重点一次入口」才成立。
        窗口已是竖屏的那一支由下面两条测。
        """
        runtime, calls = self.make_runtime()
        portrait = _FakePortrait(portrait=False)
        # 旧行为：尺寸不对时抛的是裸 RuntimeError。
        portrait.capture_error = RuntimeError(
            "竖屏截图尺寸不对：1920x1080，应为 1080x1920；多半是模拟器方向又变了"
        )
        lines: list[str] = []
        runtime._emit = lines.append
        switch = cm.attach_dual_channel(runtime, portrait)
        switch.expect("portrait")
        frame = runtime.capture()  # 旧代码在这里就炸了
        self.assertEqual(
            tuple(frame.shape[:2]),
            (1132, 1982),
            "窗口还在横屏时该退回横屏取图，而不是把异常抛给主循环",
        )
        self.assertEqual(switch.state, cm.ChannelSwitch.LANDSCAPE)
        self.assertTrue(any("退回横屏" in line for line in lines), lines)

    def test_never_falls_back_to_landscape_once_the_window_is_already_portrait(self):
        """⚠️⚠️ 用户点 2 的正样：窗口**已是竖屏**时，取图失败**不许**退回横屏。

        12:45 实跑：12:45:02 点「游戏社区」→ 12:45:05 就
        「收尾=人还在社区竖屏页面里」⇒ 那一刻 ``is_portrait()`` 为真。
        旧代码无条件退回横屏 ⇒ ``RuntimeError: render size changed``
        ⇒ 失败收尾**把刚打开的社区关掉**（用户原话：「进入社区之后又会退回来」）。

        这条钉住「先问方向、再决定退不退」这个**判据本身**：
        - 不许调横屏取图（``calls`` 里不许出现 ``landscape-capture``）；
        - 不许把通道降级（否则后面每帧都拿竖屏画面撞横屏模板）。
        """
        runtime, calls = self.make_runtime()
        portrait = _FakePortrait(portrait=True)
        portrait.capture_error = OrientationError("截图尺寸不对（假的）")
        lines: list[str] = []
        runtime._emit = lines.append
        switch = cm.attach_dual_channel(runtime, portrait)
        switch.expect("portrait")
        with self.assertRaises(OrientationError):
            runtime.capture()
        self.assertEqual(
            calls,
            [],
            "窗口已是竖屏时退回横屏取图，会拿竖屏画面撞横屏模板并触发失败收尾",
        )
        self.assertNotEqual(
            switch.state,
            cm.ChannelSwitch.LANDSCAPE,
            "不许把通道降级成横屏：窗口真的是竖屏",
        )
        self.assertTrue(
            any("不退回横屏" in line for line in lines),
            f"必须说清为什么不退回：{lines}",
        )

    def test_stays_portrait_and_succeeds_when_the_canvas_settles_on_the_retry(self):
        """窗口已竖 + 第一次画幅没跟上 ⇒ **留在竖屏再取一帧**，取到就正常用。

        这是上一条的正向一半：新逻辑不是「反正会抛」，而是先留在竖屏重试一次
        （``core/portrait.py`` 内部已有有界等待），多数情况下这一帧就成了。
        """
        runtime, calls = self.make_runtime()
        portrait = _FakePortrait(portrait=True)
        portrait.capture_error = OrientationError("画幅还没跟上（假的）")
        portrait.capture_failures_left = 1
        lines: list[str] = []
        runtime._emit = lines.append
        switch = cm.attach_dual_channel(runtime, portrait)
        switch.expect("portrait")
        frame = runtime.capture()
        self.assertEqual(
            tuple(frame.shape[:2]),
            (1920, 1080),
            "留在竖屏重试后应当拿到竖屏帧",
        )
        self.assertEqual(calls, [], "全程都不该碰横屏取图")
        self.assertEqual(switch.state, cm.ChannelSwitch.PORTRAIT)

    def test_portrait_capture_reports_a_wrong_size_as_an_orientation_error(self):
        """``core.portrait`` 那一支**必须**抛 ``OrientationError``。

        ⚠️ 为什么单独钉这一条：上面那条用替身模拟「抛什么」，而这一条盯住
        **真的那一行代码**。两层都写错时（例如有人为了「更通用」把它改回
        ``RuntimeError``），上面那条会绿、这一条会红 —— 两层都要有。
        """
        import inspect

        from auto_game_unified.core import portrait as portrait_module

        source = inspect.getsource(portrait_module.PortraitChannel.capture)
        self.assertIn(
            "OrientationError",
            source,
            "PortraitChannel.capture() 在截图尺寸不对时必须抛 OrientationError，"
            "否则上层「等不到转屏就退回横屏」的兜底接不到（2026-10-07 实跑崩溃）",
        )

    def test_refuses_to_attach_when_the_runtime_shape_changed(self):
        """通道属性被改名 ⇒ **开跑前**当场报错，不许静默失效。"""
        runtime, _ = self.make_runtime()
        del runtime._back
        with self.assertRaises(RuntimeError) as ctx:
            cm.attach_dual_channel(runtime, _FakePortrait())
        self.assertIn("_back", str(ctx.exception))


class CommunityRunnerTests(unittest.TestCase):
    """Runner 的接线：契约开关、超时覆盖、方向预期、心跳。"""

    @classmethod
    def setUpClass(cls):
        cls.templates, cls.glyphs = cm.build_screen_reader(TEMPLATES)

    def make_runner(self, *, dry_run: bool = False, portrait=None):
        runtime = Runtime(
            capture=lambda: np.zeros((1132, 1982, 3), np.uint8),
            click=lambda point: None,
            dry_run=dry_run,
            emit=lambda _: None,
        )
        machine = cm.CommunityStateMachine(self.templates, self.glyphs)
        return cm.CommunityRunner(machine, runtime, portrait=portrait, sleep=lambda _: None)

    def test_it_declares_the_transition_contract(self):
        self.assertIs(cm.CommunityRunner._REQUIRE_TRANSITION_CONTRACT, True)

    def test_timeouts_cover_every_state(self):
        """漏一个状态，`_timeout_for` 会在实跑那一刻 KeyError —— 这是加载期就该发现的事。"""
        self.assertEqual(
            set(cm.CommunityRunner._TIMEOUT_SECONDS), set(cm.CommunityState)
        )

    def test_order_confirm_window_is_wider_than_the_measured_result_wait(self):
        """兑换结果实测最长约 40 秒；这一档给 45 秒的话，正常等待会被判成超时。"""
        self.assertGreater(
            cm.CommunityRunner._TIMEOUT_SECONDS[cm.CommunityState.ORDER_CONFIRM], 90
        )

    def test_entry_retry_window_is_longer_than_the_orientation_wait(self):
        """⚠️ 重试入口的间隔必须比「等转屏」更宽。

        竖屏通道默认要等满 20 秒才认输；间隔比它短就会在**转屏动画还没走完**时
        再点一次 —— 那时的横屏坐标已经不可信了。
        """
        from auto_game_unified.core.portrait import _DEFAULT_ORIENTATION_TIMEOUT

        runner = self.make_runner()
        self.assertGreater(
            runner._action_retry_seconds("enter_community"),
            _DEFAULT_ORIENTATION_TIMEOUT,
        )

    def test_quick_actions_do_not_wait_45_seconds(self):
        runner = self.make_runner()
        self.assertLess(runner._action_retry_seconds("ack_redeem_done"), 20)
        self.assertEqual(
            runner._action_retry_seconds("open_item"),
            cm.ModeRunnerBase._ACTION_RETRY_SECONDS,
        )

    def test_clicking_the_entry_and_exit_arms_the_switch(self):
        runner = self.make_runner(dry_run=True)
        runner._switch = cm.ChannelSwitch(_FakePortrait())
        runner._after_action_click(cm.CommunityAction("enter_community", (1, 1)))
        self.assertEqual(runner._switch.state, cm.ChannelSwitch.PENDING_PORTRAIT)
        runner._after_action_click(cm.CommunityAction("close_community", (1, 1)))
        self.assertEqual(runner._switch.state, cm.ChannelSwitch.PENDING_LANDSCAPE)

    def test_dry_run_does_not_attach_the_adb_channel(self):
        runner = self.make_runner(dry_run=True)
        runner._attach_channels()
        self.assertIsNone(runner._switch)

    def test_closing_out_waits_for_the_screen_to_turn_back_before_handing_over(self):
        """收尾点完退出社区之后**必须等方向真的转回横屏**，才能交棒给「回首页」。

        ⚠️ 这是 2026-10-07 10:51 那次「异常也回家失败」的**直接原因**：
        旧代码点完 X 与两下返回键就 ``return``，方向转没转完不管 ⇒
        ``super()._close_out()`` 紧接着调 ``return_home`` 取图，那一刻窗口
        往往还在竖屏 ⇒ 横屏模板被喂竖屏画面 ⇒
        ``RuntimeError: 画面宽高比与模板基准不一致``。

        断言的是**顺序**（先点后等、等完才返回），不是「等了几秒」——
        那是实现细节，改秒数不该让这条红。
        """
        portrait = _FakePortrait(portrait=True)
        portrait.turns_while_waiting = True
        runner = self.make_runner(portrait=portrait)
        runner._switch = cm.ChannelSwitch(portrait)
        runner._leave_portrait_if_needed()
        self.assertIn(
            "wait_landscape",
            portrait.calls,
            f"收尾点完退出社区后没有等转回横屏：{portrait.calls}",
        )
        # 顺序：等必须排在最后一次点击之后。
        self.assertLess(
            max(i for i, c in enumerate(portrait.calls) if c.startswith("click")),
            portrait.calls.index("wait_landscape"),
        )
        self.assertFalse(portrait.portrait, "等完之后方向应当已经是横屏")

    def test_closing_out_says_so_when_the_screen_never_turns_back(self):
        """等不到转回横屏：**如实记一笔**，但**绝不抛异常**。

        ⚠️ 收尾抛异常会顶掉基类那步、还会改退出码 —— 而「模拟器没转回来」
        不该让一整条已经跑完的路线变成「故障」（项目规矩：收尾失败不改退出码）。
        """
        portrait = _FakePortrait(portrait=True)
        portrait.turns_while_waiting = False
        lines: list[str] = []
        runner = self.make_runner(portrait=portrait)
        runner._switch = cm.ChannelSwitch(portrait)
        runner.runtime._emit = lines.append
        runner._leave_portrait_if_needed()  # 不许抛
        self.assertTrue(
            any("仍在竖屏" in line for line in lines),
            f"等不到转回横屏却没有如实记一笔：{lines}",
        )

    def test_closing_out_does_nothing_when_the_screen_is_already_landscape(self):
        """已经是横屏 ⇒ 什么都不用做（正常路径：状态机在横屏那帧才收工）。"""
        portrait = _FakePortrait(portrait=False)
        runner = self.make_runner(portrait=portrait)
        runner._switch = cm.ChannelSwitch(portrait)
        runner._leave_portrait_if_needed()
        self.assertEqual(portrait.calls, [])

    def test_it_refuses_a_non_emulator_landscape_channel(self):
        """PC 后端没有 adb。不拦的后果是**静默点错客户端**（去找雷电窗口）。"""

        class _NotTheEmulator:
            def capture(self):
                return np.zeros((1080, 1920, 3), np.uint8)

        other = _NotTheEmulator()
        runtime = Runtime(
            capture=other.capture,
            click=lambda point: None,
            emit=lambda _: None,
        )
        machine = cm.CommunityStateMachine(self.templates, self.glyphs)
        runner = cm.CommunityRunner(machine, runtime, sleep=lambda _: None)
        with self.assertRaises(RuntimeError) as ctx:
            runner._attach_channels()
        self.assertIn("雷电", str(ctx.exception))

    def test_a_swipe_step_is_sent_through_the_swipe_channel_not_as_a_click(self):
        """like 脚本的第一步是**滑动**：不许被当成「在起点点一下」。

        ⚠️ 2026-10-07 实跑：主循环只会 ``runtime.click`` ⇒ 滑动变成「在信息流中部
        点一下」⇒ **点开一张帖子** ⇒ 下一步要求 ``feed_home`` 对不上 ⇒ 点赞任务
        三遍机会全废。修法是 Runner 认 ``swipe_end`` 换发 ``runtime.swipe``。
        这条钉的是「脚本 → 动作 → 真的走滑动通道」整条链，不是只看动作字段。
        """
        clicks: list = []
        swipes: list = []
        runtime = Runtime(
            capture=lambda: np.zeros((1132, 1982, 3), np.uint8),
            click=clicks.append,
            emit=lambda _: None,
        )
        runtime._swipe = lambda start, end, ms: swipes.append((start, end, ms))
        machine = cm.CommunityStateMachine(self.templates, self.glyphs)
        runner = cm.CommunityRunner(machine, runtime, sleep=lambda _: None)
        machine.active_task = "like"
        action = machine._drive_task(
            fixture("feed_list_live_20261006"),
            cp.PageJudgement("feed_home", 1.0, ()),
        )
        self.assertEqual(action.swipe_end, cm.FEED_TASK_SCROLL_END, "滑动步没带终点")
        runner._perform_action(action)
        self.assertEqual(
            [
                (
                    cm.FEED_TASK_SCROLL_START,
                    cm.FEED_TASK_SCROLL_END,
                    cm.FEED_TASK_SCROLL_MS,
                )
            ],
            swipes,
            "滑动步没有走 runtime.swipe",
        )
        self.assertEqual([], clicks, "滑动步被当成点击发出去了")

    def test_a_plain_step_still_goes_out_as_a_click(self):
        """没有 ``swipe_end`` 的动作照旧是点击 —— 换发只对滑动那几步生效。"""
        clicks: list = []
        runtime = Runtime(
            capture=lambda: np.zeros((1132, 1982, 3), np.uint8),
            click=clicks.append,
            emit=lambda _: None,
        )
        runner = cm.CommunityRunner(
            cm.CommunityStateMachine(self.templates, self.glyphs),
            runtime,
            sleep=lambda _: None,
        )
        runner._perform_action(cm.CommunityAction("open_item", (250, 639)))
        self.assertEqual([(250, 639)], clicks)

    def test_capture_waits_out_a_rotation_instead_of_failing_the_route(self):
        """换向那一两秒取不到图 ⇒ **有界等待**，不是秒失败收尾。

        ⚠️ 主循环取图那一行在 ``try`` 之外 ⇒ 取图一抛，整条路线立刻失败收尾，
        把**刚打开的社区**又关掉（2026-10-07 一天 8 次、连诊断帧都没留下）。
        所以断言：前两帧抛方向错、第三帧好 ⇒ 正常拿到画面。
        """
        clock = _Clock()
        left = [2]

        def capture() -> np.ndarray:
            if left[0] > 0:
                left[0] -= 1
                raise OrientationError("画幅还没跟上（假的）")
            return np.full((1920, 1080, 3), 9, np.uint8)

        runtime = Runtime(
            capture=capture,
            click=lambda _: None,
            emit=lambda _: None,
            monotonic=clock.now,
        )
        runner = cm.CommunityRunner(
            cm.CommunityStateMachine(self.templates, self.glyphs),
            runtime,
            sleep=clock.sleep,
        )
        runner._switch = cm.ChannelSwitch(_FakePortrait(portrait=True))
        frame = runner._capture_frame()
        self.assertEqual((1920, 1080), tuple(frame.shape[:2]))
        self.assertEqual(0, left[0], "还有失败没恢复，取图却没走到成功那一帧")

    def test_capture_fails_only_after_the_settle_budget_is_spent(self):
        """等满 ``_CAPTURE_SETTLE_SECONDS`` 还不行才允许失败，且要**说清在等什么**。"""
        clock = _Clock()
        logs: list[str] = []

        def capture() -> np.ndarray:
            raise OrientationError("一直没跟上（假的）")

        runtime = Runtime(
            capture=capture,
            click=lambda _: None,
            emit=logs.append,
            monotonic=clock.now,
        )
        runner = cm.CommunityRunner(
            cm.CommunityStateMachine(self.templates, self.glyphs),
            runtime,
            sleep=clock.sleep,
        )
        runner._switch = cm.ChannelSwitch(_FakePortrait(portrait=True))
        with self.assertRaises(OrientationError):
            runner._capture_frame()
        self.assertGreaterEqual(
            clock.t, runner._CAPTURE_SETTLE_SECONDS, "没等满就判失败了"
        )
        self.assertTrue(any("等满" in line for line in logs), f"失败时没说清原因：{logs}")

    def test_capture_does_not_swallow_a_manual_stop(self):
        """用户按 P（``ManualStop``）**不许**被取图的兜底吞掉。

        全线统一口径：喊停就把控制权交回去，绝不在「停」的路径上继续等待 ——
        兜底只该接「方向类」异常（``OrientationError``），不能顺手把停止也接掉。
        """

        clock = _Clock()

        def capture() -> np.ndarray:
            raise ManualStop("用户按了停止")

        runtime = Runtime(
            capture=capture,
            click=lambda _: None,
            emit=lambda _: None,
            monotonic=clock.now,
        )
        runner = cm.CommunityRunner(
            cm.CommunityStateMachine(self.templates, self.glyphs),
            runtime,
            sleep=clock.sleep,
        )
        runner._switch = cm.ChannelSwitch(_FakePortrait(portrait=True))
        with self.assertRaises(ManualStop):
            runner._capture_frame()

    def test_the_run_loop_is_delegated_to_the_base_class(self):
        """覆写 run() 只为了装配通道；主循环必须委托回基类。

        自己写循环会同时丢掉「收尾回首页」与「结论门槛」——
        `finish_home` 与 `modes` 两处的加载期自查就是拦这个的。
        """
        import inspect

        source = inspect.getsource(cm.CommunityRunner.run)
        self.assertIn("super().run(", source)
        modifiers = inspect.getsource(cm.CommunityRunner._stable_next_action)
        self.assertIn("super()._stable_next_action", modifiers)


if __name__ == "__main__":
    unittest.main()
