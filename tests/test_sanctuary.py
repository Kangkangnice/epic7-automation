"""圣域收菜（``sanctuary``）的判据测试。

三条硬要求（都是本项目踩过的坑，与 ``test_labyrinth_stone.py`` 同一套）：

1. **拿真夹具跑**：判据写反 / 阈值抄错 / 名字拼错，全都表现为「永远认不出」，
   单看代码看不出来。本文件每张断言都建立在 ``tests/fixtures/epic7_sanctuary``
   里那 18 张实拍帧上。
2. **必须有真 Runner 级的用例**：骑士团捐赠两次事故都发生在**状态机与主循环之间**
   （判据写对了却没接上）。只测 ``next_action`` 是测不出来的 —— 必须让真
   ``ModeRunnerBase.run()`` 把整条链走一遍。
3. **每个动作都要有转场契约**：``_REQUIRE_TRANSITION_CONTRACT`` 只保证「缺声明会抛错」，
   不保证「声明的是对的」；这里逐个动作点名核对。

⚠️ 画面一律转 RGB：``load_template`` 会把模板转成 RGB，用 BGR 读夹具会让
分数凭空掉一截（蓝底控件实测 1.0000 → 0.87，见 ``evidence/sanctuary.py``）。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from auto_game_unified.games.epic7 import sanctuary
from auto_game_unified.games.epic7.evidence.sanctuary import (
    claimable_rows,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen
from auto_game_unified.games.epic7.sanctuary import (
    SANCTUARY_HOME_PAGE,
    SanctuaryAction,
    SanctuaryRunner,
    SanctuaryState,
    detect_resume_point,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_sanctuary"


def frame(name: str) -> np.ndarray:
    raw = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert raw is not None, f"缺夹具 {name}.png"
    return cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)


def build_machine():
    from auto_game_unified.games.epic7.modes import get_mode

    spec = get_mode("sanctuary")
    return spec.build_machine(TEMPLATE_ROOT, spec.default_state)


# ---- ① 每张夹具认得出它该认的那一页 -------------------------------------------

PAGE_CASES = [
    # 圣域主页（三个来源各一张：刚进圣域 / 从精灵之森返回 / 准备回大厅）
    ("home", SanctuaryState.HOME),
    ("home_from_forest", SanctuaryState.HOME),
    ("home_before_leaving", SanctuaryState.HOME),
    # 精灵之森：可领两三行
    ("forest_two_claimable_00", SanctuaryState.FOREST),
    ("forest_two_claimable_05", SanctuaryState.FOREST),
    ("forest_two_claimable_entry", SanctuaryState.FOREST),
    ("forest_two_claimable_old", SanctuaryState.FOREST),
    # 精灵之森的**最坏帧**：12 帧连拍里分数最低的那一张（闪烁把分数压到 0.9733/0.9744）。
    # 它必须与上面几张一起认成同一页 —— 这就是「闪烁不影响判据」的物证。
    ("forest_two_claimable_08", SanctuaryState.FOREST),
    # 精灵之森：只剩一行可领
    ("forest_spring_only", SanctuaryState.FOREST),
    ("forest_after_penguin", SanctuaryState.FOREST),
    # 精灵之森：三行全在倒计时（本轮收工态）
    ("forest_all_done", SanctuaryState.FOREST),
    # 领取完成弹窗（三种：企鹅、等了 6 秒仍未消失、精灵之泉）
    ("popup_penguin", SanctuaryState.CLAIM_POPUP),
    ("popup_penguin_after6s", SanctuaryState.CLAIM_POPUP),
    ("popup_penguin_before_close", SanctuaryState.CLAIM_POPUP),
    ("popup_spring", SanctuaryState.CLAIM_POPUP),
]


@pytest.mark.parametrize("fixture,expected", PAGE_CASES)
def test_fixture_is_recognised_as_its_page(fixture: str, expected: SanctuaryState):
    machine = build_machine()
    assert machine.observe_page(frame(fixture)) is expected


# 大厅两帧 + 一张「点了圣域之后那一瞬间」的过渡帧。
#
# ⚠️ 这三张**必须**认不出，而且理由各不相同：
# - 大厅两帧：认不出才对，接力探针在大厅上不许接管（那样会跳过「进圣域」这一步）；
# - ``lobby_after_click`` 是**转场中间帧**（圣域主页还在淡入，``forest_row`` 只有
#   0.2417）⇒ 认不出同样是对的：主循环要求「连续两帧稳定」才发动作，
#   这种帧按设计就该被丢掉。
UNRECOGNISED_FIXTURES = ["lobby_entry", "lobby_entry_b", "lobby_after_click"]


@pytest.mark.parametrize("fixture", UNRECOGNISED_FIXTURES)
def test_these_fixtures_are_deliberately_not_recognised(fixture: str):
    machine = build_machine()
    assert machine.observe_page(frame(fixture)) is None


def test_the_transition_frame_is_not_mistaken_for_the_sanctuary_home():
    """点完「圣域」那一瞬间的帧不能被当成圣域主页。

    这是「淡入帧」这一类判据事故的守卫（``labyrinth_stone`` 2026-09-25 因为把淡入帧
    当成「认不出」而直接放弃战斗）。这里反着守：**不许把淡入帧当成已到位** ——
    真把他当到位了，状态机会立刻去点还不存在的「精灵之森」。
    """
    machine = build_machine()
    assert machine.observe_page(frame("lobby_after_click")) is None
    # 断言具体异常类型（别用 Exception 兜）：认不出画面就该是 UnrecognizedScreen，
    # 换成别的异常说明这条路径走歪了。
    with pytest.raises(UnrecognizedScreen):
        machine.next_action(frame("lobby_after_click"))

    # 反证：站稳之后（同一页的另一帧）必须认得出。
    assert machine.observe_page(frame("home")) is SanctuaryState.HOME


# ---- ② 每一页想点的那一下（含点击坐标来自模板，不是写死的）--------------------

# (夹具, 期望动作名, 期望点击点, 期望出口)
ACTION_CASES = [
    ("home", "open-forest", (1786, 312), ("精灵之森",)),
    ("home_from_forest", "open-forest", (1786, 312), ("精灵之森",)),
    # ⚠️ 可领两行时**只能点最上面那一行**（y=445）。
    ("forest_two_claimable_00", "claim-row", (1558, 445), ("领取完成弹窗",)),
    ("forest_two_claimable_08", "claim-row", (1558, 445), ("领取完成弹窗",)),
    # 企鹅领掉之后，剩下的那一行是第 2 行（y=619）。
    ("forest_spring_only", "claim-row", (1558, 619), ("领取完成弹窗",)),
    ("forest_after_penguin", "claim-row", (1558, 619), ("领取完成弹窗",)),
    # 弹窗：点掉它，**不能等它自己消失**（用户口述与实测不符，见模块 docstring）。
    ("popup_penguin", "dismiss-claim", (964, 842), ("精灵之森",)),
    ("popup_penguin_after6s", "dismiss-claim", (964, 842), ("精灵之森",)),
    ("popup_spring", "dismiss-claim", (964, 842), ("精灵之森",)),
]


@pytest.mark.parametrize("fixture,action,point,targets", ACTION_CASES)
def test_action_and_its_declared_exit(
    fixture: str,
    action: str,
    point: tuple[int, int],
    targets: tuple[str, ...],
):
    machine = build_machine()

    result = machine.next_action(frame(fixture))

    assert result is not None, f"{fixture} 上应该有动作，实际收工了"
    assert result.name == action
    assert result.point == point, "点击点必须来自模板命中框中心，不许写死"
    assert result.target_pages == targets
    # 契约两半都不能空：从哪来 + 到哪去（同页动作用页内证据）。
    assert result.source_page, f"{action} 没声明来源页面"
    assert result.target_pages or result.in_page_evidence, (
        f"{action} 既没写去处也没写页内验收依据"
    )


def test_the_click_points_really_come_from_the_templates():
    """坐标不是抄来的：``home`` 那一下 = ``forest_row`` 的命中框中心。"""
    machine = build_machine()
    screen = frame("home")
    match = machine._locate(screen, "forest_row")

    assert match is not None
    assert machine.next_action(screen).point == match.center


# ---- ③ 收工：三行全在倒计时 ---------------------------------------------------


def test_all_countdown_closes_the_pass():
    machine = build_machine()

    assert machine.next_action(frame("forest_all_done")) is None
    assert machine.completed_cycles == 1
    assert machine.state is SanctuaryState.FINISHED
    assert "领取奖励" in machine.finish_reason


# ---- ④ 「领取奖励」是唯一判据：闪烁、红点、蓝底都不参与 -----------------------


# 12 帧连拍里分数最低的那一张（0.9733 / 0.9744）。它离阈值 0.80 还有 0.17 的余量。
WORST_FLASHING_FRAME = "forest_two_claimable_08"


def test_the_slowest_flashing_frame_still_shows_both_claimable_rows():
    """闪烁只把分数从 1.0000 压到 0.9733，**远没有到要调阈值的程度**。

    用户描述的可领特征里有「整块在闪」，12 帧连拍（间隔 0.4s）实测相邻帧差异
    0.68~2.49、整幅亮度 53.29~54.86 脉动。模板匹配是零均值归一化的，闪的是底色
    亮度不是形状 ⇒ 代价可以接受，**不需要为它做补偿，更不该为它降阈值**。
    """
    machine = build_machine()

    rows = claimable_rows(frame(WORST_FLASHING_FRAME), machine.templates.claim_text)

    assert [sanctuary.claim_row_label(row.center[1]) for row in rows] == [
        "第1行·企鹅巢穴",
        "第2行·精灵之泉",
    ]
    assert min(row.score for row in rows) > 0.95, "最坏帧也要离阈值 0.80 有足够余量"


def test_rows_are_ordered_top_to_bottom_not_by_score():
    """**按位置排序，不按分数排序** —— 这是一条真会翻车的判据。

    实测第 1/2 行的分数只差 0.001~0.01，而且帧间会互相反超：这一帧第 1 行 0.9733
    / 第 2 行 0.9744（第 2 行更高），下一帧又反过来。按分数排的实现在几行之间
    来回跳，表现是「同一个材料被反复点、另一行永远轮不到」。
    """
    machine = build_machine()

    rows = claimable_rows(frame(WORST_FLASHING_FRAME), machine.templates.claim_text)

    assert rows[0].center[1] < rows[1].center[1], "必须按 y 从上到下"
    assert rows[0].score < rows[1].score, (
        "这一帧第 1 行的分数**低于**第 2 行 —— 正是「按分数排会选错」的物证；"
        "把排序改成按分数，这条会红"
    )


def test_the_dimmed_page_under_the_popup_offers_no_claim():
    """弹窗盖着的时候，底页的「领取奖励」被压暗到 0.52~0.55 ⇒ 一行都找不出来。

    ⚠️ 这是**有用的副作用**，不是判据本身：即使页面判定顺序写错、把弹窗判成
    精灵之森页，也不会误点「领取奖励」。
    """
    machine = build_machine()

    for name in ("popup_penguin", "popup_penguin_after6s", "popup_spring"):
        assert claimable_rows(frame(name), machine.templates.claim_text) == []


def test_the_popup_wins_over_the_page_underneath():
    """弹窗必须判在精灵之森**之前**：它只把底页压暗，标题照样 0.9998 命中。

    顺序反了的后果：对着一页盖着弹窗的画面去点「领取奖励」—— 那一下点在
    弹窗遮罩上，什么都不发生，然后主循环会反复重试到报错。
    """
    machine = build_machine()
    screen = frame("popup_penguin")

    # 前提：底页的锚点在弹窗下**仍然**过阈 —— 所以顺序不能靠分数救。
    assert machine._locate(screen, "forest_title") is not None
    assert machine._locate(screen, "popup_close") is not None
    assert machine.observe_page(screen) is SanctuaryState.CLAIM_POPUP


def test_the_popup_does_not_disappear_on_its_own():
    """**钉住与用户口述不符的那条实测结论**：弹窗不会自己消失。

    用户 2026-09-29 说「点完之后它就是一个很小的弹窗，**也不需要你点**」。
    实测：弹出 6 秒后（``popup_penguin_after6s``）弹窗仍在，整幅平均亮度与刚弹出时
    一模一样，底部明写「点击关闭」+ ▼。⇒ 路线必须自己点掉它。

    这条用例守的是「不许把 dismiss-claim 删掉换成等待」：
    ``popup_penguin_after6s`` 是一张**真实等待了 6 秒**才拍的帧。
    """
    machine = build_machine()

    assert machine.observe_page(frame("popup_penguin_after6s")) is (
        SanctuaryState.CLAIM_POPUP
    )
    assert machine.next_action(frame("popup_penguin_after6s")).name == "dismiss-claim"


# ---- ⑤ 真 Runner：整条链走一遍 -------------------------------------------------


class FakeRuntime:
    """按顺序吐真夹具帧的假 Runtime。

    ⚠️ 时钟**必须走**：主循环对「同名动作连点」有一条「等 8 秒再看」的窗口
    （``_SHORT_RETRY_SECONDS``）。每抓一帧走 10 秒，刚好越过 8 秒的重试窗口，
    又远小于任何一条状态超时（HOME 45 / FOREST 60）。
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
        # 取完就停在最后一帧：让主循环自己收尾，不要越界。
        index = min(self._index, len(self._frames) - 1)
        self._index += 1
        self.now_value += self._step
        return self._frames[index]

    def click(self, point, name) -> None:
        self.clicks.append((point, name))

    def log(self, message: str) -> None:
        self.messages.append(message)

    def save_diagnostic(self, label, screen):
        return Path(label)


