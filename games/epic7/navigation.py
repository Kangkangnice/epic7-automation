"""Fail-closed navigation from any supported Epic Seven page."""

from dataclasses import dataclass
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.matcher import (
    Match,
    find_best_template,
    load_template,
)
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import (
    StableObservation,
    left_page,
)
from auto_game_unified.games.epic7.arena import find_rank_promotion_confirm
from auto_game_unified.games.epic7.evidence.arena import THRESHOLDS as ARENA_THRESHOLDS
from auto_game_unified.games.epic7.evidence.story import THRESHOLDS as STORY_THRESHOLDS
from auto_game_unified.games.epic7.template_paths import resolve_template_dir
from auto_game_unified.games.epic7.global_popups import (
    find_friendship_points_popup_close,
    find_gift_support_close,
    find_knights_signin_close,
    find_knights_weekly_reward_close,
)
from auto_game_unified.games.epic7.home_return import (
    HomeReturnTemplates,
    build_home_return_templates,
    return_home_v2,
)
from auto_game_unified.games.epic7.story import (
    find_prepare_battle_button,
    find_story_skip_button,
    find_story_skip_confirm,
    find_watch_story_button,
)
from auto_game_unified.games.epic7.hero_synthesis import (
    HERO_INFORMATION_TAB_POINT,
    hero_equipment_tab_selected,
    hero_information_tab_selected,
    hero_tab_blue_pixel_counts,
    imprint_button_saturation,
)
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    REGIONS as SHOP_REFRESH_REGIONS,
    ShopPage,
    ShopRefreshObserver,
    build_shop_refresh_evidence,
    build_shop_refresh_observer,
)
from auto_game_unified.games.epic7.evidence.world_boss import (
    REGIONS as WORLD_BOSS_REGIONS,
    build_world_boss_evidence,
)
from auto_game_unified.games.epic7.evidence.sanctuary import (
    REGIONS as SANCTUARY_REGIONS,
    build_sanctuary_evidence,
)
from auto_game_unified.games.epic7.modes import MODE_LABELS, MODE_SPECS
from auto_game_unified.games.epic7.navigation_plan import NavigationPlan
from auto_game_unified.games.epic7.unknown_screen import (
    UnknownScreenWake,
    UnknownWakeResult,
)


REFERENCE_SIZE = (1982, 1132)

# 段位提升确认框的「箭头 + 确认」联合判据门槛。以前这个值按平台分叉
# （PC 0.85 / 模拟器 0.90），分叉的原因是拿模拟器的图去认 PC 的按钮；
# 现在差异收敛到图片，阈值只剩模拟器基线这一套。
ARENA_RANK_CONFIRM_THRESHOLD = 0.90

# 「回家」那套模板（v2 要用，其中六个直接复用迷宫那条路的模板文件）。
TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class PageObservation:
    name: str
    confidence: float


# 日志用画面名：observe() 的页面标识 -> 中文画面描述
PAGE_LABELS = {
    "invalid": "无效画面",
    "friendship_points_popup": "友情点数弹窗",
    "arena_rank_promotion": "竞技场段位晋升弹窗",
    "exit_dialog": "退出确认框",
    "story_skip_confirm": "跳过剧情确认",
    "story_playing": "剧情播放中",
    "lobby": "大厅",
    "battle_menu": "战斗菜单",
    "season_menu": "赛季菜单",
    "expedition_home": "远征主页",
    "arena_mode": "竞技场模式选择",
    "fodder_episode_detail": "支线详情",
    "fodder_special_book": "特别之书",
    "fodder_side_story": "支线故事",
    "hero_list": "英雄列表",
    "hero_equipment": "英雄装备子页",
    "quick_menu": "快捷菜单",
    "story_ready": "主线入口",
    "arena_ready": "竞技场入口",
    "shop_refresh": "秘密商店",
    "knights_home": "骑士团主页",
    "worldboss_home": "世界首领战主页",
    "sanctuary_home": "圣域主页",
    # ---- 社区签到路线（2026-10-06）----
    # ⚠️ 三条都只是**横屏段**的画面。真正进社区后是竖屏，横屏通道认不出来，
    # 由 ``core/portrait.py`` 那条独立链路负责，画面名不在这张表里。
    "activity_menu": "活动页（未选推广）",
    "activity_web_promo": "活动页（推广态/可前往）",
    "web_activity_list": "网页活动列表",
    "knights_signin_popup": "骑士团签到弹窗",
    "gift_support_popup": "领取支援物品弹窗",
    "knights_weekly_reward_popup": "骑士团周结算奖励弹窗",
    "unknown": "未知画面",
}

# 日志用模式名：模式标识 -> 中文模式名。
#
# ⚠️ 直接用 ``modes.MODE_LABELS``（那边的 ``ModeSpec.label`` 是唯一来源），
# **不要**在这里再写一份。这里曾经有一张自己的表，而且漏了 ``survivor`` ——
# 下面 ``.get(mode, mode)`` 有默认值兜底，漏了不会报错，只会把日志悄悄写成英文名。
# （因为 survivor ``needs_navigation=False`` 走不到那条日志，一直没人发现。）
# 现在这份引用是**全量**的（含 survivor），比原来那张手抄表更正确。


# 「接力」白名单：模式 -> 允许 ``navigate(already_at=...)`` 的导航链页面。
#
# ⚠️ 唯一来源是每条路线在 ``modes.MODE_SPECS`` 里声明的 ``NavigationPlan.resume_entries``；
# 这里只是给调试和既有测试留一个**只读视图** —— 别再往这里手抄页面名。
# 白名单**保持显式、不从 steps 派生**：「链条上有这个页面」不等于「允许从它接力」
# （迷宫的落点全在业务链上，它的白名单就该是空的）。
# 传别的一律报错，不做静默降级（失败关闭）。
_RESUME_ENTRY_PAGES = {
    name: spec.navigation_plan.resume_entries
    for name, spec in MODE_SPECS.items()
    if spec.navigation_plan is not None
}



def _plan_for(mode: str) -> NavigationPlan:
    """按模式名取导航链；唯一来源是 ``modes.MODE_SPECS``。

    ⚠️ 报错文案 `导航不支持的模式：{mode}` 与 2026-09-30 之前那个 ``else`` 分支
    逐字一致，别改 —— 那是「传了没有导航的路线」时外面唯一看得到的线索。
    """
    spec = MODE_SPECS.get(mode)
    if spec is None or spec.navigation_plan is None:
        raise ValueError(f"导航不支持的模式：{mode}")
    return spec.navigation_plan


def page_label(name: str) -> str:
    return PAGE_LABELS.get(name, name)


@dataclass
class _StoryRecoveryAttempts:
    action: str | None = None
    clicks: int = 0


