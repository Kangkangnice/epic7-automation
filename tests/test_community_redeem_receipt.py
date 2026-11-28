"""社区兑换「确认发出后先等这一笔回执」的离线回归（2026-11-26 实跑重复提交后立）。

## 现场

``runtime_logs/epic7_community.log`` 17:03~17:05：

* 17:03:48 第一次 ``confirm_redeem``；
* 几秒后「兑换成功」弹窗的判据漂移（0.6156 < 阈 0.82）⇒ 判 ``unknown``；
* 陌生页逃生**按返回** ⇒ 回兑换中心 ⇒ 重新开单 ⇒ 17:04:20 **第二次**
  ``confirm_redeem``；此后 ``open_item → unknown → stranger_back → exchange_center``
  一路转圈。

实际业务：商品「行动力*30」已经 ``每日限购 2/2``、余额 930，程序日志却还写着
「已兑 0/2」。这一次启动按 ``unsafe`` 记，不是 ``completed``。

## 旧代码的两条失败路径（本文件前两条用例就是它们）

1. **确认页一直停在原地会重复点击**：``_on_order_confirm`` 只要还能定位到绿按钮
   就再给一次 ``confirm_redeem``，而主循环对「来源页仍被确认」的动作会**原样重发**。
   离线实测（真执行器 + 假窗口、120 帧）：同一点被点 **4 次**（主循环 4 次上限）。
2. **确认后遇到陌生页 ⇒ 返回 ⇒ 重新开单 ⇒ 再次确认**：离线实测 120 帧内
   ``confirm_redeem`` 被点 **8 次**、按返回 7 次；把帧放长到 400 帧就是 25 次 ——
   **没有任何上界**，因为每圈都回 ``EXCHANGE`` 把状态计时重置了。

## 修完以后的规矩（用户 2026-11-26 明确）

确认兑换发出后**先等这一笔的结果**：

* 只有**可信成功回执**（``redeem_done``）才继续后续兑换；
* 只有**明确失败证据**（订单确认页一进来「确认兑换」就是灰的）才走失败分支；
* 确认页没动 / 回到商品页 / 陌生页 / 截图超时**都不许**当成兑换失败，
  也不许按返回、重新开单、再次确认；
* 等满 ``_RECEIPT_WAIT_SECONDS`` 仍无法确认 ⇒ 记商品与最后可用画面、
  **停在原地待人工对账**（``PurchaseReceiptUnclear``，与竞技场购票同一套停机语义）。

## 为什么用真执行器 + 假输入

只断言 ``CommunityAction`` 的字段守不住这一条：真正扣费的是主循环发出的那一下点击，
而它的去处由「主循环的重发机制 + 状态机的决策 + 执行层的拦截」三处共同决定。
所以这里用**真 ``CommunityRunner`` + 真 ``Runtime`` + 假窗口**，断言的是
**实际点击/返回序列**，不是动作字段。
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import cv2
import numpy as np

from auto_game_unified.core.portrait import OrientationError
from auto_game_unified.core.runtime import ManualStop, PurchaseReceiptUnclear, Runtime
from auto_game_unified.games.epic7 import community as cm
from auto_game_unified.games.epic7.daily_tasks import run_daily_tasks
from auto_game_unified.main import _make_stop_requested


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_community"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "community"

# 三张现成的真机帧：兑换中心（卡 1 还差一次）→ 商品详情 → 订单确认。
EXCHANGE = "exchange_after_redeem_live_20261006"
ITEM = "item_detail_live_20261006"
CONFIRM = "order_confirm_live_20261006"
SUCCESS = "redeem_success_live_20261006"
STRANGER = "stranger_account_page_live_20261018"


def fixture(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    if image is None:
        raise AssertionError(f"缺夹具 {name}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class _SceneDone(RuntimeError):
    """假窗口把这批帧放完了 —— 用例用它给「只跑到这里」画一条终点线。"""


class _Clock:
    """假时钟：``sleep`` 被换掉之后真时钟几乎不动，等回执要靠它推进。"""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 0.05
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class _Scene:
    """假窗口：喂哪一帧由 ``index`` 决定，收到输入后由子类决定推进到哪一帧。

    ⚠️ ``capture`` 恒定返回当前帧（不自动前进）：主循环要求同一页**连续两帧稳定**
    才会出手，一取图就翻页会让任何动作都发不出去。
    """

    def __init__(self, frames: list[np.ndarray], *, cap: int = 200) -> None:
        self.frames = frames
        self.index = 0
        self.cap = cap
        self.clicks: list[tuple[int, int]] = []
        self.backs = 0
        self.captures = 0
        self.timeout_after_click = False

    # ---- 假窗口接口 ----
    def capture(self) -> np.ndarray:
        self.captures += 1
        if self.timeout_after_click and self.clicks:
            raise subprocess.TimeoutExpired(["adb", "exec-out", "screencap", "-p"], 20.0)
        if self.captures > self.cap:
            raise _SceneDone(f"假窗口帧数用尽（{self.cap} 帧）")
        return self.frames[self.index]

    def click(self, point: tuple[int, int]) -> None:
        self.clicks.append(point)
        self.on_click(point)

    def back(self) -> None:
        self.backs += 1
        self.on_back()

    def stop_requested(self) -> bool:
        return False

    # ---- 由用例覆写的推进规则 ----
    def on_click(self, point: tuple[int, int]) -> None:
        raise NotImplementedError

    def on_back(self) -> None:
        raise NotImplementedError


class _OfflineCommunityRunner(cm.CommunityRunner):
    """只跳过「装配竖屏通道 / 抢点入口 / 收通知栏」三步准备，主循环全用真的。"""

    def _attach_channels(self) -> None:
        return

    def _collapse_status_bar(self) -> None:
        return

    def _enter_community_immediately(self) -> None:
        return


class _NoInputPortrait:
    """竖屏通道替身：只记账，不碰设备。

    ``is_portrait()`` 恒真 ⇒ 收尾那条链（``_leave_portrait_if_needed``）**会真的**
    去点 ⊗、按返回。于是「回执未明时一个字都不发」这条可以被断言看见，
    而不是靠「反正没接通道」蒙过去。
    """

    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []
        self.backs = 0

    def is_portrait(self) -> bool:
        return True

    def click(self, point: tuple[int, int]) -> None:
        self.clicks.append(point)

    def back(self) -> None:
        self.backs += 1

    def wait_for_landscape(self, timeout: float | None = None) -> None:
        raise OrientationError("假的：一直没转回横屏")

    def wait_for_portrait(self, timeout: float | None = None) -> None:
        return


class _RedeemCase(unittest.TestCase):
    """公共装配：模板、四个真实落点、真 Runtime + 假窗口。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.templates, cls.glyphs = cm.build_screen_reader(TEMPLATES)
        machine = cm.CommunityStateMachine(cls.templates, cls.glyphs)
        machine.progress.signed_in = True
        step = cm.plan_redeem(cm.read_exchange(fixture(EXCHANGE), cls.glyphs))
        assert step.kind == "open_card" and step.point is not None, step
        cls.open_point = step.point
        cls.order_point = cm.locate_bottom_green_button(fixture(ITEM))
        cls.confirm_point = cm.locate_green_button(fixture(CONFIRM))
        cls.ack_point = cm.REDEEM_CONFIRM

    def build(self, scene: _Scene, *, portrait: _NoInputPortrait | None = None):
        clock = _Clock()
        logs: list[str] = []
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.diagnostic_dir = Path(directory.name)
        runtime = Runtime(
            scene.capture,
            scene.click,
            back=scene.back,
            emit=logs.append,
            diagnostic_dir=self.diagnostic_dir,
            # 用 lambda 现查属性：用例可以在跑起来之后再换掉「停止请求」的实现，
            # 直接传 ``scene.stop_requested`` 会把构造那一刻的绑定方法焊死。
            stop_requested=lambda: scene.stop_requested(),
            monotonic=clock,
        )
        machine = cm.CommunityStateMachine(
            self.templates, self.glyphs, state=cm.CommunityState.EXCHANGE
        )
        machine.progress.signed_in = True
        # 睡眠按 5 秒/帧推进假时钟：等回执 90 秒 ≈ 18 帧，用例才不会跑成分钟级。
        runner = _OfflineCommunityRunner(
            machine, runtime, sleep=lambda seconds: clock.advance(max(seconds, 5.0))
        )
        if portrait is not None:
            runner._switch = cm.ChannelSwitch(portrait)
            runner._switch.expect("portrait")
        self.logs = logs
        return runner, machine

    def shots(self) -> list[str]:
        return sorted(path.name for path in self.diagnostic_dir.glob("*.png"))


