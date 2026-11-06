"""模板路径解析：PC 与模拟器的**唯一**差异点必须只有图片。

背景（2026-09-28 这次重构）：以前平台差异散在业务代码里 —— 7 个证据模块各有一张
``PC_THRESHOLD_OVERRIDES``，竞技场 / 导航 / 英雄合成还有就地写死的
``0.85 if backend == "pc" else 0.90``。结果是「改 PC」= 到处找这些分叉，
改一处漏一处不会报错。现在全部收敛到 ``template_paths.TemplateDir``：
平台只决定**去哪个目录取图**，别的什么都不决定。

这组用例守三件事：
1. 覆盖 / 回落规则本身（``pc/`` 里有图就用它，没有就用共享图）；
2. ``.name`` / ``.parent`` 必须还原到共享目录 —— 业务代码靠 ``.name`` 认路线，
   靠 ``.parent`` 跨路线取图，退化成纯 ``Path`` 或变成 ``"pc"`` 都会出真错；
3. 业务代码里不许再长出门槛分叉（``PC_THRESHOLD_OVERRIDES`` / ``thresholds_for``）。
"""

from pathlib import Path

from auto_game_unified.games.epic7.template_paths import (
    PC_SUBDIR,
    TemplateDir,
    resolve_template,
    resolve_template_dir,
)


GAMES = Path(__file__).resolve().parents[1] / "games"
REAL_ROOT = GAMES / "epic7" / "templates"


def _story_layout(root: Path) -> Path:
    """``<root>/story/{skip.png, pc/skip.png, select_team.png}`` 的最小布局。"""
    story = root / "story"
    (story / PC_SUBDIR).mkdir(parents=True)
    (story / "skip.png").write_bytes(b"shared")
    (story / PC_SUBDIR / "skip.png").write_bytes(b"pc")
    (story / "select_team.png").write_bytes(b"shared")
    return story


def test_emulator_never_reads_the_pc_subdir(tmp_path):
    story = _story_layout(tmp_path)
    directory = resolve_template_dir(story)

    assert (directory / "skip.png").read_bytes() == b"shared"
    assert (directory / "select_team.png").read_bytes() == b"shared"
    assert directory.backend == "emulator"


def test_pc_prefers_the_override_and_falls_back_per_file(tmp_path):
    story = _story_layout(tmp_path)
    directory = resolve_template_dir(story, "pc")

    # 有 PC 图 ⇒ 用 PC 图。
    assert (directory / "skip.png") == story / PC_SUBDIR / "skip.png"
    assert (directory / "skip.png").read_bytes() == b"pc"
    # 没 PC 图 ⇒ 自动回落共享图（不是「找不到就报错」）。
    assert (directory / "select_team.png") == story / "select_team.png"
    assert (directory / "select_team.png").read_bytes() == b"shared"


def test_name_and_parent_stay_on_the_shared_directory(tmp_path):
    """``.name`` / ``.parent`` 必须还原到共享目录，不许变成 ``"pc"``。

    ⚠️ 这两条都是**真踩过的坑**：
    - ``pre_battle.py`` 靠 ``template_dir.name in {"story", "fodder", ...}``
      认路线，``.name`` 一旦变成 ``"pc"``，战前页会认错路线；
    - 远征 / 世界首领战会 ``template_dir.parent`` 之后跨到 ``story`` 取图，
      ``.parent`` 退回纯 ``Path`` 就把覆盖能力断在这一跳上。
    """
    (tmp_path / "arena").mkdir()
    story = _story_layout(tmp_path)
    directory = resolve_template_dir(story, "pc")
    overridden = directory / "skip.png"

    assert directory.name == "story"
    assert str(directory) == str(story)
    # 覆盖只发生在「取图」这一步：解析出的文件路径确实在 pc/ 下 …
    assert str(overridden.parent) == str(story / PC_SUBDIR)
    # … 但目录对象自己仍然代表共享目录。
    assert str(directory.parent) == str(tmp_path)

    sibling = directory.parent / "arena"
    assert isinstance(sibling, TemplateDir)
    assert sibling.backend == "pc"
    assert sibling.name == "arena"


