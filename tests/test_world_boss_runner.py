"""世界首领战 Runner 的回归测试。

守四类事：
1. 战斗移交后的状态落点（结算 / 体力弹窗退回配置页）。
2. **次数耗尽时不再开下一局** —— 这是这条路线最重要的安全边界。
3. 生命之叶耗尽走资源退出，不是故障。
4. **战斗画面认得出、右上角「跳过」点得掉** —— 2026-09-22 实跑报错
   「战斗画面持续无法识别 45 秒」的回归（见 ``WorldBossBattleScreenTests``）。
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.matcher import find_best_template
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.games.epic7.battle_controls import battle_scene_visible
from auto_game_unified.games.epic7.world_boss import (
    BATTLE_SKIP_REGION,
    BATTLE_SKIP_THRESHOLD,
    CLICK_POINTS,
    SELECT_TEAM_BAR_RELATIVE_V,
    SELECT_TEAM_ENABLED_GREEN_RATIO,
    WEEKLY_CHEST_BOX,
    WEEKLY_CHEST_BRIGHTNESS_RATIO,
    WEEKLY_CHEST_MAX_CLICKS,
    WEEKLY_CHEST_REGION,
    WEEKLY_CHEST_THRESHOLD,
    WEEKLY_CHEST2_BOX,
    WEEKLY_CHEST2_REGION,
    AttemptsExhausted,
    WorldBossAction,
    WorldBossRunner,
    WorldBossState,
    WorldBossStateMachine,
    find_world_boss_skip,
    find_weekly_chest,
    team_configured,
    select_team_bar_relative_v,
    select_team_enabled,
    select_team_green_ratio,
    state_label,
    weekly_chest_brightness_ratio,
    world_boss_battle_visible,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_world_boss"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "world_boss"


def fixture(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert image is not None, f"读不到夹具 {name}"
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def blank() -> np.ndarray:
    return np.zeros((1132, 1982, 3), dtype=np.uint8)


def darkened(image: np.ndarray, scale: float) -> np.ndarray:
    """模拟页面淡入：整幅按比例压暗（真实淡入就是往黑里混合）。"""
    return np.clip(image.astype(np.float32) * scale, 0, 255).astype(np.uint8)


class WorldBossCountTests(unittest.TestCase):
    """次数口径：看「选择队伍」按钮亮不亮，不看进程跑了几轮。"""

    def test_actionable_home_has_a_bright_green_button(self):
        screen = fixture("worldboss_home")

        ratio = select_team_green_ratio(screen)

        self.assertGreater(ratio, SELECT_TEAM_ENABLED_GREEN_RATIO)
        self.assertTrue(select_team_enabled(screen))

    def test_exhausted_home_has_a_grey_button(self):
        screen = fixture("worldboss_home_exhausted")

        ratio = select_team_green_ratio(screen)

        self.assertEqual(0.0, ratio)
        self.assertFalse(select_team_enabled(screen))

    def test_exhausted_home_still_identifies_as_the_home_page(self):
        """按钮变灰只是「没次数了」，页面本身还是主页 —— 不能认成未知画面。

        认不出来会落到「未知画面唤醒」点屏幕中央，而那里正好是队伍卡片。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        self.assertIs(
            WorldBossState.HOME, machine.observe_page(fixture("worldboss_home_exhausted"))
        )

    def test_faded_home_with_attempts_left_is_not_read_as_exhausted(self):
        """页面淡入变暗时**不许**把「还有次数」读成「次数用完」。

        这是 2026-09-23 接上次数判据时差点埋下的破坏性回归：页面识别用的
        ``TM_CCOEFF_NORMED`` 对亮度缩放**不敏感**（暗帧照样认得出主页），
        而绿条的**绝对**亮度判据很敏感 —— 两边一凑，淡入暗帧会同时满足
        「是主页」+「绿条判灰」⇒ 提前退出，**还有次数却把这一轮收摊了**。

        实测（``runtime_logs/_wb_fade_probe.py``）：``worldboss_home.png``（1/2）
        压到 50% 亮度时绿占比从 0.5924 掉到 0.0102（低于 0.10 阈值），
        而页面**仍被识别成主页** —— 所以这里先把旧判据塌掉这件事钉住，
        再断言新判据（绝对 + 相对取或）不会上当。
        """

        screen = darkened(fixture("worldboss_home"), 0.5)

        self.assertLess(
            select_team_green_ratio(screen),
            SELECT_TEAM_ENABLED_GREEN_RATIO,
            "这张暗帧上绝对判据确实会塌 —— 这正是不能用它单独做决定的理由",
        )
        self.assertGreaterEqual(
            select_team_bar_relative_v(screen),
            SELECT_TEAM_BAR_RELATIVE_V,
            "相对亮度对整屏压暗免疫，不该跟着掉下去",
        )
        self.assertTrue(
            select_team_enabled(screen),
            "还有次数的主页被压暗一格，仍然必须判成「可点」",
        )

    def test_faded_exhausted_home_is_still_read_as_exhausted(self):
        """反向补齐：真变灰的按钮压暗之后**依然是灰的**，别把免疫做成失明。"""

        screen = darkened(fixture("worldboss_home_exhausted"), 0.5)

        self.assertFalse(
            select_team_enabled(screen),
            "压暗不能把真变灰洗成可点 —— 那会退回「一直点」",
        )

    def test_exhausted_home_stops_instead_of_asking_for_the_team_button(self):
        """次数用完时**不许**再报「点选择队伍」，必须当场以资源退出收场。

        这就是 2026-09-23 实跑反馈的「按钮明明 0/2 了还在一直点」：
        判据（``select_team_enabled``）早就写好并有单测，但 ``next_action``
        **从来没调用过它** ⇒ 主页在 0/2 时照样返回 ``open-team-select`` ⇒
        灰按钮点不动 ⇒ 45 秒转场超时 ⇒ 重试 4 次 ⇒ 回大厅恢复 ⇒ 再点……
        所以这条用例守的不是判据，而是**判据有没有被接到决策路径上**。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        with self.assertRaises(AttemptsExhausted):
            machine.next_action(fixture("worldboss_home_exhausted"))

    def test_faded_home_with_attempts_left_is_still_asked_for_the_team_button(self):
        """反向守门：淡入暗帧不能触发上面那条停止（否则会白白收摊）。"""

        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(darkened(fixture("worldboss_home"), 0.5))

        self.assertEqual("open-team-select", action.name)


class WorldBossWeeklyChestTests(unittest.TestCase):
    """主页「每周贡献度」宝箱：发光（可领）/ 未点亮 要分得开，且顺序是「先领宝箱再判次数」。

    2026-09-23 用户实拍补充：右上角进度条上够量的宝箱会**发光**，
    应该「在开下一把之前先领掉」，且**领完才算一轮结束**。
    """

    #: 宝箱 #1（27,500,000）实测中心（画布坐标）。
    CHEST_POINT = (1657, 372)

    def test_claimable_chest_is_found_at_the_measured_centre(self):
        machine = WorldBossStateMachine(TEMPLATES)

        match = find_weekly_chest(
            fixture("worldboss_home_chest_claimable"), machine.templates.weekly_chest
        )

        self.assertIsNotNone(match, "可领的宝箱必须认得出")
        self.assertGreater(match.score, WEEKLY_CHEST_THRESHOLD)
        self.assertLessEqual(abs(match.center[0] - self.CHEST_POINT[0]), 3)
        self.assertLessEqual(abs(match.center[1] - self.CHEST_POINT[1]), 3)

    def test_unlit_chest_is_not_reported_as_claimable(self):
        """没点亮的宝箱**不是**可领 —— 判错的后果是站在原地反复点一个死箱子。

        两张未点亮主页都要过一遍：`1/2`（还打得动）和 `0/2`（次数用完）。
        除了「不命中」，还断言**原始得分离阈值有多远** —— 只断言 ``is None``
        的话，把阈值调成 0.10 也能通过。
        """

        template = WorldBossStateMachine(TEMPLATES).templates.weekly_chest

        for name in ("worldboss_home", "worldboss_home_exhausted"):
            with self.subTest(page=name):
                screen = fixture(name)
                best = find_best_template(screen, template, region=WEEKLY_CHEST_REGION)
                self.assertLess(
                    best.score,
                    WEEKLY_CHEST_THRESHOLD - 0.10,
                    f"{name} 的得分离阈值太近（{best.score:.4f}），余量不足",
                )
                self.assertIsNone(
                    find_weekly_chest(screen, template),
                    f"{name} 的宝箱没点亮，不该判成可领",
                )

    def test_no_other_world_boss_page_looks_claimable(self):
        """本路线其它页一张都不许被判成「有宝箱可领」。

        误判的后果不是灾难性的（多点一下箱子），但会让每一轮都白点一次，
        而且会把「宝箱」这个信号变得不可信。全库 194 张的扫描是探针做的
        （`runtime_logs/_wb_chest_build_assets.py`：其它路线最高 0.4878），
        这里守住本路线这 18 张 —— **包含「已领（绿勾）」那一张**。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        hits = {
            path.name
            for path in sorted(FIXTURES.glob("*.png"))
            if find_weekly_chest(fixture(path.stem), machine.templates.weekly_chest)
            is not None
        }

        self.assertEqual({"worldboss_home_chest_claimable.png"}, hits)

    def test_claimed_chest_is_not_reported_as_claimable(self):
        """绿勾那一态**不是**可领 —— 判错的后果是「领完还一直点」。

        绿勾底下还架着宝箱本体，所以它比全暗的两版未点亮主页**更像**可领
        （0.7085 对 0.6559）。余量比那两版薄，所以这条用 0.05 而不是 0.10 的
        余量；全库证据在 `runtime_logs/_wb_chest_build_assets.py` 的输出里
        （阈值 0.80 下命中 1 张 = 只有「可领」那张）。
        """

        template = WorldBossStateMachine(TEMPLATES).templates.weekly_chest
        screen = fixture("worldboss_home_chest_claimed")

        best = find_best_template(screen, template, region=WEEKLY_CHEST_REGION)
        self.assertLess(
            best.score,
            WEEKLY_CHEST_THRESHOLD - 0.05,
            f"绿勾那一态的得分离阈值太近（{best.score:.4f}），余量不足",
        )
        self.assertIsNone(
            find_weekly_chest(screen, template),
            "宝箱已经领过了，不该再判成可领（否则会原地反复点一个领不动的箱子）",
        )

    def test_home_after_claiming_ends_the_cycle_instead_of_clicking_again(self):
        """领完宝箱之后的终点：**不再碰宝箱**，直接判次数、干净收场。

        用户要的是「领完宝箱之后才是一轮结束」。这张实拍图上宝箱已是绿勾、
        次数是 0/2 ⇒ 这条链路的终点就该是 ``AttemptsExhausted``（退出码 2），
        而不是回头再点一遍绿勾、也不是去点那颗灰掉的「选择队伍」。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        screen = fixture("worldboss_home_chest_claimed")

        self.assertIs(WorldBossState.HOME, machine.observe_page(screen))
        with self.assertRaises(AttemptsExhausted):
            machine.next_action(screen)

    def test_home_with_a_claimable_chest_claims_before_judging_attempts(self):
        """⚠️ 这条是**顺序**回归：截图里同时是「0/2」和「宝箱可领」。

        用户明确要求「先领宝箱，再判次数」「领完宝箱之后才是一轮结束」。
        顺序反了的话，这个状态下会立刻抛 ``AttemptsExhausted`` 收摊走人 ——
        宝箱永远领不到。所以这里断言的是：**同一个画面，先出领宝箱的动作**。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        screen = fixture("worldboss_home_chest_claimable")

        # 前提：这张图确实是主页，而且按钮确实是灰的（顺序才有意义）。
        self.assertIs(WorldBossState.HOME, machine.observe_page(screen))
        self.assertFalse(select_team_enabled(screen), "这张截图上次数是 0/2")

        action = machine.next_action(screen)

        self.assertEqual(
            "claim-weekly-chest",
            action.name,
            "有宝箱可领时必须先领宝箱，不能因为次数用完就直接收摊",
        )
        self.assertEqual(self.CHEST_POINT, action.point)
        # 同页动作（点完宝箱不发光、页面不变）⇒ 不声明 target_pages。
        self.assertEqual((), action.target_pages)
        self.assertEqual("世界首领战主页", action.source_page)

    def test_home_without_a_chest_still_reports_the_team_button(self):
        """反向守门：没有宝箱可领时不许冒出「领宝箱」动作（原有行为不回退）。"""

        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("worldboss_home"))

        self.assertEqual("open-team-select", action.name)

    def test_a_home_without_a_chest_reports_the_scan_instead_of_staying_silent(self):
        """⚠️ 不许哑判（2026-09-26 用户要求）：「没有宝箱」也是结论，要带**实测数字**。

        2026-09-25 23:01 那次实跑：到主页两秒后就以「今日次数已用完」收场，日志里
        **一句关于宝箱的话都没有** —— 事后根本分不清「当时确实没得领」还是
        「判据漏了、本来该领没领」。所以两个槽位的形状分/亮度比都要写进结论里，
        让人一眼看出是「差得远」还是「差一点」。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        with self.assertRaises(AttemptsExhausted) as caught:
            machine.next_action(fixture("worldboss_home_exhausted"))

        message = str(caught.exception)
        self.assertIn(
            "宝箱扫描", message, f"没有宝箱时的结论必须带扫描数字，实际 {message}"
        )
        for slot in ("#1", "#2"):
            self.assertIn(slot, message, f"两个槽位都要量到，实际 {message}")

    def test_chest_box_matches_the_template_size(self):
        """裁框与模板必须同尺寸 —— 模板换了、框不跟着改，得分会莫名其妙变低。"""

        machine = WorldBossStateMachine(TEMPLATES)
        template = machine.templates.weekly_chest

        self.assertEqual(WEEKLY_CHEST_BOX[2], template.shape[1])
        self.assertEqual(WEEKLY_CHEST_BOX[3], template.shape[0])

    def test_a_claimed_chest_from_a_darker_frame_is_not_reported_as_claimable(self):
        """⚠️ **模板得分单独守不住** —— 2026-09-25 实跑就是死在这里。

        同一个「已领（绿勾）」态，换一张截图（`worldboss_home_chest_claimed_dark`，
        整幅偏暗）对可领模板却能得 **0.8069**，越过 0.80 的阈值 ⇒ 程序把已领的箱子
        当成可领：点 4 次不生效 → 回大厅 → 重新导航进来 → 再点 4 次，把路线拖死；
        而当时局内 0/2 本该直接收场。

        所以这条**先断言原始得分确实越阈**（否则它就守不住那个现场），
        再断言 ``find_weekly_chest`` 因为第二道亮度判据而没有判成可领。
        """

        template = WorldBossStateMachine(TEMPLATES).templates.weekly_chest
        screen = fixture("worldboss_home_chest_claimed_dark")

        best = find_best_template(screen, template, region=WEEKLY_CHEST_REGION)
        self.assertGreater(
            best.score,
            WEEKLY_CHEST_THRESHOLD,
            f"这张图的意义就在于它越阈（实测 {best.score:.4f}）；若它跌到阈值以下，"
            "说明夹具换过了，这条回归也就守不住现场了",
        )
        self.assertIsNone(
            find_weekly_chest(screen, template),
            "它在「有没有发光」这道判据上不成立 -> 不该判成可领（判错就是原地反复点）",
        )

    def test_brightness_ratio_separates_glowing_from_not_glowing(self):
        """「有没有在发光」这道判据：可领明显过线，不发光的两态都远在阈值下方。

        用**比值**而不是绝对亮度：整幅画面被压暗时两边一起降、比值不变，
        所以它不会被「同一个状态换张截图/赶上淡入」骗过去 —— 这正是它比模板得分可靠之处。
        """

        lit = weekly_chest_brightness_ratio(fixture("worldboss_home_chest_claimable"))
        self.assertGreater(
            lit,
            WEEKLY_CHEST_BRIGHTNESS_RATIO + 0.30,
            f"可领那张要明显过线（实测 {lit:.3f}），否则这道判据没有余量",
        )
        for name in ("worldboss_home_chest_claimed_dark", "worldboss_home_chest_claimed"):
            with self.subTest(page=name):
                ratio = weekly_chest_brightness_ratio(fixture(name))
                self.assertLess(
                    ratio,
                    WEEKLY_CHEST_BRIGHTNESS_RATIO - 0.30,
                    f"{name} 没在发光，亮度比应远低于阈值（实测 {ratio:.3f}）",
                )


class WorldBossWeeklyChest2Tests(unittest.TestCase):
    """宝箱 #2（`44,000,000`，进度条右侧那一档）—— 2026-09-25 补齐的那一档。

    守三件事：
    1. 它在实测中心（画布 **(1824,527)**）认得出；
    2. ⚠️ **两个槽位互不串台** —— 两档外观不同（#2 发光态对 #1 的模板只有 0.5161），
       混用不是「效果差一点」，而是漏领或点错箱子；
    3. 未到档（两版未点亮主页）认不出，且余量足够。
    """

    #: 宝箱 #2 实测中心（画布坐标，由亮度峰值定位，见 `runtime_logs/_wb_chest2_assets.py`）。
    CHEST2_POINT = (1824, 527)

    def _find2(self, name: str):
        machine = WorldBossStateMachine(TEMPLATES)
        return find_weekly_chest(
            fixture(name),
            machine.templates.weekly_chest2,
            region=WEEKLY_CHEST2_REGION,
            box=WEEKLY_CHEST2_BOX,
        )

    def test_claimable_chest2_is_found_at_the_measured_centre(self):
        match = self._find2("worldboss_home_chest2_claimable")

        self.assertIsNotNone(match, "第二个宝箱发光时必须认得出")
        self.assertGreater(match.score, WEEKLY_CHEST_THRESHOLD)
        self.assertLessEqual(abs(match.center[0] - self.CHEST2_POINT[0]), 3)
        self.assertLessEqual(abs(match.center[1] - self.CHEST2_POINT[1]), 3)

    def test_the_two_slots_do_not_cross_talk(self):
        """⚠️ 两个槽位各有模板与搜索区，**谁都不许认到对面的箱子**。

        串台的后果分别是：认漏（该领的没领）和认错（点着一个领不动的箱子磨到撒手）。
        所以两个方向都要断言，而不是只测「正例能命中」。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        # 方向一：#2 发光那张图里，**#1 的判据**必须认不出（#1 那格是绿勾）。
        self.assertIsNone(
            find_weekly_chest(
                fixture("worldboss_home_chest2_claimable"), machine.templates.weekly_chest
            ),
            "#1 的判据不该认到 #2 的箱子（会把点击落到错的位置）",
        )
        # 方向二：#1 发光那张图里，**#2 的判据**必须认不出。
        self.assertIsNone(
            self._find2("worldboss_home_chest_claimable"),
            "#2 的判据不该认到 #1 的箱子",
        )

    def test_unlit_chest2_is_not_reported_as_claimable(self):
        """#2 没到档（两版未点亮主页）不许判成可领，并断言余量够厚。"""

        template = WorldBossStateMachine(TEMPLATES).templates.weekly_chest2

        for name in ("worldboss_home", "worldboss_home_exhausted"):
            with self.subTest(page=name):
                best = find_best_template(
                    fixture(name), template, region=WEEKLY_CHEST2_REGION
                )
                self.assertLess(
                    best.score,
                    WEEKLY_CHEST_THRESHOLD - 0.20,
                    f"{name} 的 #2 槽位没到档，得分离阈值太近（{best.score:.4f}）",
                )
                self.assertIsNone(
                    self._find2(name), f"{name} 的 #2 没到档，不该判成可领"
                )

    def test_no_other_world_boss_page_looks_like_chest2(self):
        """本路线其它页一张都不许被 #2 的判据认成可领（含 #1 的三种态）。"""

        hits = {
            path.name
            for path in sorted(FIXTURES.glob("*.png"))
            if self._find2(path.stem) is not None
        }

        self.assertEqual({"worldboss_home_chest2_claimable.png"}, hits)

    def test_chest2_box_matches_the_template_size(self):
        """裁框与模板必须同尺寸 —— 模板换了框不跟着改，得分会莫名其妙变低。"""

        template = WorldBossStateMachine(TEMPLATES).templates.weekly_chest2

        self.assertEqual(WEEKLY_CHEST2_BOX[2], template.shape[1])
        self.assertEqual(WEEKLY_CHEST2_BOX[3], template.shape[0])

    def test_home_with_chest2_claimable_claims_that_slot(self):
        """站在「#2 可领」的主页上：动作要指向 #2 的中心，日志要能看出是哪个槽位。"""

        machine = WorldBossStateMachine(TEMPLATES)
        screen = fixture("worldboss_home_chest2_claimable")

        self.assertIs(WorldBossState.HOME, machine.observe_page(screen))
        action = machine.next_action(screen)

        self.assertEqual("claim-weekly-chest", action.name)
        self.assertEqual(self.CHEST2_POINT, action.point)
        self.assertIn("#2", action.reason, "日志要写明是哪个槽位，否则看不出现场")

    def test_brightness_ratio_is_measured_on_the_matching_slot(self):
        """亮度比必须量**对应槽位**的那一块：量错箱子，这道判据就等于没有。

        #2 发光那张图上：按 #2 的框量明显过线（≈3.2），按 #1 的框量不过线（≈1.0）。
        这就是为什么 ``weekly_chest_brightness_ratio`` 要带 ``box`` 参数。
        """

        screen = fixture("worldboss_home_chest2_claimable")

        self.assertGreater(
            weekly_chest_brightness_ratio(screen, box=WEEKLY_CHEST2_BOX),
            WEEKLY_CHEST_BRIGHTNESS_RATIO + 0.30,
        )
        self.assertLess(
            weekly_chest_brightness_ratio(screen, box=WEEKLY_CHEST_BOX),
            WEEKLY_CHEST_BRIGHTNESS_RATIO - 0.30,
        )