@dataclass(frozen=True)
class NavigationTemplates:
    arena_rank_promotion_arrow: np.ndarray
    arena_rank_confirm: np.ndarray
    friendship_points_title: np.ndarray
    friendship_points_close: np.ndarray
    lobby_story: np.ndarray
    lobby_arena: np.ndarray
    lobby_battle: np.ndarray
    lobby_hero: np.ndarray
    # ---- 快捷菜单（2026-10-04 新增）----
    #
    # 背景：大厅右下角那条**横排快捷栏**（英雄 / 骑士团 / …）是**账号自己排的**，
    # 不同账号位置不一样（用户原话：「这个是快捷栏，相当于」）。靠它进「英雄列表」
    # 与「骑士团」在别的账号上会点错地方。
    #
    # 改走**右上角蓝色四格 → 快捷菜单 → 菜单里的入口**。用户确认菜单是**固定布局**
    # （真机三张不同底页/不同时间的菜单帧实测：两个图标命中在**逐像素相同的中心**）。
    #
    # ``lobby_quick_menu_button`` —— 大厅右上那颗蓝四格（开菜单的按钮）。
    # ⚠️ 它**不能**直接照抄迷宫那张 ``quick_menu_button``：那是另一个长相，
    # 在大厅上只有 0.4834。而且大厅这颗左上角会挂**橙色未读角标**（角标里还可能带
    # 数字，如「2」）⇒ 角标是**可变内容**，绝不能裁进模板。裁法：**从角标下方起裁**
    # （只取四格的下 3/4），实测干净帧 1.0000 / 带角标帧 0.9983 ⇒ 角标免疫，一张模板够。
    lobby_quick_menu_button: np.ndarray
    # 快捷菜单第 1 行最右那颗「英雄」（进英雄列表）。
    #
    # 这两颗**同时**也是「菜单已展开」的身份判据（``observe()`` 里两个都要命中）。
    # ⚠️ 刻意**不用**那块大网格 ``quick_menu_grid_top``（迷宫那张）：它罩住整片菜单底图，
    # 对底页不同 / 节日装饰浮层敏感 —— 实测三张菜单帧给出 1.0000 / 0.9978 / **0.7987**，
    # 最后那张（`pet_gift`，菜单区上盖着一份节日礼物装饰）掉到 0.82 门槛之下。
    # 两颗图标在同样三帧上分别有 0.997+ / 0.997，且**菜单专属**（全库次高仅 0.41/0.44）。
    quick_menu_hero: np.ndarray
    # 快捷菜单第 3 行中间那颗「骑士团」（进骑士团主页）。
    # ⚠️ 它左上角也有个**蓝点**（未读角标）。模板从盾牌本体起裁，**零蓝点像素**。
    quick_menu_knights: np.ndarray
    # 装备子页（英雄界面左侧那个剑盾图标）的选中态。
    # ⚠️ **必需模板，不是可选的**：它是 ``observe()`` 区分「英雄列表」与
    # 「英雄装备子页」的**唯一依据**。历史上这里写成 ``Optional`` 并配
    # ``if exists() else None``，模板被误删后判据**静默消失**、页面退化到靠
    # 「管理装备」按钮撞轮廓去猜，2026-10-03 真机改版就直接认不出（unknown）。
    # 判据型锚点必须 fail closed：模板没了要在加载期报错，而不是悄悄降级。
    hero_equipment_tab_active: np.ndarray
    imprint_button_normal: np.ndarray
    exit_title: np.ndarray
    exit_cancel: np.ndarray
    exit_title_updated: np.ndarray
    exit_cancel_updated: np.ndarray
    arena_mode_title: np.ndarray
    # 竞技场模式选择页底部四个入口里的**第二个**（「新手竞技场」/「竞技场」那个）。
    # ⚠️ 它**有两种长相**：入口名随账号状态变 —— 新手期叫「新手竞技场」，脱离新手期后
    # 叫「竞技场」（2026-10-05 用户实机确认）。旧模板在那一帧只有 **0.7301**、低于
    # 0.82 门槛，而 `observe()` 判 `arena_mode` 要的是「标题 **且** 这个按钮」都命中
    # ⇒ 整个「竞技场模式选择」页认不出来（导航、接力一起受影响）。
    # 语义与 ``lobby_shop_entry`` 一致：**任一候选过阈即命中**，取过阈里分数最高的。
    novice_arena: tuple[np.ndarray, ...]
    story_back: np.ndarray
    story_watch: np.ndarray
    story_skip: np.ndarray
    story_skip_confirm: np.ndarray
    story_ready: np.ndarray
    story_ready_updated: np.ndarray
    arena_ready: np.ndarray
    expedition_battle_title: np.ndarray
    expedition_season_tab: np.ndarray
    expedition_season_active: np.ndarray
    # 「战斗」页左起第一格「一般」标签条（240x90，与「赛季」同尺寸、紧挨在其左侧）。
    # 存在理由：游戏**记住**上次停在哪个标签页 —— 跑过远征（它要点「赛季」）之后，
    # 下一次从大厅点进「战斗」会直接落在赛季页；而**迷宫入口只在「一般」页**。
    # 2026-10-04 每日任务就卡在这里：迷宫的导航链只认 battle_menu，落到 season_menu
    # 后干等 92 秒然后报「导航开始前应处于[大厅]」。这枚锚点是 season_menu →
    # battle_menu 的唯一通道（远征那条链是反向的：battle_menu → season_menu）。
    battle_general_tab: np.ndarray
    expedition_entry: np.ndarray
    expedition_home: np.ndarray
    lobby_story_click_offset: tuple[int, int]
    lobby_side_story: np.ndarray
    side_story_special_book: np.ndarray
    special_book_episode: np.ndarray
    episode_adventure: np.ndarray
    fodder_stage_title: np.ndarray
    fodder_prepare_battle: np.ndarray
    # 「秘密商店」入口是唯一会挂通知角标的大厅入口，故它的候选模板**不止一张**
    # （干净版 + 带角标版），任一过阈即可命中。其余锚点仍是单张 ndarray。
    lobby_shop_entry: tuple[np.ndarray, ...]
    lobby_knights: np.ndarray
    worldboss_entry: np.ndarray
    lobby_worldboss_select_team: np.ndarray
    # 大厅左侧竖排菜单最上面那个「圣域」入口（在「光辉里程碑」上方）。
    # ⚠️ 截的是**文字标签**而不是那个城墙堡垒图标 —— 图标上没有文字，做模板只会
    # 截到一片渐变色块；文字是唯一「只此一处」的稳定特征。代价见
    # ``docs/maintenance/sanctuary.md``「已知缺口」：没有「带红点角标」的第二张候选图。
    lobby_sanctuary: np.ndarray
    # 圣域主页右侧第一行「精灵之森」的文字。**只为 ``observe()`` 判页而存在** ——
    # 导航把画面送到圣域主页后，``_transition`` 要靠 ``observe()`` 认出
    # ``sanctuary_home`` 才算转场成功（没有它这条转场永远验收不通过、只会超时）。
    # ⚠️ 复用 ``evidence/sanctuary.py`` 的锚点图，**不另存一份** —— 与
    # ``lobby_worldboss_select_team`` 复用 ``world_boss`` 的图同一个道理：
    # 同一个控件维护两份模板迟早漂移。
    sanctuary_forest_row: np.ndarray
    knights_signin_title: np.ndarray
    knights_signin_close: np.ndarray
    gift_support_title: np.ndarray
    gift_support_close: np.ndarray
    knights_weekly_reward_title: np.ndarray
    knights_weekly_reward_close: np.ndarray
    # ---- 社区签到路线（2026-10-06）----
    # 大厅左侧竖排最后一个「活动」入口（记事本+星+时钟图标 与「活动」二字）。
    # ⚠️ 与 ``lobby_knights`` 同理：实测 220 张同尺寸夹具里过阈 12 张、**全是大厅类帧**
    # ⇒ 它是**大厅常驻控件**，只作**点击目标**，**不能判页**（判页看下面三张）。
    lobby_activity: np.ndarray
    # 游戏内「活动」页左列表里的「更多精彩活动」那一行（**未选中态**）。
    # 既是这一步的点击目标，也是 ``activity_menu`` 的页判据。
    # ⚠️ 选中的那个会出现「前往活动页」，是**另一个态**（``activity_web_promo``）；
    # 本模板在那个态上只有 0.25~0.34 —— 两态靠下面那张白字模板区分。
    activity_more: np.ndarray
    # 「更多精彩活动」**选中态**那一行里的**白字**（橙底白字）。
    #
    # ⚠️⚠️ **为什么不用「前往活动页」按钮（``web_activity_gate``）当选中态判据**：
    # 那颗按钮上有一团**会滑动的光球**。2026-10-06 光球罩住「活动」二字 ⇒
    # 1.0000；2026-10-07 光球滑到右边罩住「动页」⇒ **同一位置 (1690,968) 掉到
    # 0.7282** ⇒ 过不了 0.82 ⇒ 整页判 ``unknown``，导航第二步超时失败关闭。
    # 这就是 ``docs/TRANSITION_CONTRACTS.md`` 明令禁止的「模板里放会动的元素」。
    #
    # 本模板只取**白字那一块**（52x154，2026-10-07 真机帧裁的），不含光球、
    # 不含橙底渐变的边界、不含橙点。全库 369 张横屏帧实测：
    # 选中态 0.8924~1.0000（跨两天两帧都过阈，含转场动画中那帧 0.8924），
    # **未选中态只有 0.2482 / 0.3435，全库次高 0.3732** ⇒ 空档 0.37→0.89 极宽。
    activity_more_selected: np.ndarray
    # 「前往活动页」按钮 —— **只当点击目标**（第 3 步要按它），**不当判据**
    # （光球会滑动，见上）。⚠️ 正是这一点让它在 10-07 掉到 0.7282。
    # 只裁了光晕盖不到的右段（65x34），整钮是半透明的、背后横幅会呼吸发光。
    web_activity_gate: np.ndarray
    # 横屏「网页活动列表」页右侧的「游戏社区」按钮 —— **竖屏社区就从这里进**。
    web_community: np.ndarray
    shop_refresh_observer: ShopRefreshObserver


