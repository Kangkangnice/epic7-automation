import unittest
from pathlib import Path

from auto_game_unified.games.epic7.modes import MODE_SPECS, get_mode


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"


class Epic7ModeRegistryTests(unittest.TestCase):
    def test_registry_exposes_the_supported_routes(self):
        self.assertEqual(
            {
                "arena",
                "story",
                "expedition",
                "fodder",
                "hero_synthesis",
                "shop_refresh",
                "survivor",
            },
            set(MODE_SPECS),
        )
        self.assertEqual("list", get_mode("arena").default_state)
        self.assertEqual("stage", get_mode("story").default_state)
        self.assertEqual("home", get_mode("expedition").default_state)
        self.assertEqual("stage", get_mode("fodder").default_state)
        self.assertEqual("hero_list", get_mode("hero_synthesis").default_state)
        self.assertEqual("scan_top", get_mode("shop_refresh").default_state)
        self.assertEqual("card", get_mode("survivor").default_state)

    def test_shop_refresh_is_simulator_only(self):
        shop = get_mode("shop_refresh")

        shop.validate_backend("emulator")
        with self.assertRaisesRegex(ValueError, "仅支持模拟器"):
            shop.validate_backend("pc")

    def test_survivor_starts_inside_the_activity_without_navigation(self):
        survivor = get_mode("survivor")

        # 起点固定是用户人工停好的「选第一张卡」页，只有这一个合法起始状态。
        survivor.validate_backend("emulator")
        self.assertEqual("card", survivor.resolve_state(None))
        self.assertFalse(survivor.needs_navigation)
        with self.assertRaisesRegex(ValueError, "不支持后端 pc"):
            survivor.validate_backend("pc")
        with self.assertRaisesRegex(ValueError, "不适用于模式 survivor"):
            survivor.resolve_state("battle")

    def test_each_mode_validates_only_its_own_resume_states(self):
        self.assertEqual("active", get_mode("story").resolve_state("active"))
        self.assertEqual("list", get_mode("arena").resolve_state(None))

        with self.assertRaisesRegex(ValueError, "不适用于模式 story"):
            get_mode("story").resolve_state("list")

        self.assertEqual("battle", get_mode("expedition").resolve_state("battle"))
        self.assertEqual("replay", get_mode("fodder").resolve_state("replay"))

    def test_formal_pc_modes_receive_pc_evidence_without_old_hero_coordinates(self):
        story = get_mode("story").build_machine(TEMPLATES, "stage", "pc")
        arena = get_mode("arena").build_machine(TEMPLATES, "list", "pc")
        expedition = get_mode("expedition").build_machine(TEMPLATES, "home", "pc")
        hero = get_mode("hero_synthesis").build_machine(
            TEMPLATES, "hero_list", "pc"
        )

        self.assertEqual(0.55, story._THRESHOLDS["skip"])
        self.assertEqual(0.70, arena._THRESHOLDS["battle_start"])
        self.assertEqual("pc", expedition.backend)
        self.assertEqual(0.65, hero._THRESHOLDS["filter_level_label"])
        self.assertEqual(0.40, hero._button_struct_min)
        self.assertFalse(hero.templates.pc_client)

    def test_emulator_defaults_remain_separate_from_pc_overrides(self):
        story = get_mode("story").build_machine(TEMPLATES, "stage", "emulator")
        arena = get_mode("arena").build_machine(TEMPLATES, "list", "emulator")
        hero = get_mode("hero_synthesis").build_machine(
            TEMPLATES, "hero_list", "emulator"
        )

        self.assertEqual(0.65, story._THRESHOLDS["skip"])
        self.assertEqual(0.90, arena._THRESHOLDS["battle_start"])
        self.assertEqual(0.75, hero._THRESHOLDS["filter_level_label"])
        self.assertEqual(0.50, hero._button_struct_min)


if __name__ == "__main__":
    unittest.main()
