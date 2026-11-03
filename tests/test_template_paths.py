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
        # 月塔：入场按钮 / 阶段确认弹窗 / 楼层列表的「选择队伍」。
        "tower/pc/home_enter.png",
        "tower/pc/reset_confirm_title.png",
        "tower/pc/floor_select_team.png",
        # 2026-11-03：战斗菜单「赛季」页签（只截文字 58x30）+ 战斗菜单一般页的
        # 三选一装置提示（模拟器原样只有 0.5581，补后 1.0000）。
        "navigation/pc/expedition_season_tab.png",
        "tower/pc/card_hint.png",
        # 准备战斗页的两个主判据（2026-11-03 补，模拟器原样 0.9397 / 0.9078 都差一点）。
        "tower/pc/prepare_title.png",
        "tower/pc/team_battle_start.png",
        # 支线故事主页：左下「快速入场」+ 右下「冒险」。
        "side_story/pc/quick_entry.png",
        "side_story/pc/adventure.png",
        # 2026-11-03：迷宫强化石整条打通（买了 3 块强化石）。
        # ⚠️ region_row1_label 配套放宽了 region（990,400,400,360）——PC 上「1 区域」
        # 在 y≈467，原 region 从 555 起 ⇒ 锚点只能乱匹配到 621，导致误判"1 区域已选中"、
        # 实际进了 2 区域、地图里找不到商人出口。详见 playbook 坑 13。
        "labyrinth_stone/pc/labyrinth_card.png",
        "labyrinth_stone/pc/labyrinth_entry.png",
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
        "moonlight_theater/pc/guide_title.png",

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