def _script(*fixtures: str, repeat: int = 2) -> list[np.ndarray]:
    """每一帧重复 repeat 次：主循环要**两帧稳定**才肯发动作。"""
    frames: list[np.ndarray] = []
    for name in fixtures:
        frames.extend([frame(name)] * repeat)
    return frames


# 完整链路：圣域主页 → 精灵之森（两行可领）→ 领第一行 → 弹窗 → 关掉
#   → 精灵之森（只剩第 2 行）→ 领第 2 行 → 弹窗 → 关掉 → 精灵之森（全在倒计时）→ 收工
FULL_CHAIN = (
    "home",
    "forest_two_claimable_00",
    "popup_penguin",
    "forest_after_penguin",
    "popup_spring",
    "forest_all_done",
)


def test_runner_walks_the_whole_route_and_closes_one_pass():
    """真主循环跑完整条链 —— 这是唯一能守住「判据真的接进主循环」的用例。

    ⚠️ 只调 ``next_action`` 测不出「判据没接上主循环」这一类事故
    （骑士团捐赠 2026-09-25 连出两次，都在状态机与主循环**之间**）。
    """
    machine = build_machine()
    runtime = FakeRuntime(_script(*FULL_CHAIN))
    runner = SanctuaryRunner(
        machine, runtime, sleep=lambda _: None, poll_seconds=0.0
    )

    completed = runner.run(max_cycles=1)

    assert completed == 1
    assert [name for _, name in runtime.clicks] == [
        "open-forest",
        "claim-row",
        "dismiss-claim",
        "claim-row",
        "dismiss-claim",
    ]
    # 两行各自点在自己的 y 上（第 1 行 445、第 2 行 619），不是写死的同一个点。
    claim_points = [point for point, name in runtime.clicks if name == "claim-row"]
    assert [sanctuary.claim_row_label(point[1]) for point in claim_points] == [
        "第1行·企鹅巢穴",
        "第2行·精灵之泉",
    ]
    assert claim_points[0][1] != claim_points[1][1], "两行必须点在各自的 y 上"
    assert machine.state is SanctuaryState.FINISHED
    # 每个动作都得通过机器校验才发得出来（缺契约当场 RuntimeError，跑不到这里）。
    assert SanctuaryRunner._REQUIRE_TRANSITION_CONTRACT is True


