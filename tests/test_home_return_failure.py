"""「出岔子也回大厅」的契约测试。

## 这件事的来龙去脉

用户 2026-09-25 拍板：

> 异常了也该走回大厅，**包括战斗里，直接放弃这一局**。

以前异常退出是**撒手不管**的（`runner_base._close_out` 只挂在「正常跑完」和
「资源耗尽」两条路上），理由是「跑到一半挂了，硬按 Back 可能把已承诺的战斗弄丢」。
新流程处理这个顾虑的办法不是撒手不管，而是**显式放弃**（暂停 → 放弃战斗 →
放弃确认），所以异常也回家更干净。

## 守三件事

1. **出岔子就回家，而且回家本身不吞掉错因** —— 回家之后原异常照旧往外抛，
   结论还是「运行失败」。
2. **你按 P 停就不许动游戏** —— `ManualStop` 不是「出岔子」，是「我要停了」，
   这时候再操作游戏是添乱。这是全线统一口径，不能因为「异常也回家」被带偏。
3. **白名单外的路线一个字都不变** —— 这条新行为**只对切到 v2 的路线生效**，
   推进节奏是「先在竞技场验收，验收一条加一条」。

## 为什么必须是真 Runner 级

2026-09-25 那两次事故（骑士团捐赠）都发生在**状态机与主循环之间**：判据本身是对的，
但主循环压根没用它。所以这里不测「判据存不存在」，而是真的把 `run_mode` 跑一遍，
看它有没有真去调用「回大厅」。
"""

import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from auto_game_unified import main as main_module
from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.games.epic7.modes import get_mode
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)
import auto_game_unified.games.epic7.home_return as home_return_module


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
NAVIGATION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"


def _lobby_frame() -> np.ndarray:
    """真大厅帧 —— 全黑帧认不出来，会掉进兜底分支，测不出「到家」这条路。"""
    image = np.asarray(
        Image.open(NAVIGATION_FIXTURES / "lobby.png").convert("RGB")
    )
    return image[:1132, :1982]


def _indoor_frame() -> np.ndarray:
    """真「局内」帧 —— 右上角有 ``‖`` 暂停图标，会走进「按 ESC」那条分支。

    用迷宫的房间帧（``pause_icon`` 在这张上 1.0000 命中），不是临时造的图：
    这条测试要说的是**实跑里真实发生的事**，用真帧才有说服力。
    """
    image = np.asarray(
        Image.open(
            ROOT / "tests" / "fixtures" / "epic7_labyrinth_stone" / "room.png"
        ).convert("RGB")
    )
    return image[:1132, :1982]


def _shop_frame() -> np.ndarray:
    """迷宫商店页（**对导航层是 unknown**）—— 2026-10-19 那次卡死 120 秒的现场。

    这张帧上「蓝色四格」照样得 **0.835**（阈值 0.80），因为商店浮层只把它压暗、
    没把它移走；但点下去**什么也不会发生**（那颗按钮其实被浮层盖着）。
    """
    image = np.asarray(
        Image.open(
            ROOT
            / "tests"
            / "fixtures"
            / "epic7_labyrinth_stone"
            / "shop_clipped_bottom_row_live_20261019.png"
        ).convert("RGB")
    )
    return image[:1132, :1982]


LOBBY_FRAME = _lobby_frame()
INDOOR_FRAME = _indoor_frame()
SHOP_FRAME = _shop_frame()


def _sequence_runtime(frames: list, *, sleeps: list | None = None, logs: list | None = None):
    """真 Runtime，但截图器按给定序列回放（用完最后一张就一直回放它）。

    给「回家必须连续两帧稳定才返回」这类守卫测试用：回家要连吃两帧才能稳定，
    所以截图器必须能多喂几张、而不是只回放同一张。
    """
    clock = _FakeClock()

    def capture():
        if frames:
            capture._sent.append(frames.pop(0))
        return capture._sent[-1]

    capture._sent = []

    def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)
        clock.advance(seconds)

    runtime = Runtime(
        capture,
        click=lambda *_a, **_k: None,
        back=lambda: None,
        emit=(logs.append if logs is not None else lambda _m: None),
        monotonic=clock,
    )
    return runtime, sleep


