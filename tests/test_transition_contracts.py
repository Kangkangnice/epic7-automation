"""新路线「转场契约」护栏。

背景：8 条路线的判据是历史上各长各的 —— 字段名叫法有两种、还有 3 条自带独立主循环，
所以**搜索任何一个字段名都判不出某条路线到底有没有长眼睛**（竞技场和刷书签都有眼睛，
却都不含 ``target_pages``）。本文件守三件事：

① 现状登记表必须覆盖全部路线（防新路线悄悄加进来却没人登记）；
② **每条路线都必须对「动作的出口验收」表态** —— 打开开关，或进豁免名单写明
   用自己的什么机制。漏了在 import 阶段就报错（``modes._assert_transition_stance_declared``），
   这里是第二道（那道自查被人删了也得红）；
③ 强制开关打开后，缺声明的动作一步都点不出去（跑真主循环验证，不是只调校验方法）。

契约本身的定义与填写方式见 ``docs/TRANSITION_CONTRACTS.md``。
"""

import contextlib
import unittest
from pathlib import Path

import numpy as np

from auto_game_unified.games.epic7 import modes
from auto_game_unified.games.epic7.modes import MODE_SPECS, TRANSITION_EXEMPT
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase

DOCS = Path(__file__).resolve().parents[1] / "docs" / "TRANSITION_CONTRACTS.md"


class _LoopStop(BaseException):
    """让主循环停下来的哨兵。

    故意不继承 ``RuntimeError`` —— 主循环里有 ``except RuntimeError`` 的
    「页面识别超时」分支，继承了会被它吞掉。
    """


class FakeAction:
    """只带被测字段的动作；缺的字段用 ``getattr`` 取默认值。"""

    def __init__(self, name: str, **fields) -> None:
        self.name = name
        self.point = (10, 10)
        self.__dict__.update(fields)


class FakeMachine:
    """固定返回同一个动作，第二次取动作时停下主循环。"""

    def __init__(self, action: FakeAction) -> None:
        self.action = action
        self.state = "fake.page"
        self.completed_cycles = 0
        self._served = 0

    def preview(self, screen):
        return FakeAction(self.action.name), None

    def next_action(self, screen):
        self._served += 1
        if self._served > 1:
            raise _LoopStop
        return self.action


class FakeRuntime:
    diagnostic_dir = None
    dry_run = False

    def __init__(self) -> None:
        self.clicks: list = []
        self.messages: list[str] = []
        self.now_value = 0.0

    def now(self) -> float:
        return self.now_value

    def capture(self):
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def click(self, point, name) -> None:
        self.clicks.append((point, name))

    def log(self, message: str) -> None:
        self.messages.append(message)

    def save_diagnostic(self, label, screen):
        return Path(label)


class _EnforcedRunner(ModeRunnerBase):
    """新路线应当长成的样子：打开强制开关。"""

    _MODE_LABEL = "契约测试"
    _REQUIRE_TRANSITION_CONTRACT = True


class _DefaultRunner(ModeRunnerBase):
    """现有路线的样子：不开开关，行为必须与加开关之前完全一致。"""

    _MODE_LABEL = "契约测试"


def _run(action: FakeAction, runner_class) -> tuple[FakeRuntime, Exception | None]:
    """跑真主循环直到停下或被拦下，返回 (runtime, 被拦下的异常)。"""
    runtime = FakeRuntime()
    runner = runner_class(
        FakeMachine(action), runtime, sleep=lambda _: None, poll_seconds=0.0
    )
    error: Exception | None = None
    try:
        runner.run()
    except _LoopStop:
        pass
    except RuntimeError as exc:  # 契约缺失就是走这里
        error = exc
    return runtime, error