def test_runner_refuses_an_action_without_an_exit_declaration():
    """开关打开后，缺「从哪来 / 到哪去」的动作一步都点不出去。"""
    runner = SanctuaryRunner(
        build_machine(),
        FakeRuntime(_script("home")),
        sleep=lambda _: None,
        poll_seconds=0.0,
    )

    broken = SanctuaryAction(name="open-forest", point=(1, 1))
    with pytest.raises(RuntimeError, match="缺少转场契约"):
        runner._require_transition_contract(broken)


def test_runner_fails_loudly_when_the_claim_click_never_lands():
    """点了 4 次都没生效 ⇒ **留诊断 + 报错**，绝不当成「今天收完了」。

    ⚠️ 这里刻意**不做**「跳过这一行、去点别的行」（骑士团捐赠有那张跳过表，
    因为那边存在「今日支援上限已满」这种**合理**的点不动）。圣域没有这种情形：
    「领取奖励」在画面上清清楚楚，推不动就是真出了问题 ——
    替用户决定「这一行不要了」等于悄悄少领一个材料。

    ⚠️ 这条同时钉住 ``_on_action_exhausted`` **没有**被覆写成返回 True：
    ``True`` 的语义是「已优雅收尾」，主循环会正常返回 ⇒ 退出码 **0**、
    通知写「已完成」—— 用户看到「任务完成」而实际一个材料都没领到。
    """
    machine = build_machine()
    # 一直停在「两行可领」上：点下去毫无反应。
    runtime = FakeRuntime(_script(*["forest_two_claimable_00"] * 20))
    runner = SanctuaryRunner(
        machine, runtime, sleep=lambda _: None, poll_seconds=0.0
    )

    with pytest.raises(RuntimeError, match="claim-row"):
        runner.run(max_cycles=1)

    assert machine.completed_cycles == 0, "没点动就不算完成一遍"


