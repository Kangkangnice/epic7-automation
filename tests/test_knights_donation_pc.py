# -*- coding: utf-8 -*-
"""骑士团捐赠在 PC 客户端上的判据护栏（2026-11-08 修）。

## 这一组测试守的是哪一次事故

2026-11-08 10:26 每日任务连打，骑士团捐赠这一步报
``页面无进展：骑士团捐赠画面[骑士团活动·资源支援]未识别``，整批以退出码 1 结束。

真因不在「弹窗没打开」，而在**模板把会变的数字焊进了图里**：
``pc/flower_cell.png`` / ``pc/flower_cell_selected.png`` 采图那天那格是「363」，
11-08 现场那格是「1321」⇒ 原样比只有 **0.8426**（阈 0.88）⇒
``request_popup`` 页面组合（``popup_title`` + 花朵格子任一态）不成立 ⇒
``observe_page`` 返回 None ⇒ ``UnrecognizedScreen``。

修法：把两张 PC 图各裁到高 130（数字行去掉，花朵 / 绿勾 / 金框都还在），判据与阈值一字未改。

## 为什么用 ``_locate`` 而不是模块级函数

和 ``test_epic7_story_pc.py`` 同一个理由：``_locate`` 分派了白掩膜 / 低通兜底 / 缩放，
只有调它才是**与实跑同一把尺**。测试要回答的是「这一帧上这颗判据到底认不认得出」。
"""

from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.core.matcher import find_template
from auto_game_unified.games.epic7.knights_donation import (
    KnightsDonationState,
    KnightsDonationStateMachine,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_knights_donation"
PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_knights_donation_pc"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "knights_donation"


def load_pc_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(PC_FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class KnightsDonationPcTests(unittest.TestCase):
    """PC 版花朵格判据：正例要够高、反例要够低、页面要认得出。"""

    def setUp(self):
        self.machine = KnightsDonationStateMachine(
            TemplateDir(TEMPLATES, "pc")
        )

    def test_the_request_popup_frame_is_recognised_at_all(self):
        """11-08 的故障帧：必须先能判成「请求支援弹窗」。

        这是那次事故最直接的回归护栏 —— 这条断言红，说明整条路线会在同一步
        重新崩成 ``UnrecognizedScreen``。
        """
        frame = load_pc_fixture("request_popup_pc_live_20261108")
        self.assertIs(
            self.machine.observe_page(frame),
            KnightsDonationState.REQUEST_POPUP,
        )

    def test_the_flower_cell_anchor_survives_a_different_holding_count(self):
        """花朵格正例：那格写的是 1321（模板采的是 363），仍须高分命中。

        ⚠️ 这条断言就是「模板不含会变内容」这条纪律的落地检查：
        数字一进模板，这张图上只有 0.8426。
        """
        frame = load_pc_fixture("request_popup_pc_live_20261108")
        match = self.machine._locate(frame, "flower_cell")

        self.assertIsNotNone(match)
        # 纪律门槛：正例 ≥ 0.94
        self.assertGreaterEqual(match.score, 0.94)
        # 落点必须压在花朵那一格里，不能跑到画面上别处
        x, y, width, height = self.machine.templates.evidence.atom("flower_cell").region
        self.assertTrue(x <= match.center[0] <= x + width)
        self.assertTrue(y <= match.center[1] <= y + height)

    def test_the_selected_state_does_not_fire_on_an_unselected_cell(self):
        """花朵格反例：这一格**没被选中**，选中态判据必须冷着。

        纪律门槛：反例 ≤ 0.70。它红了意味着「没选中也会被当成选中」，
        那一步就会跳过选花、直接按下确认 —— 请求出去的就不是下级精灵之花。
        """
        frame = load_pc_fixture("request_popup_pc_live_20261108")
        match = self.machine._locate(frame, "flower_cell_selected")

        self.assertIsNone(match)
        # 「不过阈」还不够 —— 要量出真实分数，确认间隔是**分数**给的，不是阈值擦边。
        atom = self.machine.templates.evidence.atom("flower_cell_selected")
        scored = find_template(
            frame,
            self.machine.templates.flower_cell_selected,
            0.0,
            region=atom.region,
            reference_size=atom.reference_size,
        )
        self.assertIsNotNone(scored)
        self.assertLessEqual(scored.score, 0.70)

    def test_the_template_no_longer_carries_the_holding_count(self):
        """结构性护栏：花朵格模板不得再包住下面那行数字。

        原图 184 高，底部约 30~54 行是「持有数量」——**每天都不一样**。
        裁到 130 后数字行落在模板之外。谁要是重新采一张带数字的图进来，
        高度会立刻超过这里的上限，测试当场变红。
        """
        for name in ("flower_cell", "flower_cell_selected"):
            with self.subTest(template=name):
                image = Image.open(TEMPLATES / "pc" / f"{name}.png")
                self.assertLessEqual(
                    image.size[1],
                    140,
                    f"pc/{name}.png 高 {image.size[1]}，已经把会变的数字行包回来了",
                )

    def test_the_resource_support_page_never_reads_as_the_popup(self):
        """反例方向：资源支援页那一帧上，花朵格判据不得命中。

        两者背景相近（弹窗是压在这张列表页上的）。若列表页也能命中花朵格，
        程序会在列表页上点一下「选花」——那个坐标上是别人的行。
        """
        frame = load_pc_fixture("resource_support_pc_live_20261102")

        self.assertIs(
            self.machine.observe_page(frame),
            KnightsDonationState.RESOURCE_SUPPORT,
        )
        self.assertIsNone(self.machine._locate(frame, "flower_cell"))
        self.assertIsNone(self.machine._locate(frame, "flower_cell_selected"))


if __name__ == "__main__":
    unittest.main()
