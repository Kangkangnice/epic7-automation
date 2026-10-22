import unittest
from pathlib import Path
from unittest.mock import patch

from auto_game_unified.games.epic7.evidence import shop_refresh as shop_evidence
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
                "labyrinth_stone",
                "sanctuary",
                "community",
                "tower",
                "side_story",
                "moonlight_theater",
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
        self.assertEqual("battle_menu", get_mode("labyrinth_stone").default_state)
        self.assertEqual("home", get_mode("sanctuary").default_state)
        # 社区签到的起点是**横屏**的网页活动列表（点「游戏社区」之后才转竖屏），
        # 终态 `done` 不是一页画面，不该能当起始状态。
        self.assertEqual("web_entry", get_mode("community").default_state)
        with self.assertRaisesRegex(ValueError, "不适用于模式 community"):
            get_mode("community").resolve_state("done")

        # 支线故事从**关卡地图**起步（用户人工停在那张地图上），与主线的
        # 「关卡入口」不是同一页，只是恰好共用了 StoryState.STAGE 这个名字。
        self.assertEqual("stage", get_mode("side_story").default_state)
        # 一次把本期所有关卡打完 ⇒ 次数不给用户填（与 community 同一手法）。
        self.assertFalse(get_mode("side_story").cycles_editable)

        # 月光剧场从**支线故事页**起步（导航只把游戏带到大厅 → 支线故事那一跳），
        # 之后「剧场选择页 / 分集页 / 剧情页」都归它自己认。
        self.assertEqual("entry", get_mode("moonlight_theater").default_state)
        self.assertFalse(get_mode("moonlight_theater").cycles_editable)

        # ⚠️ 次数是**兜底上限**，不是「跑一幕」：`completed_cycles` 记的是**幕**
        # （一个剧场一幕），填 1 就成了「打完第一个剧场就收工」，其余剧场白放着。
        # 真实终点靠 `MoonlightCleared` 提前收工，同 `side_story` 的口径。
        self.assertGreater(
            get_mode("moonlight_theater").default_cycles,
            1,
            "给 1 会让日常任务只打一个剧场",
        )
        self.assertEqual(
            get_mode("moonlight_theater").default_cycles,
            get_mode("side_story").default_cycles,
            "两条都是「一次打光」的路线，上限口径必须一致",
        )

    def test_survivor_starts_inside_the_activity_without_navigation(self):
        survivor = get_mode("survivor")

        # 起点固定是用户人工停好的「选第一张卡」页，只有这一个合法起始状态。
        self.assertEqual("card", survivor.resolve_state(None))
        self.assertFalse(survivor.needs_navigation)
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
        machine = world_boss.build_machine(TEMPLATES, "home")

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
        machine = donation.build_machine(TEMPLATES, "guild_home")

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

    def test_every_backend_shares_the_emulator_baseline_thresholds(self):
        """平台差异收敛到图片之后，阈值只剩模拟器基线这一套。

        以前 story / arena / hero_synthesis 各有一份「PC 专用门槛表」，跑 PC 时
        整体放宽一档。实测那些放宽只是拿模拟器图去认 PC 画面的止痛药（见
        ``docs/PC_TEMPLATE_MIGRATION.md``），真要做 PC 应该换图而不是放门槛。
        ⇒ 这里钉死「工厂不再接受平台参数、阈值恒为模拟器基线」。
        """
        story = get_mode("story").build_machine(TEMPLATES, "stage")
        arena = get_mode("arena").build_machine(TEMPLATES, "list")
        hero = get_mode("hero_synthesis").build_machine(TEMPLATES, "hero_list")

        self.assertEqual(0.65, story._THRESHOLDS["skip"])
        self.assertEqual(0.90, arena._THRESHOLDS["battle_start"])
        self.assertEqual(0.75, hero._THRESHOLDS["filter_level_label"])
        self.assertEqual(0.50, hero._button_struct_min)
        # 旧的「PC 坐标开关」（``pc_client``）连同那 8 个 `_PC_*` 坐标**一并删掉**了。
        # 实测（2026-09-28）：PC 帧上「三星」按钮的真实落位与模拟器常量只差 1 像素，
        # 与那套 PC 常量差 37 像素 ⇒ 那套坐标是统一画布之前的遗留，是错的。
        self.assertFalse(hasattr(hero.templates, "pc_client"))


