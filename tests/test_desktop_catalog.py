import pytest

from auto_game_unified.desktop import catalog
from auto_game_unified.desktop.catalog import (
    BACKENDS,
    GROUPS,
    PC_READY_ROUTES,
    PRODUCT_NAME,
    ROUTES,
    group_description,
    route_by_name,
    visible_backends,
)


def test_the_pc_backend_is_back_on_the_ui():
    """PC 客户端 2026-11-01 重新露面：竞技场已通过 PC 真机验收。"""
    assert visible_backends() == ("emulator", "pc")
    assert BACKENDS == ("emulator", "pc")


def test_pc_ready_routes_only_names_verified_ones():
    """界面只放行**已验收**的路线 ⇒ 这条名单必须写真凭实据，不许写「估计能跑」。

    加一条进来的唯一依据：按 `docs/PC_TEMPLATE_MIGRATION.md` 第 3 节走完五步验收。
    """
    assert "arena" in PC_READY_ROUTES
    for mode in PC_READY_ROUTES:
        assert route_by_name(mode) is not None


def test_catalog_lists_every_route_in_menu_order():
    assert PRODUCT_NAME == "第七史诗自动助手"
    assert [route.mode for route in ROUTES] == [
        "hero_synthesis",
        "story",
        "arena",
        "expedition",
        "tower",
        "fodder",
        "side_story",
        "shop_refresh",
        "survivor",
        "activity_story",
        "world_boss",
        "knights_donation",
        "labyrinth_stone",
        "sanctuary",
        "community",
        "moonlight_theater",
        "achievement",
        "story_star",
    ]
    # 2026-10-20 用户拍板：路线不再分「正式 / 实验」—— 十五条他都实机验证过了。
    # 这条守着「分级彻底没有」：字段、属性都不该回来（不是把值都改成「正式功能」）。
    assert all(not hasattr(route, "status") for route in ROUTES)
    assert all(not hasattr(route, "experimental") for route in ROUTES)


def test_community_warns_about_daily_limits():
    """社区签到：界面上必须写清两件事。

    ① 这条路线有一半在**竖屏**（用户得知道点下去画面会转过去）；
    ② 它点的东西**多数一天只能点一次**（签到 / 三条任务 / 三样兑换各有每日上限），
       所以**不能拿它当冒烟测试反复跑** —— 重复跑不报错、但什么也领不到，
       用户会以为程序坏了。界面上得先把这个预期讲明白。

    （2026-10-07 之前这条断言写的是「必须说明现在只能空跑」，
    那天真机数据采齐、实跑闸门放开，断言随之改成上面的两句。）
    """
    community = route_by_name("community")

    assert community.label == "社区签到"
    assert community.cycles_editable is False
    assert "竖屏" in community.description
    assert "每日上限" in community.description


def test_survivor_explains_the_manual_entry_page():
    survivor = route_by_name("survivor")

    assert survivor.label == "活动"
    # 起点是用户人工停好的页面，必须写在界面上让人看得见。
    assert "选第一张卡" in survivor.description
    # 平台限制**不逐条写进路线说明**：放行范围由 ``PC_READY_ROUTES`` 决定、
    # 启动时由 ``STARTUP_HINTS`` 统一说明。逐条写「只支持模拟器」正是这里历史上
    # 反复过期的原因（PC 放行后没人回来改文案）。改为校验真正的业务前提：
    # 这条不从大厅导航进入，因此不能与别的路线一起勾。
    assert "不可与其它路线同时勾选" in survivor.description


def test_shop_refresh_explains_cycle_semantics():
    shop = route_by_name("shop_refresh")

    # 用户 2026-09-29 拍板：默认 **0 次** —— 秘密商店自己会随时间自动刷新，
    # 每天进店扫一遍、把自动刷出来的买掉就行，0 次不花天空石。
    assert shop.default_cycles == 0
    assert shop.min_cycles == 0
    # 2026-10-20 改写说明（去掉「付费刷新」「初始页面」这类偏实现的措辞）时，
    # 断言跟着换成语义等价的锚点：**默认不刷新**、**刷新要花天空石**、
    # **商店自己会刷新**这三件事必须还写在界面上。
    assert "0 次" in shop.description
    assert "天空石" in shop.description
    assert "刷新" in shop.description
    # 「0 次」这条口子只开给刷书签，别的路线照样必须为正。
    for route in ROUTES:
        if route.mode != "shop_refresh":
            assert route.min_cycles == 1, f"{route.mode} 的次数下限不该被改动"


def test_hero_synthesis_is_fixed_to_one_cycle():
    hero = route_by_name("hero_synthesis")
    assert hero.default_cycles == 1
    assert hero.cycles_editable is False