def test_claiming_uses_the_short_retry_not_the_45s_transition_window():
    """回归守卫：点「领取奖励」/ 关弹窗若没生效，必须 8 秒就重点。

    默认 45 秒窗口是给「换页」定的，而这两个动作点完**立刻**能看出生效没有。
    谁把它们移出 ``_SHORT_RETRY_ACTIONS``，这条会变红把它拦住。
    """
    runner = SanctuaryRunner(
        build_machine(),
        FakeRuntime([]),
        sleep=lambda _: None,
        poll_seconds=0.0,
    )

    assert runner._action_retry_seconds("claim-row") == 8.0
    assert runner._action_retry_seconds("dismiss-claim") == 8.0
    # 顺带确认：真正的换页动作仍是 45 秒（不被短重试带偏）。
    assert runner._action_retry_seconds("open-forest") == 45


# ---- ⑥ 开局接力 ---------------------------------------------------------------


def test_resume_takes_over_on_the_sanctuary_home_and_asks_the_navigator_to_skip():
    """停在圣域主页 ⇒ 就地接管，并告诉导航「我已经在链子上了」。

    ``entry`` 非空是这条路线接力**省下最多**的一处：没有它就得先回大厅、
    再点一次「圣域」，白走一趟（还要冒被别的弹窗截住的风险）。
    """
    machine = build_machine()

    point = detect_resume_point(machine, frame("home"))

    assert point is not None
    assert point.page == "圣域主页"
    assert point.entry == SANCTUARY_HOME_PAGE
    assert point.state is None, "本路线每帧重判页面，不需要拨状态"


