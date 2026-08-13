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
from auto_game_unified.games.epic7.story import (
    find_friendship_points_popup_close,
    find_prepare_battle_button,
    find_watch_story_button,
)


REFERENCE_SIZE = (1982, 1132)


@dataclass(frozen=True)
class PageObservation:
    name: str
    confidence: float


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
    exit_title: np.ndarray
    exit_cancel: np.ndarray
    exit_title_updated: np.ndarray
    exit_cancel_updated: np.ndarray
    arena_mode_title: np.ndarray
    novice_arena: np.ndarray
    story_back: np.ndarray
    story_watch: np.ndarray
    story_ready: np.ndarray
    story_ready_updated: np.ndarray
    arena_ready: np.ndarray
    expedition_battle_title: np.ndarray
    expedition_season_tab: np.ndarray
    expedition_season_active: np.ndarray
    expedition_entry: np.ndarray
    expedition_home: np.ndarray


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
        exit_title=load_template(str(navigation / "exit_title.png")),
        exit_cancel=load_template(str(navigation / "exit_cancel.png")),
        exit_title_updated=load_template(str(navigation / "exit_title_updated.png")),
        exit_cancel_updated=load_template(str(navigation / "exit_cancel_updated.png")),
        arena_mode_title=load_template(str(navigation / "arena_mode_title.png")),
        novice_arena=load_template(str(navigation / "novice_arena.png")),
        story_back=load_template(str(navigation / "story_back.png")),
        story_watch=load_template(str(template_root / "story" / "watch_story.png")),
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
    )