def build_navigation_templates(template_root: Path) -> NavigationTemplates:
    navigation = template_root / "navigation"
    global_templates = template_root / "global"
    shop_evidence = build_shop_refresh_evidence(template_root)
    shop_entry = shop_evidence.atom("lobby_shop_entry")
    world_boss_evidence = build_world_boss_evidence(template_root / "world_boss")
    world_boss_select_team = world_boss_evidence.atom("select_team_button")
    sanctuary_evidence = build_sanctuary_evidence(template_root / "sanctuary")
    sanctuary_forest_row = sanctuary_evidence.atom("forest_row")
    return NavigationTemplates(
        arena_rank_promotion_arrow=load_template(
            str(global_templates / "arena_rank_promotion_arrow.png")
        ),
        arena_rank_confirm=load_template(str(template_root / "rank_confirm.png")),
        friendship_points_title=load_template(
            str(global_templates / "friendship_points_title.png")
        ),
        friendship_points_close=load_template(
            str(global_templates / "friendship_points_close.png")
        ),
        lobby_story=load_template(str(navigation / "lobby_story.png")),
        lobby_arena=load_template(str(navigation / "lobby_arena.png")),
        lobby_battle=load_template(str(navigation / "lobby_battle.png")),
        lobby_hero=load_template(str(navigation / "lobby_hero.png")),
        # 快捷菜单三张：大厅蓝四格 + 两个菜单入口（入口同时兼作「菜单已展开」判据），
        # 见 ``NavigationTemplates`` 上那段的说明。
        lobby_quick_menu_button=load_template(
            str(navigation / "lobby_quick_menu_button.png")
        ),
        quick_menu_hero=load_template(str(navigation / "quick_menu_hero.png")),
        quick_menu_knights=load_template(str(navigation / "quick_menu_knights.png")),
        # 直接 load_template：模板缺失就抛 FileNotFoundError（fail closed）。
        # 这里**不许**再写 ``if path.exists() else None`` —— 那会让判据静默降级。
        hero_equipment_tab_active=load_template(
            str(navigation / "hero_equipment_tab_active.png")
        ),
        imprint_button_normal=load_template(
            str(template_root / "hero" / "imprint_button_normal.png")
        ),
        exit_title=load_template(str(navigation / "exit_title.png")),
        exit_cancel=load_template(str(navigation / "exit_cancel.png")),
        exit_title_updated=load_template(str(navigation / "exit_title_updated.png")),
        exit_cancel_updated=load_template(str(navigation / "exit_cancel_updated.png")),
        arena_mode_title=load_template(str(navigation / "arena_mode_title.png")),
        # 两张候选：`novice_arena` = 新手期长相，`arena_entry` = 脱离新手期后的长相。
        # 顺序不影响结果（`_locate` 取过阈候选里的最高分，不看先后）。
        novice_arena=(
            load_template(str(navigation / "novice_arena.png")),
            load_template(str(navigation / "arena_entry.png")),
        ),
        story_back=load_template(str(navigation / "story_back.png")),
        story_watch=load_template(str(template_root / "story" / "watch_story.png")),
        story_skip=load_template(str(template_root / "story" / "skip.png")),
        story_skip_confirm=load_template(
            str(template_root / "story" / "skip_confirm.png")
        ),
        story_ready=load_template(str(template_root / "story" / "prepare_battle.png")),
        story_ready_updated=load_template(
            str(template_root / "story" / "prepare_battle_updated.png")
        ),
        arena_ready=load_template(str(template_root / "list_ready.png")),
        expedition_battle_title=load_template(
            str(navigation / "expedition_battle_title.png")
        ),
        expedition_season_tab=load_template(
            str(navigation / "expedition_season_tab.png")
        ),
        expedition_season_active=load_template(
            str(navigation / "expedition_season_active.png")
        ),
        # 源帧：今天 08:17 卡在赛季栏的真机帧（见 ``battle_general_tab`` 注释里的
        # 事故经过）。模板取的是「一般」处于**未选中**时的样子 —— 也正是需要点它
        # 时它的样子。选中态同格实测只有 0.3532（``battle_menu`` 夹具），
        # 236 张夹具全扫：过阈的只有两张赛季栏页（1.0000 / 0.8668），分离余量充足。
        battle_general_tab=load_template(str(navigation / "battle_general_tab.png")),
        expedition_entry=load_template(str(navigation / "expedition_entry.png")),
        expedition_home=load_template(str(navigation / "expedition_home.png")),
        lobby_story_click_offset=(65, 11),
        lobby_side_story=load_template(str(navigation / "lobby_side_story.png")),
        side_story_special_book=load_template(
            str(navigation / "side_story_special_book.png")
        ),
        special_book_episode=load_template(
            str(navigation / "special_book_episode.png")
        ),
        episode_adventure=load_template(str(navigation / "episode_adventure.png")),
        fodder_stage_title=load_template(str(navigation / "fodder_stage_title.png")),
        fodder_prepare_battle=load_template(
            str(template_root / "fodder" / "prepare_battle.png")
        ),
        lobby_shop_entry=tuple(
            load_template(str(template_root / path))
            for path in (shop_entry.template_path, *shop_entry.alt_template_paths)
        ),
        lobby_knights=load_template(str(navigation / "lobby_knights.png")),
        worldboss_entry=load_template(str(navigation / "worldboss_entry.png")),
        lobby_worldboss_select_team=load_template(
            str(template_root / "world_boss" / world_boss_select_team.template_path)
        ),
        lobby_sanctuary=load_template(str(navigation / "lobby_sanctuary.png")),
        sanctuary_forest_row=load_template(
            str(template_root / "sanctuary" / sanctuary_forest_row.template_path)
        ),
        knights_signin_title=load_template(
            str(navigation / "knights_signin_title.png")
        ),
        knights_signin_close=load_template(
            str(navigation / "knights_signin_close.png")
        ),
        gift_support_title=load_template(
            str(navigation / "gift_support_title.png")
        ),
        gift_support_close=load_template(
            str(navigation / "gift_support_close.png")
        ),
        knights_weekly_reward_title=load_template(
            str(navigation / "knights_weekly_reward_title.png")
        ),
        knights_weekly_reward_close=load_template(
            str(navigation / "knights_weekly_reward_close.png")
        ),
        # 社区签到路线（2026-10-06）。全部直接 ``load_template``：缺文件就抛
        # ``FileNotFoundError``（fail closed），不写 ``exists() else None``。
        lobby_activity=load_template(str(navigation / "lobby_activity.png")),
        activity_more=load_template(str(navigation / "activity_more.png")),
        activity_more_selected=load_template(
            str(navigation / "activity_more_selected.png")
        ),
        web_activity_gate=load_template(str(navigation / "web_activity_gate.png")),
        web_community=load_template(str(navigation / "web_community.png")),
        shop_refresh_observer=build_shop_refresh_observer(template_root),
    )