def test_world_boss_explains_the_resource_boundary():
    world_boss = route_by_name("world_boss")

    assert world_boss.label == "世界首领战"
    # 「每次 20 体力」和「不会用钻石」是用户定的红线，必须写在界面上让人看得见。
    assert "20 体力" in world_boss.description
    # 生命之叶是游戏内的正式名称（``StaminaExhausted.stop_label`` 同此），
    # 2026-11-13 统一文案时把旧的简写「树叶」改回正式名称。
    assert "生命之叶" in world_boss.description


def test_world_boss_is_fixed_to_two_cycles():
    """每天就 2 次，用户明确要求「不要让我选择次数」。"""
    world_boss = route_by_name("world_boss")

    assert world_boss.default_cycles == 2
    assert world_boss.cycles_editable is False
    # 用户看得见的说明里要写清「每天 2 次」，否则置灰的输入框会被当成坏了。
    assert "2 次" in world_boss.description


def test_knights_donation_is_fixed_to_one_pass():
    """每天跑一遍就够，用户明确要求「不要让我选择次数」。"""
    donation = route_by_name("knights_donation")

    assert donation.label == "骑士团捐赠"
    assert donation.default_cycles == 1
    assert donation.cycles_editable is False
    # 界面上要能看见「干什么」和「怎么结束的」，否则用户不知道它会自己收工。
    # 2026-10-20 改写说明时为「资源支援页 / 每周任务页」两段，断言跟着换成语义等价的锚点。
    assert "资源支援" in donation.description
    assert "每周任务" in donation.description
    # ⚠️ 用户 2026-09-24 更正：有没有红点都要进 ⇒ 界面上不许再写「没红点就结束」。
    assert "红点" not in donation.description
    # 一天只能请求一次支援是用户定的红线，必须写在界面上。
    assert "每日请求一次" in donation.description


# --------------------------------------------------------------------------
# 说明文字的统一规格（2026-10-20 用户：「说明都很古老了…至少写个几行」）
# --------------------------------------------------------------------------


def test_every_route_description_explains_itself():
    """每条说明都要讲清「干什么 / 你能决定什么 / 注意什么」。

    用户原话（2026-10-20）：「用户不关心你是靠什么识别的…他只关心这个运行的时候
    他在做什么事儿…我能不能自己挑对手啊，我能不能根据战斗力识别对手，我能不能
    调整队伍阵容」。所以第 2 段必须交代「哪些我能定、哪些它替我决定了」。
    """
    for route in ROUTES:
        text = route.description
        where = f"路线 {route.mode} 的说明"

        # 三段式：第 1 段干什么，第 2 段「一轮 = …」+ 能不能自己改，第 3 段「注意：」。
        assert text.count("\n") >= 2, f"{where}没分段，至少要三段"
        # 「一轮到哪儿」这件事必须写清。2026-11-13 改说明体后多出两种等价表述
        # （「一次运行完成…」「每日执行一次即结束」），断言接受这四种，但要求
        # 至少命中一个 —— 不许一条都不写。
        assert any(word in text for word in ("一轮", "一遍", "一次运行", "执行一次")), (
            f"{where}没写清一轮跑到哪儿"
        )
        assert "注意：" in text, f"{where}缺「注意：」那一段"

        # ⚠️ 这段文字直接进 tk 的 Label，写 `**重点**` 会原样显示成星号。
        assert "**" not in text, f"{where}里混进了 Markdown 星号"

        # 「几行」但「不能太多字」：上限按 200 字控住，再长就该搬进维护手册。
        assert len(text) <= 200, f"{where}有 {len(text)} 字，用户要求简明"


#: 界面文案里不许出现的词：这是给玩家看的，不是给写代码的人看的。
#:
#: 用户 2026-10-20 两次收紧：「不要出现代码术语，什么冒烟测试」，
#: 以及「用户不关心你是靠什么识别的…你要跳出技术，回到业务去」。
#: 所以除了实现术语，**描述识别动作的词也一并禁掉**（识别 / 判定 / 坐标 / 按钮）——
#: 要写业务结果（「战斗动画自动跳过」），不写它是怎么认出来的。
CODE_JARGON = (
    "冒烟",
    "报错",
    "阈值",
    "模板",
    "锚点",
    "状态机",
    "字段",
    "参数",
    "变量",
    "函数",
    "接口",
    "日志",
    "重试",
    "轮询",
    "断言",
    # 识别动作 —— 玩家不关心它是靠什么认出来的。
    "识别",
    "判定",
    "坐标",
    "按钮",
    "检测",
    "代码",
    "程序",
    "算法",
    # 2026-11-13 改说明体时补：这些是操作方式或内部概念，不是业务结果。
    "滚轮",
    "拖拽",
    "素材",
    "后端",
    "转场",
)


def test_the_interface_text_never_leaks_code_jargon():
    """说明区是给人看的：不许出现「冒烟测试」这类只有写代码的人懂的词。

    这条也覆盖分组说明 —— 它们和路线说明进的是同一个 Label。
    """
    texts = [("路线 " + route.mode, route.description) for route in ROUTES]
    texts += [("分组 " + group, group_description(group)) for group in GROUPS]

    for where, text in texts:
        for word in CODE_JARGON:
            assert word not in text, f"{where} 的说明里出现了代码术语「{word}」"


