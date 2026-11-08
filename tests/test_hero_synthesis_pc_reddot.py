# -*- coding: utf-8 -*-
"""PC 英雄合成「刻印记忆」红点漏认的回归（2026-11-08）。

## 守的是哪一次事故

11-08 16:41 日志：
```
16:41:26 判断依据=当前英雄非SSS但刻印按钮无红点，跳过，详情指纹=fb4cfee2
16:41:30 判断依据=当前英雄非SSS但刻印按钮无红点，跳过，详情指纹=d1051d78
16:41:34 判断依据=当前英雄非SSS且刻印按钮红点存在 → open_imprint
```
用户截图里那颗红点明明在，程序却直接翻卡了。

## 病因与取证

`HeroVisionMixin._red_dot_present` 按模拟器标框收紧到
`_REDDOT_ZONE=(1030,942,32,35)`，还要求色块四周留 3px。
- 模拟器红点 `(1038,949,18,19)` → 稳稳在框内 ⇒ True
- PC 静止态红点 `(1030,942,26~29,26)`，且左边同色橙棕斜带与它相连
  ⇒ boundingRect 贴框左上边界 ⇒ `local_x=0/local_y=0` ⇒ False
- PC 翻卡动画中斜带分离、圆点缩回 `(1038,949,18,19)` ⇒ 偶尔 True

颜色完全合格（H 7~22、364~503 个橙红像素），所以**不是识别不稳，
是几何位置被模拟器窗口裁掉**。全库 2830 帧模板审计：PC 静止态正例
0.9177~1.0000，非红点最高约 0.51，阈 0.80。

## 修法边界

新判据图只放 `templates/hero/pc/`；新判据只在
`modes.py::_build_hero_synthesis` 的 `if is_pc(...)` 装配口挂上去。
`hero_synthesis.py` / `hero_vision.py` 不改，模拟器实例完全不动。
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.hero_synthesis import (
    HeroSynthState,
    HeroSynthStateMachine,
    build_hero_templates,
)
from auto_game_unified.games.epic7.hero_vision_pc import (
    install_pc_red_dot_vision,
    load_pc_red_dot_template,
    pc_red_dot_match,
)
from auto_game_unified.games.epic7.modes import _build_hero_synthesis
from auto_game_unified.games.epic7.template_paths import TemplateDir

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
PC_FIX = ROOT / "tests" / "fixtures" / "epic7_hero_pc"
SIM_FIX = ROOT / "tests" / "fixtures" / "epic7_hero"

USER_SHOT = "list_reddot_pc_live_20261108"          # 用户 JPG 还原的生产画布
SWITCH_BEFORE = "list_reddot_pc_switch_20261108"    # 真机「判无红点」现场
PC_NEGATIVE = "imprint_page_no_reddot_pc_20261108"  # 同轮刻印页（该处无红点）


def pc_fixture(name: str) -> np.ndarray:
    return np.asarray(Image.open(PC_FIX / f"{name}.png").convert("RGB"))


def sim_fixture(name: str) -> np.ndarray:
    return cv2.cvtColor(
        cv2.imread(str(SIM_FIX / f"{name}.png")), cv2.COLOR_BGR2RGB
    )


def raw_pc_machine() -> HeroSynthStateMachine:
    """未经装配的 PC 状态机 = 修复前的行为，用作反向基线。"""
    return HeroSynthStateMachine(build_hero_templates(TemplateDir(TEMPLATES, "pc")))


def assembled_pc_machine() -> HeroSynthStateMachine:
    return _build_hero_synthesis(
        TemplateDir(TEMPLATES, "pc"), HeroSynthState.HERO_LIST.value
    )


def assembled_emulator_machine() -> HeroSynthStateMachine:
    return _build_hero_synthesis(
        TemplateDir(TEMPLATES, "emulator"), HeroSynthState.HERO_LIST.value
    )


class PcRedDotTemplateTests(unittest.TestCase):
    def test_template_is_shipped_as_a_tight_dot_crop(self):
        tpl = load_pc_red_dot_template(TemplateDir(TEMPLATES, "pc"))
        self.assertEqual((28, 28, 3), tpl.shape)

    def test_missing_template_fails_closed_instead_of_silently_disappearing(self):
        empty = TemplateDir(ROOT / "tests" / "__no_such_template_root__", "pc")
        with self.assertRaises(FileNotFoundError):
            load_pc_red_dot_template(empty)

    def test_install_is_idempotent(self):
        m = raw_pc_machine()
        install_pc_red_dot_vision(m, TemplateDir(TEMPLATES, "pc"))
        first = m._red_dot_present
        install_pc_red_dot_vision(m, TemplateDir(TEMPLATES, "pc"))
        self.assertIs(first, m._red_dot_present, "重复装配会叠出多层包装")


class PcRedDotRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.machine = assembled_pc_machine()

    def test_user_shot_static_red_dot_is_now_recognised(self):
        frame = pc_fixture(USER_SHOT)
        self.assertFalse(
            raw_pc_machine()._red_dot_present(frame),
            "修复前的基线必须仍是 False，否则这条测试证明不了任何事",
        )
        self.assertTrue(self.machine._red_dot_present(frame))

    def test_real_skipped_frame_is_now_recognised(self):
        frame = pc_fixture(SWITCH_BEFORE)
        self.assertFalse(raw_pc_machine()._red_dot_present(frame))
        self.assertTrue(self.machine._red_dot_present(frame))

    def test_positive_scores_clear_the_threshold_with_margin(self):
        tpl = load_pc_red_dot_template(TemplateDir(TEMPLATES, "pc"))
        for name in (USER_SHOT, SWITCH_BEFORE):
            with self.subTest(fixture=name):
                match = pc_red_dot_match(pc_fixture(name), tpl)
                self.assertIsNotNone(match)
                self.assertGreaterEqual(match.score, 0.90)

    def test_original_true_short_circuits_without_asking_the_pc_template(self):
        """模拟器尺寸的红点：原判据就为真，不该依赖 PC 图。

        这张帧对 PC 图的分数只有约 0.72（低于阈 0.80），
        所以返回 True 只能来自原判据短路。
        """
        frame = sim_fixture("list_reddot")
        tpl = load_pc_red_dot_template(TemplateDir(TEMPLATES, "pc"))
        match = pc_red_dot_match(frame, tpl)
        self.assertIsNotNone(match)
        self.assertLess(match.score, 0.80)
        self.assertTrue(self.machine._red_dot_present(frame))


class PcRedDotExclusivityTests(unittest.TestCase):
    def setUp(self):
        self.machine = assembled_pc_machine()

    def test_hero_route_negatives_do_not_fire(self):
        negatives = {
            "PC 刻印页": pc_fixture(PC_NEGATIVE),
            "PC 传送页": pc_fixture("transmit_select_pc_live_20261106"),
            "PC 传送页(护栏后)": pc_fixture(
                "transmit_select_after_guard_pc_live_20261106"
            ),
            "PC 刻印已满提示": pc_fixture("imprint_max_level_pc_live_20261108"),
            "模拟器无红点": sim_fixture("list_no_reddot"),
        }
        for label, frame in negatives.items():
            with self.subTest(frame=label):
                self.assertFalse(self.machine._red_dot_present(frame), label)

    def test_negative_scores_stay_well_below_threshold(self):
        tpl = load_pc_red_dot_template(TemplateDir(TEMPLATES, "pc"))
        for name in (
            PC_NEGATIVE,
            "transmit_select_pc_live_20261106",
            "imprint_max_level_pc_live_20261108",
        ):
            with self.subTest(fixture=name):
                match = pc_red_dot_match(pc_fixture(name), tpl)
                score = match.score if match is not None else -1.0
                self.assertLess(score, 0.60)

    def test_unrelated_orange_ui_in_other_routes_does_not_ring_the_bell(self):
        """全库审计里 zone 内橙红像素 1100+ 的战斗/剧情帧，模板分数仍要低。"""
        tpl = load_pc_red_dot_template(TemplateDir(TEMPLATES, "pc"))
        nav = ROOT / "tests" / "fixtures" / "epic7_navigation"
        for name in ("lobby.png", "story_stage.png"):
            path = nav / name
            if not path.is_file():
                continue
            frame = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            with self.subTest(frame=name):
                self.assertFalse(self.machine._red_dot_present(frame), name)


class PcRedDotEndToEndTests(unittest.TestCase):
    def test_real_pc_assembly_opens_imprint_on_the_frame_it_used_to_skip(self):
        """业务后果：这一帧现在必须出 open_imprint，而不是 next_card_*。"""
        frame = pc_fixture(SWITCH_BEFORE)

        before = raw_pc_machine()
        before.filter_verified = True
        before_action = before.next_action(frame)

        after = assembled_pc_machine()
        after.filter_verified = True
        after_action = after.next_action(frame)

        self.assertIsNotNone(before_action)
        self.assertIsNotNone(after_action)
        self.assertTrue(
            before_action.name.startswith("next_card"),
            f"修复前基线应是翻卡，实际 {before_action.name}",
        )
        self.assertEqual("open_imprint", after_action.name)
        self.assertEqual(
            "当前英雄非SSS且刻印按钮红点存在", after_action.reason
        )

    def test_user_shot_red_dot_judgement_is_positive(self):
        """用户 JPG 比生产客户区矮 3px，页面结构证据不足，只验红点判据本身。
        端到端的「会不会出 open_imprint」由真机 switch_before 帧那条守。
        """
        m = assembled_pc_machine()
        self.assertTrue(m._red_dot_present(pc_fixture(USER_SHOT)))


class EmulatorIsolationTests(unittest.TestCase):
    """用户 11-07 硬约束：所有改动只能在 PC 生效，模拟器完全不动。"""

    def test_emulator_assembly_never_installs_the_pc_judgement(self):
        m = assembled_emulator_machine()
        self.assertFalse(getattr(m, "_pc_red_dot_vision_installed", False))
        self.assertIs(m._red_dot_present.__self__, m, "应是原绑定方法，不是包装函数")
        self.assertEqual("_red_dot_present", m._red_dot_present.__name__)

    def test_emulator_still_misses_the_pc_static_dot_exactly_as_before(self):
        m = assembled_emulator_machine()
        self.assertFalse(m._red_dot_present(pc_fixture(USER_SHOT)))
        self.assertFalse(m._red_dot_present(pc_fixture(SWITCH_BEFORE)))

    def test_emulator_positive_and_negative_are_unchanged(self):
        m = assembled_emulator_machine()
        self.assertTrue(m._red_dot_present(sim_fixture("list_reddot")))
        self.assertFalse(m._red_dot_present(sim_fixture("list_no_reddot")))

    def test_modes_source_only_installs_under_is_pc_guard(self):
        source = (ROOT / "games" / "epic7" / "modes.py").read_text(encoding="utf-8")
        self.assertTrue(
            "if is_pc(template_root):" in source,
            "PC 装配口必须挂在 is_pc 守卫下",
        )
        self.assertTrue(
            "install_pc_red_dot_vision(machine, template_root)" in source,
            "PC 装配口不见了",
        )
        block = source[
            source.index("def _build_hero_synthesis") : source.index(
                "def _build_shop_refresh"
            )
        ]
        self.assertEqual(1, block.count("install_pc_red_dot_vision"))
        self.assertIn("if is_pc(template_root):", block)

    def test_install_is_never_called_on_emulator_path(self):
        """直接打桩：模拟器装配时该入口一次都不能被调用。"""
        with patch(
            "auto_game_unified.games.epic7.modes.install_pc_red_dot_vision"
        ) as install:
            assembled_emulator_machine()
            install.assert_not_called()

    def test_install_is_called_exactly_once_on_pc_path(self):
        with patch(
            "auto_game_unified.games.epic7.modes.install_pc_red_dot_vision",
            wraps=install_pc_red_dot_vision,
        ) as install:
            m = assembled_pc_machine()
            install.assert_called_once()
            self.assertTrue(m._pc_red_dot_vision_installed)


if __name__ == "__main__":
    unittest.main()