class FrozenConfirmPageTests(_RedeemCase):
    """旧失败路径一：确认页一直停在原地 ⇒ 旧代码连点 4 次「确认兑换」。"""

    def test_a_frozen_confirm_page_is_submitted_once_and_then_held_for_reconciliation(self):
        class Frozen(_Scene):
            def on_click(self, point: tuple[int, int]) -> None:
                if point == case.open_point:
                    self.index = 1
                elif point == case.order_point:
                    self.index = 2
                elif point == case.confirm_point:
                    # 确认页**一直不动**：这是现场最贵的那一种画面
                    # （兑换结果还没弹出来，或者弹出来了但判据认不出）。
                    return
                else:  # pragma: no cover - 出现第三种点击就是行为变了
                    raise AssertionError(f"没预料到的点击 {point}")

            def on_back(self) -> None:
                raise AssertionError("回执未明时不许按返回")

        case = self
        portrait = _NoInputPortrait()
        scene = Frozen([fixture(EXCHANGE), fixture(ITEM), fixture(CONFIRM)], cap=120)
        runner, machine = self.build(scene, portrait=portrait)

        with self.assertRaises(PurchaseReceiptUnclear) as caught:
            runner.run(max_cycles=1)

        # ① 实际输入序列：开单、进确认页、确认 —— 各一次，到此为止。
        self.assertEqual(
            [self.open_point, self.order_point, self.confirm_point],
            scene.clicks,
            f"「确认兑换」被重复提交了：{scene.clicks}",
        )
        self.assertEqual(0, scene.backs, "回执未明时按了返回键")
        # ② 退场链一个字都没发（竖屏通道替身全程可点，这是真的「没发」）。
        self.assertEqual([], portrait.clicks, "回执未明时仍去点了退出社区的 ⊗")
        self.assertEqual(0, portrait.backs, "回执未明时仍去按了返回键")
        # ③ 对账现场：商品名 + 最后页面 + 一张可用画面。
        message = str(caught.exception)
        self.assertIn("行动力*30", message, message)
        self.assertIn("人工对账", message, message)
        self.assertIn("订单确认", message, message)
        self.assertTrue(
            any("receipt_unclear" in name for name in self.shots()),
            f"超时对账必须留一张现场帧：{self.shots()}",
        )
        joined = "\n".join(self.logs)
        self.assertIn("不重复提交", joined, joined)

    def test_a_capture_timeout_after_submit_is_also_receipt_unclear(self):
        """截图超时不是「页面认不出」，更不是「兑换失败」——同样是未拿到回执。"""

        class TimesOut(_Scene):
            def on_click(self, point: tuple[int, int]) -> None:
                if point == case.open_point:
                    self.index = 1
                elif point == case.order_point:
                    self.index = 2
                elif point == case.confirm_point:
                    self.timeout_after_click = True
                else:  # pragma: no cover
                    raise AssertionError(f"没预料到的点击 {point}")

            def on_back(self) -> None:
                raise AssertionError("截图超时后不许按返回")

        case = self
        portrait = _NoInputPortrait()
        scene = TimesOut([fixture(EXCHANGE), fixture(ITEM), fixture(CONFIRM)])
        runner, _machine = self.build(scene, portrait=portrait)

        with self.assertRaises(PurchaseReceiptUnclear) as caught:
            runner.run(max_cycles=1)

        self.assertIsInstance(
            caught.exception.__cause__,
            subprocess.TimeoutExpired,
            "必须用异常链保留原始截图超时，否则事后看不出是取图挂了",
        )
        self.assertEqual(
            [self.open_point, self.order_point, self.confirm_point], scene.clicks
        )
        self.assertEqual(0, scene.backs)
        self.assertEqual([], portrait.clicks)
        self.assertEqual(0, portrait.backs)
        message = str(caught.exception)
        self.assertIn("截图超时", message, message)
        self.assertIn("对账", message, message)
        self.assertTrue(
            any("receipt_capture_timeout" in name for name in self.shots()),
            self.shots(),
        )


