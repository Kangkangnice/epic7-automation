from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectLayoutTests(unittest.TestCase):
    def test_epic7_global_fixture_set_exists(self):
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_global"
        self.assertEqual(
            {
                "friendship_points_pc_20260830.png",
                "intimacy_level_up_live_20260815.png",
                "network_disconnected.png",
                "network_reconnect.png",
                "network_reconnect_navigation.png",
            },
            {path.name for path in fixture_dir.glob("*.png")},
        )

    def test_epic7_arena_fixture_set_exists(self):
        expected = {
            "list.png",
            "selected.png",
            "team.png",
            "battle.png",
            "battle_auto_dead_one_live_20260814.png",
            "battle_auto_dead_three_live_20260814.png",
            "battle_manual_stuck_live_20260814.png",
            "battle_skill_animation_live_20260825.png",
            "battle_auto_off_enemy_turn_live_20260826.png",
            "result.png",
            "rank_confirm.png",
            "rank_promotion_master.png",
            "no_ticket.png",
            "friendship_ticket_offer_live_20260826.png",
            "failed_first_opponent.png",
            "free_refresh_confirm_live_20260814.png",
            "quick_battle_selected_live_20260826.png",
            "normal_battle_ready_live_20260826.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_arena"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_epic7_story_fixture_set_exists(self):
        expected = {
            "stage.png",
            "stage_variant.png",
            "assistant.png",
            "assistant_live_20260809.png",
            "team.png",
            "team_live_20260809.png",
            # 2026-09-17 游戏把队伍准备页的开始按钮从橙「进行任务」换成绿「战斗开始」，
            # 旧模板在这张画面上只剩 0.36 → 实跑卡在队伍准备页。留着当换皮回归证据。
            "team_live_20260917.png",
            # 2026-09-18 主线卡在队伍准备页：当天送的快速战斗次数让这页的按钮变成
            # 「快速战斗」（宽按钮 + 右侧切换控件）。宽按钮对 global 的快速战斗模板只有
            # 0.7341 < 0.88，所以被当成普通页点了 5 次无进展。右侧切换控件本身 0.9883，
            # 是这一页最干净的排他证据。留着当主线快速战斗页的回归证据。
            "team_quick_battle_live_20260918.png",
            "story.png",
            "story_variant.png",
            "story_watch_ready_live_20260810.png",
            "story_watch_next_ep4.png",
            "stage_battle_ready_updated.png",
            "stage_prepare_battle_ep5.png",
            "friendship_points_popup.png",
            "skip_confirm.png",
            "skip_confirm_persisted_live_20260813.png",
            "stamina_popup_live_20260809.png",
            "stamina_popup_after_start_live_20260815.png",
            "battle.png",
            "battle_variant.png",
            "battle_auto_off_live_20260809.png",
            "battle_auto_on_live_20260809.png",
            "battle_auto_skill_cooldown_live_20260818.png",
            "battle_guide_warning_live_20260815.png",
            "battle_manual_skill_variant_live_20260815.png",
            "skill_animation_live_20260813.png",
            "friend_request.png",
            "reward.png",
            "clear.png",
            "bonus_reward.png",
            "results.png",
            "complete.png",
            "next_stage.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_story"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_epic7_fodder_fixture_set_exists(self):
        expected = {
            "side_story.png",
            "special_book.png",
            "episode_detail.png",
            "stage_3_7.png",
            "assistant.png",
            "team.png",
            "battle.png",
            "clear.png",
            "results.png",
            "replay.png",
            "replay_assistant.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_fodder"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_epic7_survivor_fixture_set_exists(self):
        expected = {
            # 循环的四个页面各一张，顺序即一轮的运行顺序。
            "first_card_select.png",
            "battle_live_probe.png",
            "level_up.png",
            "result.png",
            # 2026-09-16 实跑留下的三选一实时帧：副标题锚点当年在它上面只有 0.7101，
            # 三选一整页因此认不出来。这张必须留着当回归证据。
            "level_up_live_20260916.png",
            # 同一天 21:29 第二次实跑又卡在三选一：这次是「升级」标题被半透明面板
            # 拖到 0.8662、「重新抽取」被模拟器键位浮层咬掉一角只剩 0.9134，
            # 两个锚点同时压在 0.90 门槛下。收成夹具守住「字要裁到只剩字形」这条修法。
            "level_up_live_20260916_2129.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_survivor"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_epic7_world_boss_fixture_set_exists(self):
        expected = {
            # 2026-09-21 用户授权 AI 直接操作模拟器，实机走通一整轮世界首领战，
            # 逐页采集。顺序即一轮的运行顺序。
            "lobby_with_knights.png",
            "knights_home.png",
            "worldboss_home.png",
            # 同一主页的两种状态：次数是「剩余/上限」，可打时 1/2、打完 0/2 且
            # 「选择队伍」变灰（按钮文字区 HSV 亮度 118.8 → 49.8）。两张都要留，
            # 是判断「还有没有次数」的回归证据。
            "worldboss_home_exhausted.png",
            "team_select.png",
            "team_config.png",
            # 体力 17 < 20 时弹出的全局体力弹窗，与 story 共用同一套模板
            # （实测 stamina_popup 0.9999 / material 0.9895 / confirm 1.0000）。
            "stamina_popup.png",
            "battle_result.png",
            "level_reward.png",
            # 2026-09-22 用户实测发现「每天第一次进骑士团」会先弹签到达成度奖励弹窗。
            # 两张一组：弹窗帧（盖住骑士团主页）+ 点掉后的骑士团主页。
            # 关键实测：弹窗把底页的 worldboss_entry 从 0.9890 压到 0.4477，
            # 所以弹窗期间认不出底页，必须先关掉再识别。
            "knights_signin_popup.png",
            "knights_home_after_popup.png",
            # 2026-09-22 用户实测第二类骑士团弹窗：「进骑士团时团员赠送的支援资源到账」
            # （标题「领取支援物品」）。同上，盖住骑士团主页、压暗底页锚点。
            # 实跑时它把导航打成「未知画面」，连点中央 4 次唤醒失败 —— 故纳入全局弹窗守卫。
            "gift_support_popup.png",
            # 2026-09-22 首次实跑失败帧：配置队伍页但「自动配置」按钮已转蓝。
            # 与 team_config.png 构成一组两态证据（橙=未配置 / 蓝=已配置），
            # 是「配置队伍页要分两阶段走」的回归依据。
            "team_config_configured.png",
            # 2026-09-22 「战斗开始」的**出口标志**：战斗画面本身没有稳定标题可裁模板，
            # 靠 battle_controls.battle_scene_visible（右上控制区 + 左侧行动顺序）
            # 判。这张图是「战斗画面已出现」的正例，用来守住「看到战斗画面才移交监督」。
            "battle.png",
            # 2026-09-22 用户实拍两张真实世界首领战画面（1920×1080 截图按
            # core/window.py::_legacy_canvas 的 (0,+52) 偏移还原成 1982×1132 画布）。
            # 上面那张 battle.png 是**另一种战斗布局**，团本战斗画面在旧判据下
            # battle_scene_visible 恒为 False —— 这两张才是「实跑看到的那一屏」。
            #   battle_live_skip.png：HUD 正常帧（右上角有「跳过」，识别锚点 + 点击目标）
            #   battle_skill_anim.png：boss 技能演出帧（UI 整块隐藏，预期认不出来）
            "battle_live_skip.png",
            "battle_skill_anim.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_world_boss"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_navigation_templates_for_knights_and_world_boss_exist(self):
        # 骑士团/世界首领战导航链要用的两个新锚点。都是排他锚点，必须有：
        # 骑士团主页与首领战主页顶部标题完全相同，只有靠这两个按钮区分得开。
        navigation = ROOT / "games" / "epic7" / "templates" / "navigation"
        for name in (
            "lobby_knights.png",
            "worldboss_entry.png",
            # 骑士团签到弹窗的两个锚点（标题 + 点击关闭），双锚点同时命中才算。
            "knights_signin_title.png",
            "knights_signin_close.png",
            # 「领取支援物品」弹窗的两个锚点，同样双锚点同时命中才算。
            "gift_support_title.png",
            "gift_support_close.png",
        ):
            self.assertTrue((navigation / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