def test_subdirectories_keep_the_override_alive(tmp_path):
    """``root / "hero"`` 之后再拼文件名，覆盖能力不能断（英雄合成走这条路）。"""
    (tmp_path / "hero" / PC_SUBDIR).mkdir(parents=True)
    (tmp_path / "hero" / "filter_button.png").write_bytes(b"shared")
    (tmp_path / "hero" / PC_SUBDIR / "filter_button.png").write_bytes(b"pc")

    hero = resolve_template_dir(tmp_path, "pc") / "hero"

    assert isinstance(hero, TemplateDir)
    assert hero.name == "hero"
    assert (hero / "filter_button.png").read_bytes() == b"pc"

    # 子目录里没放的图照样回落。
    (tmp_path / "hero" / "rating_sss.png").write_bytes(b"shared")
    assert (hero / "rating_sss.png").read_bytes() == b"shared"


def test_resolve_template_agrees_with_the_directory_rule(tmp_path):
    story = _story_layout(tmp_path)

    assert resolve_template(story, "skip.png", "pc") == (
        story / PC_SUBDIR / "skip.png"
    )
    assert resolve_template(story, "select_team.png", "pc") == (
        story / "select_team.png"
    )
    assert resolve_template(story, "skip.png", "emulator") == story / "skip.png"