class Epic7Navigator:
    """Return to the lobby, then follow a verified mode-specific route."""

    _BACK_RETRY_SECONDS = 15

    _REGIONS = {
        "lobby_profile": (0, 35, 500, 200),
        "lobby_story": (1450, 220, 480, 200),
        "lobby_arena": (1600, 520, 330, 220),
        "lobby_battle": (1650, 430, 332, 220),
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

    def _locate(self, screen: np.ndarray, name: str, threshold: float = 0.82) -> Optional[Match]:
        return find_template(
            screen,
            getattr(self.templates, name),
            threshold,
            region=self._REGIONS[name],
            reference_size=REFERENCE_SIZE,
        )

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

        exit_title = self._locate(screen, "exit_title")
        exit_cancel = self._locate(screen, "exit_cancel")
        if exit_title and exit_cancel:
            return PageObservation("exit_dialog", min(exit_title.score, exit_cancel.score))
        exit_title_updated = self._locate(screen, "exit_title_updated")
        exit_cancel_updated = self._locate(screen, "exit_cancel_updated")
        if exit_title_updated and exit_cancel_updated:
            return PageObservation(
                "exit_dialog",
                min(exit_title_updated.score, exit_cancel_updated.score),
            )

        lobby = [
            self._locate(screen, "lobby_story", 0.80),
            self._locate(screen, "lobby_arena"),
        ]
        if all(lobby):
            return PageObservation("lobby", min(match.score for match in lobby if match))

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
            raise RuntimeError(f"global popup {observation.name} lost a required anchor")
        self.runtime.log(
            f"模式=导航 页面={observation.name} 置信度={close.score:.3f} 动作={action}"
        )
        self.runtime.click(close.center, action)
        return True

    def return_home(self) -> np.ndarray:
        self.runtime.log("模式=导航 目标=大厅 状态=开始")
        stable = StableObservation(required=2)
        back_count = 0
        last_back_at: Optional[float] = None
        back_wait_logged = False
        invalid_count = 0
        for _ in range(self.transition_frames * 4):
            screen, observation = self._capture()
            is_stable = stable.update(observation.name)
            if observation.name == "invalid":
                invalid_count += 1
                if invalid_count >= self.transition_frames:
                    diagnostic = self._diagnostic("black_or_non_game")
                    raise RuntimeError(f"black or non-game frame persisted; saved {diagnostic}")
                self.sleep(self.poll_seconds)
                continue
            invalid_count = 0
            if not is_stable:
                self.sleep(self.poll_seconds)
                continue
            if self._dismiss_global_popup(screen, observation):
                last_back_at = None
                back_wait_logged = False
                stable.reset()
                self.sleep(1.0)
                continue
            self.runtime.log(
                f"模式=导航 页面={observation.name} 置信度={observation.confidence:.3f}"
            )
            if observation.name == "lobby":
                self.runtime.log("模式=导航 页面=大厅 状态=已确认")
                return screen
            if observation.name == "exit_dialog":
                cancel = self._locate(screen, "exit_cancel") or self._locate(
                    screen, "exit_cancel_updated"
                )
                if cancel is None:
                    raise RuntimeError("exit dialog lost its cancel anchor")
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
                            f"模式=导航 页面={observation.name} "
                            f"等待=返回后确认转场 剩余={remaining:.1f}秒"
                        )
                        back_wait_logged = True
                    self.sleep(self.poll_seconds)
                    continue
            if back_count >= 8:
                diagnostic = self._diagnostic("return_home_failed")
                raise RuntimeError(f"could not return home after 8 controlled backs; saved {diagnostic}")
            if observation.name == "story_ready":
                back = self._locate(screen, "story_back", 0.90)
                if back is None:
                    raise RuntimeError("story page lost its visible back button")
                back_count += 1
                self.runtime.log(
                    f"mode=navigation page=story_ready action=click-game-back "
                    f"retry={back_count}/8"
                )
                self.runtime.click(back.center, "click-story-back")
                last_back_at = self.now()
                back_wait_logged = False
                stable.reset()
                self.sleep(1.0)
                continue
            back_count += 1
            self.runtime.log(f"模式=导航 页面={observation.name} 动作=受控返回 重试={back_count}/8")
            self.runtime.back("受控返回大厅")
            last_back_at = self.now()
            back_wait_logged = False
            stable.reset()
            self.sleep(1.0)
        diagnostic = self._diagnostic("return_home_timeout")
        raise RuntimeError(f"return home exceeded 120-second observation budget; saved {diagnostic}")

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
        else:
            raise ValueError(f"unsupported navigation mode: {mode}")
        self.runtime.log(f"模式={mode} 状态=导航完成")

    def _transition(
        self,
        source: str,
        target: str | tuple[str, ...],
        anchor: str,
        action: str,
        *,
        source_screen: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        source_screen = source_screen if source_screen is not None else self._wait_for_page(source)
        targets = (target,) if isinstance(target, str) else target
        target_label = "/".join(targets)
        for attempt in range(1, 3):
            threshold = 0.80 if anchor == "lobby_story" else 0.82
            match = self._locate(source_screen, anchor, threshold)
            if match is None:
                raise RuntimeError(f"{source} lost required navigation anchor {anchor}")
            self.runtime.log(f"模式=导航 页面={source} 目标={target_label} 动作={action} 尝试={attempt}/2")
            offset = self._CLICK_OFFSETS.get(anchor, (0, 0))
            click_point = (match.center[0] + offset[0], match.center[1] + offset[1])
            self.runtime.click(click_point, action)
            stable = StableObservation(required=2)
            last_source: Optional[np.ndarray] = None
            for _ in range(self.transition_frames):
                screen, observation = self._capture()
                is_stable = stable.update(observation.name)
                if is_stable and self._dismiss_global_popup(screen, observation):
                    stable.reset()
                    self.sleep(1.0)
                    continue
                if is_stable and observation.name in targets:
                    self.runtime.log(
                        f"模式=导航 页面={observation.name} 置信度={observation.confidence:.3f} 状态=转场确认"
                    )
                    return screen
                if observation.name == source:
                    last_source = screen
                self.sleep(self.poll_seconds)
            if last_source is not None:
                source_screen = last_source
                self.runtime.log(f"模式=导航 页面={source} 等待=无转场 重试={attempt}/2")
                continue
            break
        diagnostic = self._diagnostic(f"navigation_{source}_to_{target_label}_failed")
        raise RuntimeError(f"navigation {source} -> {target_label} failed safely; saved {diagnostic}")

    def _wait_for_page(self, expected: str) -> np.ndarray:
        stable = StableObservation(required=2)
        for _ in range(self.transition_frames):
            screen, observation = self._capture()
            is_stable = stable.update(observation.name)
            if is_stable and self._dismiss_global_popup(screen, observation):
                stable.reset()
                self.sleep(1.0)
                continue
            if is_stable and observation.name == expected:
                return screen
            self.sleep(self.poll_seconds)
        diagnostic = self._diagnostic(f"expected_{expected}")
        raise RuntimeError(f"expected {expected} before navigation; saved {diagnostic}")

    def _diagnostic(self, label: str):
        if self.runtime.diagnostic_dir is None:
            return "not-configured"
        return self.runtime.save_diagnostic(label)