class WorldBossStateMachineTests(unittest.TestCase):
    def test_full_cycle_walks_every_page_in_order(self):
        machine = WorldBossStateMachine(TEMPLATES)
        expected = [
            ("worldboss_home", WorldBossState.HOME, "open-team-select"),
            ("team_select", WorldBossState.TEAM_SELECT, "build-team"),
            # 配置队伍页分两阶段：按钮还是橙色 ⇒ 先自动配置，不点战斗开始。
            ("team_config", WorldBossState.TEAM_CONFIG, "auto-configure"),
            # 按钮转蓝 ⇒ 自动配置已生效，这一步才点战斗开始。
            ("team_config_configured", WorldBossState.TEAM_CONFIG, "battle-start"),
            ("stamina_popup", WorldBossState.TEAM_CONFIG, "stamina_material"),
            ("battle_result", WorldBossState.RESULT, "open-level-reward"),
            ("level_reward", WorldBossState.LEVEL_REWARD, "open-all-chests"),
            # 从奖励弹窗回到结算页：同一个页面，这一步要做的是「回主页」。
            ("battle_result", WorldBossState.RESULT_CONFIRM, "confirm-result"),
        ]

        for name, state, action_name in expected:
            with self.subTest(page=name):
                action = machine.next_action(fixture(name))
                self.assertEqual(state, machine.state)
                self.assertEqual(action_name, action.name)

    def test_team_config_is_recognised_without_walking_through_team_select(self):
        """配置队伍页有自己的排他锚点，不依赖「上一帧在哪」。

        靠上下文猜的判据在状态拨错时不会自愈，只会卡到超时 —— 这里守住它不会退回去。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("team_config"))

        self.assertEqual(WorldBossState.TEAM_CONFIG, machine.state)
        self.assertEqual("auto-configure", action.name)
        self.assertEqual(CLICK_POINTS["auto-configure"], action.point)

    def test_auto_configure_is_skipped_once_teams_are_filled(self):
        """队伍配好后不能重复点「自动配置」，必须直接点「战斗开始」。

        判据是**三队槽位里有没有英雄**（画面细节量），不是按钮颜色 ——
        两张 fixture 的按钮配色可以一样，但一个槽位空、一个槽位满：

        - ``team_config.png``：三队槽位空、战斗力 0（细节量 ≈ 451）
        - ``team_config_configured.png``：三队各 5 人、战斗力 58~67 万（细节量 ≈ 1182）

        ⚠️ 2026-09-22 曾经拿「自动配置」按钮的橙/蓝色相当判据，实跑直接翻车：
        那颗按钮的配色与「队伍配没配」无关，同一个空队伍页面几分钟内就会由蓝转橙。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        self.assertFalse(team_configured(fixture("team_config")))
        self.assertTrue(team_configured(fixture("team_config_configured")))

        action = machine.next_action(fixture("team_config_configured"))

        self.assertEqual(WorldBossState.TEAM_CONFIG, machine.state)
        self.assertEqual("battle-start", action.name)
        self.assertEqual(CLICK_POINTS["battle-start"], action.point)

    def test_team_config_with_empty_slots_asks_for_auto_configure(self):
        """三队槽位还是空的 ⇒ 必须先点「自动配置」，不能直接开战。

        这正是 2026-09-22 实跑失败的根因：判据误判成「已配置」，
        跳过了自动配置，去点一个打不起来的「战斗开始」。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("team_config"))

        self.assertEqual("auto-configure", action.name)
        self.assertEqual(CLICK_POINTS["auto-configure"], action.point)

    def test_stamina_popup_does_not_click_the_button_behind_it(self):
        """体力弹窗期间只能买树叶，绝不能点弹窗背后的「战斗开始」。"""

        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("stamina_popup"))

        self.assertIn(action.name, {"stamina_material", "stamina_confirm"})
        self.assertNotEqual(CLICK_POINTS["battle-start"], action.point)

    def test_every_action_declares_its_source_page(self):
        """每个动作都必须声明出处，换页的动作还要声明去处（转场契约）。

        2026-09-22 首次实跑就是栽在这上面：动作只有 name+point，主循环没有任何依据
        判断「这一步该不该做」「做了到底生效没有」，于是在进配置队伍页的同一秒
        直接点了战斗开始，漏掉自动配置，队伍空着就开打。

        **同页动作**（点自动配置 / 买树叶）只声明 ``source_page``，不声明
        ``target_pages`` —— 目标页写本页的话，转场验收会永远通过，「验收」形同虚设。
        """
        machine = WorldBossStateMachine(TEMPLATES)
        expected = [
            ("worldboss_home", "世界首领战主页", ("选择辅助队伍",)),
            ("team_select", "选择辅助队伍", ("配置队伍",)),
            # 自动配置不换页：不声明 target_pages，验收靠按钮由橙转蓝。
            ("team_config", "配置队伍", ()),
            ("team_config_configured", "配置队伍", ("战斗中",)),
            ("battle_result", "战斗结算", ("战斗级别奖励",)),
            # 「全部开启」是同一按钮换字，同样不换页。
            ("level_reward", "战斗级别奖励", ()),
        ]

        for name, source_page, target_pages in expected:
            with self.subTest(page=name):
                action = machine.next_action(fixture(name))
                self.assertEqual(source_page, action.source_page)
                self.assertEqual(target_pages, action.target_pages)
                self.assertTrue(action.reason)
                # 契约要对账，靠的是状态机在发动作时写下「我站在这页」。
                self.assertEqual(source_page, machine._confirmed_page)

    def test_stamina_actions_declare_the_popup_as_source_page(self):
        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("stamina_popup"))

        self.assertEqual("行动力不足弹窗", action.source_page)
        # 弹窗内不换页 ⇒ 不声明 target_pages。
        self.assertEqual((), action.target_pages)
        self.assertEqual("行动力不足弹窗", machine._confirmed_page)

    def test_unrecognized_screen_clears_the_confirmed_page(self):
        """认不出画面时必须清掉对账依据，不能拿旧页面去比对下一帧。"""

        machine = WorldBossStateMachine(TEMPLATES)
        machine.next_action(fixture("worldboss_home"))
        self.assertEqual("世界首领战主页", machine._confirmed_page)

        with self.assertRaises(UnrecognizedScreen):
            machine.next_action(blank())

        self.assertEqual("", machine._confirmed_page)


class WorldBossRunnerTests(unittest.TestCase):
    def test_committed_battle_returns_control_to_result_state(self):
        machine = MagicMock()
        machine.state = WorldBossState.BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = WorldBossRunner(
            machine,
            Runtime(blank, lambda _: None),
            sleep=lambda _: None,
            battle_supervisor=supervisor,
        )

        runner._run_committed_battle(cycle=1)

        supervisor.run.assert_called_once_with(machine.observe_battle, cycle=1)
        self.assertEqual(WorldBossState.RESULT, machine.state)

    def test_stamina_popup_during_battle_hands_back_to_team_config(self):
        machine = MagicMock()
        machine.state = WorldBossState.BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.PRE_BATTLE_BUSINESS
        runner = WorldBossRunner(
            machine,
            Runtime(blank, lambda _: None),
            sleep=lambda _: None,
            battle_supervisor=supervisor,
        )

        runner._run_committed_battle(cycle=1)

        self.assertEqual(WorldBossState.TEAM_CONFIG, machine.state)

    def test_stamina_exhaustion_is_a_normal_resource_stop(self):
        machine = MagicMock()
        machine.state = WorldBossState.TEAM_CONFIG
        machine.completed_cycles = 0
        machine.preview.side_effect = StaminaExhausted("no leaves")
        runner = WorldBossRunner(
            machine,
            Runtime(blank, lambda _: None, emit=lambda _: None),
            sleep=lambda _: None,
        )

        completed = runner.run(max_cycles=3)

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)

    def test_failing_stamina_confirm_after_four_clicks_stops_as_resource_exhaustion(self):
        machine = MagicMock()
        machine.state = WorldBossState.TEAM_CONFIG
        machine.completed_cycles = 0
        action = WorldBossAction(
            "stamina_confirm",
            (1, 1),
            # ⚠️ 替身动作必须**照着真状态机的形状**造：本路线已打开转场契约机器强制
            # （``_REQUIRE_TRANSITION_CONTRACT``），只带名称与坐标的空洞动作会在
            # 发出去之前被拦下。这里补的判据与 ``_handle_stamina`` 里那条一致。
            source_page="行动力不足弹窗",
            in_page_evidence="购买完成后弹窗锚点消失、画面回到业务页",
        )
        machine.preview.return_value = (action, (WorldBossState.TEAM_CONFIG, 0))
        machine.next_action.return_value = action
        clicks = []
        runner = WorldBossRunner(
            machine,
            Runtime(blank, clicks.append, emit=lambda _: None),
            sleep=lambda _: None,
        )
        runner._ACTION_RETRY_SECONDS = 0

        completed = runner.run(max_cycles=1)

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)
        self.assertEqual(4, len(clicks))

    def test_exhausted_home_ends_the_run_without_a_single_click(self):
        """次数用完 ⇒ 主循环当场正常收场：退出码口径 2、**一次都不点**。

        「一直在点」的可见症状就落在最后一行的断言上：灰按钮连一下都不该点。
        用真状态机 + 真 Runner 跑，量的正是实跑那条路径。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runner = WorldBossRunner(
            machine,
            Runtime(
                lambda: fixture("worldboss_home_exhausted"),
                clicks.append,
                emit=logs.append,
            ),
            sleep=lambda _: None,
        )

        completed = runner.run(max_cycles=3)

        self.assertEqual(0, completed)
        self.assertTrue(
            runner.resource_exhausted,
            "次数用完是「没本钱了」的正常结论，不是故障（退出码应为 2）",
        )
        self.assertEqual([], clicks, f"灰按钮一下都不该点，实际点击 {clicks}")
        self.assertTrue(
            any("停止=今日次数已用完" in line for line in logs),
            f"日志要能一眼看出缺的是什么，实际 {logs}",
        )

    def test_running_out_of_attempts_logs_the_chest_scan_numbers(self):
        """真 Runner 跑一遍：日志里**必须**看得到宝箱扫描的实测数字。

        上面那条（``test_a_home_without_a_chest_reports_the_scan_...``）只证明
        「异常对象里带了数字」，这条证明**数字真的进了日志** —— 2026-09-25 23:01
        那次实跑缺的就是这一行，所以它要跑真主循环来守。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        logs: list[str] = []
        runner = WorldBossRunner(
            machine,
            Runtime(
                lambda: fixture("worldboss_home_exhausted"),
                lambda _point: None,
                emit=logs.append,
            ),
            sleep=lambda _: None,
        )

        runner.run(max_cycles=3)

        self.assertTrue(
            any("宝箱扫描" in line for line in logs),
            f"日志里必须留一条宝箱扫描结论，否则事后分不清「没得领」还是「漏判」，实际 {logs}",
        )

    def test_claiming_a_chest_that_never_goes_away_stops_after_bounded_tries(self):
        """宝箱点了不消失 ⇒ **有界撒手**，落到次数判断上正常收场 —— 绝不无限点。

        这是这条路线最容易踩的坑，2026-09-25 实跑又踩了一次：
        宝箱是**同页动作**，点完页面不变、判据也就没变，一旦「点了没生效」没有上限，
        就会变成「点 4 次 → 回大厅 → 重新导航进来 → 再点 4 次」的死循环 ——
        而当时局内已经 0/2、本该直接收场，却被排在更前面的宝箱分支拖住。

        现在的行为：**真的点了** ``WEEKLY_CHEST_MAX_CLICKS`` 次还在发光就**撒手**，
        让流程落到「选择队伍」那一步。这张图上次数是 0/2、按钮已灰 ⇒ 抛
        ``AttemptsExhausted`` ⇒ 正常收场（退出码口径 2），**不再**抛异常 + 回大厅重来。

        ⚠️ 计数挂在 Runner 的点击后钩子上，不是状态机里 —— 状态机在等重试窗口的那几秒
        里每帧都会被问一次，按它数会让「3 次」在第 2 次点击后就触发（本轮实测过）。

        帧序列一直停在「宝箱可领」的主页上 = 点了但箱子没消失。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        clock = _FakeClock([fixture("worldboss_home_chest_claimable")] * 60)
        with TemporaryDirectory() as directory:
            runner = WorldBossRunner(
                machine,
                Runtime(
                    clock.capture,
                    clicks.append,
                    emit=logs.append,
                    diagnostic_dir=Path(directory),
                    monotonic=lambda: clock.now,
                ),
                sleep=clock.sleep,
            )

            completed = runner.run(max_cycles=1)

        self.assertEqual(0, completed)
        self.assertEqual(
            [WorldBossWeeklyChestTests.CHEST_POINT] * WEEKLY_CHEST_MAX_CLICKS,
            clicks,
            f"宝箱连点 {WEEKLY_CHEST_MAX_CLICKS} 次还在发光就该撒手，实际点击 {clicks}",
        )
        self.assertTrue(
            runner.resource_exhausted,
            "撒手之后落到次数判断；这张图是 0/2 -> 正常收场（退出码 2）而不是故障",
        )
        self.assertTrue(
            any("停止=今日次数已用完" in line for line in logs),
            f"日志要能看出是「次数用完」收的场，实际 {logs}",
        )

    def test_claiming_the_chest_then_running_out_of_attempts_ends_the_cycle(self):
        """**整条链路**跑一遍真 Runner：宝箱领掉 ⇒ 判次数 ⇒ 一轮干净结束。

        这是用户 2026-09-23 那条要求的完整形态：「在进行第二把之前要先看有没有
        宝箱可领」，**领完宝箱才算一轮结束**。帧序列就是真机顺序：
        先「宝箱发光 + 0/2」，点掉之后换成「绿勾 + 0/2」那一张实拍图。

        ⚠️ 断言里最要紧的是**「只许点宝箱」**：整轮下来一次都不能碰到那颗灰掉的
        「选择队伍」（那正是用户反馈的「一直在点」）。
        宝箱本身允许点两下（3 秒短窗口内画面还没换完就再来一下），所以这里卡上界
        而不是等号 —— 卡等号等于在断言轮询节奏，不是断言行为。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        clock = _FakeClock(
            [fixture("worldboss_home_chest_claimable")] * 6
            + [fixture("worldboss_home_chest_claimed")] * 30
        )
        with TemporaryDirectory() as directory:
            runner = WorldBossRunner(
                machine,
                Runtime(
                    clock.capture,
                    clicks.append,
                    emit=logs.append,
                    diagnostic_dir=Path(directory),
                    monotonic=lambda: clock.now,
                ),
                sleep=clock.sleep,
            )

            completed = runner.run(max_cycles=3)

        self.assertEqual(0, completed)
        self.assertTrue(
            runner.resource_exhausted,
            "领完宝箱、次数又是 0/2 -> 这是「没本钱了」的正常结论（退出码 2），不是故障",
        )
        self.assertTrue(
            any("停止=今日次数已用完" in line for line in logs),
            f"日志要能一眼看出缺的是什么，实际 {logs}",
        )
        self.assertTrue(clicks, "宝箱该点，一下都没点说明根本没走到领宝箱这一步")
        self.assertLessEqual(
            len(clicks), 2, f"宝箱最多点两下（3 秒短窗口），实际 {clicks}"
        )
        self.assertEqual(
            {WorldBossWeeklyChestTests.CHEST_POINT},
            set(clicks),
            f"整轮只许点宝箱；点到别处（尤其灰掉的「选择队伍」）就是「一直在点」复发，"
            f"实际点击 {clicks}",
        )

    def test_reward_claim_second_click_waits_only_the_short_window(self):
        """领奖这一步的两下点击之间不能白等 45 秒。

        奖励弹窗点完「全部开启」后按钮**原地**变「确认」、页面**不换**（仍是
        ``LEVEL_REWARD``），所以状态机会再报一次同名动作 ``open-all-chests``。
        主循环对同名动作的默认等待是 ``_ACTION_RETRY_SECONDS``（45 秒）——
        2026-09-23 用户反馈的「干等 40 多秒」就是这一类。
        两个坐标只差 2px，第二下正好落在「确认」上，所以这里该用短窗口。

        用假时钟量「两次点击之间的间隔」，而不是断言某个常量 ——
        断言常量只能证明写了个数，证明不了主循环真的按它走。
        实测 **6.0 秒**（配置的 5 秒 + 主循环「两帧稳定」那道门占去的一帧，轮询 1 秒/帧）；
        修之前这个值是 **45 秒**。
        """

        machine = MagicMock()
        machine.state = WorldBossState.LEVEL_REWARD
        machine.completed_cycles = 0
        action = WorldBossAction(
            "open-all-chests",
            CLICK_POINTS["open-all-chests"],
            # 同上的替身契约：本路线开着机器强制，空洞动作发不出去。
            source_page=state_label(WorldBossState.LEVEL_REWARD),
            in_page_evidence="按钮原地由「全部开启」换成「确认」",
        )
        machine.preview.return_value = (action, (WorldBossState.LEVEL_REWARD, 0))
        machine.next_action.return_value = action

        clock = _FakeClock([fixture("level_reward")] * 12)

        clicks: list[tuple[tuple[int, int], float]] = []

        class _Enough(Exception):
            """内部哨兵：两下点击都发生了，停。"""

        def record(point: tuple[int, int]) -> None:
            clicks.append((point, clock.now))
            if len(clicks) == 2:
                raise _Enough

        runner = WorldBossRunner(
            machine,
            Runtime(
                clock.capture,
                record,
                emit=lambda _: None,
                monotonic=lambda: clock.now,
            ),
            sleep=clock.sleep,
        )

        with self.assertRaises(_Enough):
            runner.run(max_cycles=1)

        self.assertEqual(2, len(clicks))
        self.assertEqual(CLICK_POINTS["open-all-chests"], clicks[0][0])
        gap = clicks[1][1] - clicks[0][1]
        self.assertGreaterEqual(
            gap,
            runner._OPEN_ALL_CHESTS_RETRY_SECONDS,
            "不该比配置的窗口还早 —— 那说明根本没按配置走",
        )
        self.assertLessEqual(
            gap,
            10.0,
            f"两次「全部开启」之间等了 {gap} 秒"
            f"（默认窗口是 {runner._ACTION_RETRY_SECONDS} 秒，"
            "等于回到用户反馈的「干等 40 多秒」）",
        )

    def test_dry_run_on_home_reports_the_open_team_select_action(self):
        """空跑只拍一帧、只做一次识别，不进入轮询。

        空跑**不会真的点击**（``Runtime.click`` 在 dry_run 下只记日志），
        所以这里断言日志里的动作名，而不是点击回调。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runner = WorldBossRunner(
            machine,
            Runtime(
                lambda: fixture("worldboss_home"),
                clicks.append,
                dry_run=True,
                emit=logs.append,
            ),
            sleep=lambda _: None,
        )

        completed = runner.run(max_cycles=1)

        self.assertEqual(0, completed)
        self.assertEqual(WorldBossState.HOME, machine.state)
        self.assertEqual([], clicks)
        self.assertTrue(
            any("动作=open-team-select" in line for line in logs),
            f"空跑日志里应报出 open-team-select，实际 {logs}",
        )

    def test_dry_run_rejects_an_unrecognised_screen_without_polling(self):
        sleeps: list[float] = []
        with TemporaryDirectory() as directory:
            runner = WorldBossRunner(
                WorldBossStateMachine(TEMPLATES),
                Runtime(
                    blank,
                    lambda _: None,
                    dry_run=True,
                    diagnostic_dir=Path(directory),
                ),
                sleep=sleeps.append,
            )

            with self.assertRaisesRegex(RuntimeError, r"空跑未识别画面\[世界首领战主页\]"):
                runner.run(max_cycles=1)

        self.assertEqual([], sleeps)


