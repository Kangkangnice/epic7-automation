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


if __name__ == "__main__":
    unittest.main()
