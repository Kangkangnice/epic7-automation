"""「完成故事」弹窗：点「点击关闭」，不许点弹窗中间。

现场（2026-11-22 12:50）：主线打完第 4 章弹出「完成故事」，盖在章节地图上、
不吃 ESC。收尾连按 2 次 ESC 页面没动 ⇒「回首页失败」。

两处都必须点那一行字：
1. 主线状态机把这一页认成「通关提示」（complete 0.9883），动作落点要改成
   弹窗底部的「点击关闭」（964,774），而不是 complete 模板中心的奖励图标；
2. 回首页流程在「认不出任何页面」时也要能把这一页关掉，否则只能按 ESC 空耗。
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from auto_game_unified.games.epic7 import home_return as home_return_module
from auto_game_unified.games.epic7.story import (
    StoryStateMachine,
    build_story_templates,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
STORY_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
NAVIGATION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"


def _frame(path: Path):
    image = cv2.imread(str(path))
    assert image is not None, path
    return image


def _navigator_templates() -> SimpleNamespace:
    """只喂 build_home_return_templates 真正用到的四个大厅图。"""

    lobby = _frame(NAVIGATION_FIXTURES / "lobby.png")
    return SimpleNamespace(
        lobby_story=lobby,
        lobby_story_tight_white=lobby,
        lobby_arena=lobby,
        lobby_battle=lobby,
    )


class CompleteStoryPopupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.screen = _frame(STORY_FIXTURES / "complete_story_live_20261122.png")

    def test_story_complete_action_clicks_the_close_label(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES / "story"))

        match = machine._locate(self.screen, "complete")
        self.assertIsNotNone(match, "完成故事弹窗应当被「通关提示」认出来")
        close = machine._locate(self.screen, "complete_close")
        self.assertIsNotNone(close, "模拟器也必须载到「点击关闭」落点图")

        point = machine._action_point(self.screen, "complete", match)

        self.assertEqual(point, close.center)
        self.assertLess(abs(point[0] - 964), 24, f"落点跑偏：{point}")
        self.assertLess(abs(point[1] - 774), 24, f"落点跑偏：{point}")

    def test_home_return_closes_the_notice_on_unknown_screen(self):
        templates = home_return_module.build_home_return_templates(
            TEMPLATES, _navigator_templates()
        )

        match = home_return_module._notice_close_point(self.screen, templates)

        self.assertIsNotNone(match)
        self.assertEqual(match.center, (964, 774))

    def test_home_return_does_not_click_on_a_normal_lobby(self):
        templates = home_return_module.build_home_return_templates(
            TEMPLATES, _navigator_templates()
        )
        lobby = _frame(NAVIGATION_FIXTURES / "lobby.png")

        self.assertIsNone(
            home_return_module._notice_close_point(lobby, templates),
            "正常大厅上不许把「点击关闭」当成可点目标",
        )


if __name__ == "__main__":
    unittest.main()