class Epic7Navigator:
    """Return to the lobby, then follow a verified mode-specific route."""

    _BACK_RETRY_SECONDS = 15
    # 「点一次、验收一次」的验收窗口：点完导航锚点后等这么久，如果还停在来源页上，
    # 就认定这一下点击没有生效，立刻交给外层提前重试，而不是把整个转场窗口
    # （transition_frames=90，实测约 92 秒）干等完、再点一次**同样的坐标**。
    # 取值依据：实机成功转场约 4 秒（epic7_shop_refresh.log 2026-09-10
    # 19:33:37 点击 → 19:33:41 转场确认），取 8 秒留 2 倍余量。
    _CLICK_VERIFY_SECONDS = 8.0
    # 「受控返回」没效果时改用的页内返回箭头门槛。
    # 实测 176 张 1982×1132 夹具（runtime_logs/_probe_back_arrow.py）：
    # 真有箭头的页面大多 0.99+，深层页面偏低但仍属同源控件
    # （远征主页 0.8999 / 支线故事 0.8949 / 远征难度选择 0.7760）；
    # 没有箭头的页面最高只有 0.5278（局内战斗）、大厅 0.41、退出框 0.41。
    # 取 0.80 落在两者之间：宁可少点一次，也不在没箭头的地方乱点左上角。
    _IN_PAGE_BACK_THRESHOLD = 0.80
    _HERO_DETAIL_TAB_POINT = HERO_INFORMATION_TAB_POINT
    _HERO_DETAIL_TAB_MAX_ATTEMPTS = 4
    _HERO_DETAIL_TAB_RETRY_SECONDS = 2.0

    _REGIONS = {
        "lobby_story": (1450, 220, 480, 200),
        "lobby_arena": (1600, 520, 330, 220),
        "lobby_battle": (1650, 430, 332, 220),
        "lobby_hero": (1400, 980, 180, 130),
        # 装备图标选中态（蓝色高亮+剑盾）。区域按真机实测高亮块 y 263~358 定，
        # 旧值 (0, 200, 130, 140) 下界只到 340，模板放不进正确位置。
        "hero_equipment_tab_active": (0, 235, 155, 150),
        "imprint_button_normal": (1000, 900, 250, 200),
        "exit_title": (650, 400, 700, 280),
        "exit_cancel": (550, 620, 500, 260),
        "exit_title_updated": (650, 400, 700, 280),
        "exit_cancel_updated": (550, 620, 500, 260),
        "arena_mode_title": (0, 35, 350, 180),
        "novice_arena": (400, 780, 650, 352),
        "story_back": (0, 40, 120, 120),
        "story_watch": (1450, 930, 470, 202),
        "story_ready": (1450, 930, 470, 202),
        "story_ready_updated": (1450, 930, 470, 202),
        "arena_ready": (700, 900, 520, 232),
        "lobby_shop_entry": SHOP_REFRESH_REGIONS["lobby_shop_entry"],
        "expedition_battle_title": (0, 35, 350, 180),
        "expedition_season_tab": (250, 140, 500, 200),
        "expedition_season_active": (250, 140, 500, 200),
        # 「一般」标签条那一格：x 105..345、y 175..265（左右各留 5px 余量）。
        # 区域比「赛季」那两个窄，是因为它本身就是要把**左边这一格**抠出来。
        "battle_general_tab": (100, 165, 250, 105),
        # 赛季页那排卡片会随赛季换序：上赛季是「战术档案/远征队/考验殿堂」，
        # 远征队居中；2026-09-17 新赛季多了一张「星座考验」，远征队被挤到最右。
        # 原先区域 (850,240,500,260) 只罩住中间那张卡，远征队右移后只拿 0.4395
        # （实机帧 runtime_diagnostics/epic7_expedition/20260917_185800）→ 赛季页整页
        # 认不出来 → 落到「未知画面唤醒」点屏幕中央，而那正好压在新中间的卡上，
        # 表现为「点了中间那张卡」。改为覆盖整行卡片，按「远征队」这个名字模板
        # 命中哪里就点哪里，与卡片在第几号位无关。
        # 实测三张卡标题对该模板的分数：远征队 0.9541 / 战术档案 0.3476 /
        # 星座考验 0.3258（上赛季夹具仍为 1.0000），故放宽区域不会误点别的卡。
        "expedition_entry": (400, 240, 1580, 260),
        "expedition_home": (1400, 880, 582, 252),
        "lobby_side_story": (1700, 380, 215, 120),
        "side_story_special_book": (1520, 900, 385, 110),
        "special_book_episode": (790, 995, 500, 110),
        "episode_adventure": (1595, 945, 338, 187),
        "fodder_stage_title": (850, 760, 225, 90),
        "fodder_prepare_battle": (1365, 990, 385, 120),
        # 大厅底部「骑士团」盾牌图标。⚠️ 它其实是**大厅常驻控件**：185 张夹具
        # 里每张大厅页都在同一个位置以 0.86~0.96 命中（压暗到 55% 亮度仍 0.9643，
        # 见 runtime_logs/_wb_probe_nav.py）。也就是说它只能拿来「定位点击点」，
        # 不能拿来判「现在是哪一页」—— 判页要看世界首领战图标。
        "lobby_knights": (1150, 960, 420, 150),
        # ---- 快捷菜单（2026-10-04）----
        # 大厅右上那颗蓝四格（开菜单）。区域只罩住**那颗图标**——它是个
        # **全局常驻控件**（几乎每页右上角都有，全库 218 张里 133 张命中），
        # 所以它**不能判页**，只作**点击目标**（每页都在同一位置，点它都能开菜单）。
        # 实测大厅类帧 0.9668~1.0000、非大厅/菜单已开 0.22~0.28 ⇒ 0.82 门槛余量充足。
        "lobby_quick_menu_button": (1795, 55, 190, 110),
        # 菜单第 1 行最右「英雄」。区域只罩那一格（含少量余量），避免蹭到相邻的「图鉴」。
        # 实测：菜单帧 0.9983~0.9987、全库次高 0.4097 ⇒ 余量 0.59。
        "quick_menu_hero": (1745, 200, 150, 130),
        # 菜单第 3 行中间「骑士团」。实测菜单帧 0.9970~0.9973、全库次高 0.4401 ⇒ 余量 0.56。
        "quick_menu_knights": (1555, 550, 150, 120),
        # 骑士团主页的「世界首领战」入口图标（骷髅盾牌）。排他性实测：本页 0.9890，
        # 跨页最高 0.4210（远征海报）。
        "worldboss_entry": (380, 620, 180, 140),
        # 世界首领战主页右下角「选择队伍」按钮。⚠️ 这里复用 evidence/world_boss.py
        # 的锚点图（不是 navigation 目录下的第二份），避免同一个控件维护两份模板。
        "lobby_worldboss_select_team": WORLD_BOSS_REGIONS["select_team_button"],
        # 大厅左侧竖排菜单最上面那个「圣域」文字标签。区域只罩住那一行 ——
        # 实测真机点 (84, 318) 能进圣域主页，命中框中心落在 (84, 314) 附近。
        # ⚠️ 它同时也是**进入圣域**这个动作的点击目标（``_transition`` 用命中框中心点）。
        "lobby_sanctuary": (20, 270, 140, 130),
        # 圣域主页右侧第一行「精灵之森」：**只给 ``observe()`` 判页用**，不是点击目标
        # （点它是 ``sanctuary.py`` 状态机的事）。复用 evidence 那边的区域定义。
        "sanctuary_forest_row": SANCTUARY_REGIONS["forest_row"],
        # ---- 社区签到路线（2026-10-06）----
        # 大厅左侧竖排最后一个「活动」入口。区域留得比控件大一圈（图标 y 754~812、
        # 「活动」二字 y 826~838 ⇒ 控件占 ~75..845），给大厅动画/节日装饰留余量。
        # ⚠️ 它**同时**是「进入活动」这个动作的点击目标（``_transition`` 用命中框中心）。
        "lobby_activity": (10, 700, 220, 200),
        # 「活动」页左列表那一列 —— ⚠️ **这里曾把整条路线卡死在第一步**（2026-10-07）。
        #
        # 原来只框 y 400~580（按 2026-10-06 那一帧量的：整行 y 431~535）。10-07 真机
        # 一跑就翻车：活动页左列**顶部多了两行**（「助继承者重启冒险」×2，一个回归活动），
        # 把「更多精彩活动」从 y=460 挤到 **y=686**（+226px）⇒ 模板还在（0.9145）、
        # 但框空了 ⇒ 整页判 ``unknown`` ⇒ 导航第一步就超时失败关闭。
        #
        # ⇒ **区域罩住整列**（y 300~1150），不再随上方活动行数变化而失效。
        # 安全性实测（``runtime_logs/_whole_scan.py activity_more 0 300 420 850``，
        # 全库 360 张唯一帧）：区域内过阈的**只有 3 张** —— 10-06 那张夹具 1.0000
        # 加今天两张真机帧 0.9145；**次高只有 0.4830**，空档极大，放大区域没有代价。
        # 点击点仍取**命中框中心**（`_locate`），所以位置随行浮动不影响点击。
        "activity_more": (0, 300, 420, 850),
        # 「更多精彩活动」**选中态**那一行的白字。区域同样罩住整列。
        #
        # ⚠️ 上界为什么是 **1150** 而不是跟 ``activity_more`` 一样 850：选中态那一行
        # 的**位置本身会随上方活动行数漂**（实测 10-06 落 y=443、10-07 落 y=726，
        # 相差 283px），而未选中态那版区域（y≤1150）在两次实测里都罩住了。
        # 这里取 y 300~1150 与 ``activity_more`` 对齐，两态用同一块搜索带。
        # 安全性实测（369 张横屏帧全扫）：过阈 6 张全是选中态帧，次高 0.3732。
        "activity_more_selected": (0, 300, 420, 850),
        # 「前往活动页」按钮右下角那一段（只裁了光晕盖不到的部分）。
        # 按钮整块约 x 1580~1770 / y 960~1020，这里把区域放宽到 420x140。
        # ⚠️ **它只当点击目标、不当判据** —— 光球会滑动，同一位置跨帧 1.0000→0.7282，
        # 当判据会把整页判成 ``unknown``（2026-10-07 实跑就是这样失败的）。
        # 判「选中没选中」请用 ``activity_more_selected``。
        "web_activity_gate": (1500, 920, 420, 140),
        # 「网页活动列表」页右侧那一列按钮。「游戏社区」文字实测 x 1620~1732 /
        # y 245~267，区域罩住整列宽度以容纳左右留白。
        # ⚠️ 同上，**未复验**。
        "web_community": (1540, 180, 400, 160),
    }
    _CLICK_OFFSETS = {"lobby_story": (65, 11)}

    @classmethod
    def _assert_anchor_templates(cls, templates: NavigationTemplates) -> None:
        """登记在 ``_REGIONS`` 里的判据锚点必须都有模板，缺了当场报错。

        ``_REGIONS`` 的每个键都是 ``observe()`` / ``_transition`` 用来**认页**的
        锚点。锚点模板一旦缺失，判据不会报错、只会**静默消失**：页面认不出来，
        日志上退化成「未知画面」，看不出任何异常，直到游戏改版才暴露
        （2026-10-03 装备子页 ``hero_equipment_tab_active`` 就是这么丢的）。

        所以这里 fail closed：宁可开跑前起不来，也不要带着一个悄悄失效的判据
        跑到真机上。同一个取向见 ``docs/TRANSITION_CONTRACTS.md`` 原则 4 ——
        那条只管**危险动作**的关键模板，这里更严：**所有**判据锚点都不许缺。
        """
        missing = []
        for anchor in cls._REGIONS:
            value = getattr(templates, anchor, None)
            # None = 没加载；空元组 = 候选图一张都没有。两者都是「判据不存在」。
            if value is None or (isinstance(value, tuple) and not value):
                missing.append(anchor)
        if missing:
            raise ValueError(
                "导航判据锚点缺少模板（该判据会静默失效）：" + "、".join(sorted(missing))
            )

    def __init__(
        self,
        templates: NavigationTemplates,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 0.5,
        transition_frames: int = 90,
        template_root: Path | None = None,
    ) -> None:
        self.templates = templates
        # 开跑前先确认判据锚点都在。放在构造期而不是 ``observe()`` 里，
        # 是因为「判据缺失」是配置故障，应该在启动时立刻暴露。
        self._assert_anchor_templates(templates)
        self.runtime = runtime
        # 平台差异只在最上游注入一次（``main`` 传进来的模板根已经会按平台挑图）。
        # 不传就用模块级默认根 —— 测试替身与离线脚本走这条路。
        self._template_root = (
            resolve_template_dir(TEMPLATE_ROOT)
            if template_root is None
            else template_root
        )
        # 只有模拟器基线一套阈值；平台差异收敛到图片（templates/**/pc/*.png）。
        self._story_thresholds = STORY_THRESHOLDS
        self._arena_thresholds = ARENA_THRESHOLDS
        self.sleep = sleep
        self.now = runtime.now
        self.poll_seconds = poll_seconds
        self.transition_frames = transition_frames
        self.unknown_screen_wake = UnknownScreenWake(runtime)
        # 「回家」用的那套模板（v2）。懒构建：大部分路线压根不回家，别白读 10 张图。
        self._home_return_templates: Optional[HomeReturnTemplates] = None

    def _locate(self, screen: np.ndarray, name: str, threshold: float = 0.82) -> Optional[Match]:
        """在锚点区域内找到**最高分且过阈**的匹配。

        一个锚点可以登记多个候选模板（``NavigationTemplates`` 里那类字段是
        ``tuple[np.ndarray, ...]``）—— 典型是大厅「秘密商店」入口：它有时会挂
        「未读新内容」的红 N 角标，和干净模板的相似度只有 ~0.81（门槛 0.82）。
        多条候选之间**任一过阈即算命中**，命中取过阈候选里分数最高的那个，
        所以「带角标」和「不带角标」两种长相都能进店，不必等角标消失。
        """
        candidates = getattr(self.templates, name)
        if isinstance(candidates, np.ndarray):
            candidates = (candidates,)
        best: Optional[Match] = None
        for template in candidates:
            match = find_best_template(
                screen,
                template,
                region=self._REGIONS[name],
                reference_size=REFERENCE_SIZE,
            )
            if match is None or match.score < threshold:
                continue
            if best is None or match.score > best.score:
                best = match
        return best

    def _click_offset(self, anchor: str) -> tuple[int, int]:
        if anchor == "lobby_story":
            return self.templates.lobby_story_click_offset
        return self._CLICK_OFFSETS.get(anchor, (0, 0))

    def observe(self, screen: np.ndarray) -> PageObservation:
        content = screen[round(screen.shape[0] * 0.05) :, : round(screen.shape[1] * 0.97)]
        if float(np.mean(content)) < 3.0 or float(np.std(content)) < 5.0:
            return PageObservation("invalid", 0.0)

        popup_close = find_friendship_points_popup_close(
            screen,
            self.templates.friendship_points_title,
            self.templates.friendship_points_close,
        )
        if popup_close is not None:
            return PageObservation("friendship_points_popup", popup_close.score)

        # 骑士团签到达成度奖励弹窗（**每天第一次进骑士团**才出现）。
        # ⚠️ 必须排在 worldboss_entry 判定**之前**：这个弹窗盖在骑士团主页上，
        # 实测把 ``worldboss_entry`` 从 0.9890 压到 **0.4477**（低于 0.85 门槛），
        # 所以弹窗开着时底下那一页**认不出来**。必须让 observe 先报出「这是签到弹窗」，
        # 好让 Epic7GlobalPopupGuard 把它点掉，然后才会露出骑士团主页。
        signin_close = find_knights_signin_close(
            screen,
            self.templates.knights_signin_title,
            self.templates.knights_signin_close,
        )
        if signin_close is not None:
            return PageObservation("knights_signin_popup", signin_close.score)

        # 「领取支援物品」弹窗（进骑士团时团员赠送的支援资源到账）。
        # 与签到弹窗同理，盖在骑士团主页上、压暗底页锚点，必须先报出来让守卫点掉。
        gift_close = find_gift_support_close(
            screen,
            self.templates.gift_support_title,
            self.templates.gift_support_close,
        )
        if gift_close is not None:
            return PageObservation("gift_support_popup", gift_close.score)

        # 「获得每周骑士团点数奖励」弹窗（每周一骑士团点数结算时弹出）。
        # 与签到/支援弹窗同理，盖在骑士团主页上、压暗底页锚点，必须先报出来让守卫点掉。
        weekly_reward_close = find_knights_weekly_reward_close(
            screen,
            self.templates.knights_weekly_reward_title,
            self.templates.knights_weekly_reward_close,
        )
        if weekly_reward_close is not None:
            return PageObservation(
                "knights_weekly_reward_popup", weekly_reward_close.score
            )

        rank_confirm = find_rank_promotion_confirm(
            screen,
            self.templates.arena_rank_promotion_arrow,
            self.templates.arena_rank_confirm,
            ARENA_RANK_CONFIRM_THRESHOLD,
        )
        if rank_confirm is not None:
            return PageObservation("arena_rank_promotion", rank_confirm.score)

        exit_title = self._locate(screen, "exit_title", 0.90)
        exit_cancel = self._locate(screen, "exit_cancel")
        if exit_title and exit_cancel:
            return PageObservation("exit_dialog", min(exit_title.score, exit_cancel.score))
        exit_title_updated = self._locate(screen, "exit_title_updated", 0.90)
        exit_cancel_updated = self._locate(screen, "exit_cancel_updated")
        if exit_title_updated and exit_cancel_updated:
            return PageObservation(
                "exit_dialog",
                min(exit_title_updated.score, exit_cancel_updated.score),
            )

        story_skip_confirm = find_story_skip_confirm(
            screen,
            self.templates.story_skip_confirm,
            self._story_thresholds["skip_confirm"],
        )
        if story_skip_confirm is not None:
            return PageObservation("story_skip_confirm", story_skip_confirm.score)
        story_skip = find_story_skip_button(
            screen,
            self.templates.story_skip,
            self._story_thresholds["skip"],
        )
        if story_skip is not None:
            return PageObservation("story_playing", story_skip.score)

        # 快捷菜单（右上角蓝四格打开的那层浮层，2026-10-04 新增）。
        #
        # ⚠️ **必须排在下面所有「底页判据」之前**。菜单是**盖在底页上的浮层**：
        # 打开时底下那一页（大厅 / 骑士团…）的锚点**还看得见**（只是被压暗），
        # 而模板匹配对压暗不敏感 —— 排在后面就会被判成「已在大厅」提前收工
        # （迷宫那边写着同一条教训：「``quick_menu`` 排在 ``lobby`` 前面」）。
        #
        # 排在弹窗**之后**：弹窗是模态的，盖在菜单上时得先让守卫点掉它。
        #
        # 判据 = **菜单里两个入口图标同时命中**（「与大厅同一套双锚点做法」）。
        #
        # ⚠️ 这里**刻意不用**那块大网格 ``quick_menu_grid_top``：它罩住整片菜单底图，
        # 对**底页不同 / 节日装饰浮层**敏感。实测三张菜单帧上它给出
        # ``1.0000 / 0.9978 / **0.7987**``（第三张是 `pet_gift` 帧，画面上有一份
        # 节日礼物装饰盖在菜单区）—— **0.7987 掉在 0.82 门槛之下**，那一帧就认不出菜单了。
        # 而两个图标本身在三张帧上分别是 ``0.9983+ / 0.9970+``，**最低 0.997**，干净得多。
        # 它们本身也是**菜单专属**（全库 218 张里各只过阈 3 张菜单帧，次高 0.41/0.44）。
        menu_hero = self._locate(screen, "quick_menu_hero")
        menu_knights = self._locate(screen, "quick_menu_knights")
        if menu_hero and menu_knights:
            return PageObservation(
                "quick_menu", min(menu_hero.score, menu_knights.score)
            )

        shop_observation = self.templates.shop_refresh_observer.observe(screen)
        if shop_observation.page is ShopPage.SHOP:
            scores = shop_observation.scores or {}
            confidence = min(
                scores.get("shop_title", 0.0),
                scores.get("refresh_button_3", 0.0),
                scores.get("buy_button", 0.0),
            )
            return PageObservation("shop_refresh", confidence)

        # ⚠️ 这三条必须排在 lobby 判定**之前**。骑士团主页和世界首领战主页都在顶部
        # 保留了「世界首领战」标题栏、底部也**没有**大厅那排图标（实测骑士团页
        # lobby_knights 0.3562 / 首领战页 0.4017，而大厅页恒在 0.86~0.96），
        # 所以它们本来就过不了大厅的组合判据，会掉到「未知画面」被点屏幕中央。
        #
        # 判据只用两个排他锚点（跨页扫描见 runtime_logs/_wb_probe_nav.py）：
        #   - worldboss_entry（骑士团主页的「世界首领战」骷髅盾牌）：本页 0.9890，
        #     跨页最高 0.4210；
        #   - select_team_button（首领战主页右下角「选择队伍」）：本页 1.0000/0.9161，
        #     跨页最高 0.4192（见 evidence/world_boss.py 的扫描表）。
        # **两页顶部标题完全相同**（实测都是 1.0000），所以只能靠这两个按钮区分。
        worldboss_entry = self._locate(screen, "worldboss_entry", 0.85)
        if worldboss_entry:
            return PageObservation("knights_home", worldboss_entry.score)
        select_team = self._locate(screen, "lobby_worldboss_select_team")
        if select_team:
            return PageObservation("worldboss_home", select_team.score)

        # 圣域主页（``navigate("sanctuary")`` 的落点）。判据是右侧第一行「精灵之森」的
        # 文字 —— 139 张全库夹具扫下来它只在这一页的这个位置命中（全库最高 0.3569），
        # 大厅上更是只有 0.2411，所以放哪儿都不会跟大厅串。
        #
        # ⚠️ 这一条是**必须的**，不是锦上添花：``_transition`` 靠
        # 「``observe()`` 报出目标页名」才算转场成功（见那里的
        # ``observation.name in targets``）。少了它，「大厅 → 进入圣域」那条转场
        # 会一路等到 92 秒超时、重试 4 次然后报错 —— 表现是「这条路线的导航永远进不去」。
        # 判据本体与实测见 ``evidence/sanctuary.py``。
        sanctuary_home = self._locate(screen, "sanctuary_forest_row", 0.80)
        if sanctuary_home:
            return PageObservation("sanctuary_home", sanctuary_home.score)

        lobby_story = self._locate(screen, "lobby_story", 0.80)
        lobby_arena = self._locate(screen, "lobby_arena")
        lobby_battle = self._locate(screen, "lobby_battle")
        lobby_secondary = max(
            (match for match in (lobby_arena, lobby_battle) if match is not None),
            key=lambda match: match.score,
            default=None,
        )
        if lobby_story and lobby_secondary:
            return PageObservation(
                "lobby", min(lobby_story.score, lobby_secondary.score)
            )

        expedition_home = self._locate(screen, "expedition_home")
        if expedition_home:
            return PageObservation("expedition_home", expedition_home.score)

        # ---- 社区签到路线的活动页三态（2026-10-06 立，2026-10-07 改判据）----
        #
        # ⚠️ 这三条**都排在 ``lobby`` 判定之后**：``lobby_activity`` 在大厅帧上恒为
        # 1.0000，若放在前面会把大厅判成活动页。
        #
        # ⚠️⚠️ **顺序在 2026-10-07 换了，原因是判据本身换了**：
        # 选中态原来靠 ``web_activity_gate``（「前往活动页」按钮）认，而那颗按钮上
        # 有一颗**会滑动的光球** —— 10-06 得 1.0000，10-07 同一位置掉到 **0.7282**
        # ⇒ 过不了阈 ⇒ 选中态在代码里等于「不存在」，导航第二步必然失败关闭。
        # 现在选中态改用 ``activity_more_selected``（那一行的**白字**，不含光球），
        # 实测跨两天 0.8924~1.0000、未选中态只有 0.25~0.34。
        # ⇒ ``web_activity_gate`` **降级为纯点击目标**，不再参与判页。
        #
        # 判据本体与全库扫描见 ``docs/maintenance/community_checkin.md``。
        web_community = self._locate(screen, "web_community")
        if web_community:
            return PageObservation("web_activity_list", web_community.score)

        # ⚠️ 选中态必须**排在未选中态前面**：同一帧上两个锚点实测互斥
        # （未选中帧上选中模板 0.25~0.34、选中帧上未选中模板 0.52），
        # 但真出现边缘帧时「先认出谁」不该靠运气 —— 语义上两态互斥，
        # 顺序只影响可读性；这里按「从外到内」：先网页列表、再选中态、最后未选中态。
        activity_more_selected = self._locate(screen, "activity_more_selected")
        if activity_more_selected:
            return PageObservation("activity_web_promo", activity_more_selected.score)

        activity_more = self._locate(screen, "activity_more")
        if activity_more:
            return PageObservation("activity_menu", activity_more.score)

        expedition_title = self._locate(screen, "expedition_battle_title")
        season_active = self._locate(screen, "expedition_season_active")
        expedition_entry = self._locate(screen, "expedition_entry")
        if expedition_title and season_active and expedition_entry:
            return PageObservation(
                "season_menu",
                min(expedition_title.score, season_active.score, expedition_entry.score),
            )
        season_tab = self._locate(screen, "expedition_season_tab")
        if expedition_title and season_tab:
            return PageObservation(
                "battle_menu", min(expedition_title.score, season_tab.score)
            )

        arena_title = self._locate(screen, "arena_mode_title")
        novice = self._locate(screen, "novice_arena")
        if arena_title and novice:
            return PageObservation("arena_mode", min(arena_title.score, novice.score))

        fodder_stage_title = self._locate(screen, "fodder_stage_title")
        fodder_prepare = self._locate(screen, "fodder_prepare_battle")
        if fodder_stage_title and fodder_prepare:
            return PageObservation(
                "fodder_stage", min(fodder_stage_title.score, fodder_prepare.score)
            )
        fodder_episode = self._locate(screen, "episode_adventure")
        if fodder_episode:
            return PageObservation("fodder_episode_detail", fodder_episode.score)
        fodder_book = self._locate(screen, "special_book_episode")
        if fodder_book:
            return PageObservation("fodder_special_book", fodder_book.score)
        fodder_side_story = self._locate(screen, "side_story_special_book")
        if fodder_side_story:
            return PageObservation("fodder_side_story", fodder_side_story.score)

        # 装备子页判据。模板缺失的情况已在构造期由 ``_assert_anchor_templates``
        # 拦下，此处不必再判 None（再判一次就是又一次静默降级）。
        hero_equipment = self._locate(screen, "hero_equipment_tab_active", 0.85)
        if hero_equipment:
            return PageObservation("hero_equipment", hero_equipment.score)

        hero_list = self._locate(screen, "imprint_button_normal", 0.78)
        if hero_list and hero_equipment_tab_selected(screen):
            return PageObservation("hero_equipment", hero_list.score)
        if hero_list and hero_information_tab_selected(screen):
            return PageObservation("hero_list", hero_list.score)
        # 选中 3S 满级英雄时刻印按钮置灰（深/浅两种灰），正常模板高分失配；
        # 结构匹配（图标轮廓仍在）+ 饱和度确认置灰状态，同样认定为英雄列表。
        grey_button = self._locate(screen, "imprint_button_normal", 0.50)
        if (
            grey_button
            and imprint_button_saturation(screen) < 90
            and hero_equipment_tab_selected(screen)
        ):
            return PageObservation("hero_equipment", grey_button.score)
        if (
            grey_button
            and imprint_button_saturation(screen) < 90
            and hero_information_tab_selected(screen)
        ):
            return PageObservation("hero_list", grey_button.score)

        story = find_prepare_battle_button(
            screen,
            self.templates.story_ready,
            self.templates.story_ready_updated,
            self._story_thresholds["prepare_battle"],
        )
        if story:
            return PageObservation("story_ready", story.score)
        story_watch = find_watch_story_button(
            screen,
            self.templates.story_watch,
            self._story_thresholds["watch_story"],
        )
        if story_watch:
            return PageObservation("story_ready", story_watch.score)
        arena = self._locate(
            screen,
            "arena_ready",
            self._arena_thresholds["list_ready"],
        )
        if arena:
            return PageObservation("arena_ready", arena.score)
        return PageObservation("unknown", 0.0)

    def _capture(self) -> tuple[np.ndarray, PageObservation]:
        screen = self.runtime.capture()
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_current_frame(screen)
        observation = self.observe(screen)
        return screen, observation

    def _dismiss_global_popup(
        self, screen: np.ndarray, observation: PageObservation
    ) -> bool:
        if observation.name != "friendship_points_popup":
            if observation.name != "arena_rank_promotion":
                return False
            close = find_rank_promotion_confirm(
                screen,
                self.templates.arena_rank_promotion_arrow,
                self.templates.arena_rank_confirm,
                ARENA_RANK_CONFIRM_THRESHOLD,
            )
            action = "确认竞技场段位提升"
        else:
            close = find_friendship_points_popup_close(
                screen,
                self.templates.friendship_points_title,
                self.templates.friendship_points_close,
            )
            action = "关闭辅助英雄友情点数提示"
        if close is None:
            raise RuntimeError(
                f"全局弹窗[{page_label(observation.name)}]缺少必需锚点"
            )
        self.runtime.log(
            f"模式=导航 页面={page_label(observation.name)} "
            f"置信度={close.score:.3f} 动作={action}"
        )
        self.runtime.click(close.center, action)
        return True

    def _recover_story(
        self,
        screen: np.ndarray,
        observation: PageObservation,
        attempts: _StoryRecoveryAttempts,
    ) -> bool:
        if observation.name == "story_playing":
            match = find_story_skip_button(
                screen,
                self.templates.story_skip,
                self._story_thresholds["skip"],
            )
            action = "skip-story-during-navigation"
        elif observation.name == "story_skip_confirm":
            match = find_story_skip_confirm(
                screen,
                self.templates.story_skip_confirm,
                self._story_thresholds["skip_confirm"],
            )
            action = "confirm-story-skip-during-navigation"
        else:
            attempts.action = None
            attempts.clicks = 0
            return False
        if match is None:
            raise RuntimeError(
                f"页面[{page_label(observation.name)}]缺少必需动作锚点"
            )
        if attempts.action != observation.name:
            attempts.action = observation.name
            attempts.clicks = 0
        if attempts.clicks >= 4:
            diagnostic = self._diagnostic(f"{observation.name}_recovery_failed")
            raise RuntimeError(
                f"页面[{page_label(observation.name)}]点击4次后仍未消失；"
                f"已保存诊断 {diagnostic}"
            )
        attempts.clicks += 1
        self.runtime.log(
            f"模式=导航 页面={page_label(observation.name)} 动作={action} "
            f"尝试={attempts.clicks}/4 置信度={match.score:.3f}"
        )
        self.runtime.click(match.center, action)
        return True

    def return_home(
        self,
        *,
        stop_probe: Optional[Callable[[np.ndarray], bool]] = None,
    ) -> np.ndarray:
        """受控返回大厅 —— **实现就是 v2**（``home_return.return_home_v2``）。

        ⚠️ 2026-09-26：老的那套循环（只会按 ESC、认不出就点屏幕中央）已**整段删除**，
        10 条路线现在只有一套回家实现。这里保留方法名与签名，是为了让调用方
        （``main.HomeReturn`` / ``daily_tasks`` / 一众测试替身）**一个字都不用改** ——
        它现在是 v2 的薄封装，负责把**只有导航层才有**的三样能力喂进去：

        - ``observe``：页面身份（v2 靠它做「动作发出去之后回头看生效没有」）；
        - ``dismiss``：清路障（系统弹窗 / 退出确认框 / 剧情演出）；
        - ``stop_probe``：接力钩子（原样转发，语义不变）。

        ⚠️ 不要把这三样改回「v2 自己认一遍」：那等于把判据抄成两份，迟早漂移
        （退出确认框那份更要命 —— 那种框上按 ESC 等于「确认退出游戏」）。
        """
        if self._home_return_templates is None:
            self._home_return_templates = build_home_return_templates(
                self._template_root, self.templates
            )
        story_recovery = _StoryRecoveryAttempts()
        return return_home_v2(
            templates=self._home_return_templates,
            runtime=self.runtime,
            observe=lambda screen: self.observe(screen).name,
            dismiss=lambda screen: self._dismiss_roadblock(screen, story_recovery),
            stop_probe=stop_probe,
            # 黑屏上限沿用本导航器的转场规格（老流程就是 ``transition_frames``）。
            invalid_frame_limit=self.transition_frames,
            sleep=self.sleep,
            poll_seconds=self.poll_seconds,
        )

    def _dismiss_roadblock(
        self, screen: np.ndarray, story_recovery: _StoryRecoveryAttempts
    ) -> bool:
        """清掉挡在回家路上的东西；返回 True 表示这一帧已经动过手，重新观察。

        三样都是**老流程有、v2 不认识**的：

        1. 系统弹窗（友情点数 / 竞技场段位晋升）—— 点掉它，不然它一直盖着页面；
        2. 剧情演出（播放中 / 跳过确认）—— 跳完，不然一直停在剧情页；
        3. **退出确认框** —— 必须点「取消」。⚠️ 这一条最要命：那种框上按 ESC
           在很多游戏里等同于「确认」，v2 的 ESC 兜底会把游戏**真的退掉**。
        """
        observation = self.observe(screen)
        if self._dismiss_global_popup(screen, observation):
            return True
        if self._recover_story(screen, observation, story_recovery):
            return True
        if observation.name == "exit_dialog":
            cancel = self._locate(screen, "exit_cancel") or self._locate(
                screen, "exit_cancel_updated"
            )
            if cancel is None:
                raise RuntimeError("退出确认框缺少取消按钮锚点")
            self.runtime.click(cancel.center, "取消退出游戏")
            return True
        return False

    def navigate(
        self,
        mode: str,
        *,
        lobby_screen: Optional[np.ndarray] = None,
        already_at: Optional[str] = None,
        plan: Optional[NavigationPlan] = None,
    ) -> None:
        """按路线受控导航：执行这条路线自己声明的 ``NavigationPlan``。

        ⚠️ 本方法**不认识任何具名路线**。2026-09-30 之前它是一张
        ``if mode == "story" / elif mode == "arena" / ...`` 的分派链（约 250 行），
        每加一条路线都要回来改这里；现在链条是数据，声明在
        ``modes.MODE_SPECS[...].navigation_plan`` 里 —— 新增路线**不用再动本文件**。

        ``already_at`` 是「接力」用的入口：表示当前画面**已经**落在导航链的哪个页面上。
        执行器据此跳过「到达那一页」以及它前面的所有步，从下一步接着走（已经站在链条
        末端就等于导航已完成）；跳过的步骤不再点任何东西，但**那一帧会继续被当作后续
        步骤的来源帧**。传本模式白名单之外的页面直接报错，不做静默降级（失败关闭）。
        """
        resolved = plan if plan is not None else _plan_for(mode)
        if already_at is not None and already_at not in resolved.resume_entries:
            raise ValueError(
                f"导航不支持从页面[{already_at}]接力进入模式[{mode}]"
            )
        current = lobby_screen
        start = 0
        if already_at is not None:
            for index, step in enumerate(resolved.steps):
                if already_at in step.targets:
                    start = index + 1
                    break
            else:  # pragma: no cover - 由 NavigationPlan.__post_init__ 的不变式兜住
                raise RuntimeError(
                    f"路线 {mode} 的接力白名单里有 {already_at}，但链条上没有这一步"
                )
            self.runtime.log(
                resolved.resume_log(
                    page=page_label(already_at),
                    terminal=start >= len(resolved.steps),
                )
            )
        for step in resolved.steps[start:]:
            if (
                step.skip_if_observed
                and current is not None
                and self.observe(current).name in step.skip_if_observed
            ):
                # 已经在目的地上了（例：远征停在赛季菜单）：跳过这一步，
                # 但**不换帧** —— 下一步就用这一帧当来源。
                continue
            current = self._transition(
                step.source,
                resolved.transition_target(step),
                step.anchor,
                step.label,
                source_screen=current,
                fixed_point=step.fixed_point,
            )
        self.runtime.log(resolved.ready_log(MODE_LABELS.get(mode, mode)))

    def _transition(
        self,
        source: str,
        target: str | tuple[str, ...],
        anchor: str,
        action: str,
        *,
        source_screen: Optional[np.ndarray] = None,
        fixed_point: Optional[tuple[int, int]] = None,
    ) -> np.ndarray:
        self.unknown_screen_wake.reset()
        source_screen = source_screen if source_screen is not None else self._wait_for_page(source)
        targets = (target,) if isinstance(target, str) else target
        target_label = "/".join(targets)
        for attempt in range(1, 5):
            threshold = 0.80 if anchor == "lobby_story" else 0.82
            if fixed_point is not None:
                # ⚠️ **固定坐标点击**：按钮上有会动的元素时，模板定位跨天必然掉出阈
                # （社区路线的「前往活动页」按钮：上面有一颗来回滑动的光球，
                # 跨天从 1.0000 掉到 0.7282 ⇒ 抛「缺少导航锚点」，连点都没点）。
                # 为什么敢用固定坐标：**页面身份这道「眼睛」没有少** —— 本步的
                # ``source`` 与 ``targets`` 验收照旧，点空了目标页不出现 ⇒
                # 按额度重试 ⇒ 失败留诊断，而不是无声跳过。
                offset = self._click_offset(anchor)
                click_point = (fixed_point[0] + offset[0], fixed_point[1] + offset[1])
            else:
                match = self._locate(source_screen, anchor, threshold)
                if match is None:
                    # ⚠️ 传入的 ``source_screen`` 可能是刚回家时的**过渡帧**（大厅还在
                    # 动画 / 未稳定）—— 老 ``return_home`` 会等「连续两帧稳定认出大厅」
                    # 才返回，v2 是「第一帧认出大厅就返回」，于是偶尔会把一个还没稳下来的
                    # 大厅帧交进来。个别锚点（尤其大厅左侧那排入口，常是最后渲染的控件）
                    # 在这种帧上会暂时没过阈，直接判「缺少锚点」会把整条路线打挂，
                    # 而且这个 raise 发生在 ``_enter_mode`` 里、跑在 ``run_mode`` 的
                    # try 之外，连日志和诊断都不会留下，只剩每日任务里一个无声的 ``✗``。
                    # 这里先重新等一帧**稳定的**来源页再认一次（正常帧不会进这个分支）。
                    self.runtime.log(
                        f"模式=导航 页面={page_label(source)} 目标={target_label} "
                        f"动作={action} 重试=重新等待稳定来源页（过渡帧锚点未过阈）"
                    )
                    source_screen = self._wait_for_page(source)
                    match = self._locate(source_screen, anchor, threshold)
                    if match is None:
                        raise RuntimeError(
                            f"页面[{page_label(source)}]缺少导航锚点 {anchor}"
                        )
                offset = self._click_offset(anchor)
                click_point = (match.center[0] + offset[0], match.center[1] + offset[1])
            self.runtime.log(
                f"模式=导航 页面={page_label(source)} 目标={target_label} "
                f"动作={action} 尝试={attempt}/4"
            )
            self.runtime.click(click_point, action)
            # 「点一次、验收一次」：记住点击时刻，循环里回头比一次页面身份。
            verify_started = self.now()
            stable = StableObservation(required=2)
            story_recovery = _StoryRecoveryAttempts()
            hero_detail_tab_clicks = 0
            hero_detail_last_click_at: Optional[float] = None
            hero_detail_wait_logged = False
            hero_equipment_seen = False
            hero_container_logged = False
            # 「来源已离开、目标未到，只等」这一档只记一次日志（否则每轮都刷）。
            transition_wait_logged = False
            last_source: Optional[np.ndarray] = None
            for _ in range(self.transition_frames):
                screen, observation = self._capture()
                is_stable = stable.update(observation.name)
                if is_stable and self._dismiss_global_popup(screen, observation):
                    stable.reset()
                    self.sleep(1.0)
                    continue
                if is_stable and self._recover_story(
                    screen, observation, story_recovery
                ):
                    stable.reset()
                    self.sleep(1.0)
                    continue
                if is_stable and observation.name == "unknown":
                    wake_result = self.unknown_screen_wake.handle(
                        screen,
                        context=f"导航:{page_label(source)}→{target_label}",
                    )
                    if wake_result is UnknownWakeResult.WAITING:
                        self.sleep(self.poll_seconds)
                        continue
                    # ⚠️ **表 D 第二档：「来源已离开、目标未稳 ⇒ 只等」**。
                    #
                    # 2026-10-07 实测踩到的坑：点「打开网页活动列表」之后那个 H5 要
                    # **29 秒**才加载完（实跑日志 10:50:49 点击 → 10:51:18 才认出来），
                    # 期间是**白屏且画面静止**。而 ``UnknownScreenWake`` 只在
                    # 「画面还在变」时给 ``WAITING``，静止的未知页直接给
                    # ``EXHAUSTED``（= 交还上层按失败收尾）⇒
                    # **一次完全正常的加载被判成「点坏了」**，白等 29 秒还失败。
                    #
                    # 所以这里补一条判据：**点完这一下之后、画面已经认不出来源页了**
                    # （``left_page(source, "unknown")`` 为真）⇒ 来源已离开，
                    # 现在正处在「转场 / 加载中」，**只等**，不许当成失败。
                    #
                    # ⚠️ 为什么不直接看画面变化：转场期间**也可能真的静止**
                    # （转场动画走完、H5 还没画完第一帧就是这个样子）。
                    # 「来源还在」才是「没点中」与「正在加载」的唯一可靠区别。
                    #
                    # ⚠️ 为什么**放在 handle() 之后**而不是之前：``handle()`` 负责
                    # 记账与留诊断帧（那张帧是事后查「当时到底长什么样」的唯一物证）。
                    # 在它之前 ``continue`` 会把诊断帧一起跳过 —— 那正是 2026-09-26
                    # 「不点任何地方」那条护栏要保的东西，不能为了社区这一条路线弄丢。
                    if (
                        wake_result is UnknownWakeResult.EXHAUSTED
                        and verify_started is not None
                        and left_page(source, observation.name)
                    ):
                        if not transition_wait_logged:
                            self.runtime.log(
                                f"模式=导航 页面={page_label(source)} "
                                f"目标={target_label} 动作={action} "
                                "当前=认不出的画面 "
                                "状态=来源已离开、目标未到（转场/加载中）"
                                "动作=只等，不判失败 "
                                f"已等={self.now() - verify_started:.0f}秒"
                            )
                            transition_wait_logged = True
                        self.sleep(self.poll_seconds)
                        continue
                elif is_stable:
                    self.unknown_screen_wake.reset()
                if (
                    is_stable
                    and target == "hero_list"
                    and observation.name in {"hero_equipment", "hero_list"}
                    and not hero_container_logged
                ):
                    subpage = (
                        "英雄装备"
                        if observation.name == "hero_equipment"
                        else "英雄信息"
                    )
                    self.runtime.log(
                        "模式=导航 页面=英雄列表容器 状态=已进入 "
                        f"当前子页={subpage}"
                    )
                    hero_container_logged = True
                if (
                    is_stable
                    and target == "hero_list"
                    and observation.name == "hero_equipment"
                ):
                    information_blue, equipment_blue = hero_tab_blue_pixel_counts(
                        screen
                    )
                    hero_equipment_seen = True
                    if hero_detail_last_click_at is not None:
                        remaining = (
                            self._HERO_DETAIL_TAB_RETRY_SECONDS
                            - (self.now() - hero_detail_last_click_at)
                        )
                        if remaining > 0:
                            if not hero_detail_wait_logged:
                                self.runtime.log(
                                    "模式=导航 当前子页=英雄装备 "
                                    "等待=点击后确认装备页退出 "
                                    f"剩余={remaining:.1f}秒 "
                                    f"信息蓝={information_blue} "
                                    f"装备蓝={equipment_blue}"
                                )
                                hero_detail_wait_logged = True
                            self.sleep(self.poll_seconds)
                            continue
                        self.runtime.log(
                            "模式=导航 离开标志=未满足 "
                            "当前子页=英雄装备 "
                            f"信息蓝={information_blue} "
                            f"装备蓝={equipment_blue}"
                        )
                    if (
                        hero_detail_tab_clicks
                        >= self._HERO_DETAIL_TAB_MAX_ATTEMPTS
                    ):
                        diagnostic = self._diagnostic(
                            "hero_information_tab_entry_failed"
                        )
                        raise RuntimeError(
                            "英雄装备页点击4次后仍未离开；"
                            f"信息蓝={information_blue} "
                            f"装备蓝={equipment_blue}；"
                            f"已保存诊断 {diagnostic}"
                        )
                    hero_detail_tab_clicks += 1
                    self.runtime.log(
                        "模式=导航 进入标志=英雄装备已确认 "
                        f"信息蓝={information_blue} "
                        f"装备蓝={equipment_blue} "
                        "动作=切换英雄信息 "
                        f"尝试={hero_detail_tab_clicks}/"
                        f"{self._HERO_DETAIL_TAB_MAX_ATTEMPTS}"
                    )
                    self.runtime.click(
                        self._HERO_DETAIL_TAB_POINT, "切换英雄信息"
                    )
                    hero_detail_last_click_at = self.now()
                    hero_detail_wait_logged = False
                    stable.reset()
                    self.sleep(self.poll_seconds)
                    continue
                # 「点一次、验收一次」：点完等满验收窗口，如果还停在来源页上，
                # 说明这一下点击压根没生效 —— 立刻结束本轮等待交给外层重试，
                # 而不是把整个转场窗口（约 92 秒）干等完、再点一次同样的坐标。
                # 实机日志 epic7_shop_refresh.log 2026-09-10：三次点同一个坐标
                # (82,521)，前两次各白等 92 秒，第三次 4 秒就进去了。
                if is_stable and verify_started is not None:
                    if left_page(source, observation.name):
                        self.runtime.log(
                            f"模式=导航 点击验收=生效 "
                            f"从={page_label(source)} "
                            f"到={page_label(observation.name)} "
                            f"耗时={self.now() - verify_started:.1f}秒"
                        )
                        verify_started = None
                    elif self.now() - verify_started >= self._CLICK_VERIFY_SECONDS:
                        self.runtime.log(
                            f"模式=导航 点击验收=无效 "
                            f"页面={page_label(source)} 动作={action} "
                            f"已等={self._CLICK_VERIFY_SECONDS:.0f}秒 "
                            f"状态=提前重试 尝试={attempt}/4"
                        )
                        if attempt == 2:
                            # 连点两次都纹丝不动（不是单次偶发）⇒ 先确认模拟器输入
                            # 通道还在不在，免得一路盲试到上限、最后只留下一句
                            # 分不清病因的「导航转场失败」（2026-10-03 实测）。
                            self.runtime.ensure_input_channel()
                        last_source = screen
                        break
                if is_stable and observation.name in targets:
                    if target == "hero_list" and observation.name == "hero_list":
                        information_blue, equipment_blue = (
                            hero_tab_blue_pixel_counts(screen)
                        )
                        if hero_equipment_seen:
                            self.runtime.log(
                                "模式=导航 离开标志=英雄装备已离开 "
                                f"信息蓝={information_blue} "
                                f"装备蓝={equipment_blue}"
                            )
                        self.runtime.log(
                            "模式=导航 进入标志=英雄信息已到达 "
                            "连续=2 "
                            f"信息蓝={information_blue} "
                            f"装备蓝={equipment_blue}"
                        )
                    self.runtime.log(
                        f"模式=导航 页面={page_label(observation.name)} "
                        f"置信度={observation.confidence:.3f} 状态=转场确认"
                    )
                    return screen
                if observation.name == source:
                    last_source = screen
                self.sleep(self.poll_seconds)
            if last_source is not None:
                source_screen = last_source
                self.runtime.log(
                    f"模式=导航 页面={page_label(source)} 等待=无转场 "
                    f"重试={attempt}/2"
                )
                continue
            break
        diagnostic = self._diagnostic(f"navigation_{source}_to_{target_label}_failed")
        raise RuntimeError(
            f"导航转场 {page_label(source)} → {target_label} 失败；已保存诊断 {diagnostic}"
        )

    def _wait_for_page(self, expected: str) -> np.ndarray:
        self.unknown_screen_wake.reset()
        stable = StableObservation(required=2)
        story_recovery = _StoryRecoveryAttempts()
        for _ in range(self.transition_frames):
            screen, observation = self._capture()
            is_stable = stable.update(observation.name)
            if is_stable and self._dismiss_global_popup(screen, observation):
                stable.reset()
                self.sleep(1.0)
                continue
            if is_stable and self._recover_story(
                screen, observation, story_recovery
            ):
                stable.reset()
                self.sleep(1.0)
                continue
            if is_stable and observation.name == "unknown":
                wake_result = self.unknown_screen_wake.handle(
                    screen,
                    context=f"导航:等待{page_label(expected)}",
                )
                if wake_result is UnknownWakeResult.WAITING:
                    self.sleep(self.poll_seconds)
                    continue
            elif is_stable:
                self.unknown_screen_wake.reset()
            if is_stable and observation.name == expected:
                return screen
            self.sleep(self.poll_seconds)
        diagnostic = self._diagnostic(f"expected_{expected}")
        raise RuntimeError(
            f"导航开始前应处于[{page_label(expected)}]；已保存诊断 {diagnostic}"
        )

    def _diagnostic(self, label: str):
        if self.runtime.diagnostic_dir is None:
            return "not-configured"
        return self.runtime.save_diagnostic(label)
