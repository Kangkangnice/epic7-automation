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

from auto_game_unified.core.battle_supervisor import AutoBattleState, valid_game_frame
from auto_game_unified.core.evidence_diagnostics import inspect_profile
from auto_game_unified.core.matcher import find_best_template, load_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.tower import build_tower_evidence
from auto_game_unified.games.epic7.navigation import REFERENCE_SIZE
from auto_game_unified.games.epic7.template_paths import resolve_template_dir
from auto_game_unified.games.epic7.tower import (
    FloorTooHard,
    FloorsConquered,
    StaminaShortage,
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
    # 2026-10-31 第 20 层事故帧：「战斗指南」战力差警告**盖在准备战斗页上**。
    # ⚠️ 它在状态上**仍然是 TEAM**（弹窗半透明，底下的两个锚点照样命中）——
    # 这正是当初连点四次「战斗开始」的原因；区别只在 `next_action` 里
    # 先认弹窗、改成点「确认」。
    "battle_guide": TowerState.TEAM,
    # ⚠️ `hero_restore`（「英雄恢复」页）**不在**这张表里 —— 它和 `battle_guide`
    # 不一样：那一页把底下的准备战斗页压得更暗，`prepare_title` /
    # `team_battle_start` 只剩 **0.78**（不过阈）⇒ `is_in_state(TEAM)` 不成立。
    # 它靠 `hero_restore_title` 单独认，`next_action` 里按 state=TEAM 分派到子页面分支。
    "card": TowerState.CARD,
    "card_unselected": TowerState.CARD,
    "card_selected": TowerState.CARD,
    "result": TowerState.RESULT,
    # 打满 25 层那一次的结算页（右下角按钮是「征服」而不是「下一层」）。
    # ⚠️ 它**仍然是结算页**（`RESULT`），不是终点屏 —— 终点是下面那张征服弹窗。
    "result_conquered_floor": TowerState.RESULT,
    # 打满后的「征服欧多马顿塔」叙述屏 = **整条路线的终点**。
    "conquered": TowerState.CONQUERED,
}

# 判据 -> 该判据「本页」的夹具名。分离度断言用它区分正负样本。
JUDGE_OWNERS: dict[str, tuple[str, ...]] = {
    "season_tower_title": ("season", "season_2"),
    "home_enter": ("home", "home_2", "home_alt"),
    "floor_select_team": ("floor_list", "floor_list_2", "floor_list_alt"),
    "team_battle_start": ("team", "team_next_floor", "battle_guide"),
    # ⚠️ `battle_guide` **也是这两枚的正样本**：那一帧是「战斗指南」战力差警告
    # **盖在准备战斗页上**，弹窗半透明 ⇒ 底下两个锚点照样 0.95+ 命中。
    # 这不是判据退化，正是当初连点四次「战斗开始」的成因（见 next_action 的子页面分支）。
    # ⚠️ 但 `hero_restore` **不是**：那一页压得更暗，这两枚只有 0.78 ⇒ 它是负样本。
    "prepare_title": ("team", "team_next_floor", "battle_guide"),
    "card_decide": ("card", "card_unselected", "card_selected"),
    "card_hint": ("card", "card_unselected", "card_selected"),
    # ⚠️ 两张结算页都算 `result_clear` 的**正样本**：25 层那张只是右下角换了字、
    # 少了体力条，CLEAR 本身与普通层一模一样（实测 0.9327 / 1.0000 都过阈）。
    # 把它当负样本会让「分离度」断言拿「本页自己的另一张」去比自己 —— 那是假红。
    "result_clear": ("result", "result_conquered_floor"),
    # 终点屏的判据。⚠️ 它在 `conquered.png` 上 1.0000、其余最高 0.2810。
    "conquer_title": ("conquered",),
    # 「战斗指南」战力差警告标题（复用 story 的模板）。2026-10-31 实测：
    # 本帧 0.9956，其余帧最高 0.38（底下的准备战斗页并不包含这行标题）。
    "battle_guide_title": ("battle_guide",),
    # 「英雄恢复」页标题（本路线自裁）。2026-10-31 实测：本帧 1.0000，
    # 其余帧最高 0.5668（`conquered.png`）。
    "hero_restore_title": ("hero_restore",),
    # 「FAILED」大字（白掩膜口径）。夹具 = 2026-10-31 第 22 层实跑的诊断帧
    # （当时被报成 `battle_unrecognized` 假故障，2026-11-01 接线成正常业务退出）。
    # 实测：本帧 1.0000；其余夹具帧最高 0.5556（`floor_select_team` 帧上）。
    "battle_failed": ("battle_failed",),
}

