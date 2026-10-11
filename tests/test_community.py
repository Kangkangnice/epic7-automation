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


def scrolled_feed(frame: np.ndarray, shift: int, header: int = 420) -> np.ndarray:
    """把一帧信息流**当成往下滚了一屏**：顶栏不动、正文整体上移 ``shift`` 像素。

    ⚠️ 为什么要造帧、不再拍一张真机夹具：竖屏口径下「**整屏都没有可点的 👍**」
    的画面只有 ``feed_before_signin`` 一张（``feed_after_signin`` / ``feed_list``
    与它的正文带位置**完全相同**，量出来都是 ``[610, 622, 826, ...]``）。而
    2026-10-09 起「滑了几屏」按**画面真的动了**记账，必须有第二张位置不同的
    同款画面才测得出来。

    只挪 ``header`` 以下的正文，底部那 ``shift`` 行保持原样 —— 实测补纯色会把
    ``feed_home`` 的判据锚点一起抹掉（页面直接认不出，0.0000）。
    ``shift=200`` / ``480`` 实测：页面仍是 ``feed_home`` **满分 1.0000**、
    可点 👍 仍是 ``None``、正文带整体位移 ≥ 192px（过 ``SWIPE_MOVE_MIN_PX``）。
    """
    moved = frame.copy()
    moved[header:-shift] = frame[header + shift :]
    return moved


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
            # ① 兑换中心：不抛，点右上角 ✕ 退出社区（并记下停止原因）
            action = machine.next_action(fixture("exchange_after_redeem_live_20261006"))
            self.assertEqual(action.name, "leave_exchange")
            self.assertEqual(action.point, (989, 123))
            self.assertIn("不够", machine.stop_reason)
            # ② 画面转回横屏那一帧：这时才抛，且必须是「资源耗尽」家族
            landscape = np.zeros((1132, 1982, 3), np.uint8)
            with self.assertRaises(cm.RedeemBudgetExhausted) as ctx:
                machine.next_action(landscape)
        self.assertIn("不够", str(ctx.exception))
        self.assertEqual(cm.RedeemBudgetExhausted.stop_label, "积分不足")
        # 退出码 2 靠的是**继承关系**：挂在 RuntimeError 下会被当成「画面认不出」，
        # 白等一轮超时再报退出码 1（故障）。
        self.assertIsInstance(ctx.exception, cm.ResourceExhausted)

    def test_the_finished_exchange_closes_the_community_in_one_click(self):
        """兑换跑满 ⇒ 点兑换中心**右上角的 ✕**，社区**一步关掉**、直接回横屏。

        ⚠️ 2026-10-09 真机实跑抓到的 P0（19:58），这份代码**连着猜错两次**：
        ① 旧写法点左上角 `<` + ``target_pages=("feed_home",)`` —— `<` 是
           **H5 历史返回**，兑换中心是从「我的任务」点「去兑换」进来的 ⇒ `<` 回到的是
           **「我的任务」**；而「我的任务」的 `<` 又指回兑换中心 ⇒ 两页**互为历史上一页**，
           靠返回键**永远回不到信息流**（两次各干等 150 秒超时）。
        ② 改成点 ✕ 之后又**猜错了它的语义**：以为「它只关掉兑换中心这一层、回信息流」，
           于是把状态置成 ``FEED`` 去等一页**竖屏信息流** —— 而它压根不会出现。
           真机探针（``.workbuddy/_probe_exchange_close_layer.py``）逐步判页走了一遍：
           点完 ✕ **3 秒内窗口就变回 1920x1080**、画面就是**横屏网页活动列表** ⇒
           这颗 ✕ 关的是**整个社区**，一步到位，中间**没有信息流这一站**。
           （第二条独立证据：H5 死掉那屏点它自己那颗 ⊗ (1000,78)，窗口同样在 4 秒内
           从 ``1023x1820`` 变回 ``1920x1080``。）

        ⇒ 收工的动作必须与 ``close_community`` **同形**：``CLOSING`` +
        目标 ``web_activity_list``，收工发生在**横屏那一帧**（``_finish_closing``），
        而不是点完立刻抛结论（那时人还在竖屏里，收尾取图会撞「render size changed」）。

        ⚠️ 断言里的坐标**独立写死**，不从 ``cm.EXCHANGE_CLOSE`` 反推：
        常量被改坏时断言得跟着红才算护栏。
        """
        machine = self.machine(state=cm.CommunityState.EXCHANGE)
        # 三条任务的结论是前面几页读出来的；这里只关心**兑换之后**的收尾，
        # 所以直接摆好事实（``_finishing()`` 要它才肯收工）。
        machine.progress.tasks = {"browse": "done", "like": "done", "share": "done"}
        full = cm.ExchangeReadout(
            balance=880,
            balance_score=1.0,
            limits={1: (2, 2), 2: (1, 1), 3: (0, 1), 4: (1, 1)},
        )
        with unittest.mock.patch.object(cm, "read_exchange", return_value=full):
            leaving = machine.next_action(fixture("exchange_after_redeem_live_20261006"))
        self.assertEqual(leaving.name, "leave_exchange")
        self.assertEqual(
            leaving.point,
            (989, 123),
            "退出社区点的是兑换中心右上角的 ✕，不是左上角 <（历史返回）",
        )
        self.assertEqual(
            tuple(leaving.target_pages),
            ("web_activity_list",),
            "这颗 ✕ 关的是整个社区 -> 落点是横屏的网页活动列表",
        )
        self.assertIs(
            machine.state,
            cm.CommunityState.CLOSING,
            "必须与 close_community 同形走 CLOSING：否则横屏帧会被当成「等待画面转过去」，"
            "干等到状态超时（19:58 实跑就是这么卡满 150 秒的）",
        )
        # 横屏那一帧才收工（点完立刻收工会让人还在竖屏时取图）。
        landscape = np.zeros((1132, 1982, 3), np.uint8)
        self.assertIsNone(machine.next_action(landscape))
        self.assertIs(machine.state, cm.CommunityState.DONE)
        self.assertEqual(machine.completed_cycles, 1)

    def test_the_tasks_page_back_arrow_lands_on_the_exchange_center(self):
        """「我的任务」的 `<` 落到**兑换中心**（上一层），不是信息流。

        钉这条是为了说明上面那个 ✕ 为什么省不掉：「我的任务」和「兑换中心」
        互为历史上一页，从这一页靠返回键回不到信息流。
        """
        machine = self.machine(state=cm.CommunityState.TASKS)
        machine.progress.tasks = {"browse": "done", "like": "done", "share": "done"}
        machine.progress.redeemed = {1: 2, 2: 1, 4: 1}
        back = machine.next_action(fixture("tasks_all_done_live_20261006"))
        self.assertEqual(back.name, "leave_tasks")
        self.assertEqual(back.point, (35, 130), "「我的任务」左上角的返回键")
        self.assertEqual(
            tuple(back.target_pages),
            ("exchange_center",),
            "这一页的 < 回到的是兑换中心；写成 feed_home 会让转场永远等不到（150 秒超时）",
        )

    def test_points_running_out_does_not_bounce_back_to_the_exchange(self):
        """已经判定「积分不够、不再兑换」之后，「我的任务」**不许再往兑换中心跑**。

        「我的任务」收尾前会判一次「兑换满了没有」—— 积分不够时当然没满 ⇒
        少了 ``stop_reason`` 这个条件就是**原地打转**：兑换中心与「我的任务」
        互为历史上一页（两页的 `<` 各指对方），来回一次两次都叫得响，
        项目红线（绝不死循环）。

        ⚠️ 2026-10-09 改：旧版是**真跑一遍**「兑换中心 → 我的任务」再来断言，
        而那条路现在**不存在了** —— 兑换中心判定积分不够之后是**一步退出社区**
        （``CLOSING`` + 点 ✕），不会再退回「我的任务」。所以这里直接摆好前提
        （``stop_reason`` 已置）来钉这道闸门本身。
        """
        machine = self.machine(state=cm.CommunityState.TASKS)
        machine.stop_reason = "余额 5 不够换「行动力*30」（要 20 积分）"
        machine.progress.tasks = {"browse": "done", "like": "done", "share": "done"}
        back = machine.next_action(fixture("tasks_all_done_live_20261006"))
        self.assertEqual(
            back.name,
            "leave_tasks",
            "积分够不够已经拍过板了，却还往兑换中心跑 —— 那是死循环",
        )
        self.assertEqual(back.point, (35, 130))

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

    def _walk_this_round(self, machine: cm.CommunityStateMachine) -> list[str]:
        """把 ``machine`` 上正在跑的那条任务的**一整轮**推完，返回每一步的动作名。

        每一帧喂哪一页，直接问脚本自己（``step.page``）—— 这正是脚本存在的意义；
        测试再抄一份「第几步该在哪页」就会和脚本一起漂。
        """
        frames = {
            "feed_home": fixture("feed_before_signin_live_20261007"),
            "post_detail": fixture("post_detail_live_20261006"),
        }
        names: list[str] = []
        for step in cm.TASK_SCRIPT[machine.active_task]:
            action = machine.next_action(frames[step.page])
            self.assertIsNotNone(action, f"脚本要求停在 {step.page}，状态机却没出手")
            names.append(action.name)
        return names

    def test_the_browse_round_walks_three_posts_before_reconciling(self):
        """**一轮 = 连做 3 篇**，做完才回「我的任务」对账一次（用户 2026-10-07 拍板）。

        ⚠️ 为什么粒度必须是「一轮」而不是「一次」：每次点「去完成」都重新落在信息流
        **顶部** ⇒ 做一次就回来一趟的话，第二遍「下滑一次」又滑到**同一篇**，
        第三遍也是 —— 三遍白做，计数永远不涨。

        ⚠️ 为什么最后一步必须是「回我的任务对账」而不是「再排一遍」：任务成败只有
        页面上那个按钮说得准，脚本跑完不等于计数涨了。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        self.assertEqual(
            machine.next_action(fixture("tasks_one_browse_done_live_20261006")).name,
            "start_task",
        )
        self.assertEqual(
            len(cm.TASK_SCRIPT["browse"]), 11, "一轮浏览 = 3 篇 × 3 步 + 2 次换帖"
        )
        names = self._walk_this_round(machine)
        self.assertEqual(names, [f"task_browse_{index}" for index in range(1, 12)])
        # 一轮做完但**还没对账** ⇒ active_task 必须还在，否则对账就认不出是哪一条
        self.assertEqual(machine.active_task, "browse")
        home = machine.next_action(fixture("feed_before_signin_live_20261007"))
        self.assertEqual(home.name, "back_to_tasks_via_exchange")
        self.assertTrue(machine.via_exchange)
        detour = machine.next_action(fixture("exchange_before_redeem_live_20261007"))
        self.assertEqual(detour.name, "goto_tasks_card")
        self.assertEqual(detour.point, cm.EXCHANGE_GAIN_POINTS_CARD)
        machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        self.assertEqual(machine.active_task, "browse")

    def test_the_browse_round_swipes_between_posts_and_dwells_inside_the_post(self):
        """一轮里那两下各有不可省的语义：**帖内下滑 + 停留**、**两篇之间换帖下滑**。

        - 帖内那一下必须是滑动**并且停留 5~10 秒**（用户口径原话：「稍微往下滑一下，
          停留个 5~10 秒，然后退出来，这个就算浏览一次了」）—— 不滑不停，游戏多半
          不记这次浏览，而画面看起来一切正常。
        - 两篇之间必须夹一次下滑：返回信息流时滚动位置不会自己往前走，不滑到底
          点下去还是同一篇。

        ⚠️ 「点开帖子」这一下的落点**不是** ``FEED_FIRST_POST``（脚本里那个盲坐标）——
        它是**运行时现找**出来的（``TaskStep.point is None`` + ``kind="tap_post"``）。
        钉死坐标在 2026-10-08 两次实跑都点在帖子的图片上（图被放大 ⇒ 整条路线卡死），
        所以这里断言的是「现找结果」本身，并且**多断言一层它落在哪条带上**。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        feed = fixture("feed_before_signin_live_20261007")
        post = fixture("post_detail_live_20261006")
        opened = machine.next_action(feed)
        expected = cp.locate_feed_post_tap(feed, cm.FEED_FIRST_POST)
        self.assertIsNotNone(expected, "这一帧上找得到正文带，动作才该发出来")
        self.assertEqual(opened.point, expected)
        self.assertEqual(opened.point[0], cm.FEED_FIRST_POST[0], "x 沿用 hint 的")
        self.assertTrue(
            cp.feed_tap_band_is_text(
                feed, opened.point[1] - cp.FEED_TAP_SLAB // 2, cp.FEED_TAP_SLAB
            ),
            "点的必须是「白底 + 有字 + 不是图片」的正文带",
        )
        # 出口集合只写「点了之后会到哪」；另两个是**全局异常态**（签到弹窗、
        # 网络异常页），它们出现时状态机会抢先处理，所以必须放行。
        self.assertEqual(
            opened.target_pages, ("post_detail", "signin_done", "network_error")
        )
        self.assertNotIn("feed_home", opened.target_pages, "不许把来源页写进出口集合")
        scrolled = machine.next_action(post)
        self.assertEqual(
            (scrolled.point, scrolled.swipe_end), (cm.POST_SCROLL_START, cm.POST_SCROLL_END)
        )
        self.assertGreaterEqual(scrolled.dwell_seconds, 5.0)
        self.assertLessEqual(scrolled.dwell_seconds, 10.0)
        for _ in range(2):  # 「退回信息流」那一步（第 3 步）
            back = machine.next_action(post)
        self.assertEqual(back.point, cm.POST_BACK)
        between = machine.next_action(feed)
        self.assertEqual(
            (between.point, between.swipe_end),
            (cm.FEED_TASK_SCROLL_START, cm.FEED_TASK_SCROLL_END),
        )

    def test_every_scroll_gesture_starts_in_the_left_gutter(self):
        """所有**滑动**的起点列都要落在页面左边缘的白边上，不许落在插图那一列。

        ⚠️ 为什么值得一条护栏（用户 2026-10-08 提的角度，量过之后成立）：

        ``_perform_action`` 只在 ``swipe_end`` 非空时才发 ``swipe`` —— **那面旗子一丢，
        主循环就在起点点一下**（2026-10-07 点赞任务三遍全废正是这个形状）。
        起点在页面正中 = 点在帖子插图上 = 打开图片查看器 = 整条路线卡死；
        起点在白边上 ⇒ 退化了也只是在白边点一下。

        断言分两层：① 三个滑动起点的 x 都 ≤ ``SCROLL_GUTTER_X``；② 拿**真机帧**量那一列，
        它不许有彩色内容（x=540 那一列实测 0.057~0.191，x=60 是 0.000~0.003）。
        """
        gestures = {
            "FEED_TASK_SCROLL_START": cm.FEED_TASK_SCROLL_START,
            "FEED_ICON_SCROLL_START": cm.FEED_ICON_SCROLL_START,
            "POST_SCROLL_START": cm.POST_SCROLL_START,
        }
        for name, start in gestures.items():
            with self.subTest(gesture=name):
                self.assertLessEqual(
                    start[0],
                    cm.SCROLL_GUTTER_X,
                    f"{name} 的 x 跑到页面中间了 —— 这一滑一旦退化成点击就落在插图上",
                )
        for frame in (
            "feed_cards_all_todo_live_20261007",
            "feed_list_live_20261006",
            "post_detail_live_20261006",
        ):
            screen = fixture(frame)
            column = screen[240:1760, cm.SCROLL_GUTTER_X].astype(np.int16)
            colorful = float(
                ((column.max(axis=1) - column.min(axis=1)) > cp.FEED_TAP_SATURATION).mean()
            )
            with self.subTest(frame=frame):
                self.assertLess(
                    colorful,
                    0.05,
                    f"{frame} 上滑动起点那一列（x={cm.SCROLL_GUTTER_X}）穿过彩色内容"
                    f"（占比 {colorful:.3f}）",
                )
        # 反向：页面正中那一列**确实**穿过内容 —— 否则上面那两条可能只是「量了个空白」
        middle = fixture("feed_cards_all_todo_live_20261007")[240:1760, 540].astype(np.int16)
        middle_colorful = float(
            ((middle.max(axis=1) - middle.min(axis=1)) > cp.FEED_TAP_SATURATION).mean()
        )
        self.assertGreater(
            middle_colorful,
            0.05,
            "页面正中那一列居然是干净的 —— 这张帧已经不适合当这条用例的靶子了",
        )

    def test_the_browse_tap_never_falls_back_to_the_blind_point(self):
        """现找不出来时**必须收手**，绝不退回盲坐标。

        构造方式：把「查看器那一帧」硬说成 ``feed_home``（画面与判页不一致的极端情形）。
        那一屏上**一条正文带都没有** ⇒ ``locate_feed_post_tap`` 返回 ``None`` ⇒
        状态机只许**去做别的事**（往回滚一屏 / 回对账），**绝不许**发出 ``task_browse_*``
        去打那个盲坐标 —— 那一下正是 2026-10-08 两次实跑卡死的源头。

        ⚠️ 反过来说，这条也钉住了「``None`` 不是一个可以随便兜底的返回值」：
        ``locate_feed_post_tap(...) or FEED_FIRST_POST`` 这种「顺手写一下」的兜底
        会立刻在这里红。
        """
        machine = cm.CommunityStateMachine(self.templates, self.glyphs)
        machine.state = cm.CommunityState.FEED
        machine.active_task = "browse"
        machine.task_step = 0
        action = machine._drive_task(
            fixture("image_viewer_live_20261008"),
            cp.PageJudgement("feed_home", 1.0, ()),
        )
        self.assertNotEqual(
            action.name,
            "task_browse_1",
            "找不到正文带还去点盲坐标 —— 又会点开图片查看器，整条路线卡死",
        )

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
        machine.task_step = 2  # 「看完退回信息流」：一轮 11 步里的第 3 步（POST_BACK）
        action = machine._drive_task(
            fixture("post_detail_live_20261006"),
            cp.PageJudgement("post_detail", 1.0, ()),
        )
        self.assertEqual(action.name, "task_browse_3")
        self.assertNotIn(
            "post_detail",
            tuple(action.target_pages),
            "出口集合含来源页：点空了也判完成，分不出「点了没生效」与「点了生效了」",
        )
        self.assertIn("feed_home", tuple(action.target_pages))

    def test_task_retries_are_bounded_then_declared_impossible(self):
        """这一行跑完一轮还没变成「已完成」就再来一轮；连试 ``TASK_ATTEMPT_LIMIT`` **轮**
        ⇒ 记一笔「今天做不成」并往下走。

        ⚠️ 账本的粒度是**轮**，不是「一次动作」。旧粒度是一轮 = 1 次，所以上限必须
        大于要求的次数；现在是**一轮 = N 次**（浏览/点赞 3、分享 1），正常第 1 轮
        那行就翻成「已完成」，所以 3 轮是**纯容错**。

        ⚠️ 必须**有上限**：判据失灵时「试到成功为止」会无声转到状态超时，
        日志里只剩一句「页面识别超时」，看不出是哪条任务在磨。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        tasks = fixture("tasks_one_browse_done_live_20261006")
        feed = fixture("feed_before_signin_live_20261007")
        exchange = fixture("exchange_before_redeem_live_20261007")

        def run_one_round() -> str:
            """跑完整轮 → 经兑换中心回我的任务 → 返回对账那一帧的动作名。"""
            self._walk_this_round(machine)
            machine.next_action(feed)      # 一轮做完 ⇒ 回兑换中心
            machine.next_action(exchange)  # 路过兑换中心 ⇒ 点「获取积分卡」
            return machine.next_action(tasks).name

        machine.next_action(tasks)  # 排上「浏览帖子」
        for _ in range(cm.TASK_ATTEMPT_LIMIT - 1):
            self.assertEqual(run_one_round(), "start_task")   # 这一行还没变成「已完成」⇒ 原地再来
            self.assertIn("再来一轮", machine.last_reason)
        # 最后一轮：到上限 ⇒ 记一笔「今天做不成」，挑下一条待办（这一帧里是「分享帖子」）
        self.assertEqual(run_one_round(), "start_task")
        self.assertIn("browse", machine.stuck_tasks)
        self.assertIn("做不成", machine.last_reason)
        self.assertEqual(machine.active_task, "share")
        self.assertEqual(
            machine.task_attempts["browse"], cm.TASK_ATTEMPT_LIMIT
        )

    def test_a_round_that_stops_halfway_books_an_attempt(self):
        """一轮**没跑完**就回到「我的任务」⇒ 也必须记一笔（否则是死循环）。

        实跑形态：某一下没生效 ⇒ ``_drive_task`` 判「该在 A 页却停在 B 页」、
        把路线带回「我的任务」；回来看计数没涨 ⇒ 再排一轮 ⇒ 又作废……
        这一串动作名相邻两两都不同（``start_task`` / ``task_browse_1`` /
        ``back_to_tasks_via_exchange`` / ``goto_tasks_card``）⇒
        主循环那本「同一动作 4 次」的账**记不到它**，而每次点击都会刷新
        ``absolute_started``、绝对超时也兜不住。项目红线：绝不死循环。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        tasks = fixture("tasks_one_browse_done_live_20261006")
        feed = fixture("feed_before_signin_live_20261007")
        post = fixture("post_detail_live_20261006")
        exchange = fixture("exchange_before_redeem_live_20261007")

        machine.next_action(tasks)          # 排上浏览
        machine.next_action(feed)           # 第 1 步：点开帖子
        machine.next_action(post)           # 第 2 步：帖内下滑+停留
        # 第 3 步该在帖子详情点「退回」，却把路线带回我的任务 ⇒ 这一轮只走了 2/11
        machine._return_to_tasks(
            post, cp.PageJudgement("post_detail", 1.0, ()), "人为构造：中途作废"
        )
        machine.next_action(exchange)       # 路过兑换中心
        machine.next_action(tasks)          # 回来对账
        self.assertEqual(machine.task_attempts.get("browse"), 1, "没跑完的一轮必须记账")
        self.assertIn("没跑完", machine.last_reason)
        self.assertIn("再来一轮", machine.last_reason)

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

    # ---- 点赞：「先找再点」，位置不写死（2026-10-07 用户拍板的 C 方案）----
    #
    # ⚠️ 这一段的前身是「先读一个**写死的框**的颜色，绿了就再滑一次」，而真机复量
    #    发现**那个框根本不是 👍**（是 tab 栏「骑士团」三个字，纯白）⇒ 读色恒为
    #    「没点过」，闸门形同不存在；而它守的那个点击点 (911,735) 的 y 也随卡片
    #    高度漂（同帧实测两张卡差 558px）。现在改成：**在卡片带里找那颗空心 👍**，
    #    找不到就下滑。下面这几条钉住新的依据。

    def test_card_like_reading_box_is_centred_on_the_point_it_was_given(self):
        """读色框必须跟着**实际点下去的那个点**走，不能再是一个写死的框。

        ⚠️ 这是那道验收能不能成立的**唯一**依据：老写法读 (880,700,70,70)，
        而那一块是 tab 栏 ⇒「点完了变绿没有」永远读成「没变」，每遍白等 8 帧作废。
        """
        self.assertEqual(cm.pages.card_like_reading_box((904, 1333)), (881, 1312, 47, 43))
        self.assertEqual(cm.pages.card_like_reading_box((500, 700)), (477, 679, 47, 43))

    def test_the_locator_finds_the_unliked_thumb_and_not_the_liked_one(self):
        """``feed_cards_mixed`` 一屏里**同时**有已点赞（y≈780）和没点过（y≈1333）两颗。

        定位器必须挑中**没点过**那颗 —— 挑错了就是把别人的赞取消掉。
        断言落在「依据」上：返回的点必须离没点过那颗很近、离已点赞那颗很远。
        """
        frame = fixture("feed_cards_mixed_live_20261007")
        found = cp.locate_card_like(frame, self.templates)
        self.assertIsNotNone(found)
        unliked, liked = (904, 1333), (904, 780)
        self.assertLessEqual(abs(found[0] - unliked[0]) + abs(found[1] - unliked[1]), 4)
        self.assertGreater(
            abs(found[1] - liked[1]), 300, "挑中了已点赞那颗 —— 点下去会把赞取消"
        )

    def test_the_locator_does_not_match_an_already_liked_thumb(self):
        """分离度本身：已点赞那颗（实心青绿）在模板下**必须不过阈**。

        ⚠️ 这是「模板命中 = 还没点过」这条推理的**唯一**物证。少了它，
        有人把模板换成一张「两种长相都能匹配」的图，谁都不会红。
        """
        frame = fixture("feed_cards_mixed_live_20261007")
        template = self.templates["card_like_off"]
        strip_x, strip_y, _, _ = cp.CARD_LIKE_STRIP
        # 已点赞那颗的中心是 (904, 780)；把它那一小块单独喂给共享打分函数
        left = 904 - template.shape[1] // 2
        top = 780 - template.shape[0] // 2
        patch = frame[top : top + template.shape[0], left : left + template.shape[1]]
        score, _ = cp.best_match(patch.astype(np.float32), template.astype(np.float32))
        self.assertLess(
            float(score), cp.THRESHOLD,
            f"已点赞那颗在模板下拿到了 {score:.4f}（过阈了）—— 点下去会把赞取消",
        )
        self.assertGreaterEqual(strip_x, 0)  # 顺带确认搜索带常量还是正的
        self.assertGreaterEqual(strip_y, 0)

    def test_the_locator_returns_nothing_when_no_thumb_is_on_screen(self):
        """一屏里没有空心 👍 ⇒ 返回 ``None``，**不是**某个默认坐标。

        ``None`` 是「没找到」；调用方拿到它的正确反应是下滑再找，
        绝不能退回钉死的坐标（那颗 👍 是开关）。
        """
        for name in ("feed_before_signin_live_20261007", "tasks_all_done_live_20261006"):
            self.assertIsNone(
                cp.locate_card_like(fixture(name), self.templates), name
            )

    def _like_machine_at_the_step(self) -> cm.CommunityStateMachine:
        """把状态机摆到「正在跑点赞、该出手点第一颗了」。

        ⚠️ 为什么不走 ``next_action(tasks_page)`` 去排上它：竖屏口径下**没有一张
        「点赞未完成」的任务页夹具**（``tasks_fresh`` 是另一种口径，见
        ``test_community_pages`` 里的口径守卫），而 ``tasks_one_browse_done``
        那一帧的点赞行读出来**已经是「已完成」**。所以这里直接摆状态 ——
        被测的是 ``_drive_task`` 的「先找再点」，不是「挑哪条任务」那一步。

        ⚠️⚠️ **2026-10-11：点赞已摘出生产清单**（``TASK_SCRIPT`` / ``TASK_ROWS``，
        理由见 ``community_pages.TASK_ROWS`` 那段：服务端永久记住点赞状态 ⇒
        翻不到可点的 👍 ⇒ 死循环）。但**点赞的代码与机制一律保留**（用户拍板），
        所以这里的测试照旧要跑 —— 办法是**临时把点赞脚本注册回 ``TASK_SCRIPT``**。
        用 ``mock.patch.dict`` 而不是改生产常量：生产代码**一行不用动**，
        而机制护栏（先找再点 / 找不到就滑 / 滑满作废 / 点后验绿）**照旧被罩住**。
        将来要真正恢复点赞，只需把清单那一行加回去。
        """
        patcher = unittest.mock.patch.dict(
            cm.TASK_SCRIPT,
            # 次数**独立写死 3**（与 ``TASK_ROUND_TIMES`` 原来的值一致）：
            # 生产清单里已经没有 "like" 了，测试不该去读一个被删掉的常量。
            {"like": cm._round_script(cm._LIKE_ONE, 3)},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.active_task = "like"
        machine.task_step = 0
        return machine

    def test_like_step_clicks_the_point_it_just_located(self):
        """点赞那一步**现找**位置再点，并且把找出来的点当成动作的点击点。

        ⚠️ 脚本里那一步的 ``point`` 是 ``None``（= 位置运行时现找）——
        断言动作点 == 定位器给的坐标，才算钉住「真的用了找出来的那个点」。
        """
        machine = self._like_machine_at_the_step()
        expected = cp.locate_card_like(
            fixture("feed_cards_mixed_live_20261007"), self.templates
        )
        action = machine.next_action(fixture("feed_cards_mixed_live_20261007"))
        self.assertEqual(action.name, "task_like_1")
        self.assertEqual(action.point, expected)
        self.assertEqual(machine.task_step, 1)
        # 出手之后要等业务结果：那颗 👍 有没有变绿（下一条用例钉住它读的是哪个框）
        self.assertEqual(machine.pending_verify, cm._VERIFY_LIKE_ON)
        self.assertEqual(machine.like_point, expected)

    def test_the_like_verify_runs_even_when_the_click_was_the_last_step(self):
        """「点 👍」是点赞单元的**唯一**一步 ⇒ 一轮里总有一次它正好是脚本最后一步。

        ⚠️ 那一刻两道判断会撞在一起：「还有一步要等结果」与「脚本跑完了、回去对账」。
        顺序反了（先判 ``task_step >= len(script)``）的后果是
        ``pending_verify`` **永远够不到**：点完立刻回「我的任务」，那颗 👍 到底
        绿没绿**一次都没读过** —— 等于这道验收从来没存在过（2026-10-07 实测正是这样）。

        这里把状态机摆到**最后一步**再点，然后喂同一帧：
        必须在**等**（返回 ``None``、不动 ``task_step``），而不是掉头回去对账。
        """
        machine = self._like_machine_at_the_step()
        machine.task_step = len(cm.TASK_SCRIPT["like"]) - 1  # 最后一步
        mixed = fixture("feed_cards_mixed_live_20261007")
        self.assertEqual(machine.next_action(mixed).name, "task_like_3")
        self.assertEqual(machine.pending_verify, cm._VERIFY_LIKE_ON)
        # 下一帧：那颗 👍 还没变绿 ⇒ 只等，**不**再出手（它是开关），也**不**提前收工
        self.assertIsNone(machine.next_action(mixed))
        self.assertEqual(machine.task_step, len(cm.TASK_SCRIPT["like"]))
        self.assertIn("等看到", machine.last_reason)

    def test_a_like_round_keeps_going_after_the_verify_passes(self):
        """验收通过 = **这一步**做成了 ⇒ 接着推本轮的下一步，**不许掉头回对账**。

        ⚠️ 2026-10-07 真机实跑抓到的 P0（20:36 那次）：``_await_step_result``
        原来在验收通过时**自己** ``return self._return_to_tasks(...)``，于是
        「一轮 ``TASK_ROUND_TIMES["like"]`` 次」**永远只做第 1 次** —— 真机日志里
        只有 ``task_like_1``，没有 ``_2`` / ``_3``；回到「我的任务」又因
        ``task_step < len(script)`` 被判「这一轮没跑完就回来了」，于是重排一轮、
        再点 1 个 …… 直到 ``TASK_ATTEMPT_LIMIT`` 轮全烧在这上面。

        这里构造「验收通过」：把 ``like_point`` 指到 ``feed_cards_mixed`` 里
        **已经点过**的那颗（y≈780，实心青绿）⇒ 颜色判据读出来就是「变绿了」。
        通过之后状态机必须**接着出手第 2 步**，而不是返回回对账的动作。
        """
        machine = self._like_machine_at_the_step()
        mixed = fixture("feed_cards_mixed_live_20261007")
        first = machine.next_action(mixed)
        self.assertEqual(first.name, "task_like_1")
        self.assertEqual(machine.task_step, 1)
        # 构造「点下去之后那颗真的变绿了」
        machine.like_point = (904, 780)
        action = machine.next_action(mixed)
        self.assertIsNotNone(action, "验收通过后本轮还剩 2 步，状态机必须继续出手")
        self.assertEqual(
            action.name,
            "task_like_2",
            "验收通过后掉头回「我的任务」了 —— 「一轮 N 次」会永远只做第 1 次",
        )
        self.assertEqual(machine.task_step, 2)

    # ── 回「我的任务」那条路：别假设「兑换」图标还在视野里（2026-10-07 立）──

    def test_the_exchange_icon_is_visible_only_before_the_feed_is_scrolled(self):
        """「兑换」图标：没滚过看得见、滚过看不见 —— 这是那道闸门的**唯一物证**。

        ⚠️ 少了它，有人把模板换成一张「有没有四宫格都能匹配」的图，谁都不会红，
        而回程又会照旧去点帖子图片（那一按**不可逆**：打开图片查看器就卡死）。

        ⚠️ 2026-10-09 补 ``feed_grid_at_top``：四宫格有**两个**落点 —— 未滚动的
        y=532 与**滚回真正顶部**的 y=275。老搜索带只罩 380~680 ⇒ 在 y=275 那屏上
        恒判「看不见」（用户报的「兑换按钮滑下去了找不着」，滚 3 次全白滚）。
        """
        for name in (
            "feed_before_signin_live_20261007",
            "feed_after_signin_live_20261007",
            "feed_list_live_20261006",
            # 滚回真正顶部的那一屏（图标 y=275）：必须在正向样本里
            "feed_grid_at_top_live_20261009",
        ):
            self.assertTrue(
                cp.feed_exchange_icon_visible(fixture(name), self.templates),
                f"{name}：四宫格明明在视野里，却看不见「兑换」图标",
            )
        for name in (
            "feed_cards_mixed_live_20261007",
            "feed_cards_all_todo_live_20261007",
        ):
            self.assertFalse(
                cp.feed_exchange_icon_visible(fixture(name), self.templates),
                f"{name}：四宫格已经滚出视野，却还说看得见「兑换」图标",
            )

    def test_the_exchange_icon_search_strip_reaches_both_grid_positions(self):
        """搜索带必须**同时**罩住四宫格的两个落点（未滚动 y=532 / 滚到顶 y=275）。

        ⚠️ 这条钉的是 2026-10-09 那个 bug 的**根**：老带子 ``(360, 380, 160, 300)``
        只认「未滚动」那个高度，于是「滚回顶部」这一屏上图标明明在、分数却是 0.0
        ⇒ ``feed_exchange_icon_visible()`` 恒假 ⇒ 往回滚 3 次全白滚报错收手。

        ⚠️ 断言里的两个 y **独立写死**（不从 ``FEED_ICON_STRIP`` 反推），否则
        带子一改断言跟着改、注入违规纹丝不动 —— 那正是「护栏拿被测常量当输入」。
        """
        _x, top, _w, height = cp.FEED_ICON_STRIP
        bottom = top + height
        for icon_y, why in ((532, "未滚动的信息流"), (275, "滚回真正顶部")):
            with self.subTest(icon_y=icon_y):
                self.assertLessEqual(
                    top,
                    icon_y,
                    f"搜索带上沿 {top} 比「{why}」的图标中心 y={icon_y} 还低 "
                    "—— 那一屏会被恒判「看不见兑换图标」",
                )
                self.assertGreaterEqual(
                    bottom,
                    icon_y,
                    f"搜索带下沿 {bottom} 够不到「{why}」的图标中心 y={icon_y}",
                )

    def test_the_exchange_icon_strip_stays_clear_of_a_scrolled_away_grid(self):
        """搜索带放得再宽也不许把「四宫格真滚走了」误判成看得见。

        与上一条是一对：上一条防「够不着」，这一条防「放太宽变成永远为真」。
        ⚠️ 期望值独立写死 —— 真滚走那一帧实测 0.7080、阈值 0.82。
        """
        self.assertGreater(cp.THRESHOLD, 0.7080, "阈值高不过「真滚走」那一帧的分数")
        # 带上沿不许一路放到标题栏里（那样任何一页都会蹭到）
        _x, top, _w, _h = cp.FEED_ICON_STRIP
        self.assertGreaterEqual(
            top, 200, f"搜索带上沿 {top} 已经伸进顶部标题栏，容易蹭到别的页"
        )

    def test_returning_to_tasks_rolls_back_when_the_exchange_icon_is_off_screen(self):
        """信息流滚过之后 ⇒ **先往回滚一屏**，不许照旧点那个钉死的坐标。

        ⚠️ 2026-10-07 20:39 实跑：``FEED_ICON_EXCHANGE`` 写死成 (438,538)，
        滚过之后那个位置底下已经是**帖子里的图片** ⇒ 点下去打开了图片查看器
        （现场帧 ``20261007_203930_662457_timeout_feed.png`` 就是那张
        「平衡性调整公告」大图），画面认不出、整条路线卡到超时失败。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        scrolled = fixture("feed_cards_mixed_live_20261007")
        page = cp.PageJudgement("feed_home", 1.0, ())
        action = machine._return_to_tasks(scrolled, page, "任务做完了")
        self.assertEqual(action.name, "feed_scroll_back_for_exchange")
        # 坐标**独立写死**（不用 cm.FEED_ICON_SCROLL_START / _END）：
        # 拿被测常量当自己的输入，常量一改断言跟着改，注入违规纹丝不动。
        # 写死之后，改行程会立刻顶红这条，逼人来看一眼「新行程真的是想要的吗」。
        self.assertEqual(action.point, (60, 360))
        self.assertEqual(action.swipe_end, (60, 1750))
        self.assertIn("看不见", action.reason)

    def test_returning_to_tasks_clicks_once_the_exchange_icon_is_back(self):
        """四宫格在视野里 ⇒ 直接点那个实测有效的坐标（判据只管在不在，点不变）。"""
        machine = self.machine(state=cm.CommunityState.FEED)
        top = fixture("feed_before_signin_live_20261007")
        page = cp.PageJudgement("feed_home", 1.0, ())
        action = machine._return_to_tasks(top, page, "任务做完了")
        self.assertEqual(action.name, "back_to_tasks_via_exchange")
        self.assertEqual(action.point, cm.FEED_ICON_EXCHANGE)
        self.assertEqual(machine.feed_icon_reswipes, 0, "看见并点下去之后计数要归零")

    def test_returning_to_tasks_gives_up_instead_of_rolling_forever(self):
        """真滚满上限还看不见 ⇒ **报错收手**。绝不蒙着点 —— 那一按不可逆。

        ⚠️ 2026-10-09 起「滚了几屏」按**执行了**记：每一滑之后页面要真的动过
        （正文带位置表变了）才准记下一笔。所以这里每滑一屏换一帧（真机夹具
        ``feed_cards_mixed`` 与 ``feed_cards_all_todo``，两张都是滚过的信息流、
        都看不见「兑换」图标、正文带位置不同）。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        scrolled_a = fixture("feed_cards_mixed_live_20261007")
        scrolled_b = fixture("feed_cards_all_todo_live_20261007")
        page = cp.PageJudgement("feed_home", 1.0, ())
        # 每一滑都得让画面真的动过（正文带位置表变了）才准记下一笔 ⇒ 帧要挨着换，
        # 而且**收尾那一下也不能撞回用过的位置**（撞回去 = 画面没动 = 那是「还没落定」，
        # 本来就不该判放弃）。上限 3→4 之后交替两张会错位，所以补第三张。
        frames = [scrolled_a, scrolled_b, scrolled_feed(scrolled_b, 240)]
        # 上限**独立写死 4**（不引 ``cm.FEED_ICON_RESWIPE_LIMIT``）：它是被测常量，
        # 直接引用的话「上限被改大」这条照样绿 —— 等于没护栏。
        for index in range(4):
            self.assertEqual(
                machine._return_to_tasks(
                    frames[index % len(frames)], page, "任务做完了"
                ).name,
                "feed_scroll_back_for_exchange",
            )
        self.assertEqual(machine.feed_icon_reswipes, 4)
        with self.assertRaises(cm.CommunityDataMissing) as ctx:
            machine._return_to_tasks(scrolled_feed(scrolled_a, 360), page, "任务做完了")
        self.assertIn("看不见", str(ctx.exception))

    def test_a_still_frame_does_not_burn_the_scroll_back_ledger(self):
        """**2026-10-09 13:04 实跑的回归护栏**：画面不动就不许烧「已滚屏数」的账。

        主循环对同名动作有重试节流：节流窗口里状态机每一帧都会重新想滑。
        旧写法按帧记账，3 屏预算几秒烧穿、实际只滑了 1 屏，然后报
        「往回滚了 3 屏」（假话）。新语义：同一帧反复喂 ⇒ 只记第 1 屏的账，
        后续只重发、不记账、**不报错**（等节流放开、页面真动了才记下一笔）。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        scrolled = fixture("feed_cards_mixed_live_20261007")
        page = cp.PageJudgement("feed_home", 1.0, ())
        for _ in range(cm.FEED_ICON_RESWIPE_LIMIT + 2):
            action = machine._return_to_tasks(scrolled, page, "任务做完了")
            self.assertEqual(action.name, "feed_scroll_back_for_exchange")
        self.assertEqual(
            machine.feed_icon_reswipes,
            1,
            "画面没动过，账本必须还停在第一滑 —— 按帧烧账就是 2026-10-09 的假报错",
        )

    def test_a_step_with_no_point_and_no_locator_result_refuses_to_click(self):
        """位置没找着、脚本又没写死 ⇒ **当场抛**，绝不静默点 (0,0)。

        静默退回原点那种失败最难查：屏幕上真的会在左上角点一下，而日志一片祥和。

        ⚠️ 2026-10-11：载体从「点赞」换成「浏览」—— 点赞已摘出 ``TASK_SCRIPT``，
        但这条测的是 ``_step_action`` 的**通用机制**（位置现找的那一步，
        定位器没给出点时必须抛），浏览的 ``tap_post`` 用的是同一套。
        **机制还在，就得还有护栏。**
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.active_task = "browse"
        machine.task_step = 0
        with self.assertRaises(RuntimeError) as ctx:
            machine._step_action(
                "task_browse_1", cm.TASK_SCRIPT["browse"][0], machine.last_page or type(
                    "P", (), {"name": "feed_home"}
                )(),
                reason="人为构造：没把找出来的点传进来",
            )
        self.assertIn("没有点击点", str(ctx.exception))

    def test_like_step_scrolls_when_this_screen_has_nothing_to_like(self):
        """这一屏**找不到**没点过的 👍 ⇒ 下滑一屏再找（用户拍板的 C 方案原话）。

        断言的是依据：动作名是再滑一次、``task_step`` **没有**推进
        （推进了就等于把这步当成点过了），滑动走的是起点→终点。
        """
        machine = self._like_machine_at_the_step()
        action = machine.next_action(fixture("feed_before_signin_live_20261007"))
        self.assertEqual(action.name, "task_like_reswipe")
        self.assertEqual(action.point, cm.FEED_TASK_SCROLL_START)
        self.assertEqual(action.swipe_end, cm.FEED_TASK_SCROLL_END)
        self.assertEqual(machine.task_step, 0, "还没点下去，不该算完成这一步")
        self.assertEqual(machine.like_reswipes, 1)
        self.assertIn("没有还没点过的", action.reason)

    def test_like_step_gives_up_instead_of_swiping_forever(self):
        """连着真滑够 ``LIKE_RESWIPE_LIMIT`` 屏还是没找到 ⇒ 收手、本遍作废。

        ⚠️ 必须有上限：否则「一屏全是已点过的卡片」会把主循环卡在信息流里空转。
        ⚠️ 2026-10-09 起按**执行了**记（画面动了才准记下一笔），所以每一滑
        换一帧：基帧 ``feed_before_signin`` 上找不到可点的 👍，另外两张是它
        「往下滚了一屏 / 两屏」的样子（``scrolled_feed``，见那里的说明）。

        ⚠️ 别用 ``np.roll`` 造「滚过了」：整幅绕回去会把顶栏也挪走，页面判据
        直接认不出（实测 0.0000 ⇒ 抛「社区画面认不出」），测的根本不是这条路径。
        """
        machine = self._like_machine_at_the_step()
        top = fixture("feed_before_signin_live_20261007")
        far_down = scrolled_feed(top, 480)
        near_down = scrolled_feed(top, 200)
        # 顺序：顶 → 滚下去 480 → 滚下去 200 → 回顶。每一滑画面都得动过才准记
        # 下一笔；收尾那帧是「顶部」的样子（兑换图标在视野里）⇒ 交回兑路径。
        frames = [top, far_down, near_down, top]
        names = []
        for index in range(cm.LIKE_RESWIPE_LIMIT + 1):
            names.append(machine.next_action(frames[index]).name)
        self.assertEqual(
            names[: cm.LIKE_RESWIPE_LIMIT],
            ["task_like_reswipe"] * cm.LIKE_RESWIPE_LIMIT,
        )
        self.assertEqual(names[cm.LIKE_RESWIPE_LIMIT], "back_to_tasks_via_exchange")
        self.assertEqual(machine.like_reswipes, cm.LIKE_RESWIPE_LIMIT)

    def test_scrolling_stops_when_the_page_says_it_is_already_at_the_top(self):
        """**2026-10-10 用户拍板的「滚到顶为止」**：画面说「我到底了」就别再滚。

        到顶的 H5 再往下拖就是不动（正文带位置表一个像素都不变）。这条钉的是
        「画面连续不动 ⇒ 当场收手」，而不是「硬把次数预算烧完才收手」——
        后者正是 10-10 实跑里那 4 次白滑的来历。

        ⚠️ 与 ``test_a_swipe_that_never_executes_is_reported_honestly`` 成对：
        那条是「从头到尾没动过」（手势故障，要报「没看到页面滚动」），
        这条是「先动过、后来不动了」（正常到底）。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        scrolled_a = fixture("feed_cards_mixed_live_20261007")
        scrolled_b = fixture("feed_cards_all_todo_live_20261007")
        page = cp.PageJudgement("feed_home", 1.0, ())
        machine._return_to_tasks(scrolled_a, page, "任务做完了")  # 立基线，记第 1 笔
        machine._return_to_tasks(scrolled_b, page, "任务做完了")  # 画面动了，记第 2 笔
        self.assertEqual(2, machine.feed_icon_reswipes)
        machine._return_to_tasks(scrolled_b, page, "任务做完了")  # 没动：只是「还没落定」
        with self.assertRaises(cm.CommunityDataMissing) as ctx:
            machine._return_to_tasks(scrolled_b, page, "任务做完了")  # 又没动 ⇒ 到底了
        self.assertIn("滚到顶", str(ctx.exception))
        self.assertEqual(
            2,
            machine.feed_icon_reswipes,
            "到顶就该停：不许把次数预算烧完才收手，白滚那几下每一下都要 3 秒",
        )

    def test_a_swipe_that_never_executes_is_reported_honestly(self):
        """上一滑一直没生效（画面一直不动）⇒ 到帧数上限要**如实**报错。

        报的必须是「手势没被执行」，**不是**「滚了几屏没找到」—— 那是两回事：
        前者是通道/节流的故障，后者才是页面变了。旧写法把两者混在一句
        「往回滚了 3 屏」里（2026-10-09 13:04 实跑：实际只滑了 1 屏）。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        scrolled = fixture("feed_cards_mixed_live_20261007")
        page = cp.PageJudgement("feed_home", 1.0, ())
        with self.assertRaises(RuntimeError) as ctx:
            for _ in range(cm.SWIPE_UNEXECUTED_FRAME_LIMIT + 2):
                machine._return_to_tasks(scrolled, page, "任务做完了")
        self.assertIn("没看到页面滚动", str(ctx.exception))
        self.assertEqual(
            machine.feed_icon_reswipes,
            1,
            "从头到尾画面没动过，账本必须停在第一滑",
        )

    def test_the_like_verify_reads_the_box_it_actually_clicked(self):
        """出手之后的验收必须读**刚点的那一颗**：把它涂绿 ⇒ 认「成了」。

        ⚠️ 反过来也成立，而且这才是关键：**不涂**的时候必须认「还没绿」。
        老写法读的是一个写死的框（实际是 tab 栏）⇒ 两边都会读成「没绿」，
        于是每一遍都白等 8 帧再作废 —— 而日志只会说「等了 8 帧没看到变绿」，
        看不出是读错了地方。
        """
        machine = self._like_machine_at_the_step()
        mixed = fixture("feed_cards_mixed_live_20261007")
        action = machine.next_action(mixed)
        # ⚠️ 涂色框要**独立算**（拿点 + 常量），不能调 ``card_like_reading_box`` ——
        # 用被测函数自己算「该涂哪儿」，等于自证：函数挪到哪儿，涂色跟着挪到哪儿，
        # 恒成立（第一版就是这么写的，注入「退回写死框」时纹丝不动）。
        half_w = cm.pages.CARD_LIKE_READ_SIZE[0] // 2
        half_h = cm.pages.CARD_LIKE_READ_SIZE[1] // 2
        x, y = action.point[0] - half_w, action.point[1] - half_h
        w, h = cm.pages.CARD_LIKE_READ_SIZE
        self.assertGreater(y, 200, "读色框得落在卡片区里，不能是顶部那排 tab")
        # ① 原样那一帧：那颗还是空心的 ⇒ 验收必须**不**通过
        self.assertFalse(machine._evidence_seen(mixed, cm._VERIFY_LIKE_ON))
        # ② 把**这一次点的那个框**涂成点赞态的实心青绿 ⇒ 验收必须通过
        painted = mixed.copy()
        painted[y : y + h, x : x + w] = (40, 190, 90)
        self.assertTrue(machine._evidence_seen(painted, cm._VERIFY_LIKE_ON))

    def test_the_like_verify_refuses_to_claim_success_when_nothing_was_clicked(self):
        """没点过任何一颗却要验「变绿了」⇒ 抛，不许猜。

        猜「绿了」会把没做的事记成做成了；猜「没绿」会让本遍静默作废。
        两种都在日志里看不出来 ⇒ 当成接线自检响出来。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.active_task = "like"
        self.assertIsNone(machine.like_point)
        with self.assertRaises(RuntimeError) as ctx:
            machine._evidence_seen(
                fixture("feed_cards_mixed_live_20261007"), cm._VERIFY_LIKE_ON
            )
        self.assertIn("接线断了", str(ctx.exception))

    def test_the_last_allowed_round_still_gets_checked_before_being_declared_impossible(self):
        """第 ``TASK_ATTEMPT_LIMIT`` 轮**同时**是最后一轮 ⇒ 顺序必须是
        「先看这一行成没成，再考虑判死」。

        ⚠️ 反过来的后果：明明这一轮把 3 次都做完了、那一行也翻成了「已完成」，
        却被「已经跑满 3 轮」先判死 ⇒ 记成「今天做不成」，白做一整轮。

        用「第 3 轮才成」钉住它：前 2 轮读到「未完成」、第 3 轮读到「已完成」
        ⇒ 必须判成，且**不许**进 ``stuck_tasks``。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        not_done = fixture("tasks_one_browse_done_live_20261006")
        all_done = fixture("tasks_all_done_live_20261006")
        feed = fixture("feed_before_signin_live_20261007")
        exchange = fixture("exchange_before_redeem_live_20261007")

        def run_one_round(tasks_frame) -> str:
            self._walk_this_round(machine)
            machine.next_action(feed)
            machine.next_action(exchange)
            return machine.next_action(tasks_frame).name

        machine.next_action(not_done)  # 排上「浏览帖子」
        for _ in range(cm.TASK_ATTEMPT_LIMIT - 1):
            self.assertEqual(run_one_round(not_done), "start_task")
            self.assertNotIn("browse", machine.stuck_tasks, "最后一轮之前不许判死")
        # 最后一轮：这一行终于变成「已完成」⇒ 成了（不许被「跑满轮数」抢先判死）。
        self.assertNotEqual(run_one_round(all_done), "start_task")
        self.assertNotIn("browse", machine.stuck_tasks)
        self.assertIn("做成了", machine.last_reason)

    def test_retry_log_does_not_claim_the_counter_did_not_move(self):
        """日志别写「计数没动」—— 对账读的是**按钮**，3 次制的计数每轮都在动。

        照这句话排错会被带偏（2026-10-07 修正措辞）。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        machine.next_action(fixture("tasks_one_browse_done_live_20261006"))
        self._walk_this_round(machine)
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

    def test_network_error_refreshes_in_place_instead_of_leaving(self):
        """H5 死了（整页「网络连接异常，下拉刷新」）⇒ **照它要求的做：下拉刷新**。

        ⚠️ 2026-10-07 用户拍板改掉旧的「退出去重进」，原话：
        「你就是应该按照他的要求下拉刷新」。

        断言的是**四件事**，缺一都说明改回去了：

        - 动作名换成了 ``refresh_community_page``；
        - 它是**滑动**（``swipe_end`` 非空）—— 少了这个字段，主循环会在**起点点一下**，
          整条第①步就退化成「点一下空白」，后面全对不上；
        - 点**不是**那个钉死的退出点 ``FEED_CLOSE``：这一页的 X 实测在 (1000, 78)，
          而 ``FEED_CLOSE``=(937,92) 在这里落在空白上（旧写法就是这么空转的）；
        - 状态是 ``REFRESHING``，**不是** ``WEB_ENTRY`` —— 后者会让通道去等「转回横屏」，
          而页压根没关，等来的只有超时。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        action = machine.next_action(fixture("network_error_live_20261006"))
        self.assertEqual(action.name, "refresh_community_page")
        self.assertEqual(action.point, cm.NETWORK_PULL_START)
        self.assertEqual(action.swipe_end, cm.NETWORK_PULL_END)
        self.assertNotEqual(action.point, cm.FEED_CLOSE)
        self.assertNotIn("web_activity_list", action.target_pages)
        self.assertEqual(machine.state, cm.CommunityState.REFRESHING)

    def test_the_refresh_gesture_drags_downwards(self):
        """下拉刷新 = **手指往下移**（起点的 y 小于终点的 y）。

        方向写反就成了「上滑」，那在 webview 里是滚动、不是刷新 —— 页面不会有任何反应，
        而日志上看起来和成功一模一样（动作发出去了、没报错）。所以方向单独钉一条。
        """
        self.assertLess(cm.NETWORK_PULL_START[1], cm.NETWORK_PULL_END[1])
        self.assertGreater(cm.NETWORK_PULL_MS, 300)

    def test_network_error_does_not_count_every_frame(self):
        """同一页连着几帧都报异常 ⇒ 只记**一次**账。

        ⚠️ 这是旧写法实跑抓到的形状：计数器**按帧**涨（实跑 21 秒涨了 3），
        于是「页面刚死两秒」就被判成「拉了 3 次都不行」直接停手。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        frame = fixture("network_error_live_20261006")
        for _ in range(5):
            self.assertEqual(machine.next_action(frame).name, "refresh_community_page")
        self.assertEqual(machine._network_refreshes, 1)

    def test_network_error_gives_up_after_the_refresh_budget(self):
        """拉活次数用完 ⇒ 响亮停手，不无限刷。

        每一轮先模拟「拉活之后页面活过来了」（状态被别的页改掉）再让它死 ——
        这才是计数器要管的那件事（跨页面的反复横跳）。
        """
        machine = self.machine(state=cm.CommunityState.FEED)
        frame = fixture("network_error_live_20261006")
        for _ in range(cm.NETWORK_REFRESH_LIMIT):
            machine.state = cm.CommunityState.FEED
            self.assertEqual(machine.next_action(frame).name, "refresh_community_page")
        machine.state = cm.CommunityState.FEED
        with self.assertRaises(RuntimeError) as ctx:
            machine.next_action(frame)
        self.assertIn("网络连接异常", str(ctx.exception))
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
                # ⚠️ 滑动的**终点**同样要落在画布内：``PortraitChannel.swipe`` 把它
                # 直接拼进 adb 命令，越界那一下由安卓侧静默失败 —— 画面看着没动，
                # 日志上却是一条「执行滑动」，最难查的那种。
                if action.swipe_end:
                    ex, ey = action.swipe_end
                    self.assertTrue(
                        0 <= ex < width and 0 <= ey < height,
                        f"{action.name} 滑动终点 {action.swipe_end} 越界",
                    )

    def test_ack_redeem_done_accepts_landing_back_on_the_exchange_center(self):
        """「兑换成功」点确认之后，**落点是兑换中心**（一次退两级），不是商品详情。

        ⚠️ 2026-10-07 真机：目标只写 ``item_detail`` ⇒ 转场永远不成立 ⇒ 主循环把状态机
        随后给出的 ``open_item``（下一件要兑的）**丢掉** ⇒ 整条兑换流程卡 66 秒后失败。
        两轮实跑都在同一处，日志原文：

            ack_redeem_done 原页面=redeem_done 期望页面=item_detail
            当前已确认页面=exchange_center 内部状态=兑换中心

        现场帧 ``20261007_212358_801234_timeout_transition_ack_redeem_done.png``
        就是兑换中心本体（四张卡都在、行动力已是「每日限购 2/2」）。
        """
        machine = self.machine(state=cm.CommunityState.ORDER_CONFIRM)
        action = machine.next_action(fixture("redeem_success_live_20261006"))
        self.assertEqual(action.name, "ack_redeem_done")
        self.assertIn("exchange_center", action.target_pages)
        self.assertIn("item_detail", action.target_pages)


class PreviewKeepsSwipeLedgerTests(unittest.TestCase):
    """``preview``（试算）不许把「滑动手势的账本」留在外面。

    2026-10-10 真机事故（用户报「社区签到报错」）：主循环**每帧先试算、
    再真跑**，两次喂的是**同一帧**画面（``transactional_runner_base.run``：
    ``preview`` 拿签名做两帧稳定确认，确认过了才 ``next_action`` 真出手）。
    而 ``_register_swipe_emission`` 的账本（``_pending_swipe_*``）没进快照
    ⇒ 真跑那一次比到的是「刚刚试算时写下的基线」和**同一帧** ⇒ 恒判等
    ⇒ 恒判「页面没动」⇒ ``like_reswipes`` / ``feed_icon_reswipes`` 永远停在 0
    ⇒ 两条「滑了 N 屏就收手」的闸门**同时失效**，只能等主循环自己的 4 次
    重试烧完，报一个词不达意的 ``retry_exhausted``。

    症状极具误导性：日志里全是「上一滑还没执行」「仍在等第 0 屏生效」，
    而同一段日志里点赞点坐标一直在变（（904,1111）→（904,723）→（904,1103））、
    四宫格也真的被滚回来过 —— 页面明明在动，尺子说它没动。

    这三步（拍快照 → 调 ``_register_swipe_emission`` → 还原）就是 ``preview``
    内部所做的事。**这里直调而不从 ``preview`` 进**：要走到那条分支得先把
    ``_drive_task`` 铺到「一轮动作做完、回去核对计数」，铺出来的场景本身
    比被测行为还长，一旦哪天铺的路径断了，护栏会**静静地空转**（对着一个
    走不到 ``_register_swipe_emission`` 的机器断言「账本没变」，永远绿）。
    """

    #: 手势名**独立写死**：不从 ``community`` 里取常量，免得实现一改断言跟着改。
    SWIPE = "feed_scroll_back_for_exchange"
    #: 两个「滚动位置」的正文带位置表，也独立写死。差 780 > 阈值 120。
    TOP_FRAME_TOPS = [120, 240, 360]
    SCROLLED_FRAME_TOPS = [900, 1020, 1140]

    @classmethod
    def setUpClass(cls):
        cls.templates, cls.glyphs = cm.build_screen_reader(TEMPLATES)

    def machine(self) -> cm.CommunityStateMachine:
        return cm.CommunityStateMachine(self.templates, self.glyphs)

    def preview_this_frame(self, machine: cm.CommunityStateMachine, tops) -> None:
        """把 ``preview`` 的内部三步照原样走一遍（拍快照 → 试算 → 还原）。"""
        snapshot = machine._snapshot()
        try:
            machine._register_swipe_emission(self.SWIPE, tops)
        finally:
            machine._restore(snapshot)

    def real_run_this_frame(self, machine: cm.CommunityStateMachine, tops) -> bool:
        """主循环真正出手的那一次（用的是同一帧、同一份位置表）。"""
        return machine._register_swipe_emission(self.SWIPE, tops)

    def test_the_first_swipe_still_counts_after_the_preview(self):
        """试算过之后，真跑那一次**必须**记上账（这就是本次事故的核心）。"""
        machine = self.machine()
        self.preview_this_frame(machine, self.TOP_FRAME_TOPS)
        self.assertTrue(
            self.real_run_this_frame(machine, self.TOP_FRAME_TOPS),
            "试算把基线留下了：真跑只能拿它跟自己比，恒判「页面没动」",
        )

    def test_a_frame_that_really_moved_still_counts_after_the_preview(self):
        """页面真的滚过了 ⇒ 第二滑也要记上账（别只修好第一滑）。"""
        machine = self.machine()
        self.preview_this_frame(machine, self.TOP_FRAME_TOPS)
        self.assertTrue(self.real_run_this_frame(machine, self.TOP_FRAME_TOPS))
        self.preview_this_frame(machine, self.SCROLLED_FRAME_TOPS)
        self.assertTrue(
            self.real_run_this_frame(machine, self.SCROLLED_FRAME_TOPS),
            "画面动了却没记账：上面那条会变成「永远为真」",
        )

    def test_a_frame_that_did_not_move_is_still_not_counted(self):
        """画面没动的下一帧仍然不许记账 —— 与上面那条成对，防它变成永远为真。"""
        machine = self.machine()
        self.preview_this_frame(machine, self.TOP_FRAME_TOPS)
        self.assertTrue(self.real_run_this_frame(machine, self.TOP_FRAME_TOPS))
        self.preview_this_frame(machine, self.TOP_FRAME_TOPS)
        self.assertFalse(
            self.real_run_this_frame(machine, self.TOP_FRAME_TOPS),
            "画面一动没动却记了账",
        )

    def test_the_preview_does_not_burn_the_unexecuted_streak(self):
        """试算不许消耗「连发 N 帧都没看到页面滚」的那个计数。

        那个计数到 30 会如实报错。若试算每次都 +1，上限会**提前一半烧穿**：
        正常的一帧（试算 + 真跑）被算成两帧。
        """
        machine = self.machine()
        self.real_run_this_frame(machine, self.TOP_FRAME_TOPS)
        for _ in range(5):
            self.preview_this_frame(machine, self.TOP_FRAME_TOPS)
        self.assertEqual(0, machine._pending_swipe_streak)


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
        # 连着几次「等满超时」（抛 ``OrientationError``、方向也不动），之后才正常。
        # ⚠️ 需要它是因为「收尾挨个试三颗 ⊗」那条新逻辑：要测的出「第一颗点了没用
        # ⇒ 换第二颗」**必须**让第一次 ``wait_for_landscape`` 真的抛超时
        # —— 真机上「点了没用的那颗」正是这个形态（等满 5 秒抛 ``OrientationError``）。
        self.wait_failures_left: Optional[int] = None

    def is_portrait(self) -> bool:
        self.probes += 1
        return self.portrait

    def set_event_sink(self, sink) -> None:
        """``ChannelSwitch`` 装配时会调它（把竖屏通道的等转屏日志接到运行日志上）。

        ⚠️ 2026-10-09 补：以前只有不用 ``runner.run()`` 的测试，替身缺这个方法也照样全绿
        —— 一旦有测试真的跑主循环（装配那一步），缺它就会当场 ``AttributeError``。
        """
        self.sink = sink

    def _wait(self, target_portrait: bool, label: str) -> None:
        self.calls.append(f"wait_{label}")
        if self.wait_failures_left:
            self.wait_failures_left -= 1
            raise OrientationError(
                f"等待模拟器切成{'竖屏' if target_portrait else '横屏'}超时"
                "（已等 5.0 秒）；当前客户区=1920x1080"
            )
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

    def test_the_web_dying_ends_the_pending_transition(self):
        """网页死掉时，把「等着的那个转场」判成**已结束**，否则补救动作会被主循环丢掉。

        ⚠️ 这是 2026-10-07 实跑抓到的形状，也是**旧下加拉活（退出去重进）压根没点出去**
        的原因：主循环对「已发出、还没验收的换页动作」有一条规矩 —— ``confirmed_page``
        既不是来源页也不是目标页时，**把状态机这一帧给出的动作丢掉**
        （``runner_base`` 里 `elif last_transition_action is not None` 那一段）。

        实跑日志 20:31:35 点「兑换」→ 20:32:00 连记 3 次「网络异常」，
        中间**一条 ``执行点击 动作=logout_community`` 都没有** —— 全被丢掉了。

        断言：pending 的动作在哪一种 ``confirmed_page`` 下会被判「结束」。
        """
        runner = self.make_runner(dry_run=True)
        pending = cm.CommunityAction(
            "goto_tasks_via_exchange",
            (438, 538),
            source_page="feed_home",
            target_pages=("exchange_center", "exchange_empty"),
        )
        refresh = cm.CommunityAction(
            "refresh_community_page",
            cm.NETWORK_PULL_START,
            swipe_end=cm.NETWORK_PULL_END,
            source_page="network_error",
            in_page_evidence="「网络连接异常，下拉刷新」这一页消失",
        )
        # 网页死了 ⇒ 结束（这才是本条要保的）
        self.assertTrue(runner._transition_completed(pending, refresh, "network_error"))
        # 目标真的到了 ⇒ 照旧结束
        self.assertTrue(runner._transition_completed(pending, refresh, "exchange_center"))
        # 中途认出的别的页 ⇒ **不许**当成结束（老规矩，别为了社区这条路线放宽）
        self.assertFalse(runner._transition_completed(pending, refresh, "tasks_page"))
        self.assertFalse(runner._transition_completed(pending, refresh, "unknown"))

    def test_the_transition_abort_logs_why_it_was_abandoned(self):
        """那行 `完成=... 目标页面=network_error` 会被误读成「本步做成了」，必须补一句说明。"""
        runner = self.make_runner(dry_run=True)
        refresh = cm.CommunityAction(
            "refresh_community_page",
            cm.NETWORK_PULL_START,
            swipe_end=cm.NETWORK_PULL_END,
            source_page="network_error",
            in_page_evidence="「网络连接异常，下拉刷新」这一页消失",
        )
        detail = runner._transition_success_detail(None, refresh)
        self.assertIn("网络连接异常", detail)

    def test_the_image_viewer_ends_the_pending_transition_too(self):
        """图片查看器盖上来时，同样要把「等着的那个转场」判成已结束。

        ⚠️ 这是 2026-10-08 两次实跑（18:58 / 19:10）的死锁：任务「浏览帖子」那一指
        点在帖子的图片上 ⇒ 图被放大成全屏查看器 ⇒ 状态机认出来了、也给出了
        ``dismiss_image_viewer``（按返回键），但主循环一看 ``confirmed_page`` 既不是
        来源页（``feed_home``）也不在目标集合里 ⇒ **把这一下丢掉** ⇒ 干等 150 秒，
        收尾时人还卡在查看器里，连社区都关不掉。

        旧写法只认 ``network_error``，查看器就漏在网里了 —— 所以这条用例存在的意义是
        「名单里每一个都得有」而不是「再补一个特例」。
        """
        runner = self.make_runner(dry_run=True)
        pending = cm.CommunityAction(
            "task_browse_1",
            cm.FEED_FIRST_POST,
            source_page="feed_home",
            target_pages=("post_detail", "signin_done", "network_error"),
        )
        dismiss = cm.CommunityAction(
            "dismiss_image_viewer",
            (540, 960),
            press_back=True,
            source_page="image_viewer",
            in_page_evidence="图片查看器消失（退回社区页面）",
        )
        # ⚠️ 这里**逐个写死**，不从 ``_GLOBAL_OVERLAY_PAGES`` 里遍历 ——
        # 遍历那个集合的话，名单被缩小（例如退回只认 network_error）时循环也跟着缩小，
        # 用例照样全绿：**拿被测常量当自己的输入**是护栏最容易犯的错。
        for page in ("image_viewer", "network_error", "signin_done"):
            with self.subTest(overlay=page):
                self.assertTrue(
                    runner._transition_completed(pending, dismiss, page),
                    f"{page} 盖上来时转场没被终止（收场动作会被主循环丢掉、干等到超时）",
                )
        # 别的页照旧不许放宽（老规矩：转场中途认出的杂页不当真）
        self.assertFalse(runner._transition_completed(pending, dismiss, "tasks_page"))
        self.assertFalse(runner._transition_completed(pending, dismiss, "unknown"))
        self.assertIn(
            "查看器", runner._transition_success_detail(None, dismiss)
        )

    def test_the_machine_and_judge_page_agree_on_every_frame(self):
        """状态机的 ``observe`` 与 ``pages.judge_page`` **必须给出同一个结论**。

        ⚠️ 这条是 2026-10-08 那次「测试全绿、真机照旧卡死」的防线。
        ``observe`` 原先自己抄了一份判页逻辑（``observe_pages`` → ``top_page`` →
        栈根兜底），于是往 ``judge_page`` 里新加的「图片查看器」判据**生产路径走不到**：
        ``test_community_pages.py`` 调 ``judge_page`` 全绿，实跑照旧认不出查看器、
        照旧干等 150 秒。**两份实现的代价就是「测试守住了 A，生产跑的是 B」。**

        逐帧核过就不存在这个缝：任何一边改了拼装顺序，这里立刻红。
        """
        machine = cm.CommunityStateMachine(self.templates, self.glyphs)
        checked = 0
        # 扫**盘上全部** 1080x1920 夹具（比 PAGE_FRAMES 那张表更宽，
        # 免得「表里漏了一页」把这条防线也带出个洞）。
        for path in sorted(FIXTURES.parent.rglob("*.png")):
            image = cv2.imread(str(path))
            if image is None:
                continue
            if image.shape[:2] != (cp.PORTRAIT_CANVAS[1], cp.PORTRAIT_CANVAS[0]):
                continue
            screen = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            expected = cp.judge_page(screen, self.templates)
            actual = machine.observe(screen)
            with self.subTest(frame=path.stem):
                self.assertEqual(actual.name, expected.name)
                self.assertEqual(actual.fallback, expected.fallback)
                self.assertAlmostEqual(actual.confidence, expected.confidence, places=6)
            checked += 1
        self.assertGreaterEqual(checked, 18)
        # 查看器那一帧必须真在扫过的集合里，否则这条用例可能只是「什么都没扫到」
        self.assertIn("image_viewer_live_20261008", {
            path.stem for path in FIXTURES.parent.rglob("*.png")
        })

    def test_the_machine_sees_the_image_viewer(self):
        """真机那一刻（查看器）走的是 ``next_action``，所以**必须从这里也认得出**。

        只测 ``judge_page`` 是不够的 —— 生产路径是 ``next_action`` → ``observe``。
        """
        machine = cm.CommunityStateMachine(self.templates, self.glyphs)
        machine.state = cm.CommunityState.FEED
        action = machine.next_action(fixture("image_viewer_live_20261008"))
        self.assertIsNotNone(action, "认不出查看器（又回到 2026-10-08 那个死锁）")
        assert action is not None
        self.assertEqual(action.name, "dismiss_image_viewer")
        self.assertTrue(action.press_back, "查看器那一屏没有可点控件，只能按返回键")
        self.assertEqual(action.source_page, "image_viewer")
        # 出口只写页内证据、**不写 target_pages** —— 关掉之后落回哪一页并不固定
        self.assertFalse(getattr(action, "target_pages", ()))

    def test_the_image_viewer_is_dismissed_with_the_back_key(self):
        """``press_back`` 必须真的走返回键通道，而且**不许再补一次点击**。

        ⚠️ 少了那个 ``return``，后面会退化成「点在图片正中」—— 等于刚按完返回又去点
        那一屏，正好把要关的东西再打开。这里用假 runtime 记下发过什么。
        """
        runner = self.make_runner(dry_run=False)
        clicks: list[tuple[int, int]] = []
        backs: list[int] = []
        runner.runtime._click = lambda point: clicks.append(point)  # type: ignore[assignment]
        runner.runtime._back = lambda: backs.append(1)  # type: ignore[assignment]
        runner.machine.state = cm.CommunityState.FEED
        action = runner.machine.next_action(fixture("image_viewer_live_20261008"))
        self.assertIsNotNone(action)
        assert action is not None
        runner._perform_action(action)
        self.assertEqual(backs, [1], "返回键没发出去")
        self.assertEqual(clicks, [], f"返回键之后又点了 {clicks} —— 会把查看器再打开")
        self.assertEqual(runner.machine.state, cm.CommunityState.IMAGE_VIEWER)

    def test_every_overlay_page_has_a_way_out(self):
        """``_GLOBAL_OVERLAY_PAGES`` 名单里每一页都必须**真推得动**。

        ⚠️ 放行一个推不动的页，只是把死锁从主循环搬到状态机里 —— 更难看懂。
        所以这条拿**真机夹具**喂进 ``next_action``，要求每一页都能当场给出一发动作：
        ``image_viewer`` → 按返回键、``network_error`` → 下拉刷新、``signin_done`` → 点关闭。
        只断言「名单里有没有它」是不够的 —— 那只看打字，不看行为。
        """
        fixtures = {
            "image_viewer": "image_viewer_live_20261008",
            "network_error": "network_error_live_20261006",
            "signin_done": "signin_success_live_20261007",
        }
        # 名单与夹具表必须一一对上：名单里加人就得同时给证据，不许悄悄放行
        self.assertEqual(set(fixtures), set(cm.CommunityRunner._GLOBAL_OVERLAY_PAGES))
        for page, frame in fixtures.items():
            with self.subTest(overlay=page):
                machine = cm.CommunityStateMachine(self.templates, self.glyphs)
                machine.state = cm.CommunityState.FEED
                action = machine.next_action(fixture(frame))
                self.assertIsNotNone(
                    action, f"{page} 这一页状态机给不出任何动作 —— 放行它等于把死锁搬个家"
                )
                assert action is not None
                self.assertEqual(
                    action.source_page,
                    page,
                    f"收场动作不是在 {page} 这一页上发的，说明判页和收场对不上",
                )
                self.assertTrue(
                    action.name in cm.CommunityRunner._QUICK_ACTIONS,
                    f"{action.name} 不在快重试名单里：收场动作点完立刻能看出效果，"
                    "按默认 45 秒等纯属白等",
                )

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

    def test_swipe_actions_get_a_window_short_enough_to_keep_going(self):
        """两个滑动动作的重试间隔必须**远短于**默认那 45 秒。

        ⚠️ 2026-10-09 实跑：``feed_scroll_back_for_exchange`` / ``task_like_reswipe``
        是「发一次手势 → 看画面动没动 → 再发」的循环。走默认 45 秒窗口的话，
        滑完一屏后要干等 45 秒才准再滑 ⇒ 三屏的预算全耗在等待里，日志里只有
        1 次「执行滑动」，结尾却报「往回滚了 3 屏」。

        阈值独立写死（10 秒 / 0.5 秒），**不拿 ``_SWIPE_RETRY_SECONDS`` 自己当尺子**。
        """
        runner = self.make_runner()
        for name in ("feed_scroll_back_for_exchange", "task_like_reswipe"):
            seconds = runner._action_retry_seconds(name)
            self.assertLess(
                seconds, 10, f"{name} 的重试间隔 {seconds} 秒太长，滚不完三屏"
            )
            self.assertGreater(
                seconds, 0.5, f"{name} 的重试间隔 {seconds} 秒太短，手势还没发完就重发"
            )

    def test_clicking_the_entry_and_exit_arms_the_switch(self):
        """进/出社区那几下点击要顺手把**通道方向预期**拨过去。

        ⚠️ ``leave_exchange`` 必须在内（2026-10-09 补）：兑换中心那颗 ✕ 真机实测
        **关的是整个社区**（点完 3 秒内窗口回 1920x1080）。漏了它，通道记录会一直
        停在竖屏 —— 19:58 那次实跑就是这么白等 20 秒「等待切换为竖屏」的：
        窗口明明已经横屏，代码却拿竖屏链路去取图。
        """
        runner = self.make_runner(dry_run=True)
        runner._switch = cm.ChannelSwitch(_FakePortrait())
        runner._after_action_click(cm.CommunityAction("enter_community", (1, 1)))
        self.assertEqual(runner._switch.state, cm.ChannelSwitch.PENDING_PORTRAIT)
        runner._after_action_click(cm.CommunityAction("close_community", (1, 1)))
        self.assertEqual(runner._switch.state, cm.ChannelSwitch.PENDING_LANDSCAPE)
        runner._switch.expect("portrait")
        runner._after_action_click(cm.CommunityAction("leave_exchange", (1, 1)))
        self.assertEqual(
            runner._switch.state,
            cm.ChannelSwitch.PENDING_LANDSCAPE,
            "从兑换中心退出社区那一下同样会转回横屏，方向预期必须跟着拨",
        )

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
        """已经是横屏 ⇒ 不点、不等（正常路径：状态机在横屏那帧才收工）。"""
        portrait = _FakePortrait(portrait=False)
        runner = self.make_runner(portrait=portrait)
        runner._switch = cm.ChannelSwitch(portrait)
        runner._leave_portrait_if_needed()
        self.assertEqual(portrait.calls, [])

    def test_closing_out_hands_the_landscape_record_to_the_next_step(self):
        """异常收尾把方向等回来了 ⇒ **通道记录也必须跟着回到横屏**。

        ⚠️ 2026-10-09 实跑日志：13:07:52「收尾=人还在社区竖屏页面里」，
        13:07:54「已退出社区且方向已转回横屏」—— 方向明明已经对了，
        13:08:18 却又冒出「竖屏通道 方向=等待切换为竖屏 … 超时」，白等 20 秒
        才由竖屏通道退回横屏。原因正是**方向回来了、记录没回来**：异常收尾时
        没人点过「退出社区」，没人把记录拨成 ``PENDING_LANDSCAPE``，
        它还停在 ``PENDING_PORTRAIT`` ⇒ 下一步回首页取图先等一次不可能的转屏。
        """
        portrait = _FakePortrait(portrait=True)
        portrait.turns_while_waiting = True
        runner = self.make_runner(portrait=portrait)
        switch = cm.ChannelSwitch(portrait)
        switch.expect("portrait")
        runner._switch = switch
        runner._leave_portrait_if_needed()
        self.assertEqual(
            switch.state,
            cm.ChannelSwitch.LANDSCAPE,
            "方向已转回横屏，通道记录却还停在竖屏，下一步取图会白等竖屏超时",
        )

    def test_closing_out_also_winds_the_record_back_when_already_landscape(self):
        """人已经不在竖屏里（进社区那一下没点成）⇒ 记录同样要拨回横屏。"""
        portrait = _FakePortrait(portrait=False)
        runner = self.make_runner(portrait=portrait)
        switch = cm.ChannelSwitch(portrait)
        switch.expect("portrait")
        runner._switch = switch
        runner._leave_portrait_if_needed()
        self.assertEqual(switch.state, cm.ChannelSwitch.LANDSCAPE)

    def test_closing_out_tries_the_other_close_buttons_when_the_first_one_misses(self):
        """收尾点第一颗 ⊗ 关不掉这一屏时，要**换下一颗试**，不能就此认输。

        ⚠️ 2026-10-09 真机量出来社区里有**三颗**同义的 ⊗，位置各不相同
        （信息流 (937,92) / 兑换中心 (989,123) / H5 死掉那屏 (1000,78)；
        外径 44/48/33 互不相等 ⇒ 是三颗不同的钮，不是同一颗挪了位置）。
        异常收尾时状态机可能停在**任意一页**，只点信息流那颗在别的页上等于点空 ⇒
        收尾关不掉 ⇒ 模拟器留在竖屏 ⇒ 紧接着回家报
        「画面宽高比与模板基准不一致」（10-07 / 10-08 连撞多次的就是这条链）。

        断言的是**换了一颗**（点了两次、两次的坐标不同），不是绕过第几颗的写法。
        """
        portrait = _FakePortrait(portrait=True)
        portrait.turns_while_waiting = True
        portrait.wait_failures_left = 1  # 第一颗点了没用（等满超时）
        runner = self.make_runner(portrait=portrait)
        runner._switch = cm.ChannelSwitch(portrait)
        runner._leave_portrait_if_needed()
        clicks = [c for c in portrait.calls if c.startswith("click")]
        self.assertEqual(
            len(clicks), 2, f"第一颗 ⊗ 没关掉就应当换下一颗：{portrait.calls}"
        )
        self.assertNotEqual(
            clicks[0], clicks[1], "换的必须是**另一颗** ⊗，不是把同一颗再点一遍"
        )
        self.assertFalse(portrait.portrait, "第二颗之后方向应当已经转回横屏")

    def test_closing_out_does_not_pretend_landscape_when_it_is_still_portrait(self):
        """等不到转回横屏 ⇒ 记录**不许**动，免得把「人还在竖屏」说成已经出来。"""
        portrait = _FakePortrait(portrait=True)
        portrait.turns_while_waiting = False
        runner = self.make_runner(portrait=portrait)
        switch = cm.ChannelSwitch(portrait)
        switch.expect("portrait")
        runner._switch = switch
        runner._leave_portrait_if_needed()
        self.assertEqual(switch.state, cm.ChannelSwitch.PENDING_PORTRAIT)
        self.assertTrue(portrait.portrait, "等不到的情况下不该把方向改掉")

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
        """脚本里的**滑动步**：不许被当成「在起点点一下」。

        ⚠️ 2026-10-07 实跑：主循环只会 ``runtime.click`` ⇒ 滑动变成「在信息流中部
        点一下」⇒ **点开一张帖子** ⇒ 下一步要求 ``feed_home`` 对不上 ⇒ 任务
        三遍机会全废。修法是 Runner 认 ``swipe_end`` 换发 ``runtime.swipe``。
        这条钉的是「脚本 → 动作 → 真的走滑动通道」整条链，不是只看动作字段。

        ⚠️ 2026-10-11：载体从「点赞」换成「浏览」（点赞已摘出生产清单）。
        浏览脚本第 3 步是 ``feed_home`` 上的一次滑动（终点 ``FEED_TASK_SCROLL_END``），
        与点赞原来用的那条滑动是同一条常量 —— 换成浏览后，这条护栏**盯的是
        真在生产跑的路径**，比原来更有意义。
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
        machine.active_task = "browse"
        # 摆到浏览脚本里那一步「在信息流往下滑，把下一篇带上来」。
        swipe_index = next(
            index
            for index, step in enumerate(cm.TASK_SCRIPT["browse"])
            if step.end == cm.FEED_TASK_SCROLL_END
        )
        machine.task_step = swipe_index
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


class _ExhaustedAfterFirstLook:
    """社区状态机替身：**第一次观察之后**就报「兑换积分不够」。

    形状照着 ``ModeRunnerBase`` 的鸭子类型造（主循环只要 ``state`` /
    ``completed_cycles`` / ``preview`` / ``next_action``）。

    ⚠️ 为什么从**第二次**开始抛：``preview`` 抛出的终止性结论要过**结论门槛**
    （``runner_base._stable_next_action``：连续两帧一致才采信），第一次只会被记成
    「结论待确认」并返回 ``NOT_STABLE``。只抛一次的话主循环永远走不到收尾那一段，
    这条测试就变成了「跑不到的分支」—— 看着绿，其实什么都没验。
    """

    def __init__(self) -> None:
        self.state = cm.CommunityState.FEED
        self.completed_cycles = 0
        self._confirmed_page = ""
        self.preview_calls = 0

    def preview(self, screen):
        self.preview_calls += 1
        if self.preview_calls > 1:
            raise cm.RedeemBudgetExhausted("测试：兑换积分不够了")
        return None, (self.state, self.completed_cycles)

    def next_action(self, screen):
        return None


class CommunityEndpointMustBeHomeTests(unittest.TestCase):
    """终点契约：社区这条路跑完**必须停在大厅**（用户 2026-10-09 明确补充）。

    原话：「这条路线它的终点有点特殊，它一定要回到首页，因为不然的话，它很多按键
    都没有掉了」—— 社区走完停的是**横屏的网页活动列表**（H5），大厅那套按钮一个都
    不在；收尾那一棒没接上，整条路线照样报「成功」，人却留在网页上，下一个任务接不上。

    ⚠️ 与 ``CommunityRunnerTests.test_the_run_loop_is_delegated_to_the_base_class``
    的分工：那条是**静态**读源码（覆写了 run 有没有委托回基类）；这里补的是**动态**
    那一半 —— 真跑一轮主循环，看退出口上「回家」那一棒有没有**真的被调到**。
    两者都不能省：静态能拦住「没委托」，拦不住「委托了但回家钩子没装 / 被跳过」。

    守两件，判据**独立写死、不读被测常量**：

    ① 这条路线不该躺在「不回首页」的豁免名单里；
    ② 真跑一轮到「积分不够」（正常业务退出，退出码 2）：末棒**确实是回家**。
    """

    @classmethod
    def setUpClass(cls):
        cls.templates, cls.glyphs = cm.build_screen_reader(TEMPLATES)

    def test_the_route_is_not_exempt_from_going_home(self):
        """豁免名单里一旦出现社区，这条终点契约就没了 —— 断言是它的门栓。"""
        from auto_game_unified.games.epic7.finish_home import FINISH_HOME_EXEMPT

        self.assertNotIn(
            "community",
            FINISH_HOME_EXEMPT,
            "社区路线被划进了「不回首页」的豁免名单：它的终点契约就是大厅，不能豁免",
        )

    def test_a_finished_run_walks_all_the_way_home(self):
        """跑完一轮（按「积分不够」收）⇒ 收尾必须**走到回家这一棒**。

        ⚠️ 只断言「退出了社区」是不够的：退出社区只到网页活动列表，**那不是终点**。
        所以这里记的是 ``_finish_home``（通用回家流程）有没有被调到。
        """
        home_calls: list[str] = []

        def hook() -> Optional[str]:
            home_calls.append("finish_home")
            return None

        runtime = Runtime(
            capture=lambda: np.zeros((1132, 1982, 3), np.uint8),
            click=lambda point: None,
            emit=lambda text: None,
        )
        runner = cm.CommunityRunner(
            _ExhaustedAfterFirstLook(),
            runtime,
            portrait=_FakePortrait(portrait=False),
            sleep=lambda _: None,
        )
        runner._finish_home = hook

        completed = runner.run(max_cycles=3)

        self.assertEqual(0, completed)
        self.assertEqual(
            ["finish_home"],
            home_calls,
            "社区收尾没有走到「回家」这一棒 —— 只退了社区就收手，"
            "人会留在网页活动列表上（大厅那套按钮一个都不在）",
        )


if __name__ == "__main__":
    unittest.main()