class StrangerAfterConfirmTests(_RedeemCase):
    """旧失败路径二：确认后落陌生页 ⇒ 旧代码按返回、重新开单、再确认一次。"""

    def test_a_stranger_page_after_submit_is_not_dismissed_nor_reordered(self):
        class StrangerAfterConfirm(_Scene):
            def on_click(self, point: tuple[int, int]) -> None:
                if point == case.open_point:
                    self.index = 1
                elif point == case.order_point:
                    self.index = 2
                elif point == case.confirm_point:
                    # 现场：兑换成功弹窗判据漂移 ⇒ 这一帧判页 unknown。
                    self.index = 3
                else:  # pragma: no cover
                    raise AssertionError(f"重新开单了：{point}")

            def on_back(self) -> None:
                # 旧代码：陌生页逃生按返回 ⇒ 回兑换中心 ⇒ 再开单。
                self.index = 0

        case = self
        portrait = _NoInputPortrait()
        scene = StrangerAfterConfirm(
            [fixture(EXCHANGE), fixture(ITEM), fixture(CONFIRM), fixture(STRANGER)],
            cap=120,
        )
        runner, machine = self.build(scene, portrait=portrait)

        with self.assertRaises(PurchaseReceiptUnclear) as caught:
            runner.run(max_cycles=1)

        self.assertEqual(
            [self.open_point, self.order_point, self.confirm_point],
            scene.clicks,
            f"确认之后又发过输入：{scene.clicks}",
        )
        self.assertEqual(0, scene.backs, "陌生页被当成逃生门按了返回")
        self.assertEqual(1, scene.clicks.count(self.confirm_point))
        self.assertNotIn(self.order_point, scene.clicks[2:], "重新开了单")
        self.assertEqual([], portrait.clicks)
        message = str(caught.exception)
        self.assertIn("行动力*30", message, message)
        self.assertIn("认不出", message, message)
        self.assertTrue(machine.redeem_pending, "对账停机时在途标记必须留着")


