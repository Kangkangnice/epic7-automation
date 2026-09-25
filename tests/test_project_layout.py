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
            # 2026-09-25 真机输局帧（实跑时被判成「未知」的那两张之一）。它是
            # `arena_result_defeat.png` 锚点的唯一正例 —— 「负」这一侧以前全库没有真帧。
            "result_defeat_live_20260925.png",
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
            # 2026-09-23 用户实拍：主页「每周贡献度」宝箱 #1（27,500,000）**可领**那一态。
            # 同样是 1920×1080 按 (0,+52) 还原成 1982×1132 画布，与上面两张同一套做法。
            # 关键：这张图上次数是 **0/2**、宝箱还是亮的 —— 所以它同时是
            # 「先领宝箱、再判次数」这条顺序的回归依据（顺序反了会直接收摊走人）。
            "worldboss_home_chest_claimable.png",
            # 同一天的第二次实拍：**点完宝箱之后**的样子 —— 箱子原地变成**绿色对勾**，
            # 不弹任何窗口。这张是「领完不会重复点」的回归依据（绿勾那一态对可领模板
            # 只有 0.7085，认不出来才会往下走去判次数、干净收场）。
            "worldboss_home_chest_claimed.png",
            # 2026-09-25 第三次实跑：**同一个绿勾态、换一张截图**，对可领模板却得 **0.8069**
            # —— 越过了当时 0.80 的阈值，于是程序把已领的箱子当成可领，点 4 次不生效 →
            # 回大厅重来 → 再点 4 次，把路线拖死；而当时局内 0/2 本该直接收场。
            # ⇒ 这是「模板得分单独守不住」的现场复现件，也是亮度比那道判据的回归依据。
            "worldboss_home_chest_claimed_dark.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_world_boss"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_epic7_knights_donation_fixture_set_exists(self):
        expected = {
            # 2026-09-24 用户授权 AI 直接操作模拟器，实机走查骑士团捐赠全链路，逐页采集。
            # 主页两张一组：「骑士团活动」图标有红点 / 没红点。⚠️ 红点**不参与决策**
            # （用户当天更正：有没有红点都要进活动界面），留着是因为有红点那张是
            # activity_entry 余量最薄的回归依据（0.9259，红点盖住图标左上角）。
            "guild_home_with_dot.png",
            "guild_home_no_dot.png",
            # 资源支援页两张一组：一屏放不下时才需要下滑（列表会重排，不许按固定坐标点）。
            "support_page.png",
            "support_page_scrolled.png",
            # 2026-09-24 实跑当天现采的两张（不是按矩形裁的）：
            #   support_page_two_buttons.png：**一屏两个绿按钮**，上面那个吃不下、下面那个才行
            #     ⇒ 「挑行走 find_all_templates」这条设计的回归依据。
            #   support_confirm.png：点「支援1个」之后**先弹的确认框**（第一版采图没遇到、
            #     实机撞上后整条路线中止的一页）。
            "support_page_two_buttons.png",
            "support_confirm.png",
            # 2026-09-25 实跑当天现采（**原始诊断帧**，不是按矩形裁的）：
            #   support_page_short_material.png：一屏两个绿按钮，**上面那行材料不足**
            #     （持有 1、这一格要 2）。当时程序把它当成「没点到」连点 4 次、
            #     整条路线提前收工 ⇒ 「材料不足就跳过」这条判据的回归依据。
            #     它同时是两个数字字模唯一的实拍样本来源（需求 2 与需求 4）。
            "support_page_short_material.png",
            # 「请求支援」弹窗两张一组：未选中 / 已选中「下级精灵之花」。
            # 这两张互为对方最强的干扰源（实测 0.8279 / 0.7878），是 0.88 / 0.85 两个
            # 非默认阈值的全部依据，必须成对留着。
            "request_popup.png",
            "request_popup_selected.png",
            # 支援成功后的「获得奖励」弹窗（游戏通用对话框，实机确认点哪里都能关）。
            "reward_popup.png",
            # 每周任务页两张一组：有可领档位（角标 + 领取按钮都在）/ 全都领完了。
            # 已领完那张上「骑士团点数」原位会留下字体/宝箱碎片（面积 43/22/50/20），
            # 是角标判据「面积下限 60」的回归依据。
            "weekly_tasks_claimable.png",
            "weekly_tasks_claimed.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_knights_donation"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_every_route_is_known_to_the_local_check_gate(self):
        """每条路线都要在 `tools/check.py` 的路线表里登记。

        漏登记的后果不是「测试漏跑」——恰恰相反，是**反向**的：`route_of()` 认不出
        这个文件属于哪条路线，定向判定就退回全量。全量本身是安全的，所以不会有任何
        测试因此变红，只是改的人会奇怪「改一行怎么跑了 9 分半」（世界首领战 2026-09-23
        实测）。正因为它是「安静地变慢」而不是「响亮地失败」，才只能靠这条护栏盯着。
        """

        from auto_game_unified.games.epic7.modes import MODE_SPECS
        from auto_game_unified.tools.check import ROUTE_KEYWORDS

        missing = sorted(set(MODE_SPECS) - set(ROUTE_KEYWORDS))
        self.assertEqual(
            [],
            missing,
            f"这些路线没在 tools/check.py 的 ROUTE_KEYWORDS 里登记：{missing}"
            "（漏了不会报错，只会让改这条路线的人白跑全量）",
        )

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