class TransitionContractRegistryTests(unittest.TestCase):
    def test_every_route_has_a_row_in_the_registry_section(self):
        """防「新路线加进来了，登记表里却没有它」。"""
        text = DOCS.read_text(encoding="utf-8")
        section = text.split("## 路线判据现状登记", 1)[1].split("\n## ", 1)[0]
        missing = [name for name in MODE_SPECS if f"`{name}`" not in section]
        self.assertEqual([], missing, f"登记表缺这些路线：{missing}")


class TransitionStanceTests(unittest.TestCase):
    """路线准入的第一半：**每条路线都必须对「动作的出口验收」表态**。

    与接力那套（``RESUME_EXEMPT`` + ``test_resume_contracts.py``）刻意做成同构，
    因为它们回答的是同一类问题：「这条路线有没有对某件事表过态」。区别只是
    ——接力管「开局停在半路做不做」，这里管「跑起来之后动作靠什么验收」。

    ⚠️ 为什么不能只靠加载期自查：自查可以被一次「顺手删掉那个调用」抹掉，
    而它抹掉之后**没有任何症状**（路线照跑）。测试是第二道。
    """

    FAKE = "fake_route_for_test"

    @contextlib.contextmanager
    def _fake_route(self, runner_type):
        """临时往 MODE_SPECS 里塞一条路线，退出时一定清干净。

        用 `try/finally` 而不是 `addCleanup`：这里要保证「断言失败时也清理」，
        否则会污染同一次运行里的其它用例。
        """
        spec = modes.ModeSpec(
            name=self.FAKE,
            default_state="x",
            states=frozenset({"x"}),
            build_machine=lambda *_a, **_k: None,
            runner_type=runner_type,
        )
        MODE_SPECS[self.FAKE] = spec
        try:
            yield spec
        finally:
            MODE_SPECS.pop(self.FAKE, None)
            TRANSITION_EXEMPT.pop(self.FAKE, None)

    def test_every_route_declares_its_transition_stance(self):
        """一条路线要么打开开关，要么在豁免名单里写明理由 —— 不许「一个字不提」。"""
        for name, spec in MODE_SPECS.items():
            with self.subTest(route=name):
                enforced = (
                    getattr(spec.runner_type, "_REQUIRE_TRANSITION_CONTRACT", False)
                    is True
                )
                exempt = name in TRANSITION_EXEMPT

                self.assertTrue(
                    enforced or exempt,
                    f"路线 {name} 既没打开转场强制开关，也没在 TRANSITION_EXEMPT 里"
                    "写清「用自己的什么机制验收」",
                )
                self.assertFalse(
                    enforced and exempt,
                    f"路线 {name} 两边都写了：打开了开关就该从豁免名单里划掉",
                )

    def test_the_exemption_list_has_no_stale_names_and_no_empty_reasons(self):
        for name, reason in TRANSITION_EXEMPT.items():
            self.assertIn(
                name, MODE_SPECS, f"豁免名单里的 {name} 不是一条路线（改名了吧？）"
            )
            self.assertGreater(
                len(reason.strip()),
                20,
                f"{name} 的豁免理由太短 —— 要能说清「用自己的什么机制验收」，"
                "不是写个占位符",
            )

    def test_the_switch_only_counts_for_routes_that_use_the_base_loop(self):
        """打开开关的路线，必须真的**走得到**那段校验。

        这个开关只在 ``ModeRunnerBase.run()`` 里被读。``arena`` / ``expedition`` /
        ``shop_refresh`` / ``survivor`` 是自带独立主循环的裸定义（``super()`` 0 次），
        给它们设这个属性**没人读** —— 既不拦也不报错，是个摆设。

        ⚠️ 2026-09-24 实测踩过：我一度把「动作没有 ``target_pages``」直接推成
        「给竞技场打开会全挂」，其实它根本走不到那段代码。这条测试把这个形状钉住。
        """
        for name, spec in MODE_SPECS.items():
            with self.subTest(route=name):
                if (
                    getattr(spec.runner_type, "_REQUIRE_TRANSITION_CONTRACT", False)
                    is True
                ):
                    self.assertTrue(
                        issubclass(spec.runner_type, ModeRunnerBase),
                        f"{name} 打开了开关，却没继承 ModeRunnerBase —— "
                        "那段校验它走不到，这个开关对它是摆设",
                    )

    def test_at_least_one_route_actually_turns_the_switch_on(self):
        """反向护栏：别把「全都豁免」当成通过。"""
        enforced = [
            name
            for name, spec in MODE_SPECS.items()
            if getattr(spec.runner_type, "_REQUIRE_TRANSITION_CONTRACT", False) is True
        ]
        self.assertTrue(
            enforced, "一条打开转场强制开关的路线都没有 —— 这套机制被架空了"
        )

    def test_the_loader_refuses_a_route_that_says_nothing(self):
        """补一条「一个字不提」的路线 ⇒ import 阶段的自查必须炸。"""

        class _Plain(ModeRunnerBase):
            _MODE_LABEL = "假路线"

        with self._fake_route(_Plain):
            with self.assertRaisesRegex(RuntimeError, "TRANSITION_EXEMPT"):
                modes._assert_transition_stance_declared()

    def test_the_loader_refuses_a_route_that_says_it_twice(self):
        """开了开关又躺在豁免名单里 ⇒ 同样炸（两边只许写一边）。"""

        class _Enforced(ModeRunnerBase):
            _MODE_LABEL = "假路线"
            _REQUIRE_TRANSITION_CONTRACT = True

        with self._fake_route(_Enforced):
            TRANSITION_EXEMPT[self.FAKE] = "假理由"
            with self.assertRaisesRegex(RuntimeError, "两边只能写一边"):
                modes._assert_transition_stance_declared()


