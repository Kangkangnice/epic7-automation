"""竞技场「对手偏好」：积分读数 + 按偏好挑行（2026-11-15）。

判据分两层，用例也按两层写：

1. **读数层**（``games/epic7/arena_points.py``）：两张真帧上六个数字必须全对，
   空白帧必须三行全是 ``None`` —— 读不出时**不许拿 0 顶替**。
2. **决策层**（``ArenaStateMachine.rank_opponents``）：偏好只排序、不否决；
   一个都读不出就退回原来的随机挑选，并在动作依据里写明原因。

⚠️ 读数依赖可选依赖 ``rapidocr-onnxruntime``：没装就整组跳过，与支线倒计时同一步调。
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from auto_game_unified.games.epic7.arena import ArenaStateMachine, build_templates


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"
REFERENCE = (1982, 1132)

HAS_OCR = importlib.util.find_spec("rapidocr_onnxruntime") is not None
NEEDS_OCR = unittest.skipUnless(
    HAS_OCR, "没装可选的 OCR 依赖（rapidocr-onnxruntime）"
)


def load_frame(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    return cv2.cvtColor(image[:1132, :1982], cv2.COLOR_BGR2RGB)


def build_machine(**kwargs) -> ArenaStateMachine:
    return ArenaStateMachine(build_templates(TEMPLATES), **kwargs)


@NEEDS_OCR
class PointsReadingTests(unittest.TestCase):
    """读数层：真帧上必须读对，空白帧必须说「不知道」。"""

    def test_points_detector_does_not_upscale_the_short_edge(self):
        from auto_game_unified.games.epic7 import arena_points

        with (
            patch.object(arena_points, "_OCR_ENGINE", None),
            patch("rapidocr_onnxruntime.RapidOCR") as constructor,
        ):
            self.assertIs(arena_points._ocr_engine(), constructor.return_value)
        constructor.assert_called_once_with(limit_type="max")

    def test_reads_the_three_rows_on_a_recorded_list(self):
        from auto_game_unified.games.epic7.arena_points import read_opponent_points

        # 实测值：这一页三行依次是 积分0 / 积分102 / 积分154
        self.assertEqual((0, 102, 154), read_opponent_points(load_frame("list")))

    def test_reads_three_digit_points_on_another_frame(self):
        from auto_game_unified.games.epic7.arena_points import read_opponent_points

        # 同一列的另一种取值：积分50 / 积分75 / 积分998（三位数也要读全）
        self.assertEqual((50, 75, 998), read_opponent_points(load_frame("selected")))

    def test_blank_screen_reports_all_unknown_instead_of_zero(self):
        from auto_game_unified.games.epic7.arena_points import read_opponent_points

        # ⚠️ 三态的意义就在这条：读不出时不许返回 (0, 0, 0) —— 那会让「积分最低」
        # 的偏好挑中一行根本不知道分数的对手。
        frame = np.zeros((REFERENCE[1], REFERENCE[0], 3), dtype=np.uint8)
        self.assertEqual((None, None, None), read_opponent_points(frame))

    def test_nickname_containing_the_word_is_ignored(self):
        """证伪：昵称里带「积分」字样不许被当成读数。"""
        from auto_game_unified.games.epic7 import arena_points

        frame = load_frame("list").copy()
        # 抹掉三行真正的积分数值，只留两行昵称文字所在的横向位置
        for y in arena_points._ROW_BASELINES:
            frame[y - 14 : y + 30, 560:820] = 0
        self.assertEqual((None, None, None), arena_points.read_opponent_points(frame))


class PreferenceDecisionTests(unittest.TestCase):
    """决策层：排序、不否决、读不出就退回、每页只读一次。"""

    def test_highest_points_picks_the_top_row(self):
        machine = build_machine(choose_opponent=lambda safe: safe[0])
        machine.opponent_preference = "highest"
        with patch(
            "auto_game_unified.games.epic7.arena.read_opponent_points",
            return_value=(10, 900, 300),
        ):
            action = machine.next_action(load_frame("list"))
        self.assertEqual("select-opponent", action.name)
        self.assertEqual(1, machine._selected_opponent)
        self.assertIn("积分最高", action.reason)
        self.assertIn("第2行 900", action.reason)

    def test_lowest_points_picks_the_bottom_row(self):
        machine = build_machine(choose_opponent=lambda safe: safe[0])
        machine.opponent_preference = "lowest"
        with patch(
            "auto_game_unified.games.epic7.arena.read_opponent_points",
            return_value=(10, 900, 300),
        ):
            action = machine.next_action(load_frame("list"))
        self.assertEqual(0, machine._selected_opponent)
        self.assertIn("积分最低", action.reason)

    def test_preference_off_never_reads_the_screen(self):
        machine = build_machine(choose_opponent=lambda safe: safe[-1])
        with patch(
            "auto_game_unified.games.epic7.arena.read_opponent_points"
        ) as reader:
            action = machine.next_action(load_frame("list"))
        reader.assert_not_called()
        self.assertEqual(2, machine._selected_opponent)
        self.assertIn("未指定对手偏好", action.reason)

    def test_unreadable_points_fall_back_to_the_old_pick_and_say_so(self):
        """三行都读不出 ⇒ 退回原来的随机挑选，但依据里必须写明原因。"""
        machine = build_machine(choose_opponent=lambda safe: max(safe))
        machine.opponent_preference = "highest"
        with patch(
            "auto_game_unified.games.epic7.arena.read_opponent_points",
            return_value=(None, None, None),
        ):
            action = machine.next_action(load_frame("list"))
        self.assertEqual(2, machine._selected_opponent)
        self.assertIn("对手偏好未生效", action.reason)

    def test_partially_readable_rows_still_rank_among_the_known(self):
        machine = build_machine(choose_opponent=lambda safe: safe[0])
        machine.opponent_preference = "lowest"
        with patch(
            "auto_game_unified.games.epic7.arena.read_opponent_points",
            return_value=(None, 900, 300),
        ):
            action = machine.next_action(load_frame("list"))
        # 第 1 行读不出 ⇒ 不参与；第 3 行 300 比第 2 行 900 低 ⇒ 选第 3 行。
        self.assertEqual(2, machine._selected_opponent)
        self.assertIn("未参与", action.reason)

    def test_one_read_per_page_even_under_preview(self):
        """空跑 + 正式各调一次 ``next_action``，只许 OCR 一次。"""
        machine = build_machine(choose_opponent=lambda safe: safe[0])
        machine.opponent_preference = "highest"
        frame = load_frame("list")
        with patch(
            "auto_game_unified.games.epic7.arena.read_opponent_points",
            return_value=(10, 900, 300),
        ) as reader:
            machine.preview(frame)
            machine.next_action(frame)
        self.assertEqual(1, reader.call_count)

    def test_cache_is_dropped_when_the_list_is_refreshed(self):
        machine = build_machine(choose_opponent=lambda safe: safe[0])
        machine.opponent_preference = "highest"
        machine._points = (1, 2, 3)
        machine._points_attempts = 1
        machine._reset_points()
        self.assertIsNone(machine._points)
        self.assertEqual(0, machine._points_attempts)


if __name__ == "__main__":
    unittest.main()