def _run_mode_with_exception(
    *,
    mode: str,
    raised: BaseException,
) -> mock.MagicMock:
    """跑一次 ``run_mode``，让路线的 ``run()`` 抛出指定异常。

    返回那个假的「回大厅」对象 —— 用来断言「有没有真的去回家」。

    ⚠️ 用 ``HomeReturn`` 这个正式接口做替身，而不是去替换 ``navigator.return_home``：
    「回大厅」由前者统一入口，替换后者什么也拦不住。
    """
    runtime = mock.MagicMock()
    runtime.sleep = lambda _seconds: None
    navigator = mock.MagicMock()
    navigator.templates = object()
    navigator.poll_seconds = 0.5
    home_return = mock.MagicMock()

    with (
        mock.patch.object(main_module, "_build_runtime", return_value=runtime),
        mock.patch.object(main_module, "Epic7Navigator", return_value=navigator),
        mock.patch.object(main_module, "HomeReturn", return_value=home_return),
        mock.patch.object(main_module, "_enter_mode"),
    ):
        spec = get_mode(mode)
        with mock.patch.object(spec.runner_type, "run", side_effect=raised):
            try:
                main_module.run_mode(
                    spec=spec,
                    dry_run=False,
                    max_cycles=1,
                    start_state=spec.default_state,
                )
            except BaseException as caught:  # noqa: BLE001 —— 就是要把抛出来的接住
                # 原异常要**原样**出去，不能被「回家」这件事换掉或盖住。
                if caught is not raised:
                    raise AssertionError(
                        f"应当原样抛出 {raised!r}，实际是 {caught!r}"
                    ) from caught
            else:
                raise AssertionError(f"应当抛出 {raised!r}，实际正常返回了")

    return home_return


class FailureReturnHomeTests(unittest.TestCase):
    """出岔子之后该不该回家。"""

    def test_exception_triggers_return_home_and_reraises(self):
        """跑挂了 ⇒ 回家一次，且**原异常照旧抛出**（结论还是「运行失败」）。"""
        error = RuntimeError("页面认不出来")

        home_return = _run_mode_with_exception(mode="arena", raised=error)

        home_return.assert_called_once_with()

    def test_manual_stop_does_not_touch_the_game(self):
        """用户按 P 停 ⇒ **一个动作都不许发**（这是「我要停了」，不是「出岔子」）。"""
        error = ManualStop("用户按下 P")
        home_return = _run_mode_with_exception(mode="arena", raised=error)

        home_return.assert_not_called()

    def test_every_route_goes_home_after_a_failure(self):
        """**没有例外路线**：2026-09-26 起白名单整表删除，10 条路线一律回家。

        ⚠️ 这条用例以前是「白名单外不回家」，语义正好相反。留着它、把断言翻过来，
        是为了守住「别再把分叉加回来」—— 一旦有人又写了 ``if mode in ...``，这里就红。
        """
        error = RuntimeError("页面认不出来")
        home_return = _run_mode_with_exception(mode="labyrinth_stone", raised=error)

        home_return.assert_called_once_with()


