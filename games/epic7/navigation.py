"""Fail-closed navigation from any supported Epic Seven page."""

from dataclasses import dataclass
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation
from auto_game_unified.games.epic7.arena import find_rank_promotion_confirm
from auto_game_unified.games.epic7.global_popups import (
    find_friendship_points_popup_close,
)
from auto_game_unified.games.epic7.story import (
    find_prepare_battle_button,
    find_story_skip_button,
    find_story_skip_confirm,
    find_watch_story_button,
)
from auto_game_unified.games.epic7.hero_synthesis import (
    imprint_button_saturation,
)
from auto_game_unified.games.epic7.unknown_screen import (
    UnknownScreenWake,
    UnknownWakeResult,
)


REFERENCE_SIZE = (1982, 1132)


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
    "expedition_home": "远征主页",
    "arena_mode": "竞技场模式选择",
    "fodder_episode_detail": "支线详情",
    "fodder_special_book": "特别之书",
    "fodder_side_story": "支线故事",
    "hero_list": "英雄列表",
    "hero_equipment": "英雄装备子页",
    "story_ready": "主线入口",
    "arena_ready": "竞技场入口",
    "unknown": "未知画面",
}

# 日志用模式名：模式标识 -> 中文模式名
MODE_LABELS = {
    "story": "主线",
    "arena": "竞技场",
    "expedition": "远征",
    "fodder": "狗粮",
    "assist_auto": "辅助自动",
    "hero_synthesis": "英雄合成",
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


def build_navigation_templates(template_root: Path) -> NavigationTemplates:
    navigation = template_root / "navigation"
    global_templates = template_root / "global"
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
        lobby_story_click_offset=(120, -20)
        if template_root.name == "templates_pc"
        else (65, 11),
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
    )