# 「同一页的变体」：这些帧**不是另一页**，只是在某一页上又盖了一层/压暗了一层，
# 所以拿它们当负样本算「分离度」会得到必然很小的间隔 —— 那是同页内的变化，不是判据退化。
#
# 目前只有一条：`hero_restore`（「英雄恢复」页）把底下的准备战斗页压暗，
# `prepare_title` / `team_battle_start` 掉到 **0.7778**（不过阈）。
# ⚠️ 别把它加进 `JUDGE_OWNERS` —— 0.7778 < 0.88，会让「本页必须过阈」那条直接失败。
_SAME_PAGE_VARIANTS: dict[str, frozenset[str]] = {
    "team_battle_start": frozenset({"hero_restore"}),
    "prepare_title": frozenset({"hero_restore"}),
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


PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_tower_pc"


def recorded_screen(name: str) -> np.ndarray:
    path = FIXTURES / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def recorded_pc_screen(name: str) -> np.ndarray:
    path = PC_FIXTURES / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def real_machine(state: TowerState = TowerState.HOME) -> TowerStateMachine:
    """**所有跟真机夹具打交道**的用例都必须用这个 —— 真模板 + 真区域。"""
    return TowerStateMachine(build_tower_templates(TEMPLATES_DIR), initial_state=state)


def pc_machine_at(state: TowerState = TowerState.HOME) -> TowerStateMachine:
    """PC 后端专用：真模板 + PC 覆盖图，PC 专属的新增分支从这里才生效。"""
    return TowerStateMachine(
        build_tower_templates(resolve_template_dir(TEMPLATES_DIR, "pc")),
        initial_state=state,
    )


class TowerStateMachineTests(unittest.TestCase):
    def machine(self, state=TowerState.HOME):
        """真模板起的机器（夹具用例的默认选择）。"""
        return real_machine(state)

    # ---- 判据分离度 ----

    def test_the_reset_confirm_popup_is_answered_with_confirm(self):
        """点入场后若弹出「确认重置阶段」，必须点「确认」，不能当没看见。

        2026-10-30 现场：所选阶段**已经征服** ⇒ 点「入场」弹出
        「确定要从选择的阶段开始吗？……重置阶段后，将从1层开始进行。」
        之前没有这条判据，导航以为还停在月塔主页（弹窗压暗了页面，但
        ``home_enter`` 在这张帧上仍有 **0.9995**），于是连点 4 次入场 ⇒
        「动作[enter-tower]未稳定进入[楼层列表]」。

        用户 2026-10-30 拍板：「就是要从头开始打的，这个没问题」⇒ 点「确认」。

        ⚠️ 这条同时钉住**判定顺序**：弹窗帧上 ``home_enter`` 也是成立的，
        所以 ``reset_confirm_title`` 必须排在 ``_required(home_enter)`` **之前**。
        把顺序调回去 ⇒ 这条立刻红（会返回 ``enter-tower`` 而不是 ``confirm-reset``）。
        """
        machine = self.machine()
        screen = screen_with((machine.templates.reset_confirm_title, (775, 523)))

        action = machine.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual(
            "confirm-reset",
            action.name,
            "弹窗帧上走了别的分支 —— 判定顺序反了？",
        )
        self.assertEqual(
            TowerStateMachine._POINT_RESET_CONFIRM,
            action.point,
            "确认按钮的点击点不对",
        )
        self.assertEqual(
            (TowerState.FLOOR_LIST,),
            action.target_states,
            "确认之后应当等「楼层列表」",
        )

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
                if name not in owners and name not in _SAME_PAGE_VARIANTS.get(judge, ())
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
        """17 张夹具逐帧判页：**每张只许命中自己的那一个状态**。

        这是「零误报」的正面证据。``result`` 命中 BATTLE 是**设计如此**
        （``is_in_state(BATTLE)`` 接受「结算页可见」，好让战斗监督收手），
        所以 BATTLE 从这条唯一性检查里排除，它的交叉放行单独由下面
        ``test_result_page_is_also_a_valid_battle_handoff_frame`` 守。

        ⚠️ ``pages`` 名单是**独立写死**的，不遍历 ``TowerState`` —— 否则将来
        加一个状态、断言跟着自动放行，等于没守（2026-10-08 反向验证抓过这类空护栏）。
        新增 ``CONQUERED`` 时这里也同步补上，是有意为之的那一次「手改」。
        """
        machine = self.machine()
        pages = [
            TowerState.HOME,
            TowerState.FLOOR_LIST,
            TowerState.TEAM,
            TowerState.CARD,
            TowerState.RESULT,
            TowerState.CONQUERED,
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
        # ⚠️ 目标里**也含 TEAM**：战力差警告冒出来时，这一次要按「退回准备战斗」
        # 收掉、把控制权交回主循环（见 `action_target_state` 的弹窗分支）。
        self.assertIn(TowerState.BATTLE, action.target_states)
        self.assertIn(TowerState.TEAM, action.target_states)
        # ⚠️ CARD 落点是 **PC 专属**（2026-11-04 01:40 真机补的那条边）：
        # 秒杀型战斗只存在 1~2 秒，转场要「目标连续=2」根本抓不到，
        # 落点是稳定停住的三选一装置页 —— 见下面那条专门用例。
        # 模拟器保持改动前的两态，不许被这次 PC 移植带着变。
        self.assertNotIn(TowerState.CARD, action.target_states)
        pc_action = pc_machine_at(TowerState.TEAM).next_action(
            recorded_pc_screen("prepare_pc_live_20261103")
        )
        self.assertIn(TowerState.CARD, pc_action.target_states)

    def test_the_battle_scene_is_not_where_a_strong_team_ever_lands(self):
        """反向：**别指望靠「战斗中」这一页来接住秒杀**。

        真机逐帧探针（2026-11-04 02:1x，60 秒 × 1.5 秒采样，PC 客户端）显示这一队
        点完「战斗开始」后：

        - 1.5 秒那一帧 ``observe_battle_controls`` = ``AUTO_CONTROLS``（战斗确实发生了）；
        - 3 秒起整整 57 秒全是 ``TRANSITION``，画面停在三选一装置页；
        - ``battle_scene_visible`` **整段都是 False**。

        ⇒ 「秒杀 + 三选一页」是这条路线在 PC 上的**常态**，不是偶发。
        落点合同拿 PC 现场帧 ``prepare_pc_live_20261103`` 核对：PC 覆盖图认不出
        模拟器夹具，模拟器那条路径由 ``test_team_starts_the_battle`` 钉住。
        逐帧采样的结论仍旧成立 —— 别急着改 ``battle_scene_visible`` 去「修」
        一个不是它的问题。

        真正的落点证据在 ``tests/fixtures/epic7_tower_pc/card_after_instant_battle_pc.png``
        （PC 帧必须留在那个目录里，原因见 ``test_tower_evidence.py`` 的 ``PC_FIXTURES`` 注释）。
        """
        machine = pc_machine_at(TowerState.TEAM)
        action = machine.next_action(
            recorded_pc_screen("prepare_pc_live_20261103")
        )

        # 合同里必须有 CARD —— 否则秒杀落点无人接收，只能等 57 秒超时。
        self.assertIn(TowerState.CARD, action.target_states)

    def test_the_power_warning_interrupts_the_transition_instead_of_retrying(self):
        """弹窗一冒出来，这次转场就该判「页面变了」，让主循环**重新决策**。

        ⚠️ 2026-10-31 09:45 第二次事故：`transactional_runner_base` 的重试路径是
        **原地重发同一个点击**、不重新问状态机 ⇒ 只把弹窗分支写在 `next_action` 里
        根本轮不到执行，连点 4 次 `battle-start` 后判
        `动作[battle-start]未稳定进入[战斗中]`。
        """
        machine = real_machine(TowerState.TEAM)
        action = machine.next_action(recorded_screen("team"))
        guide = recorded_screen("battle_guide")

        with self.subTest("弹窗在场：来源不在 + 收到 TEAM"):
            self.assertFalse(machine.action_source_visible(guide, action))
            self.assertEqual(TowerState.TEAM, machine.action_target_state(guide, action))

        with self.subTest("正常转场途中：不许判成 TEAM"):
            self.assertIsNone(
                machine.action_target_state(recorded_screen("team"), action),
                "转场途中认 TEAM 会让主循环立刻重发一次 battle-start",
            )

    def test_the_power_warning_confirms_instead_of_re_clicking_battle_start(self):
        """2026-10-31 第 20 层事故：敌方战力 107 万 vs 我方 80 万 ⇒ 弹「战斗指南」警告。

        弹窗是**半透明**的，底下 `team_battle_start` / `prepare_title` 照样命中
        ⇒ 旧逻辑一直以为「还在准备战斗」，连点 4 次「战斗开始」（全点在弹窗上），
        最后报 `动作[battle-start]未稳定进入[战斗中]`（退出码 1）。
        """
        machine = real_machine(TowerState.TEAM)

        action = machine.next_action(recorded_screen("battle_guide"))

        self.assertEqual("confirm-battle-guide", action.name)
        self.assertEqual((1122, 794), action.point, "必须点弹窗的「确认」，不是「取消」")
        self.assertIn(TowerState.BATTLE, action.target_states)

    def test_the_popup_action_judges_its_source_by_the_popup_itself(self):
        """「来源还在不在」要按**弹窗**判：弹窗一关，底下仍是准备战斗页。

        若按 TEAM 判，关掉弹窗后 `is_in_state(TEAM)` 依然成立 ⇒ 主循环会认为
        「这一下没点动」而反复重试。
        """
        machine = real_machine(TowerState.TEAM)
        action = machine.next_action(recorded_screen("battle_guide"))

        self.assertTrue(
            machine.action_source_visible(recorded_screen("battle_guide"), action)
        )
        self.assertFalse(machine.action_source_visible(recorded_screen("team"), action))

    def test_a_dead_hero_restores_instead_of_looping_on_battle_start(self):
        """2026-10-31 第 22 层：队伍里有**阵亡角色**。

        这时点「战斗开始」既不进战斗、也不弹战力警告，而是跳到「英雄恢复」页
        （消耗雌蕊圣叶把角色救活）。旧逻辑不认这一页 ⇒ 连点 4 次「战斗开始」
        （全点在恢复页上）⇒ `动作[battle-start]未稳定进入[战斗中]`。
        """
        machine = real_machine(TowerState.TEAM)

        action = machine.next_action(recorded_screen("hero_restore"))

        self.assertEqual("restore-heroes", action.name)
        self.assertEqual((1130, 888), action.point, "必须点「恢复」，不是「取消」")
        self.assertIn(TowerState.TEAM, action.target_states)

    def test_the_restore_page_must_disappear_before_this_step_counts(self):
        """恢复页还在 = 这一下没点动（比如雌蕊圣叶不够），不能当成转场成功。"""
        machine = real_machine(TowerState.TEAM)
        action = machine.next_action(recorded_screen("hero_restore"))
        restore = recorded_screen("hero_restore")

        self.assertTrue(machine.action_source_visible(restore, action))
        self.assertIsNone(machine.action_target_state(restore, action))

        # 恢复页消失、回到准备战斗页 ⇒ 这一步走完，主循环接着点「战斗开始」
        back_to_team = recorded_screen("team")
        self.assertFalse(machine.action_source_visible(back_to_team, action))
        self.assertEqual(
            TowerState.TEAM, machine.action_target_state(back_to_team, action)
        )

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
        """把「重按 = 误开战斗」这条**前提**钉住：两个点击点落在同一颗按钮上。

        守的是前提，不是实现：只要这两点还这么近，转场中途补的那一下就等于
        「按下战斗开始」，「画面冻住就不补点」那道闸门就还有存在的理由。
        （若将来某次改版把「战斗开始」挪远了，这条会红，提醒重新评估那道闸门。）

        ⚠️ 这里的 40 是「两点落在同一颗按钮内」的**保守代理**（按钮本体实测宽
        231~242px），**不是**实现里的判据 —— 实现按「画面冻没冻」判，不按距离判。
        拿距离当判据是第二版修法的错误，见 ``docs/maintenance/tower.md``。
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
        """``_SETTLE_SECONDS`` 不小于实测转场时长（3.1 秒）—— 只是**少空转几帧**。

        依据来自 2026-10-09 一次真机每日任务的日志（``runtime_logs/epic7_tower.log``）：
            00:18:43 点「战斗」→ 00:18:46 点击验收 耗时=2.0秒
            00:18:48 点「进入月塔」→ 00:18:51 点击验收 耗时=3.1秒
            00:18:53 点「入场」→ 00:18:56 转场确认（约 3 秒）
        阈值 **独立写死**（不从被测模块取），改回默认 ``None``（⇒1.0 秒）会红。

        ⚠️ 这条**不是**安全护栏，别当它是：settle 加大到 3.0 之后实跑**照样重试**
        （该转场实测 >5 秒、源页 21 秒才离开）。安全职责在
        ``_RETRY_REQUIRES_MOTION`` / ``screens_are_identical`` 那道闸门上，
        这条只管「别把第一帧白白扔在转场动画里」。
        """
        self.assertIsNotNone(TowerRunner._SETTLE_SECONDS)
        self.assertGreaterEqual(TowerRunner._SETTLE_SECONDS, 3.0)

    def test_other_states_still_report_their_source_page_normally(self):
        """源页判据本身没被顺带改掉：别的动作照样能认出自己的来源页。

        ⚠️ 这条管的是 ``action_source_visible`` 的**正常性**，不是重试策略 ——
        重试策略现在按「画面冻没冻」判（见 ``RetrySuppressionTests``），与动作名无关。
        """
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

        ⚠️ 2026-10-09 起这条边**多了一个出口**：打满 25 层时同一个按钮变成「征服」，
        点下去落到 ``CONQUERED``（终点屏）。所以 ``target_states`` 现在是两个 ——
        断言按「两个都在、且 CONQUERED 在前」写死（名单独立写，不从实现取）。
        """
        machine = self.machine(TowerState.RESULT)

        action = machine.next_action(recorded_screen("result"))

        self.assertEqual("next-floor", action.name)
        self.assertEqual(
            (TowerState.CONQUERED, TowerState.TEAM), action.target_states
        )

    def test_the_conquer_button_does_not_change_the_click_point(self):
        """⚠️ 打满那一层的结算页，点的是**同一个坐标** —— 不许为「征服」另写一个落点。

        实测两张结算页的按钮绿色本体 **bbox 逐像素一致**（`1483,997 → 1879,1092`），
        只有文字不同（「下一层」/「征服」）。**坐标独立写死**成实测值
        `(1787, 1041)`，不从实现里取常量 —— 否则实现一挪，断言跟着挪，等于没守。
        """
        machine = self.machine(TowerState.RESULT)

        normal = machine.next_action(recorded_screen("result"))
        conquered = machine.next_action(recorded_screen("result_conquered_floor"))

        self.assertEqual("next-floor", normal.name)
        self.assertEqual("next-floor", conquered.name)
        self.assertEqual((1787, 1041), normal.point)
        self.assertEqual((1787, 1041), conquered.point)

    def test_the_conquered_screen_is_the_end_of_the_route(self):
        """⚠️⚠️ 终点屏：认出「征服欧多马顿塔」⇒ **立刻收工、一个按钮都不点**。

        用户 2026-10-09 实机拍板：「一碰到这个界面就代表要结束了，就是整个环节的
        最终的一个终点」。实现方式是**抛 ``FloorsConquered``**（退出码 2，走
        ``ResourceExhausted`` 那条正常业务退出通道）—— **不是**返回 None
        （那会让主循环空转到 60 秒超时，把「打满了」报成故障）。
        """
        machine = self.machine(TowerState.CONQUERED)

        with self.assertRaises(FloorsConquered) as caught:
            machine.next_action(recorded_screen("conquered"))

        self.assertEqual("月塔层数已打满", caught.exception.stop_label)

    def test_the_conquered_screen_is_reachable_from_the_battle_state_too(self):
        """终点屏也要被 ``BATTLE`` 状态接住 —— 否则监督收手时那一帧会报「战斗画面未识别」。

        ⚠️ 这是**成对契约的另一半**：``BATTLE`` 分支里认到终点屏必须走 ``FloorsConquered``，
        掉进 ``UnrecognizedScreen`` 就把「正常打满」报成了故障（超时 + 退出码 1）。
        """
        machine = self.machine(TowerState.BATTLE)

        with self.assertRaises(FloorsConquered):
            machine.next_action(recorded_screen("conquered"))

    def test_the_conquered_screen_does_not_advance_the_floor_counter(self):
        """⚠️ 走到终点**不加层数** —— 打满那一刻不该被记成「又打完一层」。

        ``commit()`` 的计数条件是 ``action.name == "next-floor" and target is TEAM``；
        终点那条边落到 ``CONQUERED``（不是 TEAM）⇒ 天然不计。这条用例把它钉住，
        防止将来有人把计数条件放宽成「只要是 next-floor 就 +1」。
        """
        machine = self.machine(TowerState.RESULT)

        action = machine.next_action(recorded_screen("result_conquered_floor"))
        machine.commit(action, TowerState.CONQUERED)

        self.assertEqual(0, machine.completed_cycles)
        self.assertIs(TowerState.CONQUERED, machine.state)

    def test_the_conquered_screen_wins_the_resume_order(self):
        """接力：认出终点屏时拨到 ``CONQUERED``，且**不给导航入口**。

        给它 ``entry`` 会让导航器白跑一趟月塔主页 —— 而那一趟毫无业务意义
        （终点就该收工），还多一次误点风险。
        """
        from auto_game_unified.games.epic7.tower import detect_resume_point

        machine = self.machine()
        point = detect_resume_point(machine, recorded_screen("conquered"))

        self.assertIsNotNone(point)
        self.assertIs(TowerState.CONQUERED, point.state)
        self.assertIsNone(point.entry)

    # ---- 打不过（FAILED 结算页，2026-11-01 接线）----

    def test_the_failed_screen_is_a_normal_business_stop(self):
        """⚠️⚠️ 打不过（FAILED 结算页）⇒ **正常业务退出**，不是故障。

        2026-10-31 第 22 层实跑：战斗失败落在 FAILED 结算页，监督两个判据
        （三选一锚点、战斗场面）全 False ⇒ 干等 45 秒报 `battle_unrecognized`
        （退出码 1 假故障）。接线后：监督收手把状态拨到 CARD，CARD 分支先判
        FAILED ⇒ 抛 `FloorTooHard`（退出码 2，「月塔这一层打不过」）。
        与「打满」是两件事：打满是完成、打不过是实力不够 —— 但对主循环语义一样。
        """
        machine = self.machine(TowerState.CARD)

        with self.assertRaises(FloorTooHard) as caught:
            machine.next_action(recorded_screen("battle_failed"))

        self.assertEqual("月塔这一层打不过", caught.exception.stop_label)

    def test_the_failed_screen_is_reachable_from_the_battle_state_too(self):
        """成对的另一半：``BATTLE`` 状态也要接得住 FAILED 屏（同征服屏那对）。

        否则监督收手时那一帧画面已翻到 FAILED、状态还停在 BATTLE ⇒ 报「战斗画面
        未识别」超时，把「打不过」报成故障。
        """
        machine = self.machine(TowerState.BATTLE)

        with self.assertRaises(FloorTooHard):
            machine.next_action(recorded_screen("battle_failed"))

    def test_the_failed_screen_wins_the_resume_order(self):
        """接力：人停在 FAILED 屏启动月塔 ⇒ 拨到 CARD（那一支先判 FAILED），不给导航入口。

        那一帧上状态循环一个状态都认不出（`battle_scene_visible` False、三选一/
        结算锚点全 miss）⇒ 不在这里显式接，就会「回大厅 → 重进塔 → 重打同一层
        → 再输一遍」。与 ``CONQUERED``「认出终点即收工」同一口径。
        """
        from auto_game_unified.games.epic7.tower import detect_resume_point

        machine = self.machine()
        point = detect_resume_point(machine, recorded_screen("battle_failed"))

        self.assertIsNotNone(point)
        self.assertEqual("战斗失败", point.page)
        self.assertIs(TowerState.CARD, point.state)
        self.assertIsNone(point.entry)

    def test_battle_adapter_hands_control_back_on_the_failed_screen(self):
        """监督必须在 FAILED 页收手（`result_visible`）—— 否则干等到 battle_unrecognized。

        那一帧上 `battle_scene_visible` 已是 False、三选一锚点也不命中，两个判据
        原本全 False ⇒ 监督永远等不到「打完」。2026-10-31 实跑即此死法。
        """
        machine = self.machine(TowerState.BATTLE)

        observation = machine.observe_battle(recorded_screen("battle_failed"), None)

        self.assertTrue(observation.result_visible)
        self.assertFalse(observation.battle_visible)

    def test_the_failed_screen_never_fires_on_a_business_page(self):
        """FAILED 判据不许在任何业务页上误响 —— 它的误判代价是「正常层被打断收工」。"""
        machine = self.machine(TowerState.CARD)

        for name in ("card", "card_unselected", "card_selected", "result", "team"):
            with self.subTest(fixture=name):
                self.assertIsNone(
                    machine._locate(recorded_screen(name), "battle_failed")
                )

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


#: 月塔**非战斗页**的全部夹具名。独立写死，不遍历实现里的任何名单。
NON_BATTLE_FIXTURES = (
    "home",
    "home_2",
    "home_alt",
    "season",
    "season_2",
    "floor_list",
    "floor_list_2",
    "floor_list_alt",
    "team",
    "team_next_floor",
    "card",
    "card_unselected",
    "card_selected",
    "result",
)


class AutoOffJudgeIsBackgroundFreeTests(unittest.TestCase):
    """右上角「自动战斗已关闭」图标：判据只认图标的白色形状，与底图无关。

    ## 为什么要换尺子（2026-10-09 月塔实跑事故）

    这张模板是**共享**的（`templates/story/auto_off.png`，主线那边裁的），
    生在亮灰雾天场景里。原样 RGB 比的时候 `TM_CCOEFF_NORMED` 把底图的**纹理**
    一起算进相似度 —— 同一枚图标叠到月塔的深色书架上只剩 **0.7492**（阈 0.80）
    ⇒ 判据失效 ⇒ 12 秒后 `auto_point_missing`，整条路线卡死在第一层开头。

    换成「白像素掩膜」口径（两侧先二值化成白色像素再比）后，同一帧回到 **0.9214**。

    ⚠️ 这条用例守的是「**同一枚控件换场景也认得出**」。谁把 `match_mode` 摘了、
    或者把阈值放水到 0.80 以下来「修」，都会在这里变红。
    """

    #: 事故帧的真机夹具。自动化诊断目录里那两张（19:34 / 13:59）原帧与它同分，
    #: 但诊断目录按路线滚动清理，所以钉夹具这一张。
    DEAD_ZONE = "battle_manual_auto_icon_dead_zone"
    #: 新口径下这张帧的实测分 —— 三帧真机素材都是这个数。
    DEAD_ZONE_SCORE = 0.9214
    #: 月塔页面上「这个图标本不该出现」时的实测上限（最亮的一张 0.4499）。
    NON_BATTLE_CEILING = 0.60

    def test_the_shared_icon_is_found_on_a_scene_it_was_not_cut_from(self):
        machine = real_machine(TowerState.BATTLE)

        found = machine._locate(recorded_screen(self.DEAD_ZONE), "auto_off")

        self.assertIsNotNone(found)
        # 断言写到「依据」：多高就是多高，不是「只要不是 None 就算过」。
        self.assertAlmostEqual(self.DEAD_ZONE_SCORE, found.score, places=3)
        self.assertGreater(
            found.score,
            machine._THRESHOLDS["auto_off"] + 0.05,
            "余量太薄 —— 擦着阈值过等于下次换个场景又失效",
        )

    def test_the_real_frame_is_reported_as_manual_with_a_click_point(self):
        """**事故的直接复现**：这一帧必须给出「手动 + 有坐标」。

        事故就是这一帧走到了 `auto_point is None` ⇒ 12 秒后 `auto_point_missing`。
        """
        machine = real_machine(TowerState.BATTLE)

        observation = machine.observe_battle(recorded_screen(self.DEAD_ZONE), None)

        self.assertEqual(AutoBattleState.MANUAL, observation.auto_state)
        self.assertIsNotNone(observation.auto_point)

    def test_the_real_frame_drives_the_route_from_the_production_entry(self):
        """从**生产入口**（`next_action`）再验一遍，而不是只看 `_locate`。

        ⚠️ 只验 `_locate` 是不够的 —— 「单测全绿、实跑照旧卡死」正是「判据被人
        抄了第二份、改的那份生产走不到」的典型症状。
        """
        machine = real_machine(TowerState.BATTLE)
        screen = recorded_screen(self.DEAD_ZONE)

        action = machine.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual("enable-auto-battle", action.name)
        self.assertEqual(machine._locate(screen, "auto_off").center, action.point)

    def test_the_old_ruler_is_what_was_broken_not_the_threshold(self):
        """同一锚点、同一帧，用**原样 RGB** 比必须仍然过不了阈 —— 修的是尺子。

        旧阈值 0.80 写死在这里：它和现在的 0.85 都过不了，所以「把阈值放水」
        解释不了这次修复。谁把 `match_mode` 摘掉，这条立刻变红。
        """
        templates = build_tower_templates(TEMPLATES_DIR)

        raw = find_best_template(
            recorded_screen(self.DEAD_ZONE),
            templates.auto_off,
            region=TowerStateMachine._REGIONS["auto_off"],
            reference_size=(1982, 1132),
            mode="raw",
        )

        self.assertLess(raw.score, 0.80, "原样比居然过阈了：事故前提不成立，先查夹具")

    def test_only_the_shared_icon_changes_ruler(self):
        """口径是**逐锚点**声明的：只有这个跨路线共享的图标走白掩膜。

        ⚠️ 名字列表独立写死（不遍历 `_MATCH_MODES` 自己），否则实现一改断言
        跟着改，注入违规纹丝不动。用**实例**上的那张表，因为它才是 `_locate`
        真正照着走的那一份（构造期由证据画像铺满每个锚点）。
        """
        modes = real_machine(TowerState.BATTLE)._MATCH_MODES

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
            with self.subTest(judge=name):
                self.assertEqual("raw", modes[name])
        with self.subTest(judge="auto_off"):
            self.assertEqual("white_mask", modes["auto_off"])

    def test_the_diagnostics_tool_uses_the_same_ruler_as_the_route(self):
        """诊断包里的分数必须与实跑判定出自**同一把尺子**。

        ⚠️ 这条守的是「判据只能有一份实现」：诊断侧漏掉口径的话，工具会报
        「0.7492 未过阈」而实跑用的是 0.9214 —— 排查时等于骗人。
        """
        screen = recorded_screen(self.DEAD_ZONE)

        report = inspect_profile(
            screen, build_tower_evidence(TEMPLATES_DIR), TEMPLATES_DIR
        )
        route = real_machine(TowerState.BATTLE)._locate(screen, "auto_off")

        self.assertTrue(report.atoms["auto_off"].observed)
        self.assertAlmostEqual(route.score, report.atoms["auto_off"].score, places=6)

    def test_no_tower_page_other_than_a_battle_shows_the_icon(self):
        """月塔自己的页面上，这个图标**一次都不许**被认出来。

        负样本名单独立写死；同时钉住「都不是 None」和「最高分有多低」——
        只看 None 的话，把阈值抬到 0.99 也能全绿，那是拿误判换漏判。
        """
        machine = real_machine(TowerState.BATTLE)
        region = TowerStateMachine._REGIONS["auto_off"]
        scores: dict[str, float] = {}

        for name in NON_BATTLE_FIXTURES:
            screen = recorded_screen(name)
            with self.subTest(fixture=name):
                self.assertIsNone(machine._locate(screen, "auto_off"))
            scores[name] = find_best_template(
                screen,
                machine.templates.auto_off,
                region=region,
                reference_size=(1982, 1132),
                mode="white_mask",
            ).score

        highest = max(scores.values())
        self.assertLess(
            highest,
            self.NON_BATTLE_CEILING,
            f"月塔非战斗页上这个图标的分太高了：{max(scores, key=scores.get)}"
            f"={highest:.4f}",
        )


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


class RetrySuppressionTests(unittest.TestCase):
    """「源页仍在」时，月塔**先看画面冻没冻**，再决定要不要原地重按。

    2026-10-09 两次实跑：点完 ``select-team`` 后基类按「源页连续 2 帧仍在 =
    这一下没生效」补点，而转场中途补的那一下会被游戏**攒着**、等下一屏出来时一次性
    兑现 ⇒ 直接按在「战斗开始」上开打，状态机还在等「准备战斗」页，白等到超时。

    ⚠️ 判据是**现象**（画面冻没冻），不是动作名单：落点重叠是布局的普遍属性，
    实测四条动作里三条压住下一屏按钮（``enter-tower`` 59px / ``select-team`` 28px /
    ``next-floor`` 61px，按钮本体宽 231~242px），列名单列不全 —— 第一版就是名单，
    用「两点距离 <= 40px」当尺子，只抓到 28px 那条。

    ⚠️ 这一组是**行为测试**：真的跑 ``_execute_transition`` 的循环、数真点了几次。
    只断言「``_SETTLE_SECONDS`` 够大」是**空护栏** —— 第一版就是这么写的，
    把 settle 从 1.0 加到 3.0 之后实跑照样重试（该转场实测 >5 秒、源页 21 秒才离开）。
    """

    class _FakeRuntime:
        """按给定序列**循环**回帧的假运行时：专门逼出「源页仍在」这条分支。

        ⚠️ 喂一张帧 = 模拟器不重绘（画面冻住）；喂两张不同的帧 = 页面还在动。
        这正是判据要分的两种情况，所以这个假运行时必须能表达「两张」，
        不能像第一版那样恒返回同一张 —— 那样会让「冻结闸门」永远命中，
        「画面在动就该补点」那半条契约测不到。
        """

        diagnostic_dir = None
        dry_run = False

        def __init__(self, screens: tuple[np.ndarray, ...]) -> None:
            self._screens = screens
            self._index = 0
            self.clicks: list[tuple[tuple[int, int], str]] = []
            self.messages: list[str] = []
            self.clock = 0.0

        def now(self) -> float:
            # 每次问时间就前进 1 秒：保证循环真的往下走，不会挂死。
            self.clock += 1.0
            return self.clock

        def capture(self) -> np.ndarray:
            frame = self._screens[self._index % len(self._screens)]
            self._index += 1
            return frame

        def click(self, point, name) -> None:
            self.clicks.append((point, name))

        def log(self, message: str) -> None:
            self.messages.append(message)

        def save_current_frame(self, screen) -> None:
            del screen

        def save_diagnostic(self, label, screen):
            del screen
            return Path(label)

    def _runner(self, screens: tuple[np.ndarray, ...]):
        machine = real_machine(TowerState.FLOOR_LIST)
        runtime = self._FakeRuntime(screens)
        runner = TowerRunner(
            machine,  # type: ignore[arg-type]
            runtime,  # type: ignore[arg-type]
            sleep=lambda _seconds: None,
            poll_seconds=0.0,
        )
        return runner, runtime

    def _run_select_team(
        self, screens: tuple[np.ndarray, ...]
    ) -> tuple[int, list[str]]:
        """跑一次 ``select-team`` 转场，返回 (点了几次, 日志)。"""
        runner, runtime = self._runner(screens)
        action = runner.machine.next_action(screens[0])
        self.assertIsNotNone(action, "楼层列表帧上应当能给出下一步动作")
        assert action is not None
        self.assertEqual("select-team", action.name)

        try:
            runner._execute_transition(action)
        except RuntimeError:
            # 超时收尾会抛错，那是**预期**的 —— 本例关心的是「点了几次」。
            pass
        clicks = [name for _point, name in runtime.clicks if name == "select-team"]
        return len(clicks), runtime.messages

    def test_a_frozen_screen_is_never_clicked_twice(self):
        """画面完全冻结（模拟器不重绘）⇒ 判为游戏正忙：**只点一次**。

        ⚠️ 这正是 2026-10-09 那两次事故的现场形态：源页判据在**陈旧帧**上一直命中
        （实测 21:03:43 点完，源页被判「仍在」整整 11 秒），而画面其实早就冻住了。
        """
        count, messages = self._run_select_team((recorded_screen("floor_list"),))

        self.assertEqual(
            1,
            count,
            f"画面冻住时补点会落到下一屏的「战斗开始」上；日志：{messages}",
        )

    def test_the_suppression_is_reported_in_the_log(self):
        """「不动手」也要留证据，否则复盘只看到「一直没重试」。"""
        _count, messages = self._run_select_team((recorded_screen("floor_list"),))

        self.assertTrue(
            any(
                "不重试" in message
                and "select-team" in message
                and "冻结" in message
                for message in messages
            ),
            f"日志里应当有一行说明为什么不动手；实际：{messages}",
        )

    def test_a_live_screen_still_retries(self):
        """⚠️ 与上一条成对：画面还在动 ⇒ 这一下确实没点到，**必须继续补点**。

        两张真机帧都是同一页（楼层列表），是两次不同时刻的实拍 —— 页面在动。
        """
        count, _messages = self._run_select_team(
            (recorded_screen("floor_list"), recorded_screen("floor_list_2"))
        )

        self.assertGreater(
            count,
            1,
            "画面在动时不许把重试机制一起关掉（真没点到就得再点一次）",
        )

    def test_a_single_different_pixel_counts_as_motion(self):
        """判据是**零阈值**的：只差一个字节也算「画面在动」⇒ 允许补点。

        真机待机的抖动正是这个量级：实测两帧之间有 112 万个像素在变，但幅度只有
        ±1~2 级，区域平均差只有 0.095~0.862 —— 用平均值做阈值的判据在这里必然失效
        （``meaningful_change`` 会把待机整个判成「冻住」）。
        """
        base = recorded_screen("floor_list")
        ticking = base.copy()
        ticking[0, 0, 0] = (int(ticking[0, 0, 0]) + 7) % 256

        count, _messages = self._run_select_team((base, ticking))

        self.assertGreater(count, 1, "差一个像素也说明页面还活着，不该拦着重按")

    def test_a_frame_we_cannot_read_is_not_reported_as_frozen(self):
        """全黑帧（窗口被遮挡）**不算**「画面冻住」—— 两件事要分开说。

        ⚠️ 这是**钩子级**用例：全黑帧上源页判据必然不命中，走不到循环里那条分支，
        所以直接调钩子证明分支可达、且两种原因**不是同一句话**（复盘时靠这句话区分
        「游戏在加载」还是「我们看不见」）。
        """
        runner, _runtime = self._runner((recorded_screen("floor_list"),))
        live = recorded_screen("floor_list")
        blank = np.zeros(SIZE, dtype=np.uint8)

        unreadable = runner._retry_block_reason(blank, frozen=True)
        self.assertIsNotNone(unreadable, "取不到画面时不许放行补点")
        assert unreadable is not None
        self.assertIn("取不到", unreadable)
        self.assertNotIn("冻结", unreadable)

        frozen = runner._retry_block_reason(live, frozen=True)
        self.assertIsNotNone(frozen)
        assert frozen is not None
        self.assertIn("冻结", frozen)

        # 成对：画面在动 ⇒ 放行。
        self.assertIsNone(runner._retry_block_reason(live, frozen=False))

    def test_every_recorded_page_is_a_valid_frame(self):
        """⚠️ 另一方向：**正常页面不许被当成「取不到画面」**。

        否则这道闸门会退化成「永远不重试」—— 判据恒真，护栏就成了摆设。
        """
        names = sorted(path.stem for path in FIXTURES.glob("*.png"))
        self.assertGreater(len(names), 8, "夹具目录不对劲，先查路径")

        for name in names:
            with self.subTest(fixture=name):
                self.assertTrue(
                    valid_game_frame(recorded_screen(name)),
                    f"{name} 被「有效帧」判据判成取不到画面",
                )


if __name__ == "__main__":
    unittest.main()


class StaminaShortageTests(unittest.TestCase):
    """「行动力不足」= 正常收工，不是转场失败（2026-11-04 14:05 真机）。

    点「战斗开始」时行动力不够，游戏弹一层模态框盖住准备战斗页。旧代码
    ``_overlay_kind`` 只认「战斗指南 / 英雄恢复」⇒ 主循环把「来源=准备战斗仍在」
    当成「没点动」，对 (1726,1040) 补点 4 次（全被弹窗吞掉），45 秒后报
    ``动作[battle-start]未稳定进入[...]``，每日任务记 ✗。
    """

    PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_tower_pc"

    def pc_frame(self, name: str) -> np.ndarray:
        path = self.PC_FIXTURES / f"{name}.png"
        return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)[:1132, :1982]

    def pc_machine(self, state=TowerState.TEAM) -> TowerStateMachine:
        root = resolve_template_dir(TEMPLATES_DIR.parent, "pc")
        return TowerStateMachine(
            build_tower_templates(root / "tower"), initial_state=state
        )

    def test_shortage_is_a_resource_exhaustion_with_its_own_label(self):
        from auto_game_unified.core.runtime import StaminaExhausted

        self.assertTrue(issubclass(StaminaShortage, StaminaExhausted))
        self.assertEqual("行动力不足（月塔不补充体力）", StaminaShortage.stop_label)
        self.assertNotEqual(StaminaExhausted.stop_label, StaminaShortage.stop_label)

    def test_pc_popup_stops_the_route_and_blocks_the_retry_path(self):
        machine = self.pc_machine()
        screen = self.pc_frame("stamina_shortage_pc_20261104")

        self.assertTrue(machine._stamina_shortage(screen))
        self.assertEqual("stamina-shortage", machine._overlay_kind(screen))
        with self.assertRaises(StaminaShortage) as caught:
            machine.next_action(screen)
        self.assertIn("不购买体力", str(caught.exception))

        action = machine._action(
            "battle-start",
            machine._POINT_BATTLE_START,
            source_page="准备战斗",
            target_states=(TowerState.BATTLE, TowerState.CARD, TowerState.TEAM),
            reason="test",
        )
        # 转场等待期间不会重新问 next_action，只问这两处；必须靠 overlay 把
        # 「来源还在」挡掉、把落点收成 TEAM，下一拍才轮得到 StaminaShortage。
        self.assertFalse(machine.action_source_visible(screen, action))
        self.assertIs(TowerState.TEAM, machine.action_target_state(screen, action))

    def test_shortage_requires_all_three_stamina_atoms(self):
        """证伪：三颗缺一就不认 —— 不许拿「弹窗标题像」当判据。"""
        machine = self.pc_machine()
        screen = self.pc_frame("stamina_shortage_pc_20261104")
        templates = machine.templates

        for name in ("stamina_popup", "stamina_material", "stamina_confirm"):
            with self.subTest(missing=name):
                broken = dataclasses.replace(
                    templates, **{name: templates.stamina_popup if name != "stamina_popup" else templates.stamina_confirm}
                )
                probe = TowerStateMachine(broken, initial_state=TowerState.TEAM)
                self.assertFalse(probe._stamina_shortage(screen))
                self.assertIsNone(probe._overlay_kind(screen))

    def test_normal_prepare_page_is_not_a_stamina_shortage(self):
        machine = self.pc_machine()
        screen = self.pc_frame("prepare_pc_live_20261103")

        self.assertFalse(machine._stamina_shortage(screen))
        self.assertIsNone(machine._overlay_kind(screen))
        action = machine.next_action(screen)
        self.assertIsNotNone(action)
        self.assertEqual("battle-start", action.name)

    def test_another_modal_popup_is_not_a_stamina_shortage(self):
        """跨页反例：战后「给予协助的朋友」弹窗也是模态框，不该被认成体力不足。"""
        machine = self.pc_machine()
        path = ROOT / "tests" / "fixtures" / "epic7_story" / "friend_request_pc_live_20261101.png"
        screen = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)[:1132, :1982]

        self.assertFalse(machine._stamina_shortage(screen))

    def test_runner_exits_cleanly_without_clicking_anything(self):
        """真 Runner 级：退出码 2 那条通道接通，且**一次都没点**（不许买体力）。"""
        frame = self.pc_frame("stamina_shortage_pc_20261104")
        runtime = RetrySuppressionTests._FakeRuntime((frame,))
        runner = TowerRunner(
            self.pc_machine(),
            runtime,  # type: ignore[arg-type]
            sleep=lambda _seconds: None,
            poll_seconds=0.0,
        )

        runner.run(max_cycles=1)

        self.assertTrue(runner.resource_exhausted)
        self.assertEqual([], runtime.clicks)
        self.assertTrue(
            any("行动力不足" in message for message in runtime.messages),
            runtime.messages,
        )