class RealWiringTests(unittest.TestCase):
    """**不 mock `HomeReturn`**，让它走真代码 —— 专抓「替身永远发现不了」的接口错配。

    2026-09-25 实跑抓到的两个 bug 都落在这个盲区里：

    1. `HomeReturn` 里写了 `self._runtime.sleep`，而 `Runtime` **压根没有这个属性**
       ⇒ 一实跑就 `AttributeError` 崩掉。单元测试全绿，因为测试统统把 `HomeReturn`
       整个 mock 掉了，真代码一行没跑。
    2. 开局就在大厅时，v2 提前返回、没问接力探针 ⇒ `_enter_mode` 的接线检查误报
       「接线断了」。测试里没造过这个场景。

    所以这一组**只 mock 窗口层**（截图/点击/返回），`Runtime` / `Epic7Navigator` /
    `HomeReturn` 全用真的。
    """

    def test_a_real_home_return_object_can_be_built_and_called(self):
        """真对象真跑一遍：能构造、能调用、最后能落到大厅。

        这条就是抓 bug ① 的 —— 只要 `HomeReturn.__call__` 里引用了 `Runtime`/
        `Epic7Navigator` 上不存在的属性，这里立刻炸。
        """
        navigator = _real_navigator(LOBBY_FRAME)
        runtime = navigator.runtime

        home_return = main_module.HomeReturn(navigator, runtime, mode="arena")

        result = home_return()

        # 大厅帧进、大厅帧出（第一帧就确认到家），且**没有任何点击**。
        self.assertIs(LOBBY_FRAME, result)
        self.assertEqual([], navigator.runtime.clicks)

    def test_lobby_start_still_asks_the_resume_probe(self):
        """开局就在大厅时，v2 **也要问一次接力探针**（答案必然是「不命中」）。

        这条抓 bug ②：`_enter_mode` 有一条接线检查 ——「挂了探针却一次没问过
        ⇒ 接线断了」。v2 如果在家时图省事提前返回，那条检查会在
        **「开局就在大厅」这个最常见的情况下**误报，逼着人放松检查。
        问一次的成本是零，收益是接线检查继续有效。
        """
        navigator = _real_navigator(LOBBY_FRAME)
        home_return = main_module.HomeReturn(
            navigator, navigator.runtime, mode="arena"
        )
        asked: list[np.ndarray] = []

        def probe(screen: np.ndarray) -> bool:
            asked.append(screen)
            return False

        home_return(stop_probe=probe)

        self.assertEqual(1, len(asked), "到家那一步必须问过探针")

    def test_another_route_uses_the_same_single_flow(self):
        """换一条路线（狗粮）走**同一套**流程，行为必须一模一样。

        以前这里测的是「白名单外的路线走老流程」；老流程 2026-09-26 已删，
        现在只剩一套实现，这条用例改守「换路线不会走出第二种行为」。
        """
        navigator = _real_navigator(LOBBY_FRAME)
        home_return = main_module.HomeReturn(
            navigator, navigator.runtime, mode="fodder"
        )

        self.assertIs(LOBBY_FRAME, home_return())
        self.assertEqual([], navigator.runtime.clicks)

    def test_home_return_v2_returns_on_second_consecutive_lobby_frame_not_the_first(self):
        """回家必须「连续两帧稳定认出大厅」（页面名 "lobby"）才返回，
        与导航层 ``StableObservation(required=2)`` 同一套约定 —— 不能「第一帧认出大厅就返回」。

        「第一帧就返回」是之前那个孤例：会把还在动画的过渡大厅帧交出去，导航层再认不到
        左侧入口（``lobby_shop_entry``）就 ✗。这条把「两帧」这个全局约定钉死。

        喂两张**不同的**大厅帧（页面名都是 "lobby"）：断言回家返回的是**第 2 帧**，
        绝不可能是第 1 帧。

        变异验证：把 ``return_home_v2`` 的返回条件改回「第一帧认出大厅就返回」
        （即 ``if observed == "lobby"`` 去掉 ``and is_stable``）⇒ 这条立刻红
        （返回的是第 1 帧而不是第 2 帧）。
        """
        lobby_a = LOBBY_FRAME
        lobby_b = LOBBY_FRAME.copy()

        def observe(screen: np.ndarray) -> str:
            return "lobby"

        templates = home_return_module.build_home_return_templates(
            TEMPLATES, build_navigation_templates(TEMPLATES)
        )
        runtime, sleep = _sequence_runtime([lobby_a, lobby_b])
        result = home_return_module.return_home_v2(
            templates=templates,
            runtime=runtime,
            observe=observe,
            sleep=sleep,
            poll_seconds=0.5,
        )
        # 返回的必须是第 2 帧（连续两帧稳定后的那一帧），而不是第 1 帧。
        self.assertIs(lobby_b, result)

    def test_esc_waits_long_enough_for_the_screen_to_turn_over(self):
        """按完 ESC 之后必须**等够时间**再判下一帧，否则同一层会退两层。

        这条守的是 2026-09-25 实跑暴露的第三件事（前两件见类 docstring）。
        实机日志：

            19:25:04 模式=导航 流程=v2 动作=按ESC 原因=兜底 次数=1/8
            19:25:06 模式=导航 流程=v2 动作=按ESC 原因=兜底 次数=2/8

        只隔 2 秒就按了第二下 —— **同一层退了两层**，白烧两次返回预算
        （上限 8 次）。老流程等 15 秒（``navigation._BACK_RETRY_SECONDS``），
        慢但不会重复按；v2 原先只等 1 秒，快但会重复按。
        用户 2026-09-25 拍板取折中 **3~5 秒**。

        ⚠️ 断言的是**区间**不是某个具体数字：以后在 3~5 秒内微调不该打红，
        但退回 1 秒（也就是重犯这个错）必须红。
        """
        waited: list[float] = []
        navigator = _real_navigator(INDOOR_FRAME, sleeps=waited)
        home_return = main_module.HomeReturn(
            navigator, navigator.runtime, mode="arena"
        )

        try:
            home_return()
        except RuntimeError:
            # 单帧反复喂同一张局内图，永远到不了家 ⇒ 最后会撞上限。
            # 这条测试只关心「按 ESC 之后等了多久」，撞上限无所谓。
            pass

        self.assertTrue(waited, "ESC 之后必须有一次等待，否则下一帧还是旧画面")
        esc_waits = [w for w in waited if w >= 2.0]
        self.assertTrue(
            esc_waits,
            f"按完 ESC 之后没有任何 ≥2 秒的等待，实际等过：{waited}",
        )
        for seconds in esc_waits:
            self.assertGreaterEqual(seconds, 3.0, f"等得太短（实跑会重复按）：{seconds}")
            self.assertLessEqual(seconds, 5.0, f"等得太久（比老流程还慢）：{seconds}")

    def test_repeated_esc_on_a_page_that_does_not_move_is_stopped(self):
        """**按了 ESC、但页面纹丝不动 ⇒ 不许一直按下去。**

        这条是整个 2026-09-25 加固的**核心**，专门抓「验收被拿掉」的退化。

        夹具就是一个「按 ESC 不管用」的页面：``INDOOR_FRAME``（迷宫房间，
        右上角有 ``‖``，走的是「局内按 ESC」那条分支），而截图器**永远回放同一帧**
        ⇒ 页面身份永远是同一个 ⇒ 每一次按 ESC 都被判「无效」。

        期望行为：**连按两次无效就止损报错**，而不是把 8 次预算全烧光。

        | 版本 | 按 ESC 次数 | 结果 |
        | --- | --- | --- |
        | 加固前（按完不验收） | **8 次**（撞上限） | 8 次全白按，最后才报错 |
        | 加固后（验收 + 止损） | **2 次** | 第 2 次就认定「ESC 在这儿不管用」 |

        ⚠️ 断言上界用的是 **3**（不是 2）：给实现留一点余地（比如以后想在两次之间
        插一次别的尝试），但**必须显著小于 8** —— 只要退回「按完不验收」，
        次数立刻回到 8，这条就红。

        变异验证：把 ``press_esc`` 里的 ``_wait_for_change`` 判定删掉、
        改成无条件 ``return back_count`` ⇒ 立刻红（实测 8 != 期望）。
        """
        navigator = _real_navigator(INDOOR_FRAME)
        home_return = main_module.HomeReturn(
            navigator, navigator.runtime, mode="arena"
        )

        try:
            home_return()
        except RuntimeError:
            pass  # 止损报错是**预期**结果，不是测试失败

        presses = len(navigator.runtime.backs)
        self.assertGreaterEqual(presses, 1, "这一帧应当会触发按 ESC")
        self.assertLessEqual(
            presses,
            3,
            f"ESC 在这一页上没用，却按了 {presses} 次（上限 8）—— "
            "说明「按完回头看」的验收没了，正在重复按同一个 ESC",
        )

    def test_a_click_that_does_not_move_the_page_is_reported(self):
        """点了东西但页面没动 ⇒ 日志里必须留下「点击验收=无效」。

        与上一条互补：上一条数**次数**（防重复按），这条查**痕迹**（防静默）。
        没有这一行日志，事后翻记录分不清「点生效了」和「点了没用」——
        2026-09-25 那次翻车之所以难查，就是因为日志里只有「动作=点酒馆」，
        没有「点完到底怎么样了」。
        """
        logs: list[str] = []
        navigator = _real_navigator(INDOOR_FRAME, logs=logs)
        home_return = main_module.HomeReturn(
            navigator, navigator.runtime, mode="arena"
        )

        try:
            home_return()
        except RuntimeError:
            pass

        joined = "\n".join(logs)
        self.assertIn(
            "返回验收=无效",
            joined,
            f"按了 ESC 但页面没动，必须留下「返回验收=无效」的日志；实际日志：{joined}",
        )

    def test_the_verdict_follows_the_page_identity_not_the_pixels(self):
        """**生效与否只看页面身份，不看画面像素** —— 用「反着来」的夹具钉死。

        做法：截图器**永远回放同一张帧**（像素零变化），但让 ``observe``
        从第 3 次调用起开始报另一个页面名。两种判据会得出相反结论：

        | 判据 | 会判成 | 日志里留下什么 |
        | --- | --- | --- |
        | 画面像素差 | **无效**（一像素没动） | `点击验收=无效` |
        | 页面身份 | **生效**（页面换了） | `点击验收=生效` |

        ⚠️ 为什么不断言「按了几次 ESC」：**主循环压根不看 ``observe``**，
        它只认模板。这一帧里有 ``pause_icon``，所以主循环每轮都会重新走
        「按 ESC」分支 —— 按几次取决于主循环的轮数，跟验收判据无关。
        真正能区分的证据是**验收那一句日志**。

        ⚠️ 为什么非要这么绕：真帧实测「同一页自己动」的画面差（``frac_gt8`` 到
        0.9004）**盖过**了「真实换页」的下限（0.7840），两个区间完全重叠。
        也就是说像素判据在这个项目里**根本没法当验收用**。
        这条测试就是不让它悄悄混进来。

        变异验证：把 ``_wait_for_change`` 里的页面身份分支改成 ``if False``
        （等于退回纯像素判据）⇒ 这条立刻红（日志里只会出现 `点击验收=无效`，
        以及一行「验收降级」）。
        """
        logs: list[str] = []
        navigator = _real_navigator(INDOOR_FRAME, logs=logs)
        original = navigator.observe
        calls = {"n": 0}

        def shifting_observe(screen: np.ndarray):
            """前两次报「局内」（让流程决定按 ESC），之后改报另一个页面。"""
            calls["n"] += 1
            result = original(screen)
            if calls["n"] <= 2:
                return result
            return type(result)("some_other_page", result.confidence)

        navigator.observe = shifting_observe  # type: ignore[method-assign]
        home_return = main_module.HomeReturn(
            navigator, navigator.runtime, mode="arena"
        )

        try:
            home_return()
        except RuntimeError:
            pass

        joined = "\n".join(logs)
        self.assertGreaterEqual(calls["n"], 1, "整个流程一次都没问过页面识别")
        self.assertIn(
            "点击验收=生效",
            joined,
            "画面一像素没动、但页面身份变了 —— 这时候应当判「生效」。"
            f"实际没有这一行，说明验收看的是像素、不是页面身份。日志：\n{joined}",
        )

    def test_the_page_identity_path_is_not_a_downgrade(self):
        """真接了 ``observe`` 时**不许走降级分支** —— 防止「接了但没用上」。

        ``_ActionVerifier`` 有两条路：有页面身份走验收、没有就降级到整帧比对
        （并打一行「验收降级」）。如果哪天接错了参数，程序**不会崩**，
        只是悄悄退回降级路径 —— 那种退化没有任何测试会红。

        所以这里断言：**接了 ``observe`` 的场合，日志里不该有「验收降级」。**
        """
        logs: list[str] = []
        navigator = _real_navigator(INDOOR_FRAME, logs=logs)
        home_return = main_module.HomeReturn(
            navigator, navigator.runtime, mode="arena"
        )

        try:
            home_return()
        except RuntimeError:
            pass

        joined = "\n".join(logs)
        self.assertNotIn(
            "验收降级",
            joined,
            "已经接入了页面识别，却还在走降级路径 —— 说明 observe 没传到验收器。"
            f"日志：\n{joined}",
        )

    def test_a_click_that_never_moves_the_page_is_retired_instead_of_retried(self):
        """**钉住 2026-10-19 事故**：点了没用就必须换招，不许原地重试到 120 秒。

        现场（``runtime_logs/desktop_worker.log`` 19:36:51~19:38:20）是这样的 ——
        同一行重复了 **8 次**，中间一个字都没变::

            动作=打开快捷菜单 置信度=0.835 坐标=(1858, 103) 动作前页面=unknown
            动作=打开快捷菜单 点击验收=无效 页面=unknown 已等=12秒

        每一轮还要空等 12 秒 ⇒ 120 秒预算全烧光，最后只报「超过 120 秒仍未回到大厅」，
        事后完全看不出它卡在哪一页。

        这一条守两件事：

        1. **同一个动作最多点 2 次**（``_MAX_INEFFECTIVE_CLICKS``），然后停用；
        2. **不许以「120 秒超时」收场** —— 停用后落到 ESC 兜底，ESC 两次无效就
           带着页面身份报错。报错要能说明「停在哪一页」。
        """
        logs: list[str] = []
        navigator = _real_navigator(SHOP_FRAME, logs=logs)
        home_return = main_module.HomeReturn(
            navigator, navigator.runtime, mode="labyrinth_stone"
        )

        with self.assertRaises(RuntimeError) as caught:
            home_return()

        message = str(caught.exception)
        self.assertNotIn(
            "超过 120 秒",
            message,
            "点无效之后应当立刻换招，而不是把 120 秒预算原地烧光；"
            f"实际报错：{message}",
        )
        self.assertIn("ESC", message, f"换招应当落到 ESC 兜底；实际报错：{message}")

        clicks = navigator.runtime.clicks
        self.assertLessEqual(
            len(clicks),
            2,
            f"同一个无效点击被重复了 {len(clicks)} 次（上限 2）：{clicks}",
        )
        self.assertIn(
            "停用该动作改走ESC兜底",
            "\n".join(logs),
            "停用动作必须留下日志 —— 不许悄悄换招",
        )

    def test_without_observe_the_downgrade_is_announced(self):
        """没接 ``observe`` 时必须**留下一行降级日志** —— 不许悄悄跳过。

        降级本身是允许的（老调用方、没导航器的场景），
        但「悄悄降级」等于「没测到」冒充「没问题」。
        所以降级必须**看得见**。
        """
        logs: list[str] = []
        navigator = _real_navigator(INDOOR_FRAME, logs=logs)

        templates = home_return_module.build_home_return_templates(
            TEMPLATES, navigator.templates
        )
        try:
            home_return_module.return_home_v2(
                templates=templates,
                runtime=navigator.runtime,
                observe=None,
                sleep=navigator.sleep,
                poll_seconds=navigator.poll_seconds,
            )
        except RuntimeError:
            pass

        # 这一帧会一直走「按 ESC」，验收每次都会降级 —— 只要记过一次就够。
        self.assertIn(
            "验收降级",
            "\n".join(logs),
            "没接页面识别时必须明确记一行「验收降级」，不能悄悄跳过。"
            f"日志：\n{chr(10).join(logs)}",
        )