class Epic7Navigator:
    """Return to the lobby, then follow a verified mode-specific route."""

    _BACK_RETRY_SECONDS = 15
    _HERO_DETAIL_TAB_POINT = (65, 150)

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
        "expedition_battle_title": (0, 35, 350, 180),
        "expedition_season_tab": (250, 140, 500, 200),
        "expedition_season_active": (250, 140, 500, 200),
        "expedition_entry": (850, 240, 500, 260),
        "expedition_home": (1400, 880, 582, 252),
        "lobby_side_story": (1700, 380, 215, 120),
        "side_story_special_book": (1520, 900, 385, 110),
        "special_book_episode": (790, 995, 500, 110),
        "episode_adventure": (1595, 945, 338, 187),
        "fodder_stage_title": (850, 760, 225, 90),
        "fodder_prepare_battle": (1365, 990, 385, 120),
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
    ) -> None:
        self.templates = templates
        self.runtime = runtime
        self.sleep = sleep
        self.now = runtime.now
        self.poll_seconds = poll_seconds
        self.transition_frames = transition_frames
        self.unknown_screen_wake = UnknownScreenWake(runtime)

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

        rank_confirm = find_rank_promotion_confirm(
            screen,
            self.templates.arena_rank_promotion_arrow,
            self.templates.arena_rank_confirm,
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
            screen, self.templates.story_skip_confirm
        )
        if story_skip_confirm is not None:
            return PageObservation("story_skip_confirm", story_skip_confirm.score)
        story_skip = find_story_skip_button(screen, self.templates.story_skip)
        if story_skip is not None:
            return PageObservation("story_playing", story_skip.score)

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
        if hero_list:
            return PageObservation("hero_list", hero_list.score)
        # 选中 3S 满级英雄时刻印按钮置灰（深/浅两种灰），正常模板高分失配；
        # 结构匹配（图标轮廓仍在）+ 饱和度确认置灰状态，同样认定为英雄列表。
        grey_button = self._locate(screen, "imprint_button_normal", 0.50)
        if grey_button and imprint_button_saturation(screen) < 90:
            return PageObservation("hero_list", grey_button.score)

        story = find_prepare_battle_button(
            screen,
            self.templates.story_ready,
            self.templates.story_ready_updated,
        )
        if story:
            return PageObservation("story_ready", story.score)
        story_watch = find_watch_story_button(screen, self.templates.story_watch)
        if story_watch:
            return PageObservation("story_ready", story_watch.score)
        arena = self._locate(screen, "arena_ready", 0.88)
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
            match = find_story_skip_button(screen, self.templates.story_skip)
            action = "skip-story-during-navigation"
        elif observation.name == "story_skip_confirm":
            match = find_story_skip_confirm(screen, self.templates.story_skip_confirm)
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

    def return_home(self) -> np.ndarray:
        self.runtime.log("模式=导航 目标=大厅 状态=开始")
        stable = StableObservation(required=2)
        back_count = 0
        last_back_at: Optional[float] = None
        back_wait_logged = False
        invalid_count = 0
        story_recovery = _StoryRecoveryAttempts()
        for _ in range(self.transition_frames * 4):
            screen, observation = self._capture()
            is_stable = stable.update(observation.name)
            if observation.name == "invalid":
                invalid_count += 1
                if invalid_count >= self.transition_frames:
                    diagnostic = self._diagnostic("black_or_non_game")
                    raise RuntimeError(
                        f"画面持续黑屏或非游戏帧；已保存诊断 {diagnostic}"
                    )
                self.sleep(self.poll_seconds)
                continue
            invalid_count = 0
            if not is_stable:
                self.sleep(self.poll_seconds)
                continue
            if observation.name != "unknown":
                self.unknown_screen_wake.reset()
            if self._dismiss_global_popup(screen, observation):
                last_back_at = None
                back_wait_logged = False
                stable.reset()
                self.sleep(1.0)
                continue
            if self._recover_story(screen, observation, story_recovery):
                last_back_at = None
                back_wait_logged = False
                stable.reset()
                self.sleep(1.0)
                continue
            self.runtime.log(
                f"模式=导航 页面={page_label(observation.name)} "
                f"置信度={observation.confidence:.3f}"
            )
            if observation.name == "lobby":
                self.runtime.log("模式=导航 页面=大厅 状态=已确认")
                return screen
            if observation.name == "exit_dialog":
                cancel = self._locate(screen, "exit_cancel") or self._locate(
                    screen, "exit_cancel_updated"
                )
                if cancel is None:
                    raise RuntimeError("退出确认框缺少取消按钮锚点")
                self.runtime.click(cancel.center, "取消退出游戏")
                last_back_at = self.now()
                back_wait_logged = False
                stable.reset()
                self.sleep(1.0)
                continue
            if last_back_at is not None:
                since_back = self.now() - last_back_at
                if since_back < self._BACK_RETRY_SECONDS:
                    if not back_wait_logged:
                        remaining = self._BACK_RETRY_SECONDS - since_back
                        self.runtime.log(
                            f"模式=导航 页面={page_label(observation.name)} "
                            f"等待=返回后确认转场 剩余={remaining:.1f}秒"
                        )
                        back_wait_logged = True
                    self.sleep(self.poll_seconds)
                    continue
            if observation.name == "unknown":
                wake_result = self.unknown_screen_wake.handle(
                    screen,
                    context="导航:回大厅",
                )
                if wake_result in {
                    UnknownWakeResult.WAITING,
                    UnknownWakeResult.CLICKED,
                }:
                    self.sleep(self.poll_seconds)
                    continue
            if back_count >= 8:
                diagnostic = self._diagnostic("return_home_failed")
                raise RuntimeError(
                    f"受控返回8次后仍未回到大厅；已保存诊断 {diagnostic}"
                )
            if observation.name == "story_ready":
                back = self._locate(screen, "story_back", 0.90)
                if back is None:
                    raise RuntimeError("主线入口页面缺少可见的返回按钮")
                back_count += 1
                self.runtime.log(
                    f"模式=导航 页面=主线入口 动作=点击游戏内返回 "
                    f"重试={back_count}/8"
                )
                self.runtime.click(back.center, "click-story-back")
                self.unknown_screen_wake.reset()
                last_back_at = self.now()
                back_wait_logged = False
                stable.reset()
                self.sleep(1.0)
                continue
            back_count += 1
            self.runtime.log(
                f"模式=导航 页面={page_label(observation.name)} "
                f"动作=受控返回 重试={back_count}/8"
            )
            self.runtime.back("受控返回大厅")
            self.unknown_screen_wake.reset()
            last_back_at = self.now()
            back_wait_logged = False
            stable.reset()
            self.sleep(1.0)
        diagnostic = self._diagnostic("return_home_timeout")
        raise RuntimeError(
            f"返回大厅超过120秒观测预算；已保存诊断 {diagnostic}"
        )

    def navigate(self, mode: str, *, lobby_screen: Optional[np.ndarray] = None) -> None:
        if mode == "story":
            self._transition(
                "lobby", "story_ready", "lobby_story", "进入主线",
                source_screen=lobby_screen,
            )
        elif mode == "arena":
            arena_mode = self._transition(
                "lobby", "arena_mode", "lobby_arena", "进入竞技场",
                source_screen=lobby_screen,
            )
            self._transition(
                "arena_mode", "arena_ready", "novice_arena", "进入新手竞技场",
                source_screen=arena_mode,
            )
        elif mode == "expedition":
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
        else:
            raise ValueError(f"导航不支持的模式：{mode}")
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
            stable = StableObservation(required=2)
            story_recovery = _StoryRecoveryAttempts()
            hero_detail_tab_switched = False
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
                    if wake_result in {
                        UnknownWakeResult.WAITING,
                        UnknownWakeResult.CLICKED,
                    }:
                        self.sleep(self.poll_seconds)
                        continue
                elif is_stable:
                    self.unknown_screen_wake.reset()
                if (
                    is_stable
                    and target == "hero_list"
                    and observation.name == "hero_equipment"
                    and not hero_detail_tab_switched
                ):
                    self.runtime.log(
                        "模式=导航 页面=英雄装备子页 动作=切换英雄详情"
                    )
                    self.runtime.click(
                        self._HERO_DETAIL_TAB_POINT, "切换英雄详情"
                    )
                    hero_detail_tab_switched = True
                    stable.reset()
                    self.sleep(self.poll_seconds)
                    continue
                if is_stable and observation.name in targets:
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
                if wake_result in {
                    UnknownWakeResult.WAITING,
                    UnknownWakeResult.CLICKED,
                }:
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
