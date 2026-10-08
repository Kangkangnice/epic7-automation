"""月塔（欧多马顿塔塔）状态机与战斗适配器的离线护栏。

覆盖范围对齐 ``test_epic7_expedition.py``：判据分离度、状态矩阵、每层的
动作链、计数口径、以及「模板缺席不许静默降级」的白名单钉子。

⚠️ 全部夹具读图必须走 ``cv2.imread`` + ``COLOR_BGR2RGB``（``load_template``
也是 RGB 口径）。用 BGR 直接喂进去，匹配分数会莫名掉到阈值以下 —— 这不是
判据的问题，是色彩口径的问题（见 ``topics/lessons``）。
"""

import dataclasses
import unittest
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import AutoBattleState
from auto_game_unified.core.matcher import find_best_template, load_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.tower import build_tower_evidence
from auto_game_unified.games.epic7.navigation import REFERENCE_SIZE
from auto_game_unified.games.epic7.tower import (
    FloorsConquered,
    TowerRunner,
    TowerState,
    TowerStateMachine,
    build_tower_templates,
)


SIZE = (1132, 1982, 3)
ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "games" / "epic7" / "templates" / "tower"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_tower"

# 每张夹具**只该**属于哪个状态。改判据前先看这张表 —— 它是「页面唯一性」的
# 真值来源，任何一行多打一个 YES 都是误报。
FIXTURE_STATES: dict[str, TowerState] = {
    "home": TowerState.HOME,
    "home_2": TowerState.HOME,
    "home_alt": TowerState.HOME,
    "floor_list": TowerState.FLOOR_LIST,
    "floor_list_2": TowerState.FLOOR_LIST,
    "floor_list_alt": TowerState.FLOOR_LIST,
    "team": TowerState.TEAM,
    "team_next_floor": TowerState.TEAM,
    "card": TowerState.CARD,
    "card_unselected": TowerState.CARD,
    "card_selected": TowerState.CARD,
    "result": TowerState.RESULT,
}

# 判据 -> 该判据「本页」的夹具名。分离度断言用它区分正负样本。
JUDGE_OWNERS: dict[str, tuple[str, ...]] = {
    "season_tower_title": ("season", "season_2"),
    "home_enter": ("home", "home_2", "home_alt"),
    "floor_select_team": ("floor_list", "floor_list_2", "floor_list_alt"),
    "team_battle_start": ("team", "team_next_floor"),
    "prepare_title": ("team", "team_next_floor"),
    "card_decide": ("card", "card_unselected", "card_selected"),
    "card_hint": ("card", "card_unselected", "card_selected"),
    "result_clear": ("result",),
}


def pattern(seed: int) -> np.ndarray:
    """随机噪点模板 —— **只能**用于 `screen_with()` 合成的画面。

    ⚠️ 千万别拿它去匹配真机夹具：噪点模板在 1982×1132 的真图上会随缘落在
    region 内的任意位置，命中与否完全看运气（本文件初版就是这么写的，
    36 条用例集体变红）。真机夹具一律走 `real_machine()` / `build_tower_templates()`。
    """
    return np.random.default_rng(seed).integers(0, 256, (24, 48, 3), dtype=np.uint8)


# 合成画面用的假模板（任意形状，只要能「贴上去再认出来」）。
FAKE = {
    "season_tower_title": pattern(1),
    "home_enter": pattern(2),
    "floor_select_team": pattern(3),
    "team_battle_start": pattern(4),
    "prepare_title": pattern(5),
    "card_decide": pattern(6),
    "card_hint": pattern(7),
    "result_clear": pattern(8),
    "auto_off": pattern(9),
}


def screen_with(*items: tuple[np.ndarray, tuple[int, int]]) -> np.ndarray:
    screen = np.zeros(SIZE, dtype=np.uint8)
    for template, (x, y) in items:
        height, width = template.shape[:2]
        screen[y : y + height, x : x + width] = template
    return screen


def recorded_screen(name: str) -> np.ndarray:
    path = FIXTURES / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def real_machine(state: TowerState = TowerState.HOME) -> TowerStateMachine:
    """**所有跟真机夹具打交道**的用例都必须用这个 —— 真模板 + 真区域。"""
    return TowerStateMachine(build_tower_templates(TEMPLATES_DIR), initial_state=state)