class RouteHookRegistryTests(unittest.TestCase):
    """路线级钩子（2026-09-27 批次 3 C1）：``preflight`` / ``runner_options``。

    这两条钩子是「新路线需要专属校验 / 专属构造参数」时的唯一入口，取代了以前
    写在 ``main.run_mode`` 里的 ``if spec.name == "..."``。它们绑在注册项上，
    所以「忘记挂」不会有任何症状 —— 得靠这几条测试盯着。
    """

    def test_shop_refresh_preflight_blocks_live_until_the_evidence_flag_is_on(self):
        """刷书签会真花钱 ⇒ 实证标志为假时**必须**拦下实跑，但干跑不受影响。"""
        shop = get_mode("shop_refresh")
        self.assertIsNotNone(shop.preflight, "刷书签的实跑闸门从注册项上掉了")

        with patch.object(shop_evidence, "LIVE_TRANSACTIONS_VERIFIED", False):
            blocked = shop.preflight("shop_refresh", False)
            self.assertIsInstance(blocked, str)
            self.assertIn("当前客户端实证", blocked)
            # 干跑必须照旧放行 —— 采样是这个闸门存在的意义。
            self.assertIsNone(shop.preflight("shop_refresh", True))

        with patch.object(shop_evidence, "LIVE_TRANSACTIONS_VERIFIED", True):
            self.assertIsNone(shop.preflight("shop_refresh", False))

    def test_arena_runner_options_carry_the_two_live_paths_and_nothing_on_dry_run(self):
        """竞技场实跑要落两个盘（买票记账 + 每局结算画面），干跑一个都不落。"""
        arena = get_mode("arena")
        self.assertIsNotNone(arena.runner_options, "竞技场的落盘参数从注册项上掉了")

        self.assertEqual({}, arena.runner_options(ROOT, True, {}))
        self.assertEqual(
            {
                "purchase_stamp_path": ROOT / "runtime_logs" / "arena_ticket_purchase.txt",
                "outcome_frame_dir": ROOT / "docs" / "manual_review" / "arena",
            },
            arena.runner_options(ROOT, False, {}),
        )
        # 参数通道通了，但**不许**把参数原样塞进 Runner 构造函数 ——
        # 那会让不接受这个关键字的路线直接 TypeError（14 条路线都没接）。
        self.assertEqual(
            {
                "purchase_stamp_path": ROOT / "runtime_logs" / "arena_ticket_purchase.txt",
                "outcome_frame_dir": ROOT / "docs" / "manual_review" / "arena",
            },
            arena.runner_options(ROOT, False, {"only_npc": True}),
        )

    def test_routes_without_special_needs_declare_no_hooks(self):
        """没需求的路线不该挂钩子 —— 挂了就是「空转的配置」，读的人会以为它有意义。

        ⚠️ 例外**必须写明理由**，不能只是把名字塞进白名单：
        挂一个空转的闸门比不挂更糟（用户以为被拦住了，其实什么都没拦）。
        """
        hooks = {
            # 「会真花钱」：目标商品与购买价格没在当前客户端实证过就不许实跑。
            "shop_refresh": "preflight",
            # 社区签到同理，而且更硬：竖屏段那三条每日任务的坐标根本还没采到，
            # 放进实跑就是一次**必然失败**。
            "community": "preflight",
            # 竞技场实跑要落两个盘（买票记账 + 每局结算画面），路径只有 main 知道。
            "arena": "runner_options",
        }
        for name, spec in MODE_SPECS.items():
            if hooks.get(name) != "preflight":
                self.assertIsNone(spec.preflight, f"{name} 不该有 preflight")
            if hooks.get(name) != "runner_options":
                self.assertIsNone(spec.runner_options, f"{name} 不该有 runner_options")


class TemplateRootConventionTests(unittest.TestCase):
    """每条路线的 ``build_machine`` 都必须在**真模板根**上构造得出来。

    这是 2026-09-27 批次 5 普查的落地：10 个工厂里 ``template_root`` 与
    ``template_root / "<路线名>"`` 两种写法并存（``arena`` / ``hero_synthesis`` /
    ``shop_refresh`` / ``survivor`` 用根，其余 6 条用子目录）。

    实测（2026-09-27）：传错一层会**当场** ``FileNotFoundError`` —— 不是静默失效。
    所以这条测试守的不是「判据准不准」，而是「模板根这件事每条路线都有人验过一遍」，
    顺带补上之前只覆盖 6 条的缺口（fodder / shop_refresh / survivor / labyrinth_stone
    原先没有直接构造过）。
    """

    def test_every_route_builds_a_machine_from_the_real_template_root(self):
        for name, spec in sorted(MODE_SPECS.items()):
            with self.subTest(mode=name):
                machine = spec.build_machine(TEMPLATES, spec.default_state)
                self.assertIsNotNone(machine, f"{name} 在真模板根上构造出了 None")

    def test_a_wrong_template_root_fails_loudly_instead_of_silently(self):
        """传错一层模板根**必须炸**，不能静默构造出一个「什么都认不出」的机器。

        不写死异常类型（现在实测是 ``FileNotFoundError``）：要守的性质是
        「不许静默通过」—— 哪天模板改成懒加载，错根就会一路漏到实跑，
        以「认不出画面」的形式出现，那时候排查成本比现在高得多。
        """
        try:
            get_mode("world_boss").build_machine(TEMPLATES / "world_boss", "home")
        except Exception:
            return
        self.fail(
            "模板根传错一层竟然构造成功了 —— 这个错会一路漏到实跑才暴露"
            "（普查时实测是 FileNotFoundError）。"
        )


if __name__ == "__main__":
    unittest.main()