class _FakeClock:
    """假时钟 + 帧游标：**一次 ``sleep`` = 前进一帧**（等价于一个轮询周期）。

    这样「画面随时间推进」和「时钟随时间推进」是同一个动作，符合真机语义：
    轮询一圈、拍一张新图。

    ``hold={下标: 次数}`` 让某个画面**多停留几个轮询周期** —— 主循环的同页
    重试窗口是 45 秒（``poll_seconds=1.0`` ⇒ 45 个周期），要让「重试一次」真的发生，
    当前画面就必须至少停留那么久。不写 ``hold`` 时每个画面只占一个周期。
    """

    def __init__(
        self, frames: list[np.ndarray], *, hold: dict[int, int] | None = None
    ) -> None:
        self.frames = frames
        self.hold = hold or {}
        self.now = 0.0
        self.index = 0
        self.remaining = self.hold.get(0, 1)

    @property
    def frame(self) -> int:
        return min(self.index, len(self.frames) - 1)

    def capture(self) -> np.ndarray:
        return self.frames[self.frame]

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.0)
        self.advance()

    def advance(self, frames: int = 1) -> None:
        for _ in range(frames):
            self.remaining -= 1
            if self.remaining > 0:
                continue
            self.index = min(self.index + 1, len(self.frames) - 1)
            self.remaining = self.hold.get(self.index, 1)


