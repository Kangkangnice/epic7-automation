"""主线在 PC 客户端上的判据护栏（2026-11-01 移植）。

为什么这条测试用 ``_locate``（内部方法）而不是模块级函数：主线的每颗判据都走
``StoryStateMachine._locate`` 分派（白掩膜 / 双模板择优 / 缩放区域都在里面），
只有调它才是**与实跑同一把尺**。测试要问的是「这一帧上这颗锚点到底认不认得出」，
用别的入口量出来的分数不能作数。
"""

from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.global_popups import (
    find_friend_request_cancel,
    load_friend_request_templates,
)
from auto_game_unified.games.epic7.story import (
    StoryStateMachine,
    build_story_templates,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"


def load_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class Epic7StoryPcTests(unittest.TestCase):
    def setUp(self):
        self.machine = StoryStateMachine(
            build_story_templates(TemplateDir(TEMPLATES, "pc"))
        )

    def test_pc_stage_page_is_recognized_by_shared_templates(self):
        """PC 真机「关卡入口」帧：准备战斗按钮必须过阈（实测 1.0000 / 0.9997）。

        这条是本路线**不需要补 PC 专属图**的证据：按钮判据是白掩膜找形状，
        与背景无关，所以同一个客户端换了渲染方式也照认。
        """
        frame = load_fixture("stage_pc_live_20261101")

        match = self.machine._locate(frame, "prepare_battle")

        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.score, 0.90)
        # 落点必须压在右下角那颗按钮上，不是画面别处
        self.assertTrue(1600 <= match.center[0] <= 1900)
        self.assertTrue(980 <= match.center[1] <= 1120)

    def test_pc_stage_page_does_not_trigger_later_pages(self):
        """反例方向：关卡入口这一帧上，后续页面的锚点一律不得命中。

        「准备战斗」认出来就够把页面判成关卡入口；若结算/通关/重试那几颗也命中，
        状态机会在关卡入口直接点走，链路就串页了。
        """
        frame = load_fixture("stage_pc_live_20261101")

        for name in (
            "results_confirm",
            "clear",
            "complete",
            "retry_stage",
            "skip_confirm",
            "watch_story",
        ):
            with self.subTest(atom=name):
                self.assertIsNone(self.machine._locate(frame, name))

    def test_pc_stamina_popup_is_fully_actionable(self):
        """PC 上「行动力不足」弹窗必须三件套都认得出，否则路线会空转到超时。

        2026-11-01 21:23 实跑就是这样：弹窗只认出素材（0.9997），标题差一点
        （0.7623 < 0.80）⇒ `next_stamina_decision` 判成"没有弹窗"⇒ 回头继续点
        「战斗开始」⇒ 连点 4 次、干等到用户手动停。

        两处根因、两种修法（都在设计内）：
        1. 标题：PC 把同一句话渲染得略大（白字 bbox 229x45 对模板 221x43）
           ⇒ `templates/story/pc/stamina_popup.png` 覆盖图（代码零改动）；
        2. 购买按钮：这版弹窗改成**三颗按钮**（取消/购买/礼包），购买被挤到
           x=807~1105，旧搜索框从 850 起摆不下模板 ⇒ 搜索框左扩到 760。
        """
        frame = load_fixture("stamina_popup_pc_live_20261101")

        for name in ("stamina_popup", "stamina_material", "stamina_confirm"):
            with self.subTest(atom=name):
                match = self.machine._locate(frame, name)
                self.assertIsNotNone(match, name)
                self.assertGreaterEqual(match.score, 0.80, name)

        # 购买按钮必须落在真正的按钮上（不是礼包、不是取消）
        confirm = self.machine._locate(frame, "stamina_confirm")
        self.assertTrue(880 <= confirm.center[0] <= 1030, confirm.center)
        self.assertTrue(820 <= confirm.center[1] <= 930, confirm.center)

    def test_pc_story_page_does_not_trigger_the_stamina_popup(self):
        """反例：关卡入口那一帧上，体力三件套一律不得命中。"""
        frame = load_fixture("stage_pc_live_20261101")

        for name in ("stamina_popup", "stamina_material", "stamina_confirm"):
            with self.subTest(atom=name):
                self.assertIsNone(self.machine._locate(frame, name))

    def test_pc_friend_request_popup_is_recognized(self):
        """战后「给予协助的朋友」弹窗：PC 上标题差一点，整个弹窗就关不掉。

        2026-11-01 21:21 那次超时的现场帧其实是**结算页 + 好友申请弹窗**：
        标题 0.6084（阈 0.82，PC 把同一句标题渲染得略大：白字 328×45 / 模板 314×44）
        ⇒ `find_friend_request_cancel` 要求标题与取消**同时**命中 ⇒ 守卫不认 ⇒
        弹窗一直压着，收尾"回首页"按 ESC 也照样无效。
        """
        frame = load_fixture("friend_request_pc_live_20261101")
        pc_templates = load_friend_request_templates(TemplateDir(TEMPLATES, "pc"))
        emulator_templates = load_friend_request_templates(
            TemplateDir(TEMPLATES, "emulator")
        )

        match = find_friend_request_cancel(
            frame, pc_templates.title, pc_templates.cancel
        )

        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.score, 0.82)
        # 点的是「取消」，不是「申请」
        self.assertTrue(760 <= match.center[0] <= 840, match.center)
        # 模拟器口径仍然解析到共享模板 —— 那份判据必须一个字都不变
        self.assertIsNone(
            find_friend_request_cancel(
                frame, emulator_templates.title, emulator_templates.cancel
            )
        )

    def test_pc_overrides_are_only_what_the_pc_really_needs(self):
        """PC 覆盖图只允许放**真的认不出**的那几张，加一张就得回来改这条。

        现有的两张都是「PC 把同一句中文标题渲染得略大」这一类：
        `stamina_popup`（行动力不足）、`friend_request_title`（给予协助的朋友）、
        `complete`（打完一关的「完成故事」弹窗 —— PC 上 0.7996 / 阈 0.80，差 0.0004
        ⇒ 主线 5 次卡在「等待结算」45 秒超时）。

        主线其余判据全是白掩膜 / 几何，PC 上本来就过阈 —— 不许顺手加图。
        """
        overrides = {path.name for path in (TEMPLATES / "pc").glob("*.png")}
        self.assertEqual(
            {"stamina_popup.png", "friend_request_title.png", "complete.png"},
            overrides,
        )


if __name__ == "__main__":
    unittest.main()
