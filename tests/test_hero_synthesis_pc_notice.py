# -*- coding: utf-8 -*-
"""英雄合成在 PC 上的「刻印已满」判据护栏（2026-11-08 修）。

## 这一组守的是哪一次事故

2026-11-08 08:51~08:56，每日任务做到英雄合成这一步，日志每 10 秒刷一行

```
模式=英雄合成 刻印页等待（判据没出货） 完整页面=0 绿色按钮=0 槽位结构=1
已填槽位=1 费用非零=0 Up材料=未识别 材料卡=card
```

整整空等 5 分钟，留下 50 多张同状态诊断帧，汇总里记成一个 ✗。

画面底部一直挂着一条黄条：「英雄 已达最高献身技能级别，无法继续刻印记忆。」
—— 这是**业务结论**（这个英雄刻满了），程序当时不认识它：

  * 绿按钮不在（不能合成）⇒ ``complete_imprint_page`` 恒 0；
  * 材料卡还能认出来 ⇒ 「既不能加料也不能合成」那道逃生门不成立；
  ⇒ 两条逃生门都不开，只能 ``return None`` 干等到超时。

## 修法

补一张 PC 判据图 ``templates/hero/pc/imprint_max_level_notice.png``（裁自那次现场帧），
在「刻印加材料且页面不完整」这一支上**先**判它：命中就返回英雄列表换下一个。

判据读数（``runtime_logs/_hero_build_notice.py``）：
正例 29 张全 **1.0000**、反例全库 1483 张最高 **0.4091**（阈 0.80）。
"""

from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.hero_synthesis import (
    HeroSynthState,
    HeroSynthStateMachine,
    build_hero_templates,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir

ROOT = Path(__file__).resolve().parents[1]
PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_hero_pc"
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"


def load_pc_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(PC_FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class HeroImprintMaxLevelNoticeTests(unittest.TestCase):
    """「已达最高献身技能级别」提示条：认得出来、不乱认、模拟器不受影响。"""

    def setUp(self):
        self.templates = build_hero_templates(TemplateDir(TEMPLATE_ROOT, "pc"))
        self.machine = HeroSynthStateMachine(self.templates)

    def test_the_pc_template_is_shipped(self):
        """判据图必须在，且只裁到那条提示文字（不含右侧背景按钮）。"""
        notice = self.templates.imprint_max_level_notice
        self.assertIsNotNone(notice, "PC 判据图没加载到，判据会静默消失")
        self.assertEqual((66, 545, 3), notice.shape)

    def test_the_notice_is_read_on_the_field_frame(self):
        """现场帧上必须认得出 —— 这条红就等于 11-08 那次空等会重演。"""
        frame = load_pc_fixture("imprint_max_level_pc_live_20261108")
        self.assertTrue(self.machine._imprint_max_level_notice_present(frame))

    def test_other_pages_do_not_ring_the_bell(self):
        """反例方向：别的页面上不许命中，否则会无故把正常英雄判成「已刻满」。"""
        for name in (
            "transmit_select_pc_live_20261106",
            "transmit_select_after_guard_pc_live_20261106",
        ):
            with self.subTest(fixture=name):
                frame = load_pc_fixture(name)
                self.assertFalse(self.machine._imprint_max_level_notice_present(frame))

    def test_the_emulator_has_no_such_judgement(self):
        """双平台隔离：模拟器没有这张图 ⇒ 模板是 None、判据恒 False。

        这条守的是「模拟器零改动」——判据是 PC 专属补的，模拟器上必须连门都不开。
        """
        emulator = build_hero_templates(TemplateDir(TEMPLATE_ROOT, "emulator"))
        self.assertIsNone(emulator.imprint_max_level_notice)
        emulator_machine = HeroSynthStateMachine(emulator)
        frame = load_pc_fixture("imprint_max_level_pc_live_20261108")
        self.assertFalse(emulator_machine._imprint_max_level_notice_present(frame))

    def test_a_full_imprint_hero_goes_back_to_the_list(self):
        """业务后果：判到这条提示就该返回英雄列表，而不是继续空转。"""
        frame = load_pc_fixture("imprint_max_level_pc_live_20261108")
        self.machine.state = HeroSynthState.IMPRINT_ADD

        action = self.machine.next_action(frame)

        self.assertIsNotNone(action, "还在 return None，会像 11-08 那样空等到超时")
        self.assertEqual("back_to_list", action.name)
        self.assertIn("英雄列表", action.target_pages)
        self.assertIn("最高献身", action.reason)


if __name__ == "__main__":
    unittest.main()