class WorldBossTeamConfigTwoStageTests(unittest.TestCase):
    """配置队伍页必须走「先自动配置、验收通过、再战斗开始」。

    2026-09-22 首次实跑就是在这里栽的：进页同一秒直接点了战斗开始。
    下面用**真状态机 + 真 Runner**跑一遍完整流程，守住这个顺序。

    战斗入口与竞技场同构（``ArenaRunner`` 也是 ``_BATTLE_ENTRY_ACTION="battle-start"``
    + 默认 ``_CLICK_BEFORE_BATTLE=True``）：主循环点「战斗开始」，点完**立刻**
    把这一局交给 ``BattleSupervisor``，由监督一路跟到结算页。
    转场契约（``target_pages=(战斗中,)``）保证「点了没生效」能被看出来。
    """

    @staticmethod
    def _runner_with_frames(
        frames: list[np.ndarray],
        clicks: list[tuple[int, int]],
        *,
        diagnostics: str | None = None,
        supervisor_outcome: BattleOutcome = BattleOutcome.RESULT_REACHED,
        hold: dict[int, int] | None = None,
    ) -> tuple[WorldBossRunner, MagicMock, _FakeClock]:
        """真状态机 + 真 Runner，按帧序列喂画面；监督由 MagicMock 记录其点击后放行。

        监督的 ``run`` 直接返回 ``supervisor_outcome`` —— 默认 ``RESULT_REACHED``
        表示这一局正常打到结算；``PRE_BATTLE_BUSINESS`` 表示监督发现战前业务页
        （体力弹窗）开着、把控制权交还业务状态机。

        ⚠️ **必须喂假时钟**：Runner 的 ``self.now`` 是 ``runtime.now``（默认
        ``time.monotonic``）。如果让时钟走真时间，测试里 ``sleep`` 只是瞬间推进
        帧下标、真时间几乎不动，于是「同页重试窗口 45 秒」和「状态超时 45 秒」
        都永远到不了 —— 帧序列取完后 ``capture`` 一帧帧地喂同一张图，
        主循环会**无限循环**（2026-09-22 的死循环就是这么在测试里挂住的）。
        （同类写法见 ``test_navigation.py::clocked_navigator``。）
        """

        clock = _FakeClock(frames, hold=hold)
        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.TEAM_CONFIG
        supervisor = MagicMock()
        supervisor.run.side_effect = lambda *_, **__: supervisor_outcome
        runner = WorldBossRunner(
            machine,
            Runtime(
                clock.capture,
                clicks.append,
                emit=lambda _: None,
                diagnostic_dir=Path(diagnostics) if diagnostics else None,
                monotonic=lambda: clock.now,
            ),
            sleep=clock.sleep,
            battle_supervisor=supervisor,
        )
        # ⚠️ 重试窗口**不能**清零：被清零时「同页动作的重试间隔」恒为 0，
        # 4 次尝试会在 4 帧内烧光，等不到「画面第三次变蓝」——那正是本组要验的行为。
        # 用真实窗口（45 秒）+ `poll_seconds=1.0`，等于「每 45 帧才允许重试一次」，
        # 帧序列按这个节奏排即可（见各用例的注释）。
        return runner, supervisor, clock

    @classmethod
    def _run_until_handoff(
        cls, frames: list[np.ndarray], clicks: list[tuple[int, int]], **kwargs
    ) -> tuple[WorldBossRunner, list[int], _FakeClock]:
        """喂到「控制权刚交给战斗监督」为止就停 —— 不把监督那一段跑下去。

        做法：监督的 ``run`` **只记录调用、不返回**，直接抛一个哨兵异常把
        ``runner.run()`` 掀掉。这样主循环不会越过移交点继续跑
        （否则 mock 的立即返回会让状态机把「结算」当既成事实，
        接着又拿配置页的帧去重判，产生一串假的 ``battle-start`` 点击）。
        终局行为交给专门的用例去测。

        返回的第二个值是「移交次数」列表（长度为 1 表示恰好移交一次）。
        """

        class _HandedOff(Exception):
            """内部哨兵：控制权已到监督手里。"""

        runner, supervisor, clock = cls._runner_with_frames(frames, clicks, **kwargs)
        handoffs: list[int] = []

        def _hand_off(*_args, **_kw):
            handoffs.append(1)
            raise _HandedOff

        supervisor.run.side_effect = _hand_off
        try:
            runner.run(max_cycles=1)
        except _HandedOff:
            pass
        else:
            raise AssertionError("帧序列已喂完但战斗监督始终没被移交")
        return runner, handoffs, clock

    def test_auto_configure_runs_before_battle_start(self):
        """橙帧 → 必须先点自动配置；转蓝后点战斗开始；点完即移交监督。

        帧序列按「一次 sleep = 一帧」排，并用 ``hold`` 让橙色页停留足够久
        （超过一个 45 秒重试窗口，所以自动配置会被点两次 —— 这正是
        「按一次、验收一次」：还是橙就再来一次）：
        橙①（点自动配置 ×2）→ 蓝②（两帧稳定 → 点战斗开始）→ 战斗③（移交监督）。
        """

        clicks: list[tuple[int, int]] = []
        frames = [
            fixture("team_config"),  # ① 橙：还没配
            fixture("team_config_configured"),  # ② 蓝：配完了
            fixture("battle"),  # ③ 战斗画面 = 出口标志
        ]
        with TemporaryDirectory() as directory:
            runner, handoffs, _ = self._run_until_handoff(
                frames, clicks, diagnostics=directory, hold={0: 60, 1: 4, 2: 2}
            )

        auto_point = CLICK_POINTS["auto-configure"]
        battle_point = CLICK_POINTS["battle-start"]
        self.assertEqual(
            [auto_point, auto_point, battle_point],
            clicks,
            f"必须「先自动配置（未生效就重试）、再战斗开始」，实际点击 {clicks}",
        )
        self.assertEqual(1, len(handoffs), "战斗监督应恰好被移交一次")

    def test_battle_start_declares_the_battle_page_as_its_target(self):
        """「战斗开始」必须声明 ``target_pages=(战斗中,)`` —— 出口标志。

        没有它，主循环点完就盲目往下走，分不出「点了没生效」和「点了生效了」。
        同时也是 ``observe_page`` 必须能认出战斗画面的理由
        （目标页要真认得出来，这个契约才有意义）。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.TEAM_CONFIG

        action = machine.preview(fixture("team_config_configured"))[0]

        self.assertEqual("battle-start", action.name)
        self.assertEqual(
            (state_label(WorldBossState.BATTLE),),
            action.target_pages,
            "「战斗开始」必须声明落点是战斗中，否则转场验收无从谈起",
        )
        # 落点必须真认得出：拿战斗画面过一遍状态机，得判成 BATTLE。
        self.assertEqual(
            WorldBossState.BATTLE,
            machine.observe_page(fixture("battle")),
            "战斗画面必须被识别成 BATTLE，否则 target_pages 是空头支票",
        )

    def test_battle_page_confirms_itself_so_the_transition_can_close(self):
        """认出战斗画面时必须 ``_confirm_page`` —— 否则 ``target_pages`` 永远匹配不上。

        主循环是在**拍完这一帧、调 next_action 之前**读 ``_confirmed_page`` 的，
        所以「我现在站在战斗中」必须被这一帧写下来，下一帧才读得到「已到达目标页」。
        不写的话 ``_confirmed_page`` 一直停在上一个动作的 source_page（配置队伍）
        ⇒ 契约空转 ⇒ 45 秒后走「转场超时」。

        ⚠️ 只断言 ``target_pages`` 里写了「战斗中」是不够的（见上一个用例）——
        那只能证明**声明**了落点，证明不了落点**真会被确认**。这个用例补的就是后者。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.TEAM_CONFIG

        action = machine.next_action(fixture("team_config_configured"))
        self.assertEqual("battle-start", action.name)
        self.assertNotIn(
            state_label(WorldBossState.BATTLE),
            (machine._confirmed_page,),
            "还没看到战斗画面，不该已经确认成战斗中",
        )

        # 游戏推进到战斗画面：这一帧必须把「战斗中」写成已确认页面。
        machine.next_action(fixture("battle"))
        self.assertEqual(
            state_label(WorldBossState.BATTLE),
            machine._confirmed_page,
            "认出战斗画面后必须 _confirm_page(战斗中)，否则转场契约永远不成立",
        )
        self.assertIn(
            machine._confirmed_page,
            action.target_pages,
            "已确认页面必须落在 battle-start 声明的 target_pages 里，契约才闭合",
        )

    def test_blue_button_never_clicks_auto_configure_again(self):
        """按钮已转蓝时不许重复点自动配置（避免无意义的重复动作）。"""

        clicks: list[tuple[int, int]] = []
        with TemporaryDirectory() as directory:
            runner, handoffs, _ = self._run_until_handoff(
                [fixture("team_config_configured"), fixture("battle")],
                clicks,
                diagnostics=directory,
                hold={0: 4, 1: 2},
            )

        self.assertNotIn(CLICK_POINTS["auto-configure"], clicks)
        self.assertIn(CLICK_POINTS["battle-start"], clicks)
        self.assertEqual(1, len(handoffs))

    def test_orange_button_retries_auto_configure_until_it_turns_blue(self):
        """自动配置**按一次验收一次**：还是橙就重试，转蓝才推进。

        橙色页停满**两个**重试窗口 ⇒ 自动配置要被点两次；画面转蓝后不再点它，
        只点战斗开始。这守住「不换页动作靠按钮颜色验收」，而不是靠 target_pages 空转。
        """

        clicks: list[tuple[int, int]] = []
        frames = [
            fixture("team_config"),  # 持续为橙 —— 需要反复重试
            fixture("team_config_configured"),  # 终于转蓝
            fixture("battle"),
        ]
        with TemporaryDirectory() as directory:
            runner, handoffs, clock = self._run_until_handoff(
                frames, clicks, diagnostics=directory, hold={0: 60, 1: 4, 2: 2}
            )

        auto_point = CLICK_POINTS["auto-configure"]
        battle_point = CLICK_POINTS["battle-start"]
        # 橙色期间至少重试过一次自动配置；转蓝后**不再**点自动配置，只点战斗开始。
        self.assertGreaterEqual(clicks.count(auto_point), 2, f"实际点击 {clicks}")
        self.assertIn(battle_point, clicks, f"实际点击 {clicks}")
        last_auto = len(clicks) - 1 - clicks[::-1].index(auto_point)
        self.assertLess(
            last_auto,
            clicks.index(battle_point),
            f"自动配置的重试必须都发生在点战斗开始之前，实际点击 {clicks}",
        )
        # 假时钟真的被推进过：说明「重试窗口」是靠时间等出来的，
        # 而不是靠帧下标碰巧走到（那样测试会假绿）。
        self.assertGreater(clock.now, 0.0)
        self.assertEqual(1, len(handoffs))

    def test_battle_start_without_battle_screen_stops_after_bounded_retries(self):
        """点了战斗开始但战斗画面始终不出现 ⇒ 有界重试后安全停止，**绝不无限重交**。

        这是 2026-09-22 的死循环回归：修复前监督交还 → 主循环又移交，
        实测交了 199 次都停不下来。现在必须有**明确上限**并走安全停止。

        帧序列一直停在「蓝按钮的配置队伍页」= 点了战斗开始但画面毫无变化
        （战斗监督发现打不起来、把控制权交还，回到配置队伍页），如此循环。
        """

        clicks: list[tuple[int, int]] = []
        with TemporaryDirectory() as directory:
            runner, supervisor, clock = self._runner_with_frames(
                [fixture("team_config_configured")] * 40,
                clicks,
                diagnostics=directory,
                supervisor_outcome=BattleOutcome.PRE_BATTLE_BUSINESS,
            )
            with self.assertRaises(RuntimeError) as caught:
                runner.run(max_cycles=1)

        message = str(caught.exception)
        # 终局必须是「点了几次都没进战斗」这个业务结论，而不是「点击 4 次没转场」
        # 这种兜底错误 —— 前者说明程序知道自己在等什么。
        self.assertIn("仍未进入战斗", message)
        # 关键断言：移交次数必须被**上限**截住，而不是无限循环。
        self.assertLessEqual(
            supervisor.run.call_count,
            runner._MAX_BATTLE_ATTEMPTS + 1,
            f"战斗监督最多被移交 {runner._MAX_BATTLE_ATTEMPTS + 1} 次，"
            f"实际 {supervisor.run.call_count} 次（说明仍在无限重交）",
        )
        self.assertGreater(clock.now, 0.0)