def _real_navigator(
    frame: np.ndarray,
    *,
    sleeps: list[float] | None = None,
    logs: list[str] | None = None,
) -> Epic7Navigator:
    """造一个**真的**导航器：真模板、真 Runtime，只有窗口层被换成喂帧。

    返回的导航器上挂了两个便于断言的列表（`clicks` / `backs`）—— 是测试自加的属性，
    不改生产代码。

    ``sleeps`` 给了就把每次等待的秒数记进去。**记录的同时还要推进假时钟** ——
    ``return_home_v2`` 靠 ``runtime.now()`` 判 120 秒超时，真实时钟在 no-op sleep
    下几乎不动，不推就会绕到超时上去。

    ``logs`` 给了就把每条日志收进去（用于断言「有没有留下验收痕迹」）。
    """
    clicks: list[tuple[int, int]] = []
    backs: list[int] = []
    clock = _FakeClock()

    def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)
        clock.advance(seconds)

    runtime = Runtime(
        lambda: frame,
        clicks.append,
        back=lambda: backs.append(1),
        emit=(logs.append if logs is not None else lambda _message: None),
        monotonic=clock,
    )
    runtime.clicks = clicks  # type: ignore[attr-defined]
    runtime.backs = backs  # type: ignore[attr-defined]
    navigator = Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        runtime,
        sleep=sleep,
        transition_frames=1,
    )
    return navigator


class _FakeClock:
    """单调递增的假时钟：`time.sleep` 被换成 no-op 之后，真时钟几乎不动，
    而 `return_home_v2` 要靠时间判超时，所以这里每次读都往前走一点。"""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 0.01
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


if __name__ == "__main__":
    unittest.main()