class TowerStateMachineTests(unittest.TestCase):
    def machine(self, state=TowerState.HOME):
        """真模板起的机器（夹具用例的默认选择）。"""
        return real_machine(state)

    # ---- 判据分离度 ----

    def test_every_judge_clears_its_threshold_with_a_wide_margin(self):
        """判据必须「本页最低分」与「他页最高分」之间留出余量。

        ⚠️ 断言用的正/负样本名单（``JUDGE_OWNERS``）是**独立写死**的，不遍历
        状态机里的任何常量 —— 否则实现一改断言跟着改，注入违规纹丝不动。
        """
        real = build_tower_templates(TEMPLATES_DIR)
        images = {
            path.stem: cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            for path in sorted(FIXTURES.glob("*.png"))
        }

        for judge, owners in sorted(JUDGE_OWNERS.items()):
            template = getattr(real, judge)
            region = TowerStateMachine._REGIONS[judge]
            own_scores = [
                find_best_template(
                    images[name], template, region=region, reference_size=(1982, 1132)
                ).score
                for name in owners
            ]
            other_scores = [
                find_best_template(
                    image, template, region=region, reference_size=(1982, 1132)
                ).score
                for name, image in images.items()
                if name not in owners
            ]
            with self.subTest(judge=judge):
                self.assertGreater(min(own_scores), 0.88)
                self.assertLess(max(other_scores), 0.88)
                # 余量门槛：实测最小 +0.41（floor_select_team / team_battle_start）。
                # 留 0.30 做下限，既拦住「刚好擦线」的漂移，又不至于卡住小改动。
                self.assertGreater(
                    min(own_scores) - max(other_scores),
                    0.30,
                    f"{judge} 分离度不足：本页最低 {min(own_scores):.4f} "
                    f"他页最高 {max(other_scores):.4f}",
                )

    # ---- 页面唯一性 ----

    def test_every_fixture_matches_exactly_one_page(self):
        """14 张夹具逐帧判页：**每张只许命中自己的那一个状态**。

        这是「零误报」的正面证据。``result`` 命中 BATTLE 是**设计如此**
        （``is_in_state(BATTLE)`` 接受「结算页可见」，好让战斗监督收手），
        所以 BATTLE 从这条唯一性检查里排除，它的交叉放行单独由下面
        ``test_result_page_is_also_a_valid_battle_handoff_frame`` 守。
        """
        machine = self.machine()
        pages = [
            TowerState.HOME,
            TowerState.FLOOR_LIST,
            TowerState.TEAM,
            TowerState.CARD,
            TowerState.RESULT,
        ]
        for name, expected in sorted(FIXTURE_STATES.items()):
            screen = recorded_screen(name)
            hits = [page.value for page in pages if machine.is_in_state(screen, page)]
            with self.subTest(fixture=name, expected=expected.value):
                self.assertIn(expected.value, hits)
                # 业务页之间必须严格互斥。
                self.assertEqual([expected.value], hits)
        # 反向：结算页**必须**同时被 BATTLE 接受，否则监督接不住最后那一下。
        for name in ("result",):
            with self.subTest(fixture=name, state="battle"):
                self.assertTrue(
                    machine.is_in_state(recorded_screen(name), TowerState.BATTLE)
                )
        # 其余业务页不许被 BATTLE 抢走。
        for name in ("home", "floor_list", "team", "card"):
            with self.subTest(fixture=name, state="battle-negative"):
                self.assertFalse(
                    machine.is_in_state(recorded_screen(name), TowerState.BATTLE)
                )

    def test_result_page_is_also_a_valid_battle_handoff_frame(self):
        """结算页必须同时被 BATTLE 接受 —— 否则监督接不住最后那一下。"""
        machine = self.machine()
        screen = recorded_screen("result")

        self.assertTrue(machine.is_in_state(screen, TowerState.BATTLE))
        self.assertTrue(machine.is_in_state(screen, TowerState.RESULT))

    def test_foreign_page_is_not_recognised_as_any_tower_state(self):
        """赛季页（还没进月塔）不许被认成月塔的任何一页 —— fail-closed。"""
        machine = self.machine()
        screen = recorded_screen("season")

        for state in (
            TowerState.HOME,
            TowerState.FLOOR_LIST,
            TowerState.TEAM,
            TowerState.BATTLE,
            TowerState.CARD,
            TowerState.RESULT,
        ):
            with self.subTest(state=state.value):
                self.assertFalse(machine.is_in_state(screen, state))

    def test_season_page_still_carries_the_tower_card_anchor(self):
        """`season_tower_title` 只在赛季页可见（那是它的**唯一**用途）。

        它不参与任何 `is_in_state`，是给导航/接力用来确认「月塔入口这张卡在」的。
        """
        machine = self.machine()

        self.assertIsNotNone(
            machine._locate(recorded_screen("season"), "season_tower_title")
        )
        self.assertIsNone(
            machine._locate(recorded_screen("home"), "season_tower_title")
        )

    # ---- 动作链 ----

    def test_home_enters_the_tower_without_advancing(self):
        machine = self.machine()

        action = machine.next_action(recorded_screen("home"))

        self.assertEqual("enter-tower", action.name)
        self.assertEqual(TowerState.HOME, machine.state)
        self.assertEqual((TowerState.FLOOR_LIST,), action.target_states)

    def test_floor_list_selects_the_team(self):
        machine = self.machine(TowerState.FLOOR_LIST)

        action = machine.next_action(recorded_screen("floor_list"))

        self.assertEqual("select-team", action.name)
        self.assertEqual(TowerState.FLOOR_LIST, machine.state)

    def test_team_starts_the_battle(self):
        machine = self.machine(TowerState.TEAM)

        action = machine.next_action(recorded_screen("team"))

        self.assertEqual("battle-start", action.name)
        self.assertEqual(TowerState.TEAM, machine.state)
        self.assertEqual((TowerState.BATTLE,), action.target_states)

    def test_select_team_source_page_cannot_survive_the_team_page(self):
        """⚠️ 事故护栏（2026-10-09）：源页判据在两页之间必须**互斥**，否则重试会误开战斗。

        实机经过：点「选择队伍」后主循环等 ``settle`` 才截第一帧，当时用的是默认
        ``poll_seconds``（1.0 秒）—— **短于实测转场时长（2~3 秒）** ⇒ 源页被判
        「仍在」⇒ 基类按「这一下没生效」**重试点击**。

        而 ``select-team`` 与 ``battle-start`` 的点击点只差 **28 px**
        （(1698,1044) vs (1726,1040)，**同一个绿色按钮槽位**）⇒ 重试那一下正好按在
        已经切过去的「战斗开始」上 ⇒ **直接开打**，状态机还以为在等准备战斗页
        ⇒ 那一层白等到 60 秒超时（日志 ``no_transition_select-team``）。

        修法是把 ``settle`` 提到不小于实测转场时长上界（见下一条用例）。**这条守的是
        修法成立的前提**：准备战斗页上 ``floor_select_team`` 必须**不过阈**，否则
        「源页仍在」永远为真 ⇒ 无论等多久都会重试 ⇒ 修法失效。

        ⚠️ 阈值与锚点名**独立写死**，不从被测模块取。
        """
        machine = self.machine(TowerState.FLOOR_LIST)
        action = machine.next_action(recorded_screen("floor_list"))

        self.assertEqual("select-team", action.name)
        # 真·楼层列表：源页成立（这时点第二次确实没问题，按钮还是「选择队伍」）。
        self.assertTrue(
            machine.action_source_visible(recorded_screen("floor_list"), action)
        )
        # 准备战斗页：源页**必须不成立** —— 那里同一槽位的按钮已经变成「战斗开始」。
        self.assertFalse(
            machine.action_source_visible(recorded_screen("team"), action)
        )
        self.assertFalse(
            machine.action_source_visible(recorded_screen("team_next_floor"), action)
        )

        # 前提本身也量出来：`floor_select_team` 在准备战斗页上必须远低于阈值。
        atom = build_tower_evidence(TEMPLATES_DIR).atom("floor_select_team")
        template = load_template(str(TEMPLATES_DIR / atom.template_path))
        for fixture in ("team", "team_next_floor"):
            with self.subTest(fixture=fixture):
                match = find_best_template(
                    recorded_screen(fixture),
                    template,
                    region=atom.region,
                    reference_size=REFERENCE_SIZE,
                )
                score = match.score if match is not None else 0.0
                self.assertLess(score, 0.88)

    def test_the_second_click_of_select_team_would_land_on_battle_start(self):
        """把「重试 = 误开战斗」量化钉住：两个点击点必须近到落在同一颗按钮上。

        这条断言不是重复上面那条 —— 它守的是**前提**：只要这两点还这么近，
        「重试」就永远等价于「按下战斗开始」，第二道防线就不可回退。
        （若将来某次改版把「战斗开始」挪远了，这条会红，提醒重新评估该防线。）
        """
        self.assertLessEqual(
            abs(
                TowerStateMachine._POINT_SELECT_TEAM[0]
                - TowerStateMachine._POINT_BATTLE_START[0]
            ),
            40,
        )
        self.assertLessEqual(
            abs(
                TowerStateMachine._POINT_SELECT_TEAM[1]
                - TowerStateMachine._POINT_BATTLE_START[1]
            ),
            40,
        )

    def test_settle_window_outlasts_the_recorded_tower_transitions(self):
        """第一道防线：点完先等的时长必须**不小于**实测转场时长上界（3.1 秒）。

        依据来自 2026-10-09 一次真机每日任务的日志（``runtime_logs/epic7_tower.log``）：
            00:18:43 点「战斗」→ 00:18:46 点击验收 耗时=2.0秒
            00:18:48 点「进入月塔」→ 00:18:51 点击验收 耗时=3.1秒
            00:18:53 点「入场」→ 00:18:56 转场确认（约 3 秒）
        阈值 **独立写死**（不从被测模块取），改回默认 ``None``（⇒1.0 秒）会红。
        """
        self.assertIsNotNone(TowerRunner._SETTLE_SECONDS)
        self.assertGreaterEqual(TowerRunner._SETTLE_SECONDS, 3.0)

    def test_other_states_still_report_their_source_page_normally(self):
        """第二道防线只该管 ``select-team``：别的动作的源页判据不许被顺带改掉。"""
        machine = self.machine(TowerState.HOME)
        enter = machine.next_action(recorded_screen("home"))
        self.assertTrue(machine.action_source_visible(recorded_screen("home"), enter))

        machine.state = TowerState.TEAM
        start = machine.next_action(recorded_screen("team"))
        self.assertTrue(machine.action_source_visible(recorded_screen("team"), start))

    def test_click_points_are_constants_and_never_drift_with_the_match(self):
        """判据与点击点分离：点击点必须是常量，不许跟着 match.center 走。

        对称裁的模板一旦重裁，``match.center`` 就会漂 —— 这几条断言把它钉住。
        """
        machine = self.machine(TowerState.HOME)
        pointed = {}

        for state, fixture in (
            (TowerState.HOME, "home"),
            (TowerState.FLOOR_LIST, "floor_list"),
            (TowerState.TEAM, "team"),
            (TowerState.RESULT, "result"),
        ):
            machine.state = state
            pointed[state] = machine.next_action(recorded_screen(fixture)).point

        self.assertEqual((1640, 1055), pointed[TowerState.HOME])
        self.assertEqual((1698, 1044), pointed[TowerState.FLOOR_LIST])
        self.assertEqual((1726, 1040), pointed[TowerState.TEAM])
        self.assertEqual((1787, 1041), pointed[TowerState.RESULT])

    # ---- 三选一：两态分开 ----

    def test_card_page_picks_the_middle_card_before_deciding(self):
        machine = self.machine(TowerState.CARD)

        pick = machine.next_action(recorded_screen("card_unselected"))

        self.assertEqual("pick-middle-card", pick.name)
        self.assertEqual((958, 500), pick.point)
        self.assertEqual((TowerState.CARD_CONFIRM,), pick.target_states)
        # ⚠️ 点击点不许落到左卡(403)/右卡(1514) 上 —— 用户拍板固定选中间那张。
        self.assertNotIn(pick.point[0], (403, 1514))

    def test_decide_click_only_happens_after_the_card_is_picked(self):
        """未选卡时「决定装置」是暗态（点击无效）⇒ 不许先点按钮。"""
        machine = self.machine(TowerState.CARD)

        action = machine.next_action(recorded_screen("card_unselected"))

        self.assertNotEqual("decide-device", action.name)
        self.assertEqual((1138, 1040), self.machine(TowerState.CARD_CONFIRM)
                         .next_action(recorded_screen("card_selected")).point)

    def test_first_floor_is_counted_only_after_next_floor_returns_to_team(self):
        """一层的定义 = 点战斗开始 → 结算页点下一层。计数落在 `next-floor`。"""
        machine = self.machine(TowerState.TEAM)

        def act(screen, target):
            action = machine.next_action(screen)
            machine.commit(action, target)
            return action.name

        self.assertEqual("battle-start", act(
            recorded_screen("team"), TowerState.BATTLE
        ))
        self.assertEqual(0, machine.completed_cycles)
        # ⚠️ BATTLE 是**交给战斗监督**的那一步：状态机在这期间不发动作（`None`）。
        # 监督跑完一局后把状态拨到 CARD（见 `TowerRunner._RESULT_STATE`）。
        self.assertIsNone(machine.next_action(recorded_screen("result")))
        machine.state = TowerState.CARD
        self.assertEqual("pick-middle-card", act(
            recorded_screen("card_unselected"), TowerState.CARD_CONFIRM
        ))
        self.assertEqual(0, machine.completed_cycles)
        self.assertEqual("decide-device", act(
            recorded_screen("card_selected"), TowerState.RESULT
        ))
        self.assertEqual(0, machine.completed_cycles)
        self.assertEqual("next-floor", act(
            recorded_screen("result"), TowerState.TEAM
        ))
        self.assertEqual(1, machine.completed_cycles)
        self.assertEqual(TowerState.TEAM, machine.state)

    def test_next_floor_goes_back_to_team_not_straight_into_battle(self):
        """⚠️ 实测 2026-10-08（逐秒连拍 20 帧）：点「下一层」约 7 秒后落到**准备战斗页**。

        早先一次勘察误判成「直接开打」，是看帧时机太早。这条断言钉住正确的那条边 ——
        写成 BATTLE 会让状态机白等 60 秒超时，然后整条路线报失败。
        """
        machine = self.machine(TowerState.RESULT)

        action = machine.next_action(recorded_screen("result"))

        self.assertEqual("next-floor", action.name)
        self.assertEqual((TowerState.TEAM,), action.target_states)

    def test_card_gate_resets_when_a_new_floor_starts(self):
        """新的一层开始点卡：「本层已选卡」的闸门必须复位，否则第二层永远不点卡。

        ⚠️ 复位必须挂在 `_after_result_state`（监督打完一层、状态被拨到三选一页
        之后）**而不能只放 `commit()`** —— 基类是直接 `machine.state =` 赋值的，
        不走 `commit()`。这条用例走的就是生产路径。
        """
        machine = self.machine(TowerState.BATTLE)
        machine.card_picked = True
        runner = TowerRunner(
            machine,
            Runtime(lambda: np.zeros(SIZE, dtype=np.uint8), lambda _point: None),
        )

        machine.state = TowerRunner._RESULT_STATE
        runner._after_result_state(cycle=1)

        self.assertIs(TowerState.CARD, machine.state)
        self.assertFalse(machine.card_picked)

    def test_landing_on_battle_does_not_touch_the_card_gate(self):
        """反向：走到 BATTLE 时闸门**不动** —— 复位只该发生在「落到三选一页」那一刻。"""
        machine = self.machine(TowerState.TEAM)
        machine.card_picked = True

        machine.commit(machine.next_action(recorded_screen("team")), TowerState.BATTLE)

        self.assertIs(TowerState.BATTLE, machine.state)
        self.assertTrue(machine.card_picked)

    def test_picked_card_is_not_clicked_twice_when_the_transition_was_not_accepted(self):
        """转场没验收过、状态还停在 CARD 时：不再重复点卡，直接进确认态。"""
        machine = self.machine(TowerState.CARD)

        first = machine.next_action(recorded_screen("card_unselected"))
        self.assertEqual("pick-middle-card", first.name)
        machine.card_picked = True  # 模拟：点过了但 commit 没发生

        second = machine.next_action(recorded_screen("card_selected"))

        self.assertEqual("decide-device", second.name)
        self.assertEqual(TowerState.CARD_CONFIRM, machine.state)

    # ---- 攻击/动作合同 ----

    def test_action_target_states_are_declared_for_every_business_edge(self):
        machine = self.machine(TowerState.HOME)

        for state, fixture in (
            (TowerState.HOME, "home"),
            (TowerState.FLOOR_LIST, "floor_list"),
            (TowerState.TEAM, "team"),
            (TowerState.CARD, "card_unselected"),
            (TowerState.RESULT, "result"),
        ):
            machine.state = state
            action = machine.next_action(recorded_screen(fixture))
            with self.subTest(state=state.value):
                self.assertIs(state, action.source_state)
                self.assertTrue(action.target_states)
                self.assertTrue(action.target_pages)

    def test_commit_rejects_a_target_outside_the_contract(self):
        machine = self.machine(TowerState.HOME)
        action = machine.next_action(recorded_screen("home"))

        with self.assertRaisesRegex(RuntimeError, "目标状态不在合同中"):
            machine.commit(action, TowerState.RESULT)

    def test_commit_rejects_an_action_from_another_state(self):
        machine = self.machine(TowerState.HOME)
        machine.state = TowerState.TEAM
        action = self.machine(TowerState.HOME).next_action(recorded_screen("home"))

        with self.assertRaisesRegex(RuntimeError, "来源状态"):
            machine.commit(action, TowerState.FLOOR_LIST)

    def test_preview_does_not_mutate_state_or_count(self):
        machine = self.machine()

        action, outcome = machine.preview(recorded_screen("home"))

        self.assertEqual("enter-tower", action.name)
        self.assertEqual((TowerState.HOME, 0), outcome)
        self.assertEqual(TowerState.HOME, machine.state)
        self.assertEqual(0, machine.completed_cycles)

    def test_preview_does_not_consume_the_card_gate(self):
        machine = self.machine(TowerState.CARD)
        screen = recorded_screen("card_unselected")

        preview, _ = machine.preview(screen)
        action = machine.next_action(screen)

        self.assertEqual("pick-middle-card", preview.name)
        self.assertEqual("pick-middle-card", action.name)

    # ---- 战斗适配器 ----

    def test_battle_adapter_reports_the_three_card_page_as_the_result(self):
        """⚠️ 月塔的「打完」不是 CLEAR 结算页，而是**三选一装置页**。

        监督的收手判据就挂在 `result_visible` 上，落点对到 CARD
        （见 `TowerRunner._RESULT_STATE`）。写成 RESULT 会让状态停在 CARD
        没人驱动 —— 卡不点、装置不决定、这一层永远收不了尾。
        """
        machine = self.machine(TowerState.BATTLE)

        card = machine.observe_battle(recorded_screen("card_unselected"), None)
        clear = machine.observe_battle(recorded_screen("result"), None)

        self.assertTrue(card.result_visible)
        # 准备战斗页那半截锚点恒为 False —— 本函数只在移交监督之后被调用。
        self.assertFalse(card.pre_battle_visible)
        # CLEAR 结算页**不是**收手点：那时卡已经选完，状态该由 RESULT 自己推进。
        self.assertFalse(clear.result_visible)

    def test_battle_adapter_reports_the_readiness_of_battle_scene_frames(self):
        """局内帧：`battle_visible` 认得出战斗场面，三选一页则不算战斗场。"""
        machine = self.machine(TowerState.BATTLE)

        card = machine.observe_battle(recorded_screen("card_unselected"), None)
        team = machine.observe_battle(recorded_screen("team"), None)

        # 三选一页被明确排除在「战斗场面」之外（否则监督会以为还在打）。
        self.assertFalse(card.battle_visible)
        self.assertFalse(team.battle_visible)

    def test_battle_adapter_never_claims_result_on_a_business_page(self):
        machine = self.machine(TowerState.BATTLE)

        for name in ("home", "floor_list", "team"):
            with self.subTest(fixture=name):
                observation = machine.observe_battle(recorded_screen(name), None)
                self.assertFalse(observation.result_visible)

    def test_battle_adapter_treats_dynamic_valid_frames_as_progress_without_hud(self):
        machine = self.machine(TowerState.BATTLE)
        before = np.random.default_rng(1).integers(0, 256, SIZE, dtype=np.uint8)
        after = np.random.default_rng(2).integers(0, 256, SIZE, dtype=np.uint8)

        observation = machine.observe_battle(after, before)

        self.assertFalse(observation.battle_visible)

        self.assertTrue(observation.business_progress)
        self.assertEqual(AutoBattleState.UNKNOWN, observation.auto_state)

    def test_auto_off_is_clicked_exactly_once(self):
        """自动战斗关着 → 点一次开自动；再问就不许重复点。

        ⚠️ `auto_off` 是**共享模板**（story 那边搬过来的），所以这里用真图贴进
        合成画面 —— 它的 region 落在右上角，贴的位置必须配上。
        """
        machine = self.machine(TowerState.BATTLE)
        auto_off = machine.templates.auto_off
        region = TowerStateMachine._REGIONS["auto_off"]
        # 贴到 region 左上角，保证一定在搜索范围内。
        screen = screen_with((auto_off, (region[0], region[1])))

        action = machine.next_action(screen)

        self.assertEqual("enable-auto-battle", action.name)
        self.assertTrue(machine.auto_click_attempted)
        self.assertIsNone(machine.next_action(screen))

    def test_auto_click_flag_resets_when_a_new_battle_starts(self):
        machine = self.machine(TowerState.TEAM)
        machine.auto_click_attempted = True

        machine.commit(machine.next_action(recorded_screen("team")), TowerState.BATTLE)

        self.assertFalse(machine.auto_click_attempted)