class WorldBossBattleScreenTests(unittest.TestCase):
    """战斗画面识别 + 右上角「跳过」的回归测试。

    2026-09-22 20:57 实跑报错「战斗画面持续无法识别超时」的真因：世界首领战的战斗
    画面是**团本布局**（左上 boss 名 + 血条、右上 跳过/聊天/暂停、右侧 12 人分数列），
    旧判据 ``battle_controls.battle_scene_visible``（4 格底座 + 左侧行动顺序）在它上面
    **恒为 False** ⇒ 监督 ``recognized`` 连续 45 秒为假 ⇒ 安全停止。

    修法两条腿：① 右上角「跳过」当识别锚点；② 命中时把 ``("skip-battle", 点)``
    交给监督点掉，很快就衔接到结算页。
    """

    #: 「跳过 」的实测点击中心（画布坐标）。用户 1920×1080 实拍截图按
    #: ``core/window.py::_legacy_canvas`` 的 (0,+52) 偏移还原后量的亮像素包围盒中心。
    SKIP_POINT = (1631, 97)

    def test_live_battle_frame_is_recognised_as_the_battle_page(self):
        machine = WorldBossStateMachine(TEMPLATES)

        self.assertIs(
            WorldBossState.BATTLE, machine.observe_page(fixture("battle_live_skip"))
        )

    def test_old_detector_alone_misses_the_live_battle_frame(self):
        """守根因：**只看旧判据认不出这一屏** —— 这正是必须新增锚点的理由。

        哪天这个断言不再成立（``battle_scene_visible`` 变 True），说明底层判据被改过，
        上面那条「新增锚点」的注释与文档就得跟着复核。
        """

        template = WorldBossStateMachine(TEMPLATES).templates.battle_skip
        screen = fixture("battle_live_skip")

        self.assertFalse(
            battle_scene_visible(screen),
            "旧判据若能认出团本战斗画面，就不必新增「跳过」锚点了",
        )
        self.assertTrue(world_boss_battle_visible(screen, template))
        self.assertIsNotNone(find_world_boss_skip(screen, template))

    def test_skip_anchor_click_point_is_the_measured_button_centre(self):
        """命中点必须落在实测的那颗按钮上 —— 偏差大了就会点空。"""

        template = WorldBossStateMachine(TEMPLATES).templates.battle_skip
        match = find_world_boss_skip(fixture("battle_live_skip"), template)

        self.assertIsNotNone(match)
        self.assertLessEqual(abs(match.center[0] - self.SKIP_POINT[0]), 3)
        self.assertLessEqual(abs(match.center[1] - self.SKIP_POINT[1]), 3)
        self.assertGreater(match.score, BATTLE_SKIP_THRESHOLD)

    def test_observe_battle_offers_the_skip_action(self):
        """战斗帧上要把「跳过」作为允许动作报出去，监督才有得点。"""

        machine = WorldBossStateMachine(TEMPLATES)

        observation = machine.observe_battle(fixture("battle_live_skip"), None)

        self.assertTrue(observation.battle_visible)
        self.assertIsNotNone(observation.allowed_action)
        name, point = observation.allowed_action
        self.assertEqual("skip-battle", name)
        self.assertLessEqual(abs(point[0] - self.SKIP_POINT[0]), 3)
        self.assertLessEqual(abs(point[1] - self.SKIP_POINT[1]), 3)

    def test_skill_animation_frame_is_deliberately_unrecognised(self):
        """boss 技能演出会整块隐藏 UI ⇒ 认不出是**预期行为**，不是漏判。

        演出只有几秒，下一帧 UI 回来就重新认到，45 秒看门狗靠这个复位。
        别为了让这张帧也认出来，去给演出画面单独做锚点 —— 那种锚点会咬到场景美术。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        observation = machine.observe_battle(fixture("battle_skill_anim"), None)

        self.assertFalse(observation.battle_visible)
        self.assertIsNone(
            observation.allowed_action,
            "演出帧上不该报出跳过动作（这时候按钮根本不在画面上）",
        )

    def test_no_other_world_boss_page_is_mistaken_for_a_battle(self):
        """本路线其它页一张都不许被判成「战斗中」。

        误判的后果很重：监督会以为战斗已经开始，然后一路空等到 900 秒绝对超时。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        pages = (
            "worldboss_home",
            "worldboss_home_exhausted",
            "team_select",
            "team_config",
            "team_config_configured",
            "stamina_popup",
            "battle_result",
            "level_reward",
            "knights_home",
            "knights_home_after_popup",
            "knights_signin_popup",
            "gift_support_popup",
            "lobby_with_knights",
        )

        for name in pages:
            with self.subTest(page=name):
                self.assertFalse(
                    machine.battle_visible(fixture(name)),
                    f"{name} 被误判成战斗画面",
                )

    def test_supervisor_clicks_the_skip_button_then_returns_on_the_result(self):
        """「跳过」不能只报在观察结果里，必须由监督真的点出去。

        帧序列：战斗②帧（连续 2 帧稳定才允许点）→ 结算②帧（连续 2 帧才算到结算）。
        一次 ``sleep`` = 一帧。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.BATTLE
        clock = _FakeClock(
            [
                fixture("battle_live_skip"),
                fixture("battle_live_skip"),
                fixture("battle_result"),
                fixture("battle_result"),
            ]
        )
        clicks: list[tuple[int, int]] = []
        runner = WorldBossRunner(
            machine,
            Runtime(
                clock.capture,
                clicks.append,
                emit=lambda _: None,
                monotonic=lambda: clock.now,
            ),
            sleep=clock.sleep,
        )

        outcome = runner._run_committed_battle(cycle=1)

        self.assertIs(BattleOutcome.RESULT_REACHED, outcome)
        self.assertEqual(
            [self.SKIP_POINT], clicks, f"应恰好点一次「跳过」，实际点击 {clicks}"
        )
        self.assertEqual(WorldBossState.RESULT, machine.state)

    def test_level_reward_popup_counts_as_the_battle_being_over(self):
        """奖励弹窗出现 = 战斗已经结束，观察结果必须这么报。

        2026-09-23 实跑的第二处断点：点完「跳过」游戏**直接**弹出「战斗级别奖励」
        弹窗（弹窗把结算页压暗），于是 ``result_title`` 掉到 0.7103、``battle_visible``
        也 False、``allowed_action`` 为 None ⇒ 监督 ``recognized`` 五条全假 ⇒
        45 秒后 ``battle_unrecognized`` 安全停止，后面的领奖一步都没走到。

        奖励弹窗必须被算成「战斗结束」，监督才会及时把业务交还给状态机。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        observation = machine.observe_battle(fixture("level_reward"), None)

        self.assertTrue(
            observation.result_visible,
            "奖励弹窗出现即「战斗结束」，否则监督认不出这一屏、只能等到超时",
        )
        self.assertFalse(observation.battle_visible)

    def test_result_page_alone_still_counts_as_the_battle_being_over(self):
        """反向补齐：没有弹窗的纯结算页当然也要算「战斗结束」（原有行为不回退）。"""

        machine = WorldBossStateMachine(TEMPLATES)

        self.assertTrue(
            machine.observe_battle(fixture("battle_result"), None).result_visible
        )

    def test_battle_frame_is_not_reported_as_battle_over(self):
        """正在打的战斗画面**不许**被判成「战斗结束」。

        误判的后果是监督提前交还业务，主循环会在战斗还没结束时就去点结算页上的
        「确认」—— 等于跳到战斗前面去。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        observation = machine.observe_battle(fixture("battle_live_skip"), None)

        self.assertTrue(observation.battle_visible)
        self.assertFalse(observation.result_visible)

    def test_skip_then_level_reward_popup_hands_the_business_back(self):
        """实跑路径「点跳过 → 直接弹奖励弹窗」必须由监督交还业务，且业务接得上。

        帧序列：战斗②帧（连续 2 帧稳定才允许点跳过）→ 奖励弹窗②帧（连续 2 帧才算
        到结算）。一次 ``sleep`` = 一帧。

        这是 2026-09-23 实跑的完整回归：那天断在「监督不认这一屏」，
        奖励领不到、最后以 ``battle_unrecognized`` 报错收场。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.BATTLE
        clock = _FakeClock(
            [
                fixture("battle_live_skip"),
                fixture("battle_live_skip"),
                fixture("level_reward"),
                fixture("level_reward"),
            ]
        )
        clicks: list[tuple[int, int]] = []
        runner = WorldBossRunner(
            machine,
            Runtime(
                clock.capture,
                clicks.append,
                emit=lambda _: None,
                monotonic=lambda: clock.now,
            ),
            sleep=clock.sleep,
        )

        outcome = runner._run_committed_battle(cycle=1)

        self.assertIs(BattleOutcome.RESULT_REACHED, outcome)
        self.assertEqual(
            [self.SKIP_POINT], clicks, f"应恰好点一次「跳过」，实际点击 {clicks}"
        )
        self.assertEqual(WorldBossState.RESULT, machine.state)

        # 交还之后状态机要能自己接上：认得出奖励弹窗、给得出领奖动作。
        action = machine.next_action(fixture("level_reward"))
        self.assertIsNotNone(action)
        self.assertEqual("open-all-chests", action.name)
        self.assertEqual(WorldBossState.LEVEL_REWARD, machine.state)

    def test_skip_anchor_window_stays_left_of_the_story_skip_button(self):
        """搜索窗口必须把剧情播放页的「跳过」挡在门外。

        同一个「跳过 」图形剧情播放页也有，只是位置更靠右（x≈1769~1886）。
        窗口一旦放宽到盖住那一带，锚点分就只剩 0.05 的间距（实测 0.9086 vs 0.8585），
        等于把「是不是战斗画面」变成赌注。
        """

        x, _, width, _ = BATTLE_SKIP_REGION
        half = WorldBossStateMachine(TEMPLATES).templates.battle_skip.shape[1] // 2

        self.assertLessEqual(x + width, 1760, "搜索区右边界要留在剧情页的跳过左侧")
        # 模板必须能整个放进窗口，且实测的那颗按钮在窗口正中一带：
        # 匹配器把模板完整放在窗口内，中心落在 [x+half, x+width-half]。
        self.assertLessEqual(x + half, self.SKIP_POINT[0])
        self.assertLessEqual(self.SKIP_POINT[0], x + width - half)