class TrustedReceiptTests(_RedeemCase):
    """对照组：可信回执到了才继续下一笔；每笔仍然只提交一次。"""

    def test_each_purchase_is_submitted_once_and_a_trusted_receipt_unlocks_the_next(self):
        class TwoPurchases(_Scene):
            def on_click(self, point: tuple[int, int]) -> None:
                if point == case.open_point:
                    self.index = 1
                elif point == case.order_point:
                    self.index = 2
                elif point == case.confirm_point:
                    self.index = 3
                elif point == case.ack_point:
                    if self.clicks.count(case.ack_point) == 1:
                        self.index = 1  # 有时收起回执会落在商品详情页。
                    else:
                        self.frames[0] = fixture("exchange_balance_950_live_20261115")
                        self.index = 0
                elif point == cm.EXCHANGE_CLOSE:
                    self.index = 4
                else:  # pragma: no cover
                    raise AssertionError(f"没预料到的点击 {point}")

            def on_back(self) -> None:
                case.assertEqual(1, self.clicks.count(case.ack_point))
                self.frames[0] = fixture(EXCHANGE)
                self.index = 0

        case = self
        scene = TwoPurchases(
            [fixture("exchange_before_redeem_live_20261007"), fixture(ITEM),
             fixture(CONFIRM), fixture(SUCCESS), np.zeros((1080, 1920, 3), np.uint8)]
        )
        runner, machine = self.build(scene)

        self.assertEqual(1, runner.run(max_cycles=1))

        self.assertEqual(
            [self.open_point, self.order_point, self.confirm_point, self.ack_point] * 2
            + [cm.EXCHANGE_CLOSE],
            scene.clicks,
            f"两笔兑换的输入序列不对：{scene.clicks}",
        )
        self.assertEqual(1, scene.backs)
        self.assertFalse(machine.redeem_pending, "回执到了必须清掉在途标记")
        joined = "\n".join(self.logs)
        # 两笔都走到了「回执 → 收起 → 回到兑换中心 → 再开单」这条正常链上。
        self.assertEqual(2, joined.count("执行点击 动作=confirm_redeem"), joined)
        self.assertEqual(2, joined.count("完成=confirm_redeem 目标页面=redeem_done"), joined)
        self.assertEqual(2, machine.progress.redeemed[1])

    def test_a_stale_count_after_success_does_not_unlock_another_purchase(self):
        case = self

        class StaleCount(_Scene):
            def on_click(self, point):
                self.index = {
                    case.open_point: 1, case.order_point: 2,
                    case.confirm_point: 3, case.ack_point: 0,
                }[point]

            def on_back(self):
                raise AssertionError("限购读数未更新时不应离开兑换中心")

        scene = StaleCount(
            [fixture(name) for name in (EXCHANGE, ITEM, CONFIRM, SUCCESS)], cap=80
        )
        portrait = _NoInputPortrait()
        runner, _ = self.build(scene, portrait=portrait)
        with self.assertRaises(PurchaseReceiptUnclear) as caught:
            runner.run(max_cycles=1)
        self.assertEqual(
            [self.open_point, self.order_point, self.confirm_point, self.ack_point],
            scene.clicks,
        )
        self.assertIn("限购", str(caught.exception))
        self.assertEqual([], portrait.clicks)


