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
                # 2026-10-04 真机：竞技场掉线那一帧是「文案乙 + 按钮甲」的交叉
                # 搭配 —— 老的两两配对判定两组各缺一半，整层弹窗被漏掉。
                "network_disconnected_live_20261004.png",
                # 2026-11-03 PC 真机：英雄详情里弹出的**断线**重连帧，与 10-04 那张
                # 竞技场帧是同一句文案的又一种渲染；它钉住 global/pc 断线图不会
                # 把「断线」误判成「重连成功」（两类弹窗按钮不同、不能串味）。
                "network_disconnected_pc_hero_20261103.png",
                "network_reconnect.png",
                "network_reconnect_navigation.png",
                # 2026-11-01 PC 真机：同一句「网络连接异常，请重新连接。」在 PC 上
                # 只有 0.6272（阈 0.88）⇒ 断线弹窗认不出、一直压着。
                # 修法是 `templates/global/pc/network_message.png`（同尺寸覆盖图）。
                "network_reconnect_pc_live_20261101.png",
                # 2026-11-01 PC 真机：新支线解锁通知（盖在结算页上 ⇒ 等待结算 45 秒无进展）。
                # 弹窗正文与插画随解锁的支线变化 ⇒ 只锚「支线故事通知」+「点击关闭」。
                "side_story_notice_pc_live_20261101.png",
                # 2026-11-01 PC 真机：点完通关提示后弹出的「获得奖励」（星星奖励发放），
                # 盖住关卡入口 ⇒ `等待通关` 45 秒无进展；同帧 bonus_reward 只有 0.7724（阈 0.80）。
                "reward_notice_pc_live_20261101.png",
                # 2026-11-02 PC 真机：进骑士团时的「领取支援物品」弹窗（第 16 类）。
                "gift_claim_pc_live_20261102.png",
                # 2026-09-28 用户实拍：快捷菜单页「宠物小屋礼物角标」（宠物送礼时挂出，
                # 必须点掉才更新）。它是 home_return 点「酒馆」那一页，顺带成了这条
                # 全局弹窗的唯一正例。
                "pet_gift_live_20260928.png",
                # 2026-10-07 真机：游戏内网页（WebView）上那条黑底白字「网络错误」
                # 长条 —— 当天四次实跑里**两次**卡在它身上（网页只渲染了一半、
                # 缺了导航要的「游戏社区」那一项 ⇒ 判失败）。
                # ⚠️ 这张帧同时钉住**两种网络失败不串味**：同一帧上
                # ``find_network_retry``（断线弹窗，判文案）**完全认不出来**
                # （全帧最高 0.31，门槛 0.88），而新的长条锚点拿 1.0000。
                "web_network_error_live_20261007.png",
                # 2026-10-20 08:02 真机：竞技场第 7 局打完、点掉「段位提升」后紧接着
                # 弹出的**第二层**「升级奖励」。竞技场当时一条判据都不认它 ⇒ 转场一路
                # 等到 45 秒上限、整条竞技场记 ✗（当天唯一失败的路线）。
                # 它是「标题 + 点击关闭」这对锚点的唯一正例；同一帧上「点击关闭」单独
                # 在本页之外也有 0.9548（`imprint_result_popup.png`）⇒ 单锚点不成立。
                "arena_rank_reward_live_20261020.png",
                # 2026-10-30 18:27 真机：**进竞技场时就弹**的「战斗记录」（防守战绩 /
                # 段位变动通知）。它与上面那张不是一回事（那个在打完一局之后），
                # 但同样把底页压暗、让竞技场一条判据都认不出 ⇒ 转场只等到 129 秒。
                # 同一句报错在此前 10-28 / 10-29 两天的早晨也各出现过一次。
                "battle_record_live_20261030.png",
                # 2026-10-30 19:48 真机：骑士团**成长 Rank 提升**时的通知窗。
                # 从快捷菜单点「骑士团」后它盖住骑士团主页 ⇒ 世界首领战那条路线
                # 一路"只等"到 2 分钟上限。同一层弹窗 10-08 的骑士团捐赠诊断帧里
                # 也出现过（说明早就存在，只是当时没登记）。
                "knights_growth_rank_live_20261030.png",
                # 2026-11-02 15:35 PC 真机：账号**Rank 提升**（RANK UP 45）通知窗。
                # 盖住战斗画面 ⇒「战斗画面持续无法识别超时」；回家时它又挡着，
                # 连按 2 次 ESC 都没反应 ⇒「返回首页失败」（一条命犯两桩）。
                # 是第 17 类全局弹窗的唯一正例。
                "account_rank_up_pc_live_20261102.png",
                # 2026-11-03 PC 真机：游戏内**日期变更**通知（「日期变更，将前往大厅。」）。
                # 它把画面强制切回大厅 ⇒ 主线在「等待通关」上干等 46 秒无进展 ⇒ 超时放弃。
                # 第 18 类全局弹窗的唯一正例（标题 208x49 排他，全库最高 0.5517）。
                "date_change_pc_live_20261103.png",
                # 2026-11-03 PC 真机：每日**获得登录奖励**（6 格奖励）。
                # 这层不吃 ESC ⇒ 收尾「连按 2 次 ESC 页面不动」⇒「回首页失败」。
                # 第 19 类全局弹窗的唯一正例（标题 304x49 排他，全库最高 0.5703）。
                "login_reward_pc_live_20261103.png",
                # 2026-11-05 PC 真机：主线战斗里弹出的**断线重连**弹窗（同一句话的
                # **小一号**渲染：字高 26 vs 25、字宽 361 vs 346）。
                # 旧 PC 模板打这一帧只有 0.6882（阈 0.88），缩到 0.97 才 0.9335
                # ⇒ 判定为「同一句、不同尺寸」，补了 global/pc/ 的第二种尺寸图。
                "network_reconnect_pc_story_20261105.png",
                # 2026-11-06 12:29 PC 真机：主线打到 Episode 4 第 11 关时弹出的
                # 「轻触后解锁【觉醒者艾庭】」**全屏教学遮罩**。它把「准备战斗」
                # 和 ESC 一起吞掉 ⇒ prepare_battle 点 4 次不转场、收尾 ESC 2 次
                # 无效 ⇒ 主线 ✗ 且每日任务「已中止」，后面 8 条路线全没跑。
                # 判据只裁黑框左半（不含会变的角色名），4 帧 0.9999~1.0000，
                # 全库 360 张反例最高 0.4323。
                "tutorial_unlock_pc_live_20261106.png",
                # 2026-11-06 22:27 PC 真机：新手账号大厅右上角常驻一块「跳过教学 ✕」，
                # 把**快捷菜单蓝四格顶掉** ⇒ 导航「打开快捷菜单」锚点找不到，
                # 多条路线在这台机器上反复失败（老账号的模拟器没有这个东西）。
                "tutorial_skip_pc_live_20261106.png",
                # 2026-11-06 17:23 批量：竞技场「升级奖励」弹窗的 PC 字形版。
                # 这颗全局弹窗 10-20 就接好了，但两张锚点图是模拟器字形，
                # PC 帧上只有 0.6604 / 0.6861（阈 0.88）⇒ 守卫不出手。
                "arena_rank_reward_pc_live_20261106.png",
                # 2026-11-07 13:11 PC 真机：主线 Episode 5 第 3 关通关后弹出
                # 「解锁缘分」（已与贝洛妮卡结下缘分 + 金色 OK），整页盖住关卡
                # 入口 ⇒ 主线报「页面无进展：主线画面[跳过确认]未识别」，安全停止
                # 回家。第 24 类全局弹窗的唯一正例，判据住在 PC 专属模块里。
                "relationship_unlock_pc_live_20261107.png",
                # 2026-11-07 15:51 PC 真机（用户截图还原成 1982x1132 生产画布）：
                # 宠物小屋图标上方的紫金礼盒 + 白色对话气泡角标。这条判据
                # 2026-09-28 就有、PC 也一直在用共享图；这里补的是**首个 PC 正例**
                # ——此前全库只有模拟器帧，PC 侧没有人能证明它会点。
                "pet_gift_pc_live_20261107.png",
            },
            {path.name for path in fixture_dir.glob("*.png")},
        )

    def test_epic7_arena_fixture_set_exists(self):
        expected = {
            "list.png",
            # 2026-11-09 模拟器：进竞技场时弹出的「新的每周排名开始！」覆盖层。
            # 它不在守卫清单里 ⇒ 导航只等 106 秒后报「转场失败」。
            "weekly_rank_start_popup.png",
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
            # 2026-09-25 真机票耗尽帧。它钉住了「竞技场的终点是购买旗帜弹窗」这个
            # 事实 —— 收尾的 `_dismiss_purchase_popup` 就是照它写的判据。
            "ticket_exhausted_popup.png",
            # 2026-11-01 PC 真机：旗帜打满时弹出的「购买旗帜」弹窗（新口径画布）。
            # 共享模板在 PC 上认不出它 ⇒ 走 templates/pc/ 覆盖图；
            # 正例帧供 `test_pc_ticket_popup_uses_pc_override_templates` 用。
            "ticket_purchase_popup_pc_live_20261101.png",
            # 同日 PC 真机结算页帧：当 PC 侧锚点的**反例**用（购买弹窗三锚点
            # 在它上面一律不得命中）。
            "result_victory_pc_live_20261101.png",
            # 2026-11-02 PC 真机：点完「战斗开始」后出现的「段位 VS 确认」页
            # （PC 独有，模拟器无此页）。供 `test_pc_vs_rank_confirm_page_...` 用。
            "arena_vs_confirm_pc_live_20261102.png",
            # 2026-11-02 PC 真机：旗帜耗尽弹窗压在「队伍选择」页上（战斗开始变灰）。
            # 与 1101 弹窗是同一弹窗的两种面板渲染变体；供 PC 自动买绿叶旗测试用。
            "arena_purchase_popup_team_pc_live_20261102.png",
            # 2026-11-03 PC 真机：结算后的「段位提升」弹窗（金牌V > 金牌IV）。
            # 共享 rank_confirm 图在 PC 上只有 0.7536（阈 0.90）⇒ 双锚点整页判 unknown
            # ⇒ confirm-result 转场失败、收尾 ESC 又无效（一条命犯两桩）。
            # 正例帧供 `test_pc_rank_promotion_popup_is_recognized` 用。
            "rank_promotion_pc_live_20261103.png",
            # 2026-11-07 PC 真机：点「刷新对手」后弹出的「更新交战对手」确认窗。
            # ① 共享模板在 PC 上三个锚点全塌（0.6374/0.7967/0.7273，阈 0.90）
            #    ⇒ 补 `templates/pc/arena_refresh_{title,free,confirm}.png`；
            # ② 它同时是「半透明遮罩把红色状态压没」的物证 —— 这一帧上
            #    `has_safe_opponent` 会返回 True，而刷新前日志写的是三名均不可挑战。
            # 供 `test_safe_list_waiter_never_accepts_a_list_while_popup_is_up` 用。
            "free_refresh_confirm_pc_live_20261107.png",
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
            # 「无法前往下一个关卡，请选择下方按钮」—— 重复打同一关时的常态落点。
            # 两张来自**不同关卡、不同背景**（10-18 第 3 章白色悬崖森林 / 10-14 室内），
            # 是「重新进行」判据能不能泛化的唯一物证；只留一张就退化成记图。
            "retry_stage_live_20261018.png",
            "retry_stage_live_20261014.png",
            # 2026-11-01 PC 真机「关卡入口」帧（新口径画布 1982x1132）。
            # 主线在 PC 上**不需要**专属图：「准备战斗」是白掩膜判据，
            # 这一帧上 1.0000 / 0.9997（阈 0.90）。留作 `test_epic7_story_pc.py` 的正例。
            "stage_pc_live_20261101.png",
            # 同日 PC 真机「行动力不足」弹窗帧（三按钮版本）。它是两处修复的唯一物证：
            # 标题在 PC 上渲染得略大（0.7623 < 0.80 ⇒ 补 `templates/story/pc/
            # stamina_popup.png` 覆盖图）、购买按钮被第三颗「礼包」挤到 x=807
            # ⇒ 搜索框左扩到 760（0.9148）。
            "stamina_popup_pc_live_20261101.png",
            # 同日 PC 真机「结算页 + 给予协助的朋友弹窗」帧（超时那一刻的现场）。
            # 它证明弹窗标题在 PC 上只有 0.6084（阈 0.82）⇒ 整个弹窗关不掉、
            # ESC 也无效；修法是 `templates/story/pc/friend_request_title.png`。
            "friend_request_pc_live_20261101.png",
            # 2026-11-07 PC 真机：「战斗指南」战力差警告盖在队伍准备页上。
            # 两个共享锚点在 PC 上分别是 0.6681 / 0.9004（阈 0.85）⇒ 标题那一颗
            # 认不出 ⇒ 双锚点整页返回 None ⇒ 战斗阶段空等 20 秒后「安全停止」。
            # 修法是 `templates/story/pc/battle_guide_{title,dont_show}.png`。
            "battle_guide_warning_pc_live_20261107.png",
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
            # 2026-11-09 模拟器：未开放/次数用完时右下角换成「管理辅助队伍」。
            # 旧「选择队伍」图在这帧只有 0.5107（阈 0.82）⇒ 导航判未知画面。
            "worldboss_home_manage_support_team.png",
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
            # 2026-09-28 实跑骑士团捐赠时现采：每周一结算弹出的「获得每周骑士团点数奖励」
            # 弹窗（标题 + 点击关闭），盖住骑士团主页把导航打成「未知画面」。
            # 与签到/支援弹窗同属「骑士团主页上的全局弹窗」，接成全局弹窗守卫。
            "knights_weekly_reward_popup.png",
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
            # 2026-09-25 第四次实跑：主页「每周贡献度」宝箱 **#2**（7,500,000）可领那一态。
            # 与上面那张 #1 是同一屏的两个箱子：实跑日志里 #1 已被领掉（亮度比 1.011），
            # #2 还亮着（3.197）却没被领 —— 顺序反了、判据又没接线，两件事一起犯。
            "worldboss_home_chest2_claimable.png",
            # 2026-10-19 08:11 每日任务「世界首领战 ✗」的**原始诊断帧**：同僚团员借了
            # 辅助队伍并拿到奖励，进主页时弹「世界首领辅助队伍奖励」。它把底页压暗 ⇒
            # 「选择队伍」认不出来 ⇒ 导航转场等到超时。
            # 是那个新弹窗两个锚点（标题 + 点击关闭）的唯一正例。
            "worldboss_support_reward_live_20261019.png",
            # ── 2026-11-03 PC 客户端移植：六张实跑现场帧 ────────────────────
            # PC 压低的是**文字**类锚点（图形类不动：骷髅盾牌入口 0.9936）。
            # 这六张是每一颗「补了 PC 覆盖图」的锚点的正例，缺一张就少一条回归依据；
            # 同时它们是反向用例的输入 —— 共享图（模拟器那套）在这六张上必须**全部**
            # 认不出，否则说明 PC 图多余、或共享图被换成了 PC 图。
            "knights_home_pc_live_20261103.png",
            "worldboss_home_pc_live_20261103.png",
            "team_select_pc_live_20261103.png",
            "team_config_pc_live_20261103.png",
            # 战斗页：抓的是**跳过按钮仍在**的那一段（不是技能演出帧）。
            "battle_pc_live_20261103.png",
            # 结算页：分数 2,685,243、MVP 头像、右下「确认」。这张同时是
            # result_title 的正例，以及「奖励弹窗必须靠 forbidden 排他」的对照组。
            "battle_result_pc_live_20261103.png",
            # 2026-11-08：骑士团签到的「达成度奖励」弹窗（PC 帧）。共享层模板在这帧只有
            # 0.3796 / 0.6435 ⇒ 补了两张 `navigation/pc/knights_signin_*.png`。
            # 它借用本目录的 `_world_boss_screen` 读帧（同尺寸全屏帧，没必要再建一套）。
            "knights_signin_popup_pc_live_20261108.png",
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
            # 2026-09-26 用户现场帧（**原始帧**）：骑士团点数 1660、500/1000 已领，
            # **可领的是 1500 档**（角标中心 (1260,286)，老夹具那张是 (1073,286)）。
            # 当时搜索区是写死的 50×50 小方块、只罩得住 500 档 ⇒ 这一帧直接判
            # 「没有可领档位」收工，1500 的奖励白丢。它是「整条里程碑带 + 形态判据」
            # 的唯一回归依据（也是第二个里程碑正向样本）。
            "weekly_tasks_claimable_at_1500.png",
            # 2026-09-25 21:38 那次实跑的**原始诊断帧**（support-one 连点推不动的现场）：
            # 右上角正是「今日支援上限 200/200」。它是「上限满了」这条判据的正例来源
            # （模板就从这个框里切），也是「上限满了绿按钮照样是绿的」这个事实的证据 ——
            # 同页 30/200、90/200 那几张是它的**反向对照**（整串匹配必须分得开）。
            "support_limit_full.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_knights_donation"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_epic7_sanctuary_fixture_set_exists(self):
        """圣域收菜的 18 张夹具，每一张都有不能删的理由。

        ⚠️ 这张表是**故意的紧**：``epic7_sanctuary`` 是本仓库最新的路线夹具，
        而它的判据只有「领取奖励」一个锚点 —— 判据准不准，全靠这批帧覆盖了
        「可领 / 不可领 / 弹窗 / 淡入」这四种画面。少一张就少一种反例。
        """
        expected = {
            # 大厅两帧：接力探针必须在这两帧上都不接管（否则会跳过「进圣域」）。
            "lobby_entry.png",
            "lobby_entry_b.png",
            # 点完「圣域」那一瞬间的过渡帧：``forest_row`` 只有 0.2417 ⇒ 必须认不出。
            # 它是「淡入帧不许当成已到位」这条判据的唯一物证。
            "lobby_after_click.png",
            # 圣域主页（三个来源：刚进圣域 / 从精灵之森返回 / 准备回大厅）
            "home.png",
            "home_from_forest.png",
            "home_before_leaving.png",
            # 精灵之森 · 两行可领。``_00`` 是模板来源帧；``_08`` 是 12 帧连拍里
            # **分数最低**的那张（闪烁把分数压到 0.9733/0.9744），也是
            # 「按位置排序而不是按分数排序」的回归依据（这一帧第 1 行分数
            # 反而**低于**第 2 行）；``_old`` 是另一天拍的另一张，用于多样性。
            "forest_two_claimable_00.png",
            "forest_two_claimable_05.png",
            "forest_two_claimable_08.png",
            "forest_two_claimable_entry.png",
            "forest_two_claimable_old.png",
            # 精灵之森 · 只剩第 2 行可领（``_after_penguin`` 是领掉企鹅、关掉弹窗后
            # 那一帧：第 1 行已变倒计时）。
            "forest_spring_only.png",
            "forest_after_penguin.png",
            # 精灵之森 · 三行全在倒计时（本轮收工态）。
            "forest_all_done.png",
            # 精灵之森 · 三行全在倒计时**且「照料」按钮亮着**（按钮可点的那一态）。
            # ⚠️ 它与 ``forest_all_done`` 的差别**只有那一颗按钮**（三行状态一模一样），
            # 所以这两张天然成对：一张「按钮亮 = 可点」、一张「按钮灰 = 冷却中」。
            # 它还顺带覆盖了**白天背景**这一形态 —— 其余森林帧都是夜景，
            # 而圣域是昼夜场景（这正是不许用「绝对亮度」判亮/灰的原因）。
            "forest_care_ready.png",
            # 领取完成弹窗。``popup_penguin_after6s`` 是**弹出 6 秒后**才拍的 ——
            # 它是「弹窗不会自己消失、必须点掉」这条结论的唯一物证（用户口述
            # 「也不需要你点」被它证伪）；``popup_spring`` 是另一个弹窗（标题与
            # 物品图标都不一样），用来守住「只有『点击关闭』四个字是稳定的」。
            "popup_penguin.png",
            "popup_penguin_after6s.png",
            "popup_penguin_before_close.png",
            "popup_spring.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_sanctuary"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_sanctuary_templates_exist(self):
        """圣域的 5 张路线锚点 + 1 张导航入口。

        ⚠️ 导航入口 ``lobby_sanctuary`` 截的是**文字标签**不是那个城墙堡垒图标；
        5 张路线锚点里 ``forest_row`` 身兼两职（圣域主页的页面判据 + 进精灵之森的
        点击目标），``claim_text`` 是唯一的「可领」判据，``care_text`` 只回答
        「照料按钮在不在」（能不能点由**文字白不白**另判，见 ``probe_care``）。
        ``sanctuary_title.png``（左上角「圣域」标题）**刻意不存在** —— 它被全库
        扫描否掉了：``epic7_fodder/stage_3_7.png`` 的标题叫「圣域最深处」，
        前两个字恰好就是「圣域」⇒ 那张 2 字模板在那里得 0.9784（越阈）。
        """
        sanctuary = ROOT / "games" / "epic7" / "templates" / "sanctuary"
        self.assertEqual(
            {
                "forest_row.png",
                "forest_title.png",
                "claim_text.png",
                "popup_close.png",
                "care_text.png",
            },
            {path.name for path in sanctuary.glob("*.png")},
        )
        navigation = ROOT / "games" / "epic7" / "templates" / "navigation"
        self.assertTrue((navigation / "lobby_sanctuary.png").is_file())

    def test_epic7_community_fixture_set_exists(self):
        """社区签到的 19 张竖屏夹具，每一张都有不能删的理由。

        ⚠️ 这批帧是**唯一**能证明「竖屏判据真的分得开」的物证：社区是网页（H5），
        我们的判据全是「区域限定模板匹配」，跨帧能不能认全靠这批帧覆盖够不够杂。

        ⚠️ 两个**名字会骗人**的地方，删之前先看清楚：

        - ``exchange_center_live_20261006`` 其实是**空列表态**
          （判出来是 ``exchange_empty``），而 ``exchange_after_redeem`` 才是**正常的**
          兑换中心。这两张必须成对留：只留一张，就再也证明不了「空列表不会被当成
          正常兑换中心去点商品卡」。
        - ``tasks_one_browse_done`` 实测读出来是**第 2 行（点赞）已完成**、第 1/3 行
          未完成（见 ``test_community_pages.py::test_reads_task_rows_on_every_known_layout``）。
          名字与画面**不一致**，别照名字推内容。

        ``tasks_fresh`` 是 1103x1899 的**窗口客户区**截图（另一条采集通道、带雷电自己的
        边框），坐标系与 ``adb screencap`` 的 1080x1920 不是同一个口径 ⇒ 它只给读数
        测试用，不进判页夹具表（``test_community_pages`` 里有一条口径守卫钉着这件事）。

        2026-10-07 补的四张，每一张都对应一个**没它就没法验**的判据：

        - ``feed_before_signin`` / ``feed_after_signin`` —— 同一页的**未签到 / 已签到**
          两态。``feed_signin_state`` 是「看颜色（饱和度 49.1 vs 0.0）」的判据，
          少一张就只剩单边样本，谁改了阈值都不会红。
        - ``signin_success`` —— 「签到成功！」弹窗。它既是 ``signin_done`` 锚点的唯一
          来源帧，也是「压暗背板会被读成已签到」那条亮度闸门的**唯一物证**
          （没有它，``feed_signin_state`` 那道闸门就是空口白话）。
        - ``exchange_before_redeem`` —— 兑换中心**一件都还没兑**的那一态
          （920 分 / 0-2、0-1、0-1、0-1）。原来只有「兑过一次」的帧，
          ``plan_redeem`` 挑卡 1 的第一遍路径没有正样本。

        2026-10-07 傍晚补的两张（现场采集，同一次会话连滚 6 屏）：

        - ``feed_cards_mixed`` —— 一屏里**同时有**一颗已点赞的（实心青绿，y≈780）
          和一颗没点过的（空心描边，y≈1333）。这是 ``card_like_off`` 模板分离度的
          **唯一物证**：没有它，「模板只认没点过那颗」就只是一句空话。
        - ``feed_cards_all_todo`` —— 一屏里两颗都没点过（y≈880 / y≈1690）。
          钉住「同一屏有多颗候选时取最靠上的那颗」，以及「y 随卡片高度漂
          （880 vs 1690，同一帧内差 810px）」这件事本身。

        ⚠️ 这两张**一起**才说明问题：只留 mixed，「y 漂」证不了；只留 all_todo，
        「不会误认已点赞的那颗」证不了。

        2026-10-08 补的一张（现场采集，就是卡死那一刻的画面）：

        - ``image_viewer`` —— **帖子里的图片被点开放大成全屏**。它既是 ``image_viewer``
          那档**结构性判据**（上下两条全黑带占 0.8370）的唯一正样本，也是**负样本的
          基准线**：``test_community_pages`` 拿它跟另外 18 张逐张比黑行占比
          （其余全部 **0.0000**，阈值 0.60 坐在 0.8 宽的空档正中）。
          删了它 ⇒ 「查看器认得出来」与「别的页不会误判成查看器」两条同时失去物证。
          ⚠️ 它同时也是 ``feed_cards_all_todo`` 那次误点的**结果帧**：
          盲坐标 ``(400, 1450)`` 落在卡片 2 的图片带里（见 ``locate_feed_post_tap``）。

        2026-10-09 补的一张（现场采集，用户报「兑换按钮滑下去了找不着」那一刻）：

        - ``feed_grid_at_top`` —— 往回滚到**真正的顶部**之后的信息流。四宫格里的
          「兑换」图标落在 **y=275**，而原来 ``FEED_ICON_STRIP`` 只搜 y 380~680
          ⇒ ``feed_exchange_icon_visible()`` 在这张上恒判「看不见」，往回滚 3 次全白滚、
          最后报 ``CommunityDataMissing`` 收手。**滚回来是对的，是尺子错了。**
          ⚠️ 它是「搜索带必须同时罩住 y=532（未滚动）与 y=275（滚到顶）」这条规矩的
          唯一物证：删了它，搜索带上沿再被改回 380 也不会有任何用例变红。
          实测：这张 1.0000（图标 y=275）、``feed_list`` 1.0000（y=532），
          而真滚走的 ``feed_cards_mixed`` 0.7080 ⇒ 阈值 0.82 坐在空档里。
        """
        expected = {
            "feed_list_live_20261006.png",
            "post_detail_live_20261006.png",
            "share_sheet_live_20261006.png",
            "tasks_one_browse_done_live_20261006.png",
            "tasks_all_done_live_20261006.png",
            "tasks_fresh_live_20261006.png",
            "exchange_center_live_20261006.png",
            "exchange_after_redeem_live_20261006.png",
            "item_detail_live_20261006.png",
            "order_confirm_live_20261006.png",
            "redeem_success_live_20261006.png",
            "network_error_live_20261006.png",
            "feed_before_signin_live_20261007.png",
            "feed_after_signin_live_20261007.png",
            "signin_success_live_20261007.png",
            "exchange_before_redeem_live_20261007.png",
            "feed_cards_mixed_live_20261007.png",
            "feed_cards_all_todo_live_20261007.png",
            "image_viewer_live_20261008.png",
            "feed_grid_at_top_live_20261009.png",
            # 2026-10-18：点歪进「作者账号主页」那次事故的现场帧。
            # 它同时是两件事的唯一物证：① 陌生页逃生门的入口用例；
            # ② 「作者名行跨度 251px < 500」那条通栏门槛的反例。
            "stranger_account_page_live_20261018.png",
        }
        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_community"
        self.assertEqual(expected, {path.name for path in fixture_dir.glob("*.png")})

    def test_community_templates_exist(self):
        """社区路线的三批模板：判页 14 张 + 字模 10 张 + 导航入口 4 张。

        - ``pages/`` 里 11 个页面判据 + 2 个任务按钮长相（``task_todo`` / ``task_done``）
          + 1 张卡片 👍（``card_like_off``，**空心描边**=还没点过那颗）；
          判据型模板**一律不许缺**（``build_page_templates`` 是 fail-closed 的）。
        - ``digits/`` 十张字模，缺一张都会让积分/限购读数安静地失效。
        - ``strings/`` 是**备用路径**（整串模板，不在生产上）—— 修的时候别把它当判据。
        """
        templates = ROOT / "games" / "epic7" / "templates" / "community"
        self.assertEqual(
            {
                "feed_home.png",
                "exchange_center.png",
                "exchange_empty.png",
                "tasks_page.png",
                "item_detail.png",
                "order_confirm.png",
                "redeem_done.png",
                "share_sheet.png",
                "post_detail.png",
                "network_error.png",
                "signin_done.png",
                "task_todo.png",
                "task_done.png",
                "card_like_off.png",
                "feed_icon_exchange.png",
            },
            {path.name for path in (templates / "pages").glob("*.png")},
        )
        self.assertEqual(
            {f"{digit}.png" for digit in range(10)},
            {path.name for path in (templates / "digits").glob("*.png")},
        )
        navigation = ROOT / "games" / "epic7" / "templates" / "navigation"
        for name in (
            "lobby_activity.png",
            "activity_more.png",
            "web_activity_gate.png",
            "web_community.png",
        ):
            self.assertTrue((navigation / name).is_file(), name)

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
            # 「获得每周骑士团点数奖励」弹窗（每周一结算）的两个锚点，双锚点同时命中。
            "knights_weekly_reward_title.png",
            "knights_weekly_reward_close.png",
            # 游戏内网页（WebView）报「网络错误」时的两个锚点（2026-10-07 接，第 9 个
            # 全局弹窗）。⚠️ 分工与上面那几对**反着来**：长条是**排他判据**
            # （正例 1.0000、全库 227 张横屏帧最高 0.4908），圆钮 X 只是**定位点击点**
            # （正常网页帧上也有，0.97+，单独不能当判据）。两张缺谁都点不掉那条长条。
            "web_network_message.png",
            "web_error_close.png",
            # 「段位升级奖励」弹窗（2026-10-20 接，第 11 个全局弹窗）的两个锚点。
            # 它是竞技场「段位提升」的下一层：标题排他、底部「点击关闭」只当点击点
            # （那行灰字在 `imprint_result_popup.png` 上单独就有 0.9548）。
            "arena_rank_reward_title.png",
            "arena_rank_reward_close.png",
        ):
            self.assertTrue((navigation / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
