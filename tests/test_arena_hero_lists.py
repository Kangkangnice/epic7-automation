"""竞技场「英雄黑名单 / 白名单」：筛选口径 + 识别层回归（2026-11-15）。

三层：

1. **口径**（``hero_match.judge_row``）：纯函数，喂识别结果与两份名单，问「这一行留不留」。
   默认黑名单优先；两边都命中时按 ``hero_list_conflict`` 处置。
2. **识别**（``HeroMatcher``）：真帧上必须认出该认的，并且**弱证据必须被拒**——
   同一页里有一行只拿到 good=15，它必须报「认不出」而不是猜一个名字。
3. **有界收尾**：整页都被名单否掉时不允许无限刷新，连续若干页后按正常业务退出。

⚠️ 识别层依赖图鉴库（``templates/arena/heroes_pokedex``，11 MB）。库在打包时随
``datas`` 一起收；本地缺失时这一组跳过，而不是把「认不出」当通过。
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from auto_game_unified.games.epic7.arena import (
    ArenaRunner,
    ArenaStateMachine,
    NoEligibleOpponent,
    build_templates,
)
from auto_game_unified.games.epic7.hero_match import (
    TIER_NORMAL,
    TIER_OUT,
    TIER_WHITE,
    HeroMatcher,
    OpponentTeam,
    default_library_dir,
    library_names,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"

HAS_LIBRARY = default_library_dir().is_dir() and bool(
    library_names(default_library_dir())
)
NEEDS_LIBRARY = unittest.skipUnless(
    HAS_LIBRARY, "缺少图鉴库（templates/arena/heroes_pokedex）"
)


def load_frame(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    return cv2.cvtColor(image[:1132, :1982], cv2.COLOR_BGR2RGB)


def team(index: int, heroes: list[str], unknown: int = 0) -> OpponentTeam:
    return OpponentTeam(index=index, heroes=heroes, unknown=unknown)


class JudgeRowTests(unittest.TestCase):
    """口径：这一行进白名单优先组、普通组，还是出局。"""

    def judge(self, heroes, *, black, white, conflict="blacklist"):
        from auto_game_unified.games.epic7.hero_match import judge_row

        return judge_row(
            team(0, heroes),
            blacklist=set(black),
            whitelist=set(white),
            conflict=conflict,
        )

    def test_black_hit_eliminates_the_row(self):
        verdict = self.judge(["A", "B"], black={"A"}, white=set())
        self.assertEqual(TIER_OUT, verdict.tier)
        self.assertIn("命中避战名单", verdict.reason)

    def test_white_hit_puts_the_row_in_the_priority_group(self):
        verdict = self.judge(["A", "B"], black=set(), white={"B"})
        self.assertEqual(TIER_WHITE, verdict.tier)

    def test_no_hit_at_all_falls_back_to_the_normal_group(self):
        """⚠️ 这是本次纠正的核心：白名单没命中 **不是出局**，只是不优先。"""
        verdict = self.judge(["A", "B"], black={"X"}, white={"Y"})
        self.assertEqual(TIER_NORMAL, verdict.tier)
        self.assertTrue(verdict.keep)

    def test_more_white_than_black_goes_with_the_whitelist(self):
        verdict = self.judge(["A", "B", "C"], black={"A"}, white={"B", "C"})
        self.assertEqual(TIER_WHITE, verdict.tier)
        self.assertIn("优先命中更多", verdict.reason)

    def test_more_black_than_white_is_eliminated(self):
        verdict = self.judge(["A", "B", "C"], black={"A", "C"}, white={"B"})
        self.assertEqual(TIER_OUT, verdict.tier)
        self.assertIn("避战命中更多", verdict.reason)

    def test_equal_counts_follow_the_setting(self):
        skipped = self.judge(["A", "B"], black={"A"}, white={"B"})
        self.assertEqual(TIER_OUT, skipped.tier)
        self.assertIn("按设置跳过", skipped.reason)
        kept = self.judge(["A", "B"], black={"A"}, white={"B"}, conflict="whitelist")
        self.assertEqual(TIER_WHITE, kept.tier)
        self.assertIn("按设置照打", kept.reason)

    def test_unrecognised_team_falls_back_to_the_normal_group(self):
        """四个头像全认不出 = 两边都没命中，进普通组（白名单只是偏好）。"""
        self.assertEqual(TIER_NORMAL, self.judge([], black={"X"}, white={"Y"}).tier)

    def test_no_lists_means_no_filtering(self):
        self.assertEqual(TIER_NORMAL, self.judge(["A"], black=set(), white=set()).tier)


@NEEDS_LIBRARY
class RecognitionTests(unittest.TestCase):
    """识别层：真帧上该认的认出、弱证据不许猜。"""

    # 这一页实际出现的英雄。
    # ⚠️ 2026-11-17 修正：原记录是「2026-11-15 用 354 模板全量比对确认」，但当时库里的
    # 「安洁莉卡.png」并不是安洁莉卡本人（与该英雄官方头像 ORB 内点 0），所以行 2 列 1、
    # 行 3 列 2 两个格子被漏认。换成官方头像后，这两格对安洁莉卡模板 good=167/179、
    # 内点 163/172、第二名仅 6/8，裁图目视也确认是同一人（粉发编发蓝眼）。
    # 因此阵容以本文件为准，旧期望已订正。
    KNOWN = ["维多丽卡", "安洁莉卡", "蒙茉朗西", "泰妮布里雅", "卡麦萝兹", "克劳蒂亚"]

    def test_recorded_list_page_is_recognised(self):
        matcher = HeroMatcher(default_library_dir(), self.KNOWN)
        self.assertEqual([], matcher.missing_names)
        teams = matcher.identify_screen(load_frame("list"))

        self.assertIn("维多丽卡", teams[0].heroes)
        self.assertEqual({"安洁莉卡", "维多丽卡", "蒙茉朗西", "泰妮布里雅"}, set(teams[1].heroes))
        self.assertEqual({"安洁莉卡", "维多丽卡", "卡麦萝兹", "克劳蒂亚"}, set(teams[2].heroes))
        # 第 1 行只有一名英雄，其余三个槽位是空的。
        self.assertEqual(3, teams[0].unknown)

    def test_empty_slots_are_not_guessed(self):
        """空槽位不许被猜成任何英雄。

        ⚠️ 本条原先是「good=15 的安洁莉卡不许命中」，那是旧模板下的弱证据案例；
        换官方头像后同一格变成强命中（内点 163），原前提已不存在。
        改为盯空槽：第 1 行除首格外三个槽位都无人，必须全部计入 unknown。
        """
        matcher = HeroMatcher(default_library_dir(), self.KNOWN)
        teams = matcher.identify_screen(load_frame("list"))
        self.assertEqual(3, teams[0].unknown)
        self.assertEqual({"维多丽卡"}, set(teams[0].heroes))

    def test_screen_cache_keeps_the_same_verdict_for_the_same_frame(self):
        """同一帧只识别一次：主循环每秒都问，重复识别会拖慢整条路线。"""
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        runtime = _FakeRuntime()
        runner = ArenaRunner(
            machine,
            runtime,  # type: ignore[arg-type]
            hero_blacklist=["维多丽卡"],
        )
        matcher = runner._hero_matcher
        calls: list[np.ndarray] = []
        original = matcher.identify_screen

        def spy(screen: np.ndarray):
            calls.append(screen)
            return original(screen)

        matcher.identify_screen = spy  # type: ignore[method-assign]
        frame = load_frame("list")
        runner.machine.opponent_filter(frame, [0, 1, 2])
        runner.machine.opponent_filter(frame, [0, 1, 2])
        self.assertEqual(1, len(calls))
        # 这一页三名对手**都**带了维多丽卡（实测并排比对：同一名英雄），
        # 所以黑名单把它排除之后整页无可用行 —— 正好也是「整页被否掉」那一路。
        self.assertEqual([], list(runner.machine.opponent_filter(frame, [0, 1, 2])))


    def test_more_whitelist_hits_beat_fewer_even_with_worse_points(self):
        """白名单组内先比命中数：命中两名的队排在命中一名的队前面，哪怕积分更低。"""
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        runner = ArenaRunner(
            machine,
            _FakeRuntime(),  # type: ignore[arg-type]
            hero_whitelist=["维多丽卡", "蒙茉朗西"],
            opponent_preference="highest",
        )
        # ⚠️ 名单里的名字必须真实存在于图鉴库，否则识别器加载不到模板、
        # 过滤器根本不会挂上（那样就不是在测排序了）。
        teams = [
            OpponentTeam(index=0, heroes=["维多丽卡"]),
            OpponentTeam(index=1, heroes=["维多丽卡", "蒙茉朗西"]),
            OpponentTeam(index=2, heroes=["卡麦萝兹"]),
        ]
        with patch.object(HeroMatcher, "identify_screen", return_value=teams):
            with patch(
                "auto_game_unified.games.epic7.arena.read_opponent_points",
                return_value=(999, 1, 500),
            ):
                frame = load_frame("list")
                kept = list(runner.machine.opponent_filter(frame, [0, 1, 2]))
        # 第 2 行命中两名白名单英雄但积分只有 1；仍排第一。
        self.assertEqual(1, kept[0])
        # 命中一名的那行其次，普通组最后。
        self.assertEqual([1, 0, 2], kept)

    def test_missing_the_whitelist_still_leaves_the_page_playable(self):
        """白名单一个都没撞上 ⇒ 整页照打，不是反复刷新（用户 2026-11-15 纠正）。"""
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        runner = ArenaRunner(
            machine,
            _FakeRuntime(),  # type: ignore[arg-type]
            hero_whitelist=["维多丽卡"],
        )
        others = [
            OpponentTeam(index=0, heroes=["甲"]),
            OpponentTeam(index=1, heroes=["乙"]),
            OpponentTeam(index=2, heroes=["丙"]),
        ]
        with patch.object(HeroMatcher, "identify_screen", return_value=others):
            frame = load_frame("list")
            kept = list(runner.machine.opponent_filter(frame, [0, 1, 2]))
        self.assertEqual([0, 1, 2], kept)
        self.assertIn("无优先名单命中", runner.machine.filter_note)

    def test_whitelist_hit_wins_over_the_points_preference(self):
        """白名单是**优先**：命中的行排在最前，积分偏好只在组内起作用。"""
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        runner = ArenaRunner(
            machine,
            _FakeRuntime(),  # type: ignore[arg-type]
            hero_whitelist=["维多丽卡"],
            opponent_preference="highest",
        )
        teams = [
            OpponentTeam(index=0, heroes=["甲"]),
            OpponentTeam(index=1, heroes=["维多丽卡"]),
            OpponentTeam(index=2, heroes=["丙"]),
        ]
        with patch.object(HeroMatcher, "identify_screen", return_value=teams):
            with patch(
                "auto_game_unified.games.epic7.arena.read_opponent_points",
                return_value=(999, 1, 500),
            ):
                frame = load_frame("list")
                kept = list(runner.machine.opponent_filter(frame, [0, 1, 2]))
        # 第 2 行积分最低（1），但它命中白名单 ⇒ 仍然排第一。
        self.assertEqual(1, kept[0])
        # 其余两行按「积分最高」排：第 1 行 999 > 第 3 行 500。
        self.assertEqual([1, 0, 2], kept)


class EmptyPageStopTests(unittest.TestCase):
    """整页被否掉时必须有界收尾，不许无限刷新。"""

    @NEEDS_LIBRARY
    def test_consecutive_filtered_pages_end_the_route(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        runtime = _FakeRuntime()
        runner = ArenaRunner(
            machine,
            runtime,  # type: ignore[arg-type]
            hero_blacklist=["维多丽卡"],
        )
        all_black = [
            OpponentTeam(index=0, heroes=["维多丽卡"]),
            OpponentTeam(index=1, heroes=["维多丽卡"]),
            OpponentTeam(index=2, heroes=["维多丽卡"]),
        ]
        with patch.object(HeroMatcher, "identify_screen", return_value=all_black):
            with self.assertRaises(NoEligibleOpponent) as caught:
                for index in range(runner._HERO_FILTER_MAX_EMPTY_PAGES):
                    # 三帧彼此不同，绕过「同一帧复用结论」的缓存。
                    frame = np.zeros((1132, 1982, 3), dtype=np.uint8)
                    frame[0, index] = 255
                    runner.machine.opponent_filter(frame, [0, 1, 2])
        self.assertIn("都被避战名单否掉", str(caught.exception))
        self.assertEqual("名单条件下无对手", NoEligibleOpponent.stop_label)


class _FakeRuntime:
    dry_run = False
    diagnostic_dir = None

    def __init__(self) -> None:
        self.messages: list[str] = []

    def log(self, message: str) -> None:
        self.messages.append(message)

    def now(self) -> float:
        return 0.0

    def capture(self) -> np.ndarray:
        return np.zeros((1132, 1982, 3), dtype=np.uint8)

    def click(self, point, name) -> None:
        del point, name


if __name__ == "__main__":
    unittest.main()