class ReceiptInputBoundaryTests(_RedeemCase):
    def test_an_order_without_a_planned_item_is_never_submitted(self):
        scene = _Scene([fixture(CONFIRM)])
        runner, _ = self.build(scene)
        with self.assertRaisesRegex(RuntimeError, "商品来源"):
            runner.run(max_cycles=1)
        self.assertEqual([], scene.clicks)

    def test_only_read_only_capture_is_used_after_submit(self):
        case = self

        class AwaitingReceipt(_Scene):
            def on_click(self, point):
                self.index = {
                    case.open_point: 1, case.order_point: 2, case.confirm_point: 2,
                }[point]

            def on_back(self):
                raise AssertionError("全局弹窗守卫不应在等待回执时发输入")

        scene = AwaitingReceipt([fixture(name) for name in (EXCHANGE, ITEM, CONFIRM)])
        runner, _ = self.build(scene)

        def guard(runtime, screen):
            if self.confirm_point in scene.clicks:
                runtime.back("global-popup-recovery")
            return screen, False

        runner.runtime.set_capture_guard(guard)
        with self.assertRaises(PurchaseReceiptUnclear):
            runner.run(max_cycles=1)
        self.assertEqual(0, scene.backs)

    def test_adb_failure_at_the_confirm_input_preserves_the_scene(self):
        case = self

        class AmbiguousClick(_Scene):
            def on_click(self, point):
                if point == case.confirm_point:
                    raise subprocess.TimeoutExpired(["adb", "shell", "input", "tap"], 20)
                self.index = {case.open_point: 1, case.order_point: 2}[point]

        portrait = _NoInputPortrait()
        scene = AmbiguousClick([fixture(name) for name in (EXCHANGE, ITEM, CONFIRM)])
        runner, _ = self.build(scene, portrait=portrait)
        with self.assertRaises(PurchaseReceiptUnclear) as caught:
            runner.run(max_cycles=1)
        self.assertIsInstance(caught.exception.__cause__, subprocess.TimeoutExpired)
        self.assertEqual([self.open_point, self.order_point, self.confirm_point], scene.clicks)
        self.assertEqual([], portrait.clicks)
        self.assertEqual(0, portrait.backs)