def test_every_group_explains_what_ticking_it_does():
    """分组说明：这一组是什么节奏 + 点这个框会发生什么。

    ⚠️ 用户 2026-10-20 要的就是这一段 —— 点「每日 / 按需 / 赛季」前面的框时，
    说明区要给这几组各自的说明，不是组里路线的说明。
    """
    for group in GROUPS:
        text = group_description(group)
        where = f"分组 {group} 的说明"

        assert text, f"{where}是空的"
        assert text.count("\n") >= 2, f"{where}没分段"
        # 2026-11-13 改说明体：原文「点这个框 = …」属口语加法号，改成陈述句
        # 「勾选分组标题可整组选中」。断言跟着换成新的表述。
        assert "勾选分组标题" in text, f"{where}没写清勾选分组标题会做什么"
        assert "**" not in text, f"{where}里混进了 Markdown 星号"
        assert len(text) <= 160, f"{where}有 {len(text)} 字，太长了"


def test_unknown_group_has_no_description():
    """拼错的分组名要当场炸，不能返回空字符串让界面显示一片空白。"""
    with pytest.raises(ValueError):
        group_description("每周")


# --------------------------------------------------------------------------
# 「每日任务」面板的三分组 + 批量勾选（用户 2026-10-08 拍板）
# --------------------------------------------------------------------------


def test_groups_are_defined_in_display_order():
    """四个分组名与它们的展示顺序。

    ⚠️ 这里**写死**中文名与顺序，不从实现里读 —— 否则改实现时断言跟着改，
    等于没护栏。分组的顺序就是面板上从上到下的顺序。

    依据用户 2026-10-18 的原话：「最终就是四类：每日、按需、赛季、活动」。
    """
    assert catalog.GROUP_DAILY == "每日"
    assert catalog.GROUP_ONDEMAND == "按需"
    assert catalog.GROUP_SEASON == "赛季"
    assert catalog.GROUP_EVENT == "活动"
    assert catalog.GROUPS == ("每日", "按需", "赛季", "活动")


def test_every_route_belongs_to_exactly_one_known_group():
    for route in ROUTES:
        assert route.group in catalog.GROUPS, f"{route.mode} 的分组 {route.group!r} 不认识"


def test_group_membership_is_what_the_user_asked_for():
    """分组归属：**写死一份真值表**，不遍历实现。

    依据用户 2026-10-18 的口述：
      - 「英雄合成、主线、狗粮、支线故事、月光剧场，这几个都是按需」；
      - 「剩下的就是每日」；
      - 赛季（会轮换的远征 + 月塔）与活动（survivor）沿用 2026-10-08 的结论；
      - 活动剧情（2026-10-31 新增）与活动小游戏同属**限时活动** ⇒ 活动组。
    """
    expected = {
        catalog.GROUP_DAILY: [
            "arena",
            "shop_refresh",
            "world_boss",
            "knights_donation",
            "labyrinth_stone",
            "sanctuary",
            "community",
            "achievement",
        ],
        catalog.GROUP_ONDEMAND: [
            "hero_synthesis",
            "story",
            "fodder",
            "side_story",
            "moonlight_theater",
            "story_star",
        ],
        catalog.GROUP_SEASON: ["expedition", "tower"],
        catalog.GROUP_EVENT: ["survivor", "activity_story"],
    }
    for group, modes in expected.items():
        assert [route.mode for route in catalog.routes_in_group(group)] == modes


def test_grouped_routes_returns_display_order_and_skips_empty_groups():
    grouped = catalog.grouped_routes()

    assert [group for group, _ in grouped] == ["每日", "按需", "赛季", "活动"]
    # 四组摊平之后必须一条不漏、一条不重。
    #
    # ⚠️ 断言的是**集合**相等，不是「等于 `ROUTES` 的书写顺序」—— 两者本就
    # **故意不同**：分组渲染会把「赛季」那两条提到「按需」全组之后，
    # 而 `ROUTES` 里 `expedition` 写在 `fodder` 前面。要求顺序一致等于
    # 要求「分组不起作用」，是自相矛盾的。
    flattened = [route.mode for _group, routes in grouped for route in routes]
    assert sorted(flattened) == sorted(route.mode for route in ROUTES)
    assert len(flattened) == len(set(flattened)), "有路线被重复渲染了"
    # 组内顺序仍沿用 `ROUTES` 的书写顺序（组内不许被打乱）。
    for group, routes in grouped:
        write_order = [
            route.mode for route in ROUTES if route.group == group
        ]
        assert [route.mode for route in routes] == write_order


def test_routes_in_group_rejects_an_unknown_group():
    with pytest.raises(ValueError):
        catalog.routes_in_group("不存在的分组")