class WorldBossTransitionContractTests(unittest.TestCase):
    """转场契约：本路线的每个动作在发出去之前都必须「长眼睛」。

    这是继 ``knights_donation`` 之后第二条打开 ``_REQUIRE_TRANSITION_CONTRACT`` 的路线。
    打开之前它是「动作看起来都带判据、机器却问不出来」的状态：换页动作带 ``target_pages``，
    5 个同页动作的验收依据写在 ``next_action`` 的代码里、**没登记成字段** ⇒ 漏写不报错。

    ⚠️ **开这个开关不能靠静态印象**（2026-09-24 实测教训）：当时看代码觉得「``source_page``
    全有、换页动作都带 ``target_pages``」，一度以为打开只是纯加固；真跑一遍才发现
    ``WorldBossAction`` **连 ``in_page_evidence`` 字段都没有**，而校验规则是
    「``target_pages`` **或** ``in_page_evidence``」—— 规则里那个备选项根本不存在，
    5 个同页动作一开全被拦。第一条用例就是把这件事钉住。
    """

    # 真状态机 + 真夹具能走出来的全部动作（换页 5 + 同页 5）。
    # 第三列是「喂这一帧之前要先把状态拨到哪」，``None`` = 用默认状态。
    CASES = (
        ("worldboss_home", "open-team-select", None),
        ("worldboss_home_chest_claimable", "claim-weekly-chest", None),
        ("team_select", "build-team", None),
        ("team_config", "auto-configure", None),
        ("team_config_configured", "battle-start", None),
        ("battle_result", "open-level-reward", None),
        ("battle_result", "confirm-result", WorldBossState.LEVEL_REWARD),
        ("level_reward", "open-all-chests", None),
        ("stamina_popup", "stamina_material", None),
    )

    @staticmethod
    def _runner(machine: WorldBossStateMachine | None = None) -> WorldBossRunner:
        return WorldBossRunner(
            machine if machine is not None else WorldBossStateMachine(TEMPLATES),
            Runtime(blank, lambda _: None, emit=lambda _: None),
            sleep=lambda _: None,
        )

    def test_the_switch_is_on(self):
        self.assertIs(True, self._runner()._REQUIRE_TRANSITION_CONTRACT)

    def test_a_blind_action_is_refused(self):
        """没有判据的动作**在点下去之前**就被拦 —— 空跑同样会拦。"""
        runner = self._runner()

        with self.assertRaisesRegex(RuntimeError, "缺少转场契约"):
            runner._require_transition_contract(WorldBossAction("blind", (1, 1)))
        with self.assertRaisesRegex(RuntimeError, "缺少转场契约"):
            runner._require_transition_contract(
                WorldBossAction("no-exit", (1, 1), source_page="某页")
            )

    def test_every_action_in_the_route_carries_its_own_evidence(self):
        """真状态机走一遍，10 个动作逐个过契约 —— 少一个判据就红。"""
        runner = self._runner()

        for name, expected, state in self.CASES:
            with self.subTest(fixture=name, action=expected):
                machine = WorldBossStateMachine(TEMPLATES)
                if state is not None:
                    machine.state = state

                action = machine.next_action(fixture(name))

                self.assertIsNotNone(action, f"{name} 上认不出页面了")
                self.assertEqual(expected, action.name)
                self.assertTrue(
                    action.target_pages or action.in_page_evidence,
                    f"{expected} 既没声明 target_pages 也没声明 in_page_evidence",
                )
                runner._require_transition_contract(action)

    def test_the_stamina_confirm_step_also_carries_evidence(self):
        """体力弹窗第二步（点「确认购买」）—— 同页动作，只能靠 ``in_page_evidence``。

        它是唯一没法喂单独一帧就拿到的动作：要先让状态机把「选材料」那步走掉
        （``_stamina_material_clicked`` 置位后，同一个弹窗报出的就变成确认）。
        """
        machine = WorldBossStateMachine(TEMPLATES)

        first = machine.next_action(fixture("stamina_popup"))
        self.assertEqual("stamina_material", first.name)

        second = machine.next_action(fixture("stamina_popup"))
        self.assertEqual("stamina_confirm", second.name)
        self.assertEqual("行动力不足弹窗", second.source_page)
        self.assertTrue(second.in_page_evidence)
        self._runner(machine)._require_transition_contract(second)


if __name__ == "__main__":
    unittest.main()