class BoundedRecoveryTests(_RedeemCase):
    """「打开商品 → 陌生页 → 返回 → 再打开」必须有上界。"""

    def test_the_open_item_stranger_loop_stops_within_the_attempt_limit(self):
        class OpenLoop(_Scene):
            def on_click(self, point: tuple[int, int]) -> None:
                if point == case.open_point:
                    self.index = 1
                else:  # pragma: no cover
                    raise AssertionError(f"循环里出现了开单以外的点击：{point}")

            def on_back(self) -> None:
                self.index = 0

        case = self
        scene = OpenLoop([fixture(EXCHANGE), fixture(STRANGER)], cap=200)
        runner, _machine = self.build(scene)

        # 与「陌生页阶梯用尽」同一条失败路径：结论经门槛采信后，主循环在
        # ``RECOVERING`` 超时时把它包成一句「页面无进展：<原因>」抛出来。
        with self.assertRaises(RuntimeError) as caught:
            runner.run(max_cycles=1)
        self.assertNotIsInstance(caught.exception, PurchaseReceiptUnclear)

        self.assertEqual(
            cm.REDEEM_OPEN_ATTEMPT_LIMIT,
            scene.clicks.count(self.open_point),
            f"循环没有被上界收住：{scene.clicks}",
        )
        self.assertNotIn(self.confirm_point, scene.clicks)
        self.assertIn(str(cm.REDEEM_OPEN_ATTEMPT_LIMIT), str(caught.exception))


class StopRequestTests(_RedeemCase):
    """正式停止入口：收到停止请求之后不再发任何输入。"""

    def test_a_stop_request_while_waiting_for_the_receipt_sends_nothing_more(self):
        class Frozen(_Scene):
            def on_click(self, point: tuple[int, int]) -> None:
                if point == case.open_point:
                    self.index = 1
                elif point == case.order_point:
                    self.index = 2
                elif point == case.confirm_point:
                    return
                else:  # pragma: no cover
                    raise AssertionError(f"没预料到的点击 {point}")

            def on_back(self) -> None:
                raise AssertionError("停止请求之后不许按返回")

        case = self
        portrait = _NoInputPortrait()
        scene = Frozen([fixture(EXCHANGE), fixture(ITEM), fixture(CONFIRM)])
        runner, _machine = self.build(scene, portrait=portrait)

        stop_file = self.diagnostic_dir / "stop.signal"
        with patch("auto_game_unified.main.WindowsPStopHotkey") as hotkey:
            hotkey.return_value.pressed.return_value = False
            check_stop_file = _make_stop_requested(False, stop_file)
            assert check_stop_file is not None

            def stop_requested() -> bool:
                if case.confirm_point in scene.clicks and scene.captures > 12:
                    stop_file.touch(exist_ok=True)
                return check_stop_file()

            scene.stop_requested = stop_requested  # type: ignore[method-assign]
            with self.assertRaises(ManualStop):
                runner.run(max_cycles=1)

        self.assertEqual(
            [self.open_point, self.order_point, self.confirm_point], scene.clicks
        )
        self.assertEqual(0, scene.backs)
        self.assertEqual([], portrait.clicks, "停止之后仍去点了退出社区的 ⊗")
        self.assertEqual(0, portrait.backs, "停止之后仍按了返回键")
        self.assertTrue(stop_file.is_file())