def test_real_template_root_only_has_the_reviewed_pc_overrides():
    """仓库里只有**审查过的那几张** PC 专属图（2026-11-02 起从"零张"变成"三张"）。

    原来这条叫 ``..._currently_has_no_pc_override``，断言"一张都没有"。2026-11-01
    移植主线时补了三张（见 `docs/PC_TEMPLATE_MIGRATION.md` §2.6），所以改成
    **白名单**：多一张就红，逼着补的人回来说明理由。

    保留原意：没被覆盖的锚点，两个后端解析出来的仍是同一张图
    （即"删掉 PC 门槛分叉不改变模拟器行为"）。
    """
    actual = {
        str(path.relative_to(REAL_ROOT)).replace("\\", "/")
        for path in REAL_ROOT.rglob("*")
        if path.is_file() and path.parent.name == PC_SUBDIR
    }
    assert actual == {
        # 竞技场（2026-11-01）：购买旗帜弹窗三颗锚点在 PC 上认不出，补覆盖图。
        "pc/no_ticket.png",
        "pc/arena_purchase_title.png",
        "pc/arena_purchase_cancel.png",
        # 竞技场（2026-11-02）：点完「战斗开始」后的 VS 段位确认页（PC 独有），
        # 只裁绿色「确认」按钮本身（段位无关），模拟器无此页。
        "pc/arena_vs_confirm.png",
        # 竞技场（2026-11-03）：结算后的「段位提升」弹窗（金牌V > 金牌IV）。
        # 该锚点走 HSV 白掩膜，而 PC 上按钮是暗绿底（V≈93 < 掩膜下界 140）⇒
        # 本体被整片切掉，共享图只剩 0.7536（阈 0.90），整页判 unknown。
        # 补 PC 同名覆盖图后 1.0000；模拟器仍加载共享图，实测 1.0000 不变。
        "pc/rank_confirm.png",
        # 竞技场（2026-11-05）：「升级奖励」弹窗里那行「点击关闭 ∨」。
        # PC 上弹窗**最底部还有一颗半透明「确认」**（属于被弹窗盖住的底层页面），
        # `rank_confirm` 会命中它 ⇒ 点在被盖住的按钮上纹丝不动 ⇒ 42 秒转场超时
        # （11-05 22:28 就是这么失败的；11-04 同坐标却成功过，因为那天底下没有这颗）。
        # 实测：本帧 **1.0000**、点击点 (960,832)；模拟器无此图 ⇒ 仍走老逻辑。
        "pc/rank_close_hint.png",
        # 竞技场（2026-11-02）：购买旗帜弹窗的「100 绿叶→5 旗帜」报价格 + 绿色
        # 「购买」药丸，PC 上两种面板渲染变体都要能自动买绿叶旗继续刷。
        "pc/friendship_ticket_offer.png",
        "pc/ticket_purchase_button.png",
        # 主线（2026-11-01）：「PC 把同一句中文渲染大 4%」这类，补标题覆盖图。
        "story/pc/stamina_popup.png",
        "story/pc/friend_request_title.png",
        # 主线（2026-11-02）：打完一关的「完成故事」弹窗，PC 上 `complete` 只有
        # 0.7996（阈 0.80）——差 0.0004 ⇒ 5 次卡在「等待结算」45 秒超时。
        "story/pc/complete.png",
        # 主线（2026-11-04）：「关卡入口」页右下那颗「准备战斗」。PC 上原样
        # **0.8925**、阈值 **0.90** —— 差 0.0075 ⇒ `story_ready` 判不出来，
        # 导航在「大厅→主线入口」这一步等 95 秒后重试 4 次，整条主线 ✗。
        # 同页同控件按 PC 帧重裁后本帧 1.0000；模拟器帧上它仍是 0.8925，
        # 靠 `_updated` 那张原图拿分（两模板取 max，互不干扰）。
        "story/pc/prepare_battle_updated.png",
        # 主线（2026-11-04 P4）：「完成故事」弹窗底部「点击关闭」标签。**纯点击目标、
        # 不参与判据**（判据仍只看 ``complete`` 文案）。PC 上 ``complete`` 模板中心
        # (1001,395) 落在奖励图标、点了没反应，连点 4 次不推进；改点标签真实中心
        # (965,770) 收工。可选载入：模拟器无此图 ⇒ 原样回落旧点（零改动）。
        "story/pc/complete_close.png",
        # 主线（2026-11-04 下午）：同一颗「准备战斗」按钮在 PC 上有两套渲染，
        # 上午那批帧用旧图 1.0000 / 下午 0.8515，下午裁的这张正好反过来。
        # 两张互为候选、取最高分，阈值 0.90 与白掩膜口径都不变。
        # 全库 565 帧对比：新图过阈而旧图不过的 16 张全是关卡入口页，零冒牌。
        "story/pc/prepare_battle_updated_alt.png",
        # 骑士团捐赠（2026-11-02）：文字类锚点在 PC 上整体掉 0.15~0.3，一页 12 张。
        # 页签只截**文字**（不含蓝色高亮块），否则换页签就认不出（两态都 ≥0.9889）。
        # 支援按钮按真实边界裁（中心 (1680,549)）；原先多裁 20px 背景 ⇒ 点击点落到
        # 按钮下缘外，表现为「点了什么都不发生」（实测踩过）。
        "knights_donation/pc/panel_title.png",
        "knights_donation/pc/tab_resource_support.png",
        "knights_donation/pc/tab_weekly_tasks.png",
        "knights_donation/pc/request_support_button.png",
        "knights_donation/pc/support_one_button.png",
        "knights_donation/pc/points_label.png",
        "knights_donation/pc/claim_button.png",
        "knights_donation/pc/reward_title.png",
        "knights_donation/pc/popup_title.png",
        "knights_donation/pc/flower_cell.png",
        "knights_donation/pc/flower_cell_selected.png",
        "knights_donation/pc/popup_confirm.png",
        # 全局（2026-11-01）：同一类，断线弹窗的文案。
        "global/pc/network_message.png",
        # 全局（2026-11-03）：断线弹窗的「点击重试 ∨」按钮。**只用来定位点击点**
        # （判定仍只看文案）：PC 上这层是全屏横带，屏幕中心落在文案与按钮之间的空白，
        # 连点 4~8 次纹丝不动。跨三帧 0.9434~1.0000，中心恒为 (960,731)。
        "global/pc/network_retry_button.png",
        # 全局（2026-11-05）：断线弹窗**同一句文案的第二种尺寸**（小一号，≈97%）。
        # 00:37 真机主线战斗中掉线：11-01 那张 PC 模板在这一帧只有 **0.6882**（阈 0.88），
        # 守卫看不见这层 ⇒ 战斗监督干等 43 秒报 battle_unrecognized。
        # 证伪：把 11-01 模板缩到 0.97 再打这一帧 ⇒ **0.9335**，说明差异是纯缩放
        # （字高 26 vs 25、字宽 361 vs 346），不是换了句话。
        # 新图本帧 1.0000；全库次高 0.6842（都是别的弹窗帧）。
        # 只放 pc/：模拟器侧不存在该文件 ⇒ None ⇒ 判定集合不变。
        "global/pc/network_reconnect_message.png",
        # 全局（2026-11-05）：断线弹窗**另一句文案（乙「与服务器的连接已中断。」）的 PC 版**。
        # 共享目录那张是模拟器尺寸：文字宽 291、高 27；PC 上同一句话被拉宽到 303、
        # 高 26 ⇒ **只有横向放大，不是等比缩放**，所以扫缩放救不了它
        # （按 1.04 倍重采样峰值只到 0.8629，阈 0.88；共享模板原样 0.6300）。
        # 后果：2026-11-03 21:37 英雄合成点完「确认合成」掉线，守卫看不见这层横带 ⇒
        # 状态机把半透明遮罩下的返回箭头当成「合成结果覆盖层未完整识别」⇒ 整条路线失败，
        # 收尾连按 ESC 也无效（22:22 那次同形状）。
        # 实证：真机帧重裁后本帧 **1.0000**（中心 960,536）；全库 2588 张扫描，
        # 过阈 0.88 的 10 张**全是真·断线现场**（timeout_imprint_confirm /
        # return_home_v2_esc_no_effect / story_exit_1），正常页面零过阈。
        # 只放 pc/：模拟器解析到共享目录那张，判定集合不变。
        "global/pc/network_disconnected_message.png",
        # 全局（2026-11-05）：「骑士团活动」整屏页（左上标题 + 底部「✕ 点击关闭」）。
        # 骑士团捐赠跑完停在「每周任务」标签，PC 上 **ESC 关不掉这一页**（它不是弹窗），
        # 收尾连按 2 次 ESC 纹丝不动 ⇒「回首页失败」⇒ **整条每日任务链中止，
        # 后面四条一条都没跑**（22:35 那次就是这么断的）。
        # 实测：本帧标题+关闭 **1.0000**、点击点 (979,1092) 落在「点击关闭」上。
        # 只放 pc/：模拟器加载成 None ⇒ 整段跳过（模拟器 ESC 本来就能退）。
        "global/pc/knights_activity_title.png",
        "global/pc/knights_activity_close.png",
        # 支线故事（2026-11-05）：Episode 详情页那颗绿色「冒险」按钮，整颗裁。
        # 旧图在真实详情页上只有 **0.4963**（阈 0.82）⇒ 认不出 ⇒ 点击打在空白处，
        # 画面不动、60 秒超时（交接文档记的「卡在关卡入口」就是它）。
        # 新图本帧 1.0000、中心 (1647,1045) 正是按钮中心；反例：海报页 0.1666、战斗页 0.1395。
        "side_story/pc/adventure.png",
        # 支线故事（2026-11-05）：场景页「重新进行」。**余量问题，不是认不出** ——
        # 共享模板在两帧真实场景页上分别是 0.8278 / 0.8096，阈值 0.82 正好夹在中间 ⇒
        # 表现是「有时能接下一关、有时打完一关直接收工」。
        # 新图两帧 1.0000 / 0.9394（余量 0.12），反例 0.3869 / 0.3326。
        "side_story/pc/replay.png",
        # 支线故事（2026-11-06）：PC「快速入场」多出的**期次主页**中间层，
        # 右侧「故事/奖励/PV」三颗标签。两张图只放 pc/（模拟器侧 builder 拿到
        # 空元组 ⇒ 判据整体不启用）。裁的是两枚固定功能标签：白色「奖励」纸带
        # 420x105 @(1400,690)、黑色「PV」胶片条 220x130 @(1470,810)；不碰
        # 本期徽章 / 期间日期 / 跑马灯这些会变的内容。
        # 全库 366 张负例扫描（含 5 张**同期美术**但右侧是菜单的 hub 页）：
        # 天花板 0.4285 / 0.5288，同期 hub 页 0.3668 / 0.3629 ⇒ 阈值 0.80。
        "side_story/pc/event_home_reward.png",
        "side_story/pc/event_home_pv.png",
        # 活动剧情（2026-11-05）：左上角「观看故事」标题。**白掩膜也救不了它** ——
        # 共享模板在真机帧上只有 **0.5628**（阈 0.85），PC 字形渲染不同。
        # 认不出这一页，状态机就不知道「起点在哪」，表现是**启动后一声不响地干等**
        # （不是报错，是静默无动作，用户看到的就是「点了开始没反应」）。
        # 新图本帧 1.0000、中心 (179,97)；反例：支线海报页 0.6240、Episode 详情页 0.6332。
        "activity_story/pc/watch_story_title.png",
        # 主线（2026-11-05）：活动战斗进的那个「准备战斗」页。**不是主线那种布局** ——
        # 左侧多一个「故事队伍」标签，导致旧图（共享 `prepare_battle` 410x140）与
        # PC 备用版（`prepare_battle_updated` 300x75）在这页上**双双未命中**。
        # 实测：旧图+备用版 未命中；新图在真实判据（双候选 + 白掩膜）下 **1.0000**、
        # 中心 (1715,1058)；反例：支线海报页 0.0049、Episode 详情页 0.4194。
        # ⚠️ 安全性：`find_prepare_battle_button` 是「双候选取最高分」，主线队伍页
        # 仍由 `prepare_battle_updated`(+`_alt`) 兜住，补这张**不影响主线**。
        "story/pc/prepare_battle.png",
        # 全局（2026-11-03）：游戏按时间自己弹的两条 —— 「日期变更，将前往大厅。」
        # 与每日「获得登录奖励」。都是**必须点底部「点击关闭」**的层，不吃 ESC：
        #   变更日期 ⇒ 画面被强制切回大厅 ⇒ 主线「等待通关」46 秒无进展超时；
        #   登录奖励 ⇒ 收尾连按 2 次 ESC 页面不动 ⇒「回首页失败」。
        # 标题排他实测（全库 364 张）：0.5517 / 0.5703，阈值 0.82。
        "global/pc/date_change_title.png",
        "global/pc/date_change_close.png",
        "global/pc/login_reward_title.png",
        "global/pc/login_reward_close.png",
        # 导航（2026-11-02）：大厅左侧「圣域」入口标签，PC 原样 0.7457（阈 0.82）。
        "navigation/pc/lobby_sanctuary.png",
        # 导航（2026-11-04）：迷宫强化石「战斗」菜单的「一般」页签在 PC 上原样只有
        # 0.7344（阈 0.82），且 (100,165,250,105) 区域比 240x90 的共享模板只大 10x15px，
        # 真机页签中心 (243,229) 滑不到 → 迷宫卡在「赛季菜单缺 battle_general_tab」。
        # 重裁 96x54、只含「一般」灰底页签（不含「赛季」蓝高亮 / 橙点 / 第三页文字），
        # region 内 1.0000；全库 339 张夹具仅 4 张真·一般页命中（0.90），零误报。
        "navigation/pc/battle_general_tab.png",
        # 月光剧场（2026-11-04 下午）：「特别的时间之书」按钮也有两套渲染，
        # 11-02/11-04 下午帧用第二张 1.0000、11-04 早上帧用第一张 1.0000，
        # 互比只有 0.7720（阈 0.82）。全库 517 帧扫描：非支线故事页最高 0.6024。
        "navigation/pc/side_story_special_book_alt.png",
        # 圣域收菜（2026-11-02）：全是小号中文文字锚点，PC 上原样 0.62~0.83。
        "sanctuary/pc/forest_row.png",
        "sanctuary/pc/forest_title.png",
        "sanctuary/pc/claim_text.png",
        "sanctuary/pc/popup_close.png",
        # ── 2026-11-02 夜间 PC 移植（用户要求先放行、由他自测）─────────────
        # 大厅三个入口：战斗 / 支线故事 / 支线故事页的「特别的时间之书」。
        "navigation/pc/lobby_battle.png",
        "navigation/pc/lobby_side_story.png",
        "navigation/pc/side_story_special_book.png",
        # 英雄合成：刻印结果覆盖层（标题 + 点击关闭）。
        # ⚠️ 同一张图要**放两处**：evidence 走 ``hero/xxx.png``（根 templates ⇒
        # ``templates/pc/hero/``），工厂走 ``templates/hero`` + ``/xxx.png``（⇒
        # ``templates/hero/pc/``）。两套路径不一致，只放一处会「诊断认得出、实跑认不出」
        # （实测踩过）。本表只登记 ``*/pc/*.png`` 这一种形态，所以只列 hero/pc/ 那两个；
        # ``templates/pc/hero/`` 那份同样必须存在，但不在本测试的收集口径里。
        "hero/pc/imprint_result_title.png",
        "hero/pc/imprint_result_close.png",
        # 英雄合成：传送完成后的「获得奖励」层与全局「获得奖励」通知是同一套 UI，
        # 守卫被关掉后改由状态机自己认（PC 文字锚点掉分 ⇒ 必须补 PC 覆盖图）。
        "hero/pc/transmit_reward_title.png",
        "hero/pc/transmit_reward_close.png",
        # 月塔：入场按钮 / 阶段确认弹窗 / 楼层列表的「选择队伍」。
        "tower/pc/home_enter.png",
        "tower/pc/reset_confirm_title.png",
        "tower/pc/floor_select_team.png",
        # 2026-11-03：战斗菜单「赛季」页签（只截文字 58x30）+ 战斗菜单一般页的
        # 三选一装置提示（模拟器原样只有 0.5581，补后 1.0000）。
        "navigation/pc/expedition_season_tab.png",
        "tower/pc/card_hint.png",
        # 2026-11-05：月塔本阶段 25 层全占领后，楼层列表右下角按钮从「选择队伍」
        # 变成「编队」。判据是**同槽位换文字**：两枚模板落点中心都是 (1744,1040)、
        # 尺寸都是 280x76，只差文字 ⇒ 不存在「认错地方」这种解释。
        # 现场帧 1.0000；全库 2186 张 PC 帧只有那一张命中（次高 0.6953），
        # 392 张模拟器夹具最高 0.7567。
        # ⚠️ 只放 pc/：模拟器侧按「文件不存在」走可选加载（`_load_floor_team_edit`
        # 返回 None），两个判断点全部短路 ⇒ 模拟器行为逐字节不变。
        "tower/pc/floor_team_edit.png",
        # 准备战斗页的两个主判据（2026-11-03 补，模拟器原样 0.9397 / 0.9078 都差一点）。
        "tower/pc/prepare_title.png",
        "tower/pc/team_battle_start.png",
        # 三选一装置页的「决定装置」按钮（2026-11-03 23:44 实跑卡死后补）。
        # 共享图在 PC 上 **0.8668**（阈 0.88）—— 差 0.0132，看着像就是过不去，
        # 后果不是报错而是**静默判不出页**：``observe_battle`` 的 ``result_visible``
        # 要求「决定装置 + 提示文案」同时命中，于是监督干等 45 秒报
        # ``battle_unrecognized``；接着回家流程在这一页按 ESC 也无效（这页不响应它们），
        # 整条每日任务以「无法回到首页」中止。补图后两张现场帧都是 **1.0000**。
        # ⚠️ 几何与共享图一致（340x66，中心 (1138,1041) = ``_POINT_DECIDE``），
        # 所以按钮选中/未选中两态都能命中（模拟器实测 1.0000 vs 0.9753）。
        "tower/pc/card_decide.png",
        # 支线故事主页：左下「快速入场」（右下「冒险」已在上方 adventure.png 条目登记）。
        "side_story/pc/quick_entry.png",
        # 2026-11-03：迷宫强化石整条打通（买了 3 块强化石）。
        # ⚠️ region_row1_label 配套放宽了 region（990,400,400,360）——PC 上「1 区域」
        # 在 y≈467，原 region 从 555 起 ⇒ 锚点只能乱匹配到 621，导致误判"1 区域已选中"、
        # 实际进了 2 区域、地图里找不到商人出口。详见 playbook 坑 13。
        "labyrinth_stone/pc/labyrinth_card.png",
        "labyrinth_stone/pc/labyrinth_entry.png",
        # 迷宫（2026-11-06）：列表页卡片「混乱的提雷尔城」的**第二种画法**。
        # 用户有 5 个进行中的迷宫时，点卡片会先进「迷宫列表」让选（不是直接进详情），
        # 那页的卡片与 11-03/11-04 那批夹具长得不同：旧图 0.7138、新图 1.0000。
        # ⚠️ 但旧图在夹具上是 1.0000，**两张都不能少** —— 页面判据用 `any_of` 任一命中。
        # 实测交叉：从夹具裁的图在实跑页 0.7677、从实跑页裁的在夹具 0.7533（互不过阈，不打架）。
        "labyrinth_stone/pc/labyrinth_entry_alt.png",
        # 全局（2026-11-06）：「无法控制」剧情弹窗（主线关卡入口页会被它整页盖住）。
        "global/pc/uncontrollable_title.png",
        "global/pc/uncontrollable_close.png",
        # 刷书签（2026-11-06）：同一颗「购买」按钮在不同行分数差别大，加一张备选两取最高。
        "shop_refresh/pc/buy_button_alt.png",
        "labyrinth_stone/pc/select_team_button.png",
        "labyrinth_stone/pc/region_row1_label.png",
        "labyrinth_stone/pc/region_selected_box.png",
        "labyrinth_stone/pc/battle_start_button.png",
        "labyrinth_stone/pc/map_button.png",
        "labyrinth_stone/pc/pause_title.png",
        "labyrinth_stone/pc/giveup_button.png",
        "labyrinth_stone/pc/teleport_title.png",
        "labyrinth_stone/pc/shop_footer.png",
        "labyrinth_stone/pc/buy_dialog_title.png",
        # 2026-11-03：月光剧场「分集页」的「进行观览」按钮（模拟器原样 0.6935）。
        "moonlight_theater/pc/watch_button.png",
        # 2026-11-05：分集页**左上返回箭头**。模板本身没问题，问题在搜索区 ——
        # 证据画像的 region (0,20,180,110) 是按模拟器量的（箭头 bbox y 75~127），
        # PC 上箭头整体往右下挪到 y 88~138 ⇒ **下沿被切掉 8px**，白掩膜从 0.92 掉到
        # 0.2035（00:35 真机 timeout_episode）。配套动作：`_PC_REGION_OVERRIDES`
        # 把 PC 搜索区放宽到 (0,40,240,160)，两帧 PC 分集页都回到 1.0000。
        # ⚠️ 只放 pc/：模拟器仍用共享图 + 共享 region（episode_fresh 0.9198 不动）。
        "moonlight_theater/pc/back_button.png",
        "moonlight_theater/pc/guide_title.png",
        # 英雄合成（2026-11-03）：满 SSS 的刻印印记。PC 上这一块整体左移
        # （落点 x≈45，模拟器模板在 x≈261），且渲染不同 ⇒ 共享图在全屏也只有
        # 0.5593（阈 0.90）。**后果不是报错而是静默判错**：满 SSS 的英雄被当成
        # 「非 SSS」，进去加材料、加不动、原地死循环（16:51 的穆卡察）。
        # 配套设施：`evidence/hero_synthesis.REGIONS["rating_sss"]` 从
        # (130,435,180,130) 放宽到 (30,380,400,250)，否则新图左边 85px 会被裁掉。
        "hero/pc/rating_sss.png",
        # 世界首领战（2026-11-03 PC 移植）：**PC 压低的是「文字」类锚点，不是图形类**。
        # 同一条路线上的实测对照足以定案 —— 图形锚点 ``navigation/worldboss_entry``
        # （骷髅盾牌）在 PC 帧上 0.9936~0.9940 分文不动，而文字锚点整片塌下来：
        #   knights_title 0.7858 / worldboss_title 0.6674 / select_team_button 0.6648，
        # 都过不了 0.80 门槛。所以这里**不动口径、不动阈值**（低通 σ=2.0 虽然能把
        # 分数抬到 0.86~0.88，但全库审计显示它把跨页分也一并抬高 ~0.2，
        # 例如 result_title 在奖励弹窗上 0.7103→0.9305，等于拿判据余量换分数）。
        # 改为补 PC 同名图：模拟器行为一个字节不变，PC 上直接回到 1.0000。
        #   · select_team_button —— 只截「选择队伍」四个字，**不含左侧 1/2·2/2 徽章**
        #     （跨场次会变，且 PC 上是黄字、模拟器模板里是青字）；
        #   · knights_title —— 只截「骑士团」三字，不含背箭头与 ? 图标；
        #   · team_select_title —— 只截「选择辅助队伍」整行标题。
        # 验证：四张跨两天的 PC 帧上 1.0000，非本页 PC 帧 0.19~0.47；
        # 反向拿 PC 图打模拟器同页帧（低通）0.66~0.88，证明抓的是同一个控件。
        "world_boss/pc/knights_title.png",
        "world_boss/pc/select_team_button.png",
        "world_boss/pc/team_select_title.png",
        "world_boss/pc/team_config_auto.png",
        # 战斗页「跳过 」：只在 ``BATTLE_SKIP_REGION``（x<1760）里找 —— 剧情播放页
        # 也有同一张图形，但位置在 x≈1769~1886，窗口宽度本身就是判据的一部分。
        # PC 原样 0.6997（阈 0.80）⇒ 战斗整段认不出、45 秒看门狗收场；补图后
        # 战斗帧 0.88~1.00、剧情帧 0.25、暂停菜单下仍算战斗。
        "world_boss/pc/battle_skip.png",
        # 结算页右上「战斗结果」：PC 原样整页 unknown（监督靠它判「打完了」）。
        # ⚠️ 奖励弹窗是压暗的结算页，这颗锚点在那上面也会高分 —— 排他仍由
        # ``world_boss.result`` 的 ``forbidden=("level_reward_title",)`` 负责。
        "world_boss/pc/result_title.png",
        # 「战斗级别奖励」弹窗标题：点「跳过」后游戏**直接**弹它，不经过结算页。
        # PC 原样整页 unknown ⇒ 状态机在弹窗上反复点「确认」白转。
        "world_boss/pc/level_reward_title.png",
        # 2026-11-04：两张 PC 专属判据图从共享目录挪进各自 pc/ 子目录，
        # 模拟器不再加载它们（判页保持改动前的单维口径）。
        "labyrinth_stone/pc/region1_completed.png",
        "tower/pc/tower_home_title.png",
        # 2026-11-04：英雄合成「列表页满 SSS」印记是 PC 新增判据图，只放
        # hero/pc/；模拟器侧按「文件不存在」走可选加载，不注册该原子。
        "hero/pc/rating_sss_list.png",
        # 2026-11-04：4 类新增全局弹窗的 8 张图从共享 global/ 挪进 global/pc/。
        # 图都是从 PC 帧裁的、仓库里没有模拟器样本；用户拍板「B 类纯新增也挂 PC
        # 开关」。模拟器侧 loader 有存在性守卫 ⇒ 解析不到共享图就返回 None，
        # handler 直接跳过该类弹窗，不再无条件加载。
        "global/pc/gift_claim_title.png",
        "global/pc/gift_claim_close.png",
        "global/pc/account_rank_up_title.png",
        "global/pc/account_rank_up_close.png",
        "global/pc/side_story_notice_title.png",
        "global/pc/side_story_notice_close.png",
            "global/pc/reward_notice_title.png",
            "global/pc/reward_notice_close.png",
            # 2026-11-06：「轻触后解锁」教学遮罩（主线 Episode 4 第 11 关）。
            # 三张都是 PC-only：title 是排他判据（黑框左半，不含角色名），
            # skip / highlight 只定位点击点，不参与判据。模拟器加载成 None。
            "global/pc/tutorial_unlock_title.png",
            "global/pc/tutorial_skip_button.png",
            "global/pc/tutorial_highlight_icon.png",
            # 2026-11-06 17:29 批量四条独立 ✗ 的 PC 覆盖图（代码零改动那两条）。
            # ① 英雄合成「自动选择」：PC 把这四个字渲染成另一套字形，共享图
            #    全屏最高只有 0.6953（阈 0.85）⇒ 传送选择页判据缺一角，
            #    ``_transmit_page_ready`` 恒 False、open_transmit 目标页超时。
            # PC 图在两轮真机的传送选择页都是 1.0000；2360 张 PC 诊断帧
            # 只有那两张正例过 0.85，负例最高 0.2866。
            "hero/pc/auto_select_label.png",
            # ② 竞技场「升级奖励」弹窗：这颗全局弹窗 2026-10-20 就接好了
            #    （标题 + 点击关闭双锚点），但两张图是模拟器字形，在 PC 帧上
            #    只有 0.6604 / 0.6861（阈 0.88）⇒ 守卫不出手、干等 45 秒。
            #    补 PC 图后两锚点各 1.0000，点击点 (962,832)。
            "navigation/pc/arena_rank_reward_title.png",
            "navigation/pc/arena_rank_reward_close.png",

    }, actual

    shared = resolve_template_dir(REAL_ROOT)
    pc = resolve_template_dir(REAL_ROOT, "pc")

    # 没被覆盖的锚点，两边解析到同一张图
    assert shared / "story" / "skip.png" == pc / "story" / "skip.png"
    assert shared / "arena" / "battle_start.png" == pc / "arena" / "battle_start.png"
    # 被覆盖的，PC 端要真的指到 pc/ 那一份
    assert pc / "story" / "stamina_popup.png" == (
        REAL_ROOT / "story" / "pc" / "stamina_popup.png"
    )


