"""Fail-closed navigation from any supported Epic Seven page."""

from dataclasses import dataclass
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import (
    StableObservation,
    left_page,
)
from auto_game_unified.games.epic7.arena import (
    ARENA_ENTRY_PAGE,
    find_rank_promotion_confirm,
)
from auto_game_unified.games.epic7.evidence.arena import thresholds_for as arena_thresholds_for
from auto_game_unified.games.epic7.evidence.story import thresholds_for as story_thresholds_for
from auto_game_unified.games.epic7.global_popups import (
    find_friendship_points_popup_close,
    find_gift_support_close,
    find_knights_signin_close,
)
from auto_game_unified.games.epic7.home_return import (
    HomeReturnTemplates,
    build_home_return_templates,
    return_home_v2,
)
from auto_game_unified.games.epic7.expedition import (
    EXPEDITION_BATTLE_MENU_PAGE,
    EXPEDITION_ENTRY_PAGE,
    EXPEDITION_RESUME_PAGES,
    EXPEDITION_SEASON_PAGE,
)
from auto_game_unified.games.epic7.knights_donation import KNIGHTS_GUILD_HOME_PAGE
from auto_game_unified.games.epic7.story import (
    STORY_ENTRY_PAGE,
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
from auto_game_unified.games.epic7.world_boss import WORLD_BOSS_ENTRY_PAGE
from auto_game_unified.games.epic7.unknown_screen import (
    UnknownScreenWake,
    UnknownWakeResult,
)


REFERENCE_SIZE = (1982, 1132)

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
    "story_ready": "主线入口",
    "arena_ready": "竞技场入口",
    "shop_refresh": "秘密商店",
    "knights_home": "骑士团主页",
    "worldboss_home": "世界首领战主页",
    "knights_signin_popup": "骑士团签到弹窗",
    "gift_support_popup": "领取支援物品弹窗",
    "unknown": "未知画面",
}

# 日志用模式名：模式标识 -> 中文模式名
MODE_LABELS = {
    "story": "主线",
    "arena": "竞技场",
    "expedition": "远征",
    "fodder": "狗粮",
    "hero_synthesis": "英雄合成",
    "shop_refresh": "刷书签",
    "world_boss": "世界首领战",
    "knights_donation": "骑士团捐赠",
    "labyrinth_stone": "迷宫强化石",
}


# 「接力」白名单：模式 -> 允许 ``navigate(already_at=...)`` 的导航链页面。
# 只列模式自己声明过的接力页；传别的一律报错，不做静默降级（失败关闭）。
_RESUME_ENTRY_PAGES = {
    "arena": frozenset({ARENA_ENTRY_PAGE}),
    "story": frozenset({STORY_ENTRY_PAGE}),
    "expedition": EXPEDITION_RESUME_PAGES,
    "world_boss": frozenset({KNIGHTS_GUILD_HOME_PAGE, WORLD_BOSS_ENTRY_PAGE}),
    # 骑士团捐赠的导航链只有一级，所以「在导航链上」的落点只有骑士团主页一个。
    # 业务链里的页面（资源支援 / 每周任务）探针把 ``entry`` 留空 ⇒ 根本不会走到这里。
    "knights_donation": frozenset({KNIGHTS_GUILD_HOME_PAGE}),
    # 迷宫强化石的接力落点全在**业务链**上（战斗菜单 → 迷宫列表 → … → 大厅），
    # 探针一律就地接管、不返回 ``entry`` ⇒ 这里没有需要导航对接的页面。
    # 空集合是合法值：``already_at`` 为 None 时上面的判断根本不会走到。
    "labyrinth_stone": frozenset(),
}


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
    lobby_profile: np.ndarray
    lobby_story: np.ndarray
    lobby_arena: np.ndarray
    lobby_battle: np.ndarray
    lobby_hero: np.ndarray
    hero_equipment_tab_active: Optional[np.ndarray]
    imprint_button_normal: np.ndarray
    exit_title: np.ndarray
    exit_cancel: np.ndarray
    exit_title_updated: np.ndarray
    exit_cancel_updated: np.ndarray
    arena_mode_title: np.ndarray
    novice_arena: np.ndarray
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
    expedition_entry: np.ndarray
    expedition_home: np.ndarray
    lobby_story_click_offset: tuple[int, int]
    lobby_side_story: np.ndarray
    side_story_special_book: np.ndarray
    special_book_episode: np.ndarray
    episode_adventure: np.ndarray
    fodder_stage_title: np.ndarray
    fodder_prepare_battle: np.ndarray
    lobby_shop_entry: np.ndarray
    lobby_knights: np.ndarray
    worldboss_entry: np.ndarray
    lobby_worldboss_select_team: np.ndarray
    knights_signin_title: np.ndarray
    knights_signin_close: np.ndarray
    gift_support_title: np.ndarray
    gift_support_close: np.ndarray
    shop_refresh_observer: ShopRefreshObserver