class OptionalTemplateGuardTests(unittest.TestCase):
    """把「静默降级」钉死在代码门槛上。

    月塔**没有任何可选模板** —— 8 张判据图一张都不许缺席。谁想往白名单里
    塞东西，必须先想清楚「为什么这一页允许少一张图」。
    """

    def test_whitelist_is_empty(self):
        self.assertEqual(frozenset(), TowerStateMachine._OPTIONAL_TEMPLATES)

    def test_locator_refuses_every_missing_template(self):
        """反向喂违规：逐个把模板置 None ⇒ `_locate` 必须报错点名，不许静默塞 None。"""
        real = build_tower_templates(TEMPLATES_DIR)
        names = (
            "season_tower_title",
            "home_enter",
            "floor_select_team",
            "team_battle_start",
            "prepare_title",
            "card_decide",
            "card_hint",
            "result_clear",
        )
        for name in names:
            with self.subTest(anchor=name):
                broken = dataclasses.replace(real, **{name: None})
                machine = TowerStateMachine(broken)
                with self.assertRaisesRegex(RuntimeError, name):
                    machine._locate(np.zeros(SIZE, dtype=np.uint8), name)

    def test_whitelist_matches_the_evidence_profile(self):
        """`_OPTIONAL_TEMPLATES` 必须与证据画像的 `required` 逐字一致。"""
        profile = build_tower_evidence(TEMPLATES_DIR)
        from_evidence = {name for name, atom in profile.atoms.items() if not atom.required}

        self.assertEqual(from_evidence, set(TowerStateMachine._OPTIONAL_TEMPLATES))

    def test_every_declared_template_file_exists(self):
        """反向：8 张图必须都在盘上 —— 缺一张加载期就该炸，不该等到实跑。"""
        templates = build_tower_templates(TEMPLATES_DIR)

        for name in (
            "season_tower_title",
            "home_enter",
            "floor_select_team",
            "team_battle_start",
            "prepare_title",
            "card_decide",
            "card_hint",
            "result_clear",
        ):
            with self.subTest(template=name):
                self.assertIsNotNone(getattr(templates, name))


class FloorStopTests(unittest.TestCase):
    """打满 25 层 = 正常业务停止（资源耗尽通道，退出码 2）。"""

    def test_floors_conquered_is_a_resource_exhaustion_with_its_own_label(self):
        from auto_game_unified.core.runtime import StaminaExhausted

        self.assertTrue(issubclass(FloorsConquered, StaminaExhausted))
        self.assertEqual("月塔层数已打满", FloorsConquered.stop_label)
        # 与远征的先例对齐：每条路线一条自己的 stop_label，日志才读得出来。
        self.assertNotEqual(
            StaminaExhausted.stop_label, FloorsConquered.stop_label
        )


if __name__ == "__main__":
    unittest.main()