def test_no_platform_threshold_table_is_left_in_the_business_code():
    """平台门槛表不许复活。

    以前 7 个证据模块各有一张 ``PC_THRESHOLD_OVERRIDES`` 加一个 ``thresholds_for()``，
    另有就地写死的 ``if backend == "pc"``。它们让「改 PC」变成满仓库找分叉，
    而且实测（``runtime_logs/pc_template_scores.md``）那些放宽几乎救不回任何锚点 ——
    只是把「认不出」推迟成「认错」。这里扫源码把它们钉死在门外。

    ⚠️ 只扫**真代码**：``evidence/arena.py`` 等处的 docstring 里会点名
    ``PC_THRESHOLD_OVERRIDES`` 解释「为什么删掉它」，那是说明不是复活。
    所以先把注释和字符串 token 剔掉再扫（同 ``route_metadata`` 用 AST 而不是
    文本匹配的道理一样：文本匹配会把文档里的话当成真代码）。
    """
    banned = (
        "PC_THRESHOLD_OVERRIDES",
        "PC_DEFAULT_THRESHOLD",
        "thresholds_for",
        'backend == "pc"',
        "supported_backends",
        "validate_backend",
    )
    offenders = []
    for path in sorted(GAMES.rglob("*.py")):
        if path.name == "template_paths.py":
            # 唯一「认识 pc 这个概念」的模块，它的文档里会点名这些历史名字。
            continue
        code = _code_only(path.read_text(encoding="utf-8"))
        for token in banned:
            if token in code:
                offenders.append(f"{path.relative_to(GAMES.parent)}: {token}")

    assert [] == offenders


def _code_only(source: str) -> str:
    """去掉注释与所有字符串字面量，只留真正的代码文本。"""
    import io
    import tokenize

    kept: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return "\n".join(kept)