def build_navigation_templates(template_root: Path) -> NavigationTemplates:
    navigation = template_root / "navigation"
    global_templates = template_root / "global"
    shop_evidence = build_shop_refresh_evidence(template_root)
    shop_entry = shop_evidence.atom("lobby_shop_entry")
    world_boss_evidence = build_world_boss_evidence(template_root / "world_boss")
    world_boss_select_team = world_boss_evidence.atom("select_team_button")
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
        lobby_profile=load_template(str(navigation / "lobby_profile.png")),
        lobby_story=load_template(str(navigation / "lobby_story.png")),
        lobby_arena=load_template(str(navigation / "lobby_arena.png")),
        lobby_battle=load_template(str(navigation / "lobby_battle.png")),
        lobby_hero=load_template(str(navigation / "lobby_hero.png")),
        hero_equipment_tab_active=(
            load_template(str(navigation / "hero_equipment_tab_active.png"))
            if (navigation / "hero_equipment_tab_active.png").exists()
            else None
        ),
        imprint_button_normal=load_template(
            str(template_root / "hero" / "imprint_button_normal.png")
        ),
        exit_title=load_template(str(navigation / "exit_title.png")),
        exit_cancel=load_template(str(navigation / "exit_cancel.png")),
        exit_title_updated=load_template(str(navigation / "exit_title_updated.png")),
        exit_cancel_updated=load_template(str(navigation / "exit_cancel_updated.png")),
        arena_mode_title=load_template(str(navigation / "arena_mode_title.png")),
        novice_arena=load_template(str(navigation / "novice_arena.png")),
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
        lobby_shop_entry=load_template(
            str(template_root / shop_entry.template_path)
        ),
        lobby_knights=load_template(str(navigation / "lobby_knights.png")),
        worldboss_entry=load_template(str(navigation / "worldboss_entry.png")),
        lobby_worldboss_select_team=load_template(
            str(template_root / "world_boss" / world_boss_select_team.template_path)
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
        "lobby_profile": (0, 35, 500, 200),
        "lobby_story": (1450, 220, 480, 200),
        "lobby_arena": (1600, 520, 330, 220),
        "lobby_battle": (1650, 430, 332, 220),
        "lobby_hero": (1400, 980, 180, 130),
        "hero_equipment_tab_active": (0, 200, 130, 140),
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
        # 骑士团主页的「世界首领战」入口图标（骷髅盾牌）。排他性实测：本页 0.9890，
        # 跨页最高 0.4210（远征海报）。
        "worldboss_entry": (380, 620, 180, 140),
        # 世界首领战主页右下角「选择队伍」按钮。⚠️ 这里复用 evidence/world_boss.py
        # 的锚点图（不是 navigation 目录下的第二份），避免同一个控件维护两份模板。
        "lobby_worldboss_select_team": WORLD_BOSS_REGIONS["select_team_button"],
    }
    _CLICK_OFFSETS = {"lobby_story": (65, 11)}

    def __init__(
        self,
        templates: NavigationTemplates,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 0.5,
        transition_frames: int = 90,
        backend: str = "emulator",
    ) -> None:
        self.templates = templates
        self.runtime = runtime
        self.backend = backend
        self._story_thresholds = story_thresholds_for(backend)
        self._arena_thresholds = arena_thresholds_for(backend)
        self.sleep = sleep
        self.now = runtime.now
        self.poll_seconds = poll_seconds
        self.transition_frames = transition_frames
        self.unknown_screen_wake = UnknownScreenWake(runtime)
        # 「回家」用的那套模板（v2）。懒构建：大部分路线压根不回家，别白读 10 张图。
        self._home_return_templates: Optional[HomeReturnTemplates] = None

    def _locate(self, screen: np.ndarray, name: str, threshold: float = 0.82) -> Optional[Match]:
        return find_template(
            screen,
            getattr(self.templates, name),
            threshold,
            region=self._REGIONS[name],
            reference_size=REFERENCE_SIZE,
        )

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

        rank_confirm = find_rank_promotion_confirm(
            screen,
            self.templates.arena_rank_promotion_arrow,
            self.templates.arena_rank_confirm,
            0.85 if self.backend == "pc" else 0.90,
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

        hero_equipment = (
            self._locate(screen, "hero_equipment_tab_active", 0.85)
            if self.templates.hero_equipment_tab_active is not None
            else None
        )
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
                0.85 if self.backend == "pc" else 0.90,
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
                TEMPLATE_ROOT, self.templates
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
    ) -> None:
        """按路线受控导航。

        ``already_at`` 是「接力」用的入口：表示当前画面**已经**落在导航链的哪个页面上，
        跳过它之前的所有转场，直接从那一步接着往下走。传了本模式不认识的页面会直接报错，
        不做静默降级（失败关闭）。
        """
        if already_at is not None and already_at not in _RESUME_ENTRY_PAGES.get(
            mode, frozenset()
        ):
            raise ValueError(
                f"导航不支持从页面[{already_at}]接力进入模式[{mode}]"
            )
        if mode == "story":
            if already_at == STORY_ENTRY_PAGE:
                # 已经站在关卡入口上了：回大厅再进来一趟纯属多余，而且中途一旦
                # 按到「返回」就会把当前选区丢掉。这里直接当作导航已完成。
                self.runtime.log(
                    "模式=导航 开局=接力 页面=主线入口 "
                    "动作=跳过回大厅与进入主线 状态=已在关卡入口"
                )
            else:
                self._transition(
                    "lobby", "story_ready", "lobby_story", "进入主线",
                    source_screen=lobby_screen,
                )
        elif mode == "arena":
            if already_at == ARENA_ENTRY_PAGE:
                if lobby_screen is None:
                    raise RuntimeError("接力进入竞技场时缺少当前画面")
                self.runtime.log(
                    "模式=竞技场 开局=接力 页面=竞技场模式选择 "
                    "动作=跳过回大厅与进入竞技场 状态=直接进新手竞技场"
                )
                arena_mode = lobby_screen
            else:
                arena_mode = self._transition(
                    "lobby", "arena_mode", "lobby_arena", "进入竞技场",
                    source_screen=lobby_screen,
                )
            self._transition(
                "arena_mode", "arena_ready", "novice_arena", "进入新手竞技场",
                source_screen=arena_mode,
            )
        elif mode == "expedition":
            if already_at == EXPEDITION_ENTRY_PAGE:
                # 已经站在远征主页上：整条导航链都没有要做的了。
                self.runtime.log(
                    "模式=导航 开局=接力 页面=远征主页 "
                    "动作=跳过回大厅与进入远征队 状态=已在远征主页"
                )
            else:
                if already_at in (
                    EXPEDITION_BATTLE_MENU_PAGE,
                    EXPEDITION_SEASON_PAGE,
                ):
                    # 已经在链条中间：跳过「回大厅 → 进战斗菜单」，从当前这一级往下走。
                    # 战斗菜单和赛季菜单都靠 observe() 自己认出来（下面那行），所以两者
                    # 用同一条路径，不用分开写。
                    if lobby_screen is None:
                        raise RuntimeError("接力进入远征时缺少当前画面")
                    self.runtime.log(
                        f"模式=导航 开局=接力 页面={page_label(already_at)} "
                        "动作=跳过回大厅与进入战斗菜单 状态=从当前这一级继续"
                    )
                    battle_menu = lobby_screen
                else:
                    battle_menu = self._transition(
                        "lobby",
                        ("battle_menu", "season_menu"),
                        "lobby_battle",
                        "进入战斗菜单",
                        source_screen=lobby_screen,
                    )
                if self.observe(battle_menu).name == "season_menu":
                    season_menu = battle_menu
                else:
                    season_menu = self._transition(
                        "battle_menu",
                        "season_menu",
                        "expedition_season_tab",
                        "切换到赛季",
                        source_screen=battle_menu,
                    )
                self._transition(
                    "season_menu",
                    "expedition_home",
                    "expedition_entry",
                    "进入远征队",
                    source_screen=season_menu,
                )
        elif mode == "fodder":
            side_story = self._transition(
                "lobby",
                "fodder_side_story",
                "lobby_side_story",
                "进入支线故事",
                source_screen=lobby_screen,
            )
            special_book = self._transition(
                "fodder_side_story",
                "fodder_special_book",
                "side_story_special_book",
                "进入特别的时间之书",
                source_screen=side_story,
            )
            episode_detail = self._transition(
                "fodder_special_book",
                "fodder_episode_detail",
                "special_book_episode",
                "进入Episode",
                source_screen=special_book,
            )
            self._transition(
                "fodder_episode_detail",
                "fodder_stage",
                "episode_adventure",
                "进入冒险地图",
                source_screen=episode_detail,
            )
        elif mode == "hero_synthesis":
            self._transition(
                "lobby", "hero_list", "lobby_hero", "进入英雄列表",
                source_screen=lobby_screen,
            )
        elif mode == "shop_refresh":
            self._transition(
                "lobby",
                "shop_refresh",
                "lobby_shop_entry",
                "进入秘密商店",
                source_screen=lobby_screen,
            )
        elif mode == "world_boss":
            if already_at == WORLD_BOSS_ENTRY_PAGE:
                # 已经站在世界首领战主页上：整条导航链都没有要做的了。
                self.runtime.log(
                    "模式=导航 开局=接力 页面=世界首领战主页 "
                    "动作=跳过回大厅与进入骑士团 状态=已在世界首领战主页"
                )
            else:
                if already_at == KNIGHTS_GUILD_HOME_PAGE:
                    # 已经在链条中间：跳过「回大厅 → 进骑士团」，从当前这一级往下走。
                    if lobby_screen is None:
                        raise RuntimeError("接力进入世界首领战时缺少当前画面")
                    self.runtime.log(
                        "模式=导航 开局=接力 页面=骑士团主页 "
                        "动作=跳过回大厅与进入骑士团 状态=从当前这一级继续"
                    )
                    knights_home = lobby_screen
                else:
                    knights_home = self._transition(
                        "lobby",
                        "knights_home",
                        "lobby_knights",
                        "进入骑士团",
                        source_screen=lobby_screen,
                    )
                self._transition(
                    "knights_home",
                    "worldboss_home",
                    "worldboss_entry",
                    "进入世界首领战",
                    source_screen=knights_home,
                )
        elif mode == "knights_donation":
            # 骑士团捐赠的导航链只有一级：大厅 → 骑士团主页。
            # 「点骑士团活动图标」以及后面整条业务链都在 ``knights_donation.py`` 的
            # 状态机里，导航只负责把画面送到骑士团主页。
            if already_at == KNIGHTS_GUILD_HOME_PAGE:
                # 人已经站在骑士团主页上了：回大厅再进来一趟纯属多余。
                # 业务链里那两页（资源支援 / 每周任务）的 ``entry`` 是 None，
                # 探针就地接管、不会调到这里。
                self.runtime.log(
                    "模式=骑士团捐赠 开局=接力 页面=骑士团主页 "
                    "动作=跳过回大厅与进入骑士团 状态=已在骑士团主页"
                )
            else:
                self._transition(
                    "lobby",
                    "knights_home",
                    "lobby_knights",
                    "进入骑士团",
                    source_screen=lobby_screen,
                )
        elif mode == "labyrinth_stone":
            # 导航链只有一级：大厅 → 战斗菜单。后面「点迷宫卡片 → 选迷宫 → 选区域 →
            # 选择队伍 → 战斗开始」全在 ``labyrinth_stone.py`` 的状态机里。
            # ⚠️ 只认战斗菜单（「一般」页）：迷宫卡片只在那一页上，
            # 落到「赛季」页会当场报错而不是静默往下走 —— 那页需要另补一个
            # 「一般」页签模板才能处理，现在没有正例，不做猜。
            self._transition(
                "lobby",
                "battle_menu",
                "lobby_battle",
                "进入战斗菜单",
                source_screen=lobby_screen,
            )
        else:
            raise ValueError(f"导航不支持的模式：{mode}")
        if mode == "hero_synthesis":
            self.runtime.log(
                "模式=英雄合成 状态=导航完成 前提=英雄信息页已就绪"
            )
        elif mode == "shop_refresh":
            self.runtime.log("模式=刷书签 状态=导航完成 前提=秘密商店顶部已就绪")
        elif mode == "world_boss":
            self.runtime.log(
                "模式=世界首领战 状态=导航完成 前提=世界首领战主页已就绪"
            )
        elif mode == "knights_donation":
            self.runtime.log(
                "模式=骑士团捐赠 状态=导航完成 前提=骑士团主页已就绪"
            )
        elif mode == "labyrinth_stone":
            self.runtime.log(
                "模式=迷宫强化石 状态=导航完成 前提=战斗菜单「一般」页已就绪"
            )
        else:
            self.runtime.log(f"模式={MODE_LABELS.get(mode, mode)} 状态=导航完成")

    def _transition(
        self,
        source: str,
        target: str | tuple[str, ...],
        anchor: str,
        action: str,
        *,
        source_screen: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        self.unknown_screen_wake.reset()
        source_screen = source_screen if source_screen is not None else self._wait_for_page(source)
        targets = (target,) if isinstance(target, str) else target
        target_label = "/".join(targets)
        for attempt in range(1, 5):
            threshold = 0.80 if anchor == "lobby_story" else 0.82
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
            self.runtime.log(
                f"模式=导航 页面={page_label(source)} 目标={target_label} "
                f"动作={action} 尝试={attempt}/4"
            )
            offset = self._click_offset(anchor)
            click_point = (match.center[0] + offset[0], match.center[1] + offset[1])
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