def test_resume_takes_over_in_the_forest_without_bothering_the_navigator():
    """停在精灵之森 ⇒ 也接管，但``entry`` 留空（那一页不在导航链上）。"""
    machine = build_machine()

    point = detect_resume_point(machine, frame("forest_two_claimable_00"))

    assert point is not None
    assert point.page == "精灵之森"
    assert point.entry is None


def test_resume_ignores_the_lobby():
    """停在大厅认不出（``forest_row`` 在大厅上只有 0.2411）⇒ 照旧「回大厅 → 进圣域」。"""
    machine = build_machine()

    assert detect_resume_point(machine, frame("lobby_entry")) is None
    assert detect_resume_point(machine, frame("lobby_entry_b")) is None


def test_resume_refuses_to_take_over_the_claim_popup():
    """停在「领取完成弹窗」上不接力 —— 不是危险，是**没必要**。

    那个弹窗唯一的动作就是「点一下关闭」，而探针返回 None 之后走的老流程
    （一路受控返回 → 回大厅 → 重新导航）中，返回路上的 ESC 本来就会先把它关掉，
    效果一样。为它单开一个落点只会让 ``_RESUMABLE_STATES`` 多一个要维护的分支。
    """
    machine = build_machine()

    assert detect_resume_point(machine, frame("popup_penguin")) is None