class ClearPageEndsTheBattleOnPcOnlyTests(unittest.TestCase):
    """第 25 层打完**直接进 CLEAR 结算页**，没有三选一装置页（2026-11-04 23:52 真机）。

    事故链：PC 客户端打满 25 层后落在「CLEAR / 占领奖励 / 征服」屏上 ⇒
    ``card_decide``+``card_hint`` 不成立、``battle_failed`` 也不成立 ⇒
    ``observe_battle.result_visible`` 全 False，监督干等 216 秒后报
    「战斗画面持续无法识别」，把正常通关记成故障，每日任务 ✗。

    修法是把 ``result_clear`` 接进 ``result_visible``，**但只挂 PC 开关**：
    模拟器侧的收尾是「先三选一装置页」那一套，没有真机证据前一个字不动。

    反例证据（同一批真机帧扫描）：CLEAR 页的 ``card_decide`` 0.31 / ``card_hint``
    0.27，三选一判据确实不成立；而 ``battle_failed`` 在三选一页才是主判据，
    两组互不覆盖 ⇒ 加这一条不会把「打不过」误判成「打完了」。
    """

    PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_tower_pc"
    CLEAR_FRAME = "battle_clear_pc_20261104"

    def frame(self, name: str) -> np.ndarray:
        path = self.PC_FIXTURES / f"{name}.png"
        image = cv2.imread(str(path))
        self.assertIsNotNone(image, path)
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)[:1132, :1982]

    def pc_machine(self) -> TowerStateMachine:
        root = resolve_template_dir(TEMPLATES_DIR.parent, "pc")
        return TowerStateMachine(
            build_tower_templates(root / "tower"), initial_state=TowerState.BATTLE
        )

    def emulator_machine(self) -> TowerStateMachine:
        return TowerStateMachine(
            build_tower_templates(TEMPLATES_DIR), initial_state=TowerState.BATTLE
        )

    def test_pc_clear_page_is_a_finished_battle(self):
        machine = self.pc_machine()
        screen = self.frame(self.CLEAR_FRAME)

        observation = machine.observe_battle(screen, None)

        self.assertTrue(observation.result_visible)
        # 语义要对：这是「打完了」，不是「还在打」。
        self.assertFalse(observation.battle_visible)

    def test_the_clear_page_is_recognised_as_result_and_conquered(self):
        """状态机侧也不能瞎：CLEAR 屏必须能被 RESULT / CONQUERED 接到。"""
        machine = self.pc_machine()
        screen = self.frame(self.CLEAR_FRAME)

        # BATTLE 的判据本来就含 ``result_clear``（「最后一下打完了」）。
        self.assertTrue(machine.is_in_state(screen, TowerState.BATTLE))
        # RESULT 也是 ``result_clear``。
        self.assertTrue(machine.is_in_state(screen, TowerState.RESULT))

    def test_the_emulator_path_is_untouched(self):
        """隔离铁律：模拟器模板跑同一张 PC 帧，``result_visible`` 必须仍是 False。

        这条不是说「模拟器该认不出 CLEAR 页」，而是钉住「新增的那一条只在
        PC 后端生效」—— 万一哪天有人把 ``self.templates.pc`` 去掉，这里立刻红。
        """
        machine = self.emulator_machine()
        screen = self.frame(self.CLEAR_FRAME)

        observation = machine.observe_battle(screen, None)

        self.assertFalse(machine.templates.pc)
        self.assertFalse(observation.result_visible)

    def test_the_runner_landing_on_card_reroutes_to_the_result_page(self):
        """监督的收手落点是写死的 ``_RESULT_STATE = CARD``，PC 最后一层却直接给 CLEAR。

        不补这条出路：``_required(card_decide)`` 在 CLEAR 页上必然失败（实测 0.31），
        「正常通关」会被报成「月塔锚点 card_decide 未识别」—— 和 repair 前一样是 ✗，
        只是错误信息换了一句。所以 ``result_visible`` 与这条出路**必须成对存在**。
        """
        machine = self.pc_machine()
        machine.state = TowerState.CARD
        screen = self.frame(self.CLEAR_FRAME)

        action = machine.next_action(screen)

        self.assertIs(TowerState.RESULT, machine.state)
        self.assertIsNotNone(action)
        self.assertEqual("next-floor", action.name)
        # 打满那一层点的是「征服」⇒ 终点必须在合同里，否则收了手无处可去。
        self.assertIn(TowerState.CONQUERED, action.target_states)

    def test_the_emulator_keeps_failing_loudly_when_it_lands_on_card(self):
        """隔离铁律：模拟器后端落到 CARD + CLEAR 帧，仍是原来的「认不出」路径。

        这不是在给模拟器写理想行为，而是钉住「新出路只在 PC 生效」。
        """
        machine = self.emulator_machine()
        machine.state = TowerState.CARD

        with self.assertRaises(RuntimeError):
            machine.next_action(self.frame(self.CLEAR_FRAME))

    def test_the_three_choice_page_still_ends_the_battle_on_both_backends(self):
        """回归：三选一装置页那条老路不能被新判据挤掉（模拟器与 PC 都成立）。"""
        # PC 用 PC 帧、模拟器用模拟器帧：两套覆盖图互不通用，混用只会测出噪声。
        for label, machine, screen in (
            ("pc", self.pc_machine(), self.frame("card_pc_live_20261103")),
            (
                "emulator",
                self.emulator_machine(),
                cv2.cvtColor(
                    cv2.imread(str(FIXTURES / "card.png")), cv2.COLOR_BGR2RGB
                ),
            ),
        ):
            with self.subTest(backend=label):
                observation = machine.observe_battle(screen, None)
                self.assertTrue(observation.result_visible)