class DailyBatchStopsTests(_RedeemCase):
    """每日编排：社区回执未明 ⇒ 停整轮，不启动下一条、不巡检。"""

    def test_the_daily_batch_stops_at_community_and_does_not_start_the_next_route(self):
        class Frozen(_Scene):
            def on_click(self, point: tuple[int, int]) -> None:
                if point == case.open_point:
                    self.index = 1
                elif point == case.order_point:
                    self.index = 2
                elif point == case.confirm_point:
                    return
                else:  # pragma: no cover
                    raise AssertionError(f"没预料到的点击 {point}")

            def on_back(self) -> None:
                raise AssertionError("回执未明时不许按返回")

        case = self
        scene = Frozen([fixture(EXCHANGE), fixture(ITEM), fixture(CONFIRM)])
        runner, _machine = self.build(scene)
        started: list[str] = []
        inspected: list[bool] = []

        def run_mode(**kwargs: Any) -> object:
            started.append(kwargs["spec"].name)
            if kwargs["spec"].name != "community":  # pragma: no cover
                raise AssertionError("回执未明之后不许再启动下一条路线")
            return runner.run(max_cycles=1)

        report = run_daily_tasks(
            selected=["community", "arena"],
            cycles_override={"community": 1},
            dry_run=False,
            run_mode=run_mode,
            inspect=lambda: inspected.append(True),
        )

        self.assertEqual(["community"], started, f"多跑了一条：{started}")
        self.assertEqual(
            ["community"],
            [outcome.mode for outcome in report.outcomes],
            "回执未明必须停整轮",
        )
        outcome = report.outcomes[0]
        self.assertEqual("failed", outcome.status)
        self.assertIn("PurchaseReceiptUnclear", outcome.detail, outcome.detail)
        self.assertIn("对账", outcome.detail, outcome.detail)
        self.assertIn("对账现场", report.aborted_reason, report.aborted_reason)
        self.assertEqual([], inspected, "收尾巡检会移动现场，必须跳过")
        self.assertEqual(
            [self.open_point, self.order_point, self.confirm_point], scene.clicks
        )


class PendingDecisionTests(unittest.TestCase):
    """状态机层：在途期间任何一页都只返回 None，只有回执页能收场。

    ⚠️ 这一组不跑主循环，跑得快，守的是**规矩本身**：以后有人往
    ``next_action`` 里加处理函数、或者把闸门挪到各处理函数里去，它会立刻红。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.templates, cls.glyphs = cm.build_screen_reader(TEMPLATES)

    def machine(self) -> cm.CommunityStateMachine:
        machine = cm.CommunityStateMachine(
            self.templates, self.glyphs, state=cm.CommunityState.ORDER_CONFIRM
        )
        machine.progress.signed_in = True
        machine.redeem_pending = True
        machine.redeem_pending_card = 1
        return machine

    def test_no_page_produces_an_input_while_a_receipt_is_pending(self):
        for name in (
            "order_confirm_live_20261006",
            "item_detail_live_20261006",
            "exchange_after_redeem_live_20261006",
            "feed_list_live_20261006",
            "stranger_account_page_live_20261018",
            "network_error_live_20261006",
            "share_sheet_live_20261006",
        ):
            with self.subTest(frame=name):
                machine = self.machine()
                action = machine.next_action(fixture(name))
                self.assertIsNone(action, f"「{name}」这一页在回执未明时出了手")
                self.assertIn("只等这一笔的回执", machine.last_reason)

    def test_only_the_receipt_page_closes_the_transaction(self):
        machine = self.machine()
        action = machine.next_action(fixture(SUCCESS))
        self.assertIsNotNone(action)
        self.assertEqual("ack_redeem_done", action.name)
        self.assertFalse(machine.redeem_pending, "回执到了必须清掉在途标记")
        self.assertIsNone(machine.redeem_pending_card)

    def test_the_pending_flag_survives_a_preview_round_trip(self):
        """``preview`` 会快照/还原：在途标记与循环账都必须活得下来。"""
        machine = self.machine()
        machine.redeem_open_attempts = 2
        machine.preview(fixture(CONFIRM))
        self.assertTrue(machine.redeem_pending)
        self.assertEqual(1, machine.redeem_pending_card)
        self.assertEqual(2, machine.redeem_open_attempts)


if __name__ == "__main__":
    unittest.main()
