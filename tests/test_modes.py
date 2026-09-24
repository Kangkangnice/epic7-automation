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
                "world_boss",
                "knights_donation",
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
        self.assertEqual("home", get_mode("world_boss").default_state)
        self.assertEqual("guild_home", get_mode("knights_donation").default_state)

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

    def test_world_boss_builds_its_own_machine_from_its_own_template_dir(self):
        world_boss = get_mode("world_boss")

        # 模板子目录是 templates/world_boss；工厂必须把它当根，不能当 templates 根。
        machine = world_boss.build_machine(TEMPLATES, "home", "emulator")

        self.assertEqual("home", machine.state.value)
        self.assertEqual(
            {
                "world_boss.knights_home",
                "world_boss.home",
                "world_boss.team_select",
                "world_boss.team_config",
                "world_boss.result",
                "world_boss.level_reward",
            },
            {page.key for page in machine.templates.evidence.pages},
        )

        self.assertEqual("battle", get_mode("expedition").resolve_state("battle"))
        self.assertEqual("replay", get_mode("fodder").resolve_state("replay"))

    def test_knights_donation_builds_from_its_own_template_dir_and_hides_the_terminal_state(self):
        donation = get_mode("knights_donation")

        # 模板子目录是 templates/knights_donation；工厂必须把它当根，不能当 templates 根。
        machine = donation.build_machine(TEMPLATES, "guild_home", "emulator")

        self.assertEqual("guild_home", machine.state.value)
        self.assertEqual(
            {
                "knights_donation.guild_home",
                "knights_donation.activity_panel",
                "knights_donation.resource_support",
                "knights_donation.weekly_tasks",
                "knights_donation.request_popup",
                # 2026-09-24 实跑新发现的一页（点列表「支援1个」先弹的确认框）。
                "knights_donation.support_confirm",
                "knights_donation.reward_popup",
            },
            {page.key for page in machine.templates.evidence.pages},
        )
        # ``finished`` 是「本轮已收工」的记号，不是一页画面 —— 不许当起始状态。
        self.assertNotIn("finished", donation.states)
        with self.assertRaisesRegex(ValueError, "不适用于模式 knights_donation"):
            donation.resolve_state("finished")

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