class ConqueredFloorListTests(unittest.TestCase):
    """本阶段 25 层全部占领后，楼层列表的按钮从「选择队伍」变成「编队」。

    事故（2026-11-05 00:26 真机）：上一轮把第 25 层打完并领取后，再跑月塔
    ``enter-tower`` **转场验收就失败** —— 目标页判据 `FLOOR_LIST` 只认
    `floor_select_team`，而这一页上是「编队」，原样只有 **0.5897**（阈 0.88）。
    于是干等 60 秒报 `no_transition_enter-tower`，把「今天已经打满」报成故障。
    这条 ✗ 会**每天重复**，直到阶段重置为止。

    判据的可证伪性：`floor_select_team` 与 `floor_team_edit` 是**同一枚按钮**
    （落点中心同为 (1744,1040)、尺寸同为 280x76，只差文字）⇒ 不存在
    「模型认错了地方」这一层怀疑，只能解释为「按钮换字了」。
    """

    PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_tower_pc"
    CONQUERED_FRAME = "floor_list_conquered_pc_20261105"

    def frame(self, name: str) -> np.ndarray:
        path = self.PC_FIXTURES / f"{name}.png"
        image = cv2.imread(str(path))
        self.assertIsNotNone(image, path)
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)[:1132, :1982]

    def pc_machine(self, state: TowerState = TowerState.FLOOR_LIST):
        root = resolve_template_dir(TEMPLATES_DIR.parent, "pc")
        return TowerStateMachine(
            build_tower_templates(root / "tower"), initial_state=state
        )

    def emulator_machine(self, state: TowerState = TowerState.FLOOR_LIST):
        return TowerStateMachine(
            build_tower_templates(TEMPLATES_DIR), initial_state=state
        )

    def test_the_page_is_a_floor_list(self):
        """转场验收得先过：`enter-tower` 的目标页判据必须认这一页。"""
        machine = self.pc_machine()

        self.assertTrue(machine.is_in_state(self.frame(self.CONQUERED_FRAME), TowerState.FLOOR_LIST))

    def test_it_stops_as_a_normal_conquest_instead_of_a_timeout(self):
        from auto_game_unified.games.epic7.tower import FloorsConquered

        machine = self.pc_machine()

        with self.assertRaises(FloorsConquered) as caught:
            machine.next_action(self.frame(self.CONQUERED_FRAME))

        self.assertIn("全部占领", str(caught.exception))
        # 必须走「资源耗尽」那条通道（退出码 2），不是普通 RuntimeError。
        self.assertEqual("月塔层数已打满", FloorsConquered.stop_label)

    def test_the_clear_page_is_not_mistaken_for_a_floor_list(self):
        """跨页反例：CLEAR 结算页（右下「征服」）不能被认成楼层列表。"""
        machine = self.pc_machine()

        self.assertFalse(
            machine.is_in_state(self.frame("battle_clear_pc_20261104"), TowerState.FLOOR_LIST)
        )

    def test_the_fix_is_pc_only(self):
        """隔离铁律：模拟器没有这枚图 ⇒ 两个判断点全部短路，行为与改动前一致。"""
        machine = self.emulator_machine()
        frame = self.frame(self.CONQUERED_FRAME)

        self.assertIsNone(machine.templates.floor_team_edit)
        self.assertFalse(machine.is_in_state(frame, TowerState.FLOOR_LIST))
        with self.assertRaises(RuntimeError) as caught:
            machine.next_action(frame)
        self.assertNotIn("全部占领", str(caught.exception))