def test_every_resumable_page_is_declared_on_the_navigation_chain():
    """接力给的 ``entry`` 只能是导航链上的页面，否则 ``navigate`` 会直接报错。"""
    from auto_game_unified.games.epic7.navigation import _RESUME_ENTRY_PAGES

    assert SANCTUARY_HOME_PAGE in _RESUME_ENTRY_PAGES["sanctuary"]
    # 「精灵之森」不在导航链上 —— 它就该不在，导航根本不认识那一页。
    assert len(_RESUME_ENTRY_PAGES["sanctuary"]) == 1


# ---- ⑦ 导航把画面送到圣域主页 --------------------------------------------------


def test_the_navigator_recognises_the_sanctuary_home():
    """导航层必须认得圣域主页 —— 否则「大厅 → 进圣域」那条转场永远验收不通过。

    ``Epic7Navigator._transition`` 靠「``observe()`` 报出目标页名」才算成功
    （``observation.name in targets``）。少了这条判据，转场会一路等到 92 秒超时、
    重试 4 次然后报错，症状是「这条路线永远进不去」。
    """
    import types

    from auto_game_unified.games.epic7.navigation import (
        Epic7Navigator,
        build_navigation_templates,
    )
    from auto_game_unified.games.epic7.template_paths import resolve_template_dir

    root = resolve_template_dir(TEMPLATE_ROOT)
    navigator = Epic7Navigator(
        build_navigation_templates(root),
        types.SimpleNamespace(now=lambda: 0.0),
        template_root=root,
    )

    assert navigator.observe(frame("home")).name == "sanctuary_home"
    # 大厅帧仍是大厅（新判据不许把大厅抢走）。
    assert navigator.observe(frame("lobby_entry")).name == "lobby"


def test_the_lobby_entry_anchor_is_the_text_label_not_the_icon():
    """大厅入口锚点定位在左侧菜单那一行，且**不与骑士团图标区域重叠**。

    ⚠️ 这里守的是「别再把它挪回图标上」：图标没有文字，截出来是一片渐变色块，
    换个分辨率/换个角标就认不出；文字是只此一处的稳定特征。
    """
    from auto_game_unified.games.epic7.navigation import Epic7Navigator

    x, y, width, height = Epic7Navigator._REGIONS["lobby_sanctuary"]

    assert (x, y, width, height) == (20, 270, 140, 130)
    # 骑士团入口在 (1150, 960) 一带 —— 两者离得很远，不会互相干扰。
    knights = Epic7Navigator._REGIONS["lobby_knights"]
    assert knights[0] > x + width + 500


def test_sanctuary_is_registered_everywhere():
    """新路线登记四处（本项目最容易漏的一步）。"""
    from auto_game_unified.desktop.catalog import ROUTES
    from auto_game_unified.games.epic7.daily_tasks import DAILY_TASKS
    from auto_game_unified.games.epic7.modes import MODE_SPECS
    from auto_game_unified.tools.check import ROUTE_KEYWORDS

    spec = MODE_SPECS["sanctuary"]

    assert spec.label == "圣域收菜"
    # 每天收一遍就够 ⇒ 次数不给用户选。
    assert spec.cycles_editable is False
    assert spec.default_cycles == 1
    assert "sanctuary" in {task.mode for task in DAILY_TASKS}
    assert "sanctuary" in {route.mode for route in ROUTES}
    assert ROUTE_KEYWORDS["sanctuary"] == "sanctuary"
    assert sanctuary.SANCTUARY_HOME_PAGE == "sanctuary_home"