class TransitionContractEnforcementTests(unittest.TestCase):
    def test_blind_action_is_refused_before_it_is_ever_clicked(self):
        runtime, error = _run(FakeAction("blind-click"), _EnforcedRunner)
        self.assertIsNotNone(error, "完全没有判据的动作必须被拦下")
        self.assertIn("缺少转场契约", str(error))
        self.assertEqual([], runtime.clicks, "被拦下的动作一次都不许点出去")

    def test_action_without_exit_evidence_is_refused(self):
        runtime, error = _run(
            FakeAction("in-page-click", source_page="fake.page"), _EnforcedRunner
        )
        self.assertIsNotNone(error, "只有来源、没有去处的动作必须被拦下")
        self.assertIn("in_page_evidence", str(error))
        self.assertEqual([], runtime.clicks)

    def test_action_without_source_page_is_refused(self):
        runtime, error = _run(
            FakeAction("orphan-click", target_pages=("next.page",)), _EnforcedRunner
        )
        self.assertIsNotNone(error, "没有来源的动作必须被拦下")
        self.assertIn("source_page", str(error))
        self.assertEqual([], runtime.clicks)

    def test_page_change_action_is_allowed(self):
        runtime, error = _run(
            FakeAction(
                "go-next", source_page="fake.page", target_pages=("next.page",)
            ),
            _EnforcedRunner,
        )
        self.assertIsNone(error)
        self.assertEqual(1, len(runtime.clicks))

    def test_in_page_action_is_allowed_when_it_declares_its_evidence(self):
        runtime, error = _run(
            FakeAction(
                "flip-auto",
                source_page="fake.page",
                in_page_evidence="自动按钮由橙变蓝",
            ),
            _EnforcedRunner,
        )
        self.assertIsNone(error)
        self.assertEqual(1, len(runtime.clicks))

    def test_existing_routes_are_untouched_because_the_switch_defaults_off(self):
        """默认关闭 ⇒ 缺判据的动作照旧发出，现有路线行为不变。"""
        runtime, error = _run(FakeAction("blind-click"), _DefaultRunner)
        self.assertIsNone(error)
        self.assertEqual(1, len(runtime.clicks))


if __name__ == "__main__":
    unittest.main()
