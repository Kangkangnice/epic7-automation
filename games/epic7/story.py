from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    BattleOutcome,
    BattleSupervisor,
    valid_game_frame,
)
from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.core.supervisor import StableObservation, meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.unknown_screen import (
    UnrecognizedScreen,
    UnknownScreenWake,
    UnknownWakeResult,
)


_WATCH_STORY_REFERENCE_SIZE = (1982, 1132)
_WATCH_STORY_REGION = (1450, 930, 470, 202)
_FRIENDSHIP_POINTS_TITLE_REGION = (600, 150, 800, 180)
_FRIENDSHIP_POINTS_CLOSE_REGION = (750, 840, 450, 190)
_STORY_SKIP_REGION = (1700, 0, 240, 200)
_STORY_SKIP_CONFIRM_REGION = (850, 600, 600, 300)
_BATTLE_GUIDE_TITLE_REGION = (780, 250, 420, 180)
_BATTLE_GUIDE_DONT_SHOW_REGION = (1080, 760, 420, 190)


def find_friendship_points_popup_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Optional[Match]:
    """Return the close anchor only when both friendship-popup anchors exist."""
    lower = np.array([0, 0, 120])
    upper = np.array([179, 110, 255])

    def locate(template: np.ndarray, region: tuple[int, int, int, int]):
        scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
        ref_x, ref_y, ref_width, ref_height = region
        x, y, width, height = (
            round(ref_x * scale_x),
            round(ref_y * scale_y),
            round(ref_width * scale_x),
            round(ref_height * scale_y),
        )
        search_hsv = cv2.cvtColor(
            screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
        )
        template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
        match = find_template(
            cv2.inRange(search_hsv, lower, upper),
            cv2.inRange(template_hsv, lower, upper),
            0.85,
            reference_size=(ref_width, ref_height),
        )
        if match is None:
            return None
        return Match((x + match.center[0], y + match.center[1]), match.score)

    title = locate(title_template, _FRIENDSHIP_POINTS_TITLE_REGION)
    close = locate(close_template, _FRIENDSHIP_POINTS_CLOSE_REGION)
    if title is None or close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_battle_guide_dont_show(
    screen: np.ndarray,
    title_template: np.ndarray,
    dont_show_template: np.ndarray,
) -> Optional[Match]:
    """Return Don't Show only when both battle-guide anchors exist."""
    lower = np.array([0, 0, 150])
    upper = np.array([179, 100, 255])

    def locate(template: np.ndarray, region: tuple[int, int, int, int]):
        scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
        ref_x, ref_y, ref_width, ref_height = region
        x, y, width, height = (
            round(ref_x * scale_x),
            round(ref_y * scale_y),
            round(ref_width * scale_x),
            round(ref_height * scale_y),
        )
        search_hsv = cv2.cvtColor(
            screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
        )
        template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
        match = find_template(
            cv2.inRange(search_hsv, lower, upper),
            cv2.inRange(template_hsv, lower, upper),
            0.85,
            reference_size=(ref_width, ref_height),
        )
        if match is None:
            return None
        return Match((x + match.center[0], y + match.center[1]), match.score)

    title = locate(title_template, _BATTLE_GUIDE_TITLE_REGION)
    dont_show = locate(dont_show_template, _BATTLE_GUIDE_DONT_SHOW_REGION)
    if title is None or dont_show is None:
        return None
    return Match(dont_show.center, min(title.score, dont_show.score))


def find_watch_story_button(
    screen: np.ndarray, template: np.ndarray
) -> Optional[Match]:
    """Find the white watch-story glyph without depending on stage artwork."""
    scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
    x, y, width, height = _WATCH_STORY_REGION
    x, y, width, height = (
        round(x * scale_x),
        round(y * scale_y),
        round(width * scale_x),
        round(height * scale_y),
    )
    search_hsv = cv2.cvtColor(
        screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
    )
    template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
    lower = np.array([0, 0, 150])
    upper = np.array([179, 90, 255])
    match = find_template(
        cv2.inRange(search_hsv, lower, upper),
        cv2.inRange(template_hsv, lower, upper),
        0.72,
        reference_size=(_WATCH_STORY_REGION[2], _WATCH_STORY_REGION[3]),
    )
    if match is None:
        return None
    return Match((x + match.center[0], y + match.center[1]), match.score)


def find_prepare_battle_button(
    screen: np.ndarray,
    primary_template: np.ndarray,
    updated_template: np.ndarray,
) -> Optional[Match]:
    """Find the stable white button glyph without depending on stage artwork."""
    scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
    x, y, width, height = _WATCH_STORY_REGION
    x, y, width, height = (
        round(x * scale_x),
        round(y * scale_y),
        round(width * scale_x),
        round(height * scale_y),
    )
    search_hsv = cv2.cvtColor(
        screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
    )
    lower = np.array([0, 0, 150])
    upper = np.array([179, 90, 255])
    search_mask = cv2.inRange(search_hsv, lower, upper)
    matches = []
    for template in (primary_template, updated_template):
        template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
        match = find_template(
            search_mask,
            cv2.inRange(template_hsv, lower, upper),
            0.90,
            reference_size=(_WATCH_STORY_REGION[2], _WATCH_STORY_REGION[3]),
        )
        if match is not None:
            matches.append(match)
    if not matches:
        return None
    best = max(matches, key=lambda candidate: candidate.score)
    return Match((x + best.center[0], y + best.center[1]), best.score)


def find_story_skip_button(
    screen: np.ndarray, template: np.ndarray
) -> Optional[Match]:
    """Find the bright skip glyph without depending on story artwork."""
    scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
    ref_x, ref_y, ref_width, ref_height = _STORY_SKIP_REGION
    x, y, width, height = (
        round(ref_x * scale_x),
        round(ref_y * scale_y),
        round(ref_width * scale_x),
        round(ref_height * scale_y),
    )
    search_hsv = cv2.cvtColor(
        screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
    )
    template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
    lower = np.array([0, 0, 120])
    upper = np.array([179, 70, 255])
    match = find_template(
        cv2.inRange(search_hsv, lower, upper),
        cv2.inRange(template_hsv, lower, upper),
        0.65,
        reference_size=(ref_width, ref_height),
    )
    if match is None:
        return None
    return Match((x + match.center[0], y + match.center[1]), match.score)


def find_story_skip_confirm(
    screen: np.ndarray, template: np.ndarray
) -> Optional[Match]:
    """Find the explicit story-skip confirmation button."""
    return find_template(
        screen,
        template,
        0.80,
        region=_STORY_SKIP_CONFIRM_REGION,
        reference_size=_WATCH_STORY_REFERENCE_SIZE,
    )


class StoryState(Enum):
    STAGE = "stage"
    TEAM = "team"
    WAIT_SKIP_CONFIRM = "wait_skip_confirm"
    WAIT_BATTLE = "wait_battle"
    ACTIVE = "active"
    WAIT_RESULTS = "wait_results"
    WAIT_COMPLETE = "wait_complete"
    WAIT_NEXT_STAGE = "wait_next_stage"


@dataclass(frozen=True)
class StoryAction:
    name: str
    point: tuple[int, int]


@dataclass(frozen=True)
class StoryTemplates:
    friendship_points_title: np.ndarray
    friendship_points_close: np.ndarray
    battle_guide_title: np.ndarray
    battle_guide_dont_show: np.ndarray
    watch_story: np.ndarray
    prepare_battle: np.ndarray
    prepare_battle_updated: np.ndarray
    select_team: np.ndarray
    start_mission: np.ndarray
    skip: np.ndarray
    skip_confirm: np.ndarray
    friend_request_title: np.ndarray
    friend_request_cancel: np.ndarray
    auto_off: np.ndarray
    auto_on: np.ndarray
    reward: np.ndarray
    clear: np.ndarray
    results_confirm: np.ndarray
    complete: np.ndarray
    bonus_reward: np.ndarray
    next_stage: np.ndarray
    threshold: float = 0.80
    stamina_popup: Optional[np.ndarray] = None
    stamina_material: Optional[np.ndarray] = None
    stamina_confirm: Optional[np.ndarray] = None


def _load_optional(template_dir: Path, name: str) -> Optional[np.ndarray]:
    path = template_dir / f"{name}.png"
    return load_template(str(path)) if path.exists() else None


def build_story_templates(template_dir: Path) -> StoryTemplates:
    global_templates = template_dir.parent / "global"
    return StoryTemplates(
        friendship_points_title=load_template(
            str(global_templates / "friendship_points_title.png")
        ),
        friendship_points_close=load_template(
            str(global_templates / "friendship_points_close.png")
        ),
        battle_guide_title=load_template(str(template_dir / "battle_guide_title.png")),
        battle_guide_dont_show=load_template(
            str(template_dir / "battle_guide_dont_show.png")
        ),
        watch_story=load_template(str(template_dir / "watch_story.png")),
        prepare_battle=load_template(str(template_dir / "prepare_battle.png")),
        prepare_battle_updated=load_template(
            str(template_dir / "prepare_battle_updated.png")
        ),
        select_team=load_template(str(template_dir / "select_team.png")),
        start_mission=load_template(str(template_dir / "start_mission.png")),
        skip=load_template(str(template_dir / "skip.png")),
        skip_confirm=load_template(str(template_dir / "skip_confirm.png")),
        friend_request_title=load_template(
            str(template_dir / "friend_request_title.png")
        ),
        friend_request_cancel=load_template(
            str(template_dir / "friend_request_cancel.png")
        ),
        auto_off=load_template(str(template_dir / "auto_off.png")),
        auto_on=load_template(str(template_dir / "auto_on.png")),
        reward=load_template(str(template_dir / "reward.png")),
        clear=load_template(str(template_dir / "clear.png")),
        results_confirm=load_template(str(template_dir / "results_confirm.png")),
        complete=load_template(str(template_dir / "complete.png")),
        bonus_reward=load_template(str(template_dir / "bonus_reward.png")),
        next_stage=load_template(str(template_dir / "next_stage.png")),
        stamina_popup=_load_optional(template_dir, "stamina_popup"),
        stamina_material=_load_optional(template_dir, "stamina_material"),
        stamina_confirm=_load_optional(template_dir, "stamina_confirm"),
    )


class StoryStateMachine:
    """Story workflow in the game window's local coordinate space."""

    _THRESHOLDS = {
        "skip": 0.75,
        "friend_request_title": 0.82,
        "friend_request_cancel": 0.82,
    }
    _REFERENCE_SIZE = (1982, 1132)
    _REGIONS = {
        "watch_story": (1450, 930, 470, 202),
        "select_team": (1400, 930, 520, 202),
        "start_mission": (1400, 930, 520, 202),
        "skip": (1700, 0, 240, 200),
        "skip_confirm": (850, 600, 600, 300),
        "friend_request_title": (650, 240, 700, 160),
        "friend_request_cancel": (550, 720, 500, 230),
        "auto_off": (1550, 0, 300, 200),
        "auto_on": (1550, 0, 300, 200),
        "reward": (700, 400, 650, 400),
        "clear": (500, 150, 900, 700),
        "results_confirm": (1500, 930, 420, 202),
        "complete": (650, 150, 700, 500),
        "bonus_reward": (350, 150, 1200, 850),
        "next_stage": (1450, 930, 470, 202),
        "stamina_popup": (400, 200, 1200, 700),
        "stamina_material": (400, 200, 700, 700),
        "stamina_confirm": (850, 750, 650, 250),
    }
    _BONUS_REWARD_CLOSE_OFFSET = (0, 312)
    _AUTO_CLICK_POINT = (1690, 96)

    def __init__(
        self, templates: StoryTemplates, initial_state: StoryState = StoryState.STAGE
    ) -> None:
        self.templates = templates
        self.state = initial_state
        self.auto_enabled = False
        self.auto_click_attempted = False
        self.battle_controls = BattleControls.TRANSITION
        self.completed_cycles = 0
        self.stamina_replenished = 0
        self.stamina_replenish_max: int | None = None
        self._stamina_material_clicked = False

    def _locate(self, screen: np.ndarray, name: str):
        """Match only the expected local UI region; never the desktop."""
        if name == "watch_story":
            return find_watch_story_button(screen, self.templates.watch_story)
        if name == "prepare_battle":
            return find_prepare_battle_button(
                screen,
                self.templates.prepare_battle,
                self.templates.prepare_battle_updated,
            )
        if name == "skip":
            return find_story_skip_button(screen, self.templates.skip)
        if name == "skip_confirm":
            return find_story_skip_confirm(screen, self.templates.skip_confirm)
        if name in ("auto_off", "auto_on"):
            white = (np.array([180, 180, 180]), np.array([255, 255, 255]))
            x, y, width, height = self._scaled_region(screen, name)
            search_mask = cv2.inRange(screen[y : y + height, x : x + width], *white)
            template_mask = cv2.inRange(getattr(self.templates, name), *white)
            match = find_template(
                search_mask,
                template_mask,
                0.80,
                reference_size=(self._REGIONS[name][2], self._REGIONS[name][3]),
            )
            if match is None:
                return None
            return Match((x + match.center[0], y + match.center[1]), match.score)
        match = find_template(
            screen,
            getattr(self.templates, name),
            self._THRESHOLDS.get(name, self.templates.threshold),
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )
        return match

    def _scaled_region(self, screen: np.ndarray, name: str) -> tuple[int, int, int, int]:
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, width, height = self._REGIONS[name]
        return (
            round(x * scale_x), round(y * scale_y),
            round(width * scale_x), round(height * scale_y),
        )

    def _scaled_point(
        self, screen: np.ndarray, point: tuple[int, int]
    ) -> tuple[int, int]:
        return (
            round(point[0] * screen.shape[1] / self._REFERENCE_SIZE[0]),
            round(point[1] * screen.shape[0] / self._REFERENCE_SIZE[1]),
        )

    def observe_battle_controls(self, screen: np.ndarray) -> BattleControls:
        return observe_battle_controls(screen)

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        controls = self.observe_battle_controls(screen)
        auto_state = {
            BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
            BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
            BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
        }[controls]
        auto_match = self._locate(screen, "auto_off")
        stamina_popup = (
            self._locate(screen, "stamina_popup")
            if self.templates.stamina_popup is not None
            else None
        )
        battle_guide = find_battle_guide_dont_show(
            screen,
            self.templates.battle_guide_title,
            self.templates.battle_guide_dont_show,
        )
        allowed_action = (
            ("dismiss-battle-guide-warning", battle_guide.center)
            if battle_guide is not None
            else None
        )
        if allowed_action is None:
            for action_name in ("skip_confirm", "skip", "watch_story"):
                match = self._locate(screen, action_name)
                if match is not None:
                    allowed_action = (action_name, match.center)
                    break
        progressing = (
            auto_state is AutoBattleState.AUTO
            and meaningful_change(previous_screen, screen)
        )
        return BattleObservation(
            pre_battle_visible=self._locate(screen, "start_mission") is not None,
            battle_visible=controls is not BattleControls.TRANSITION,
            result_visible=any(
                self._locate(screen, name) is not None
                for name in ("reward", "clear", "results_confirm")
            ),
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_point=(
                auto_match.center
                if auto_match is not None
                else self._scaled_point(screen, self._AUTO_CLICK_POINT)
                if auto_state is AutoBattleState.MANUAL
                else None
            ),
            business_progress=progressing,
            allowed_action=allowed_action,
            pre_battle_business_visible=stamina_popup is not None,
        )

    def _action_point(self, screen: np.ndarray, name: str, match: Match) -> tuple[int, int]:
        if name != "bonus_reward":
            return match.center
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        return match.center[0], match.center[1] + round(self._BONUS_REWARD_CLOSE_OFFSET[1] * scale_y)

    def find_friend_request_cancel(self, screen: np.ndarray) -> Optional[Match]:
        """Return Cancel only when both friend-request popup anchors are present."""
        if self._locate(screen, "friend_request_title") is None:
            return None
        return self._locate(screen, "friend_request_cancel")

    def _handle_stamina(self, screen: np.ndarray) -> Optional[StoryAction]:
        """Detect the insufficient-stamina popup and refill via the left material.

        Returns a StoryAction when something must be clicked, None otherwise.
        Caps refills at stamina_replenish_max; once exhausted it raises
        StaminaExhausted so the run stops cleanly instead of looping.
        """
        if self.templates.stamina_popup is None:
            return None
        popup = self._locate(screen, "stamina_popup")
        if popup is None:
            self._stamina_material_clicked = False
            return None
        if (
            self.stamina_replenish_max is not None
            and self.stamina_replenished >= self.stamina_replenish_max
        ):
            raise StaminaExhausted(
                f"stamina refilled {self.stamina_replenished} times "
                f"(max {self.stamina_replenish_max}); stopping"
            )
        if not self._stamina_material_clicked:
            if self.templates.stamina_material is None:
                raise RuntimeError("stamina popup present but stamina_material template missing")
            mat = self._locate(screen, "stamina_material")
            if mat is None:
                raise RuntimeError(
                    "stamina popup present but the selected leaf offer was not confirmed"
                )
            self._stamina_material_clicked = True
            return StoryAction("stamina_material", mat.center)
        mat = self._locate(screen, "stamina_material")
        if mat is None:
            raise RuntimeError(
                "stamina popup present but the selected leaf offer was not confirmed"
            )
        if self.templates.stamina_confirm is None:
            raise RuntimeError("stamina popup present but stamina_confirm template missing")
        conf = self._locate(screen, "stamina_confirm")
        if conf is None:
            return None
        self._stamina_material_clicked = False
        self.stamina_replenished += 1
        return StoryAction("stamina_confirm", conf.center)

    def next_action(self, screen: np.ndarray) -> Optional[StoryAction]:
        popup_close = find_friendship_points_popup_close(
            screen,
            self.templates.friendship_points_title,
            self.templates.friendship_points_close,
        )
        if popup_close is not None:
            return StoryAction("close_friendship_points_popup", popup_close.center)

        stamina_action = self._handle_stamina(screen)
        if stamina_action is not None:
            return stamina_action

        friend_cancel = self.find_friend_request_cancel(screen)
        if friend_cancel is not None:
            return StoryAction("cancel_friend_request", friend_cancel.center)

        checks = [
            ("reward", StoryState.WAIT_RESULTS),
            ("clear", StoryState.WAIT_RESULTS),
            ("results_confirm", StoryState.WAIT_COMPLETE),
            ("complete", StoryState.WAIT_NEXT_STAGE),
            ("bonus_reward", StoryState.WAIT_NEXT_STAGE),
            ("skip_confirm", StoryState.ACTIVE),
            ("skip", StoryState.WAIT_SKIP_CONFIRM),
            ("watch_story", StoryState.WAIT_SKIP_CONFIRM),
            ("select_team", StoryState.TEAM),
            ("start_mission", StoryState.WAIT_BATTLE),
        ]
        for name, new_state in checks:
            match = self._locate(screen, name)
            if match is not None:
                previous_state = self.state
                self.state = new_state
                if (
                    name == "watch_story"
                    and previous_state
                    in (StoryState.WAIT_COMPLETE, StoryState.WAIT_NEXT_STAGE)
                ):
                    self.completed_cycles += 1
                if name in ("select_team", "start_mission"):
                    self.auto_enabled = False
                if name == "start_mission":
                    self.auto_click_attempted = False
                    self.battle_controls = BattleControls.TRANSITION
                return StoryAction(name, self._action_point(screen, name, match))
        match = self._locate(screen, "prepare_battle")
        if match is not None:
            if self.state in (StoryState.WAIT_COMPLETE, StoryState.WAIT_NEXT_STAGE):
                self.completed_cycles += 1
            if self.state == StoryState.WAIT_NEXT_STAGE:
                self.state = StoryState.STAGE
                return None
            self.state = StoryState.TEAM
            self.auto_enabled = False
            self.auto_click_attempted = False
            self.battle_controls = BattleControls.TRANSITION
            return StoryAction("prepare_battle", match.center)
        if self.state in (StoryState.WAIT_BATTLE, StoryState.ACTIVE):
            self.battle_controls = self.observe_battle_controls(screen)
            if self.battle_controls == BattleControls.AUTO_CONTROLS:
                self.state = StoryState.ACTIVE
                self.auto_enabled = True
                return None
            if self.battle_controls == BattleControls.MANUAL_CONTROLS:
                self.state = StoryState.WAIT_BATTLE
                self.auto_enabled = False
                if self.auto_click_attempted:
                    return None
                self.auto_click_attempted = True
                match = self._locate(screen, "auto_off")
                point = (
                    match.center
                    if match is not None
                    else self._scaled_point(screen, self._AUTO_CLICK_POINT)
                )
                return StoryAction("enable_auto", point)
        if self.state == StoryState.WAIT_NEXT_STAGE:
            match = self._locate(screen, "bonus_reward")
            if match is not None:
                return StoryAction("bonus_reward", self._action_point(screen, "bonus_reward", match))
            match = self._locate(screen, "next_stage")
            if match is not None:
                self.completed_cycles += 1
                self.state = StoryState.STAGE
                return None

        if self.state == StoryState.WAIT_COMPLETE:
            # Recovery: the screen may have already advanced to the map or is
            # showing a bonus popup. Try forward templates instead of dead-
            # ending on the (possibly stale) complete button.
            match = self._locate(screen, "bonus_reward")
            if match is not None:
                return StoryAction("bonus_reward", self._action_point(screen, "bonus_reward", match))
            match = self._locate(screen, "next_stage")
            if match is not None:
                self.completed_cycles += 1
                self.state = StoryState.STAGE
                return None
            match = self._locate(screen, "prepare_battle")
            if match is not None:
                self.state = StoryState.TEAM
                self.auto_enabled = False
                return StoryAction("prepare_battle", match.center)

        raise UnrecognizedScreen(
            f"expected {self.state.value} story screen was not recognized"
        )

    def preview(self, screen: np.ndarray):
        """Observe a frame without committing optimistic state changes."""

        snapshot = (
            self.state,
            self.auto_enabled,
            self.auto_click_attempted,
            self.battle_controls,
            self.completed_cycles,
            self.stamina_replenished,
            self._stamina_material_clicked,
        )
        try:
            action = self.next_action(screen)
            outcome = (self.state, self.completed_cycles)
            return action, outcome
        finally:
            (
                self.state,
                self.auto_enabled,
                self.auto_click_attempted,
                self.battle_controls,
                self.completed_cycles,
                self.stamina_replenished,
                self._stamina_material_clicked,
            ) = snapshot


class StoryRunner:
    """Short-polling, fail-closed runner for current-layout story stages."""

    _ACTION_RETRY_SECONDS = 45

    _TIMEOUT_SECONDS = {
        StoryState.STAGE: 45,
        StoryState.TEAM: 45,
        StoryState.WAIT_SKIP_CONFIRM: 45,
        StoryState.WAIT_BATTLE: 60,
        StoryState.ACTIVE: 120,
        StoryState.WAIT_RESULTS: 45,
        StoryState.WAIT_COMPLETE: 45,
        StoryState.WAIT_NEXT_STAGE: 45,
    }

    def __init__(
        self,
        machine: StoryStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery: Callable[[], None] | None = None,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        self.machine = machine
        self.runtime = runtime
        self.sleep = sleep
        self.now = runtime.now
        self.poll_seconds = poll_seconds
        self.recovery_gate = recovery_gate or RecoveryGate(recovery)
        self.recovery = self.recovery_gate.recover if recovery is not None else None
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(mode="story"),
            now=self.now,
            sleep=sleep,
        )
        self.unknown_screen_wake = UnknownScreenWake(
            runtime,
            recovery_gate=self.recovery_gate,
        )
        self.resource_exhausted = False

    def _run_committed_battle(self, *, cycle: int) -> None:
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = StoryState.WAIT_BATTLE
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"unexpected story battle outcome: {outcome.value}")
        self.machine.state = StoryState.WAIT_RESULTS

    def run(self, max_cycles: int | None = None) -> int:
        if self.runtime.dry_run:
            screen = self.runtime.capture()
            try:
                action = self.machine.next_action(screen)
            except RuntimeError as error:
                diagnostic = self.runtime.save_diagnostic(
                    f"dry_run_{self.machine.state.value}", screen
                )
                raise RuntimeError(
                    f"dry-run did not recognize {self.machine.state.value}; saved {diagnostic}"
                ) from error
            if action is not None:
                self.runtime.log(
                    f"模式=主线 页面={self.machine.state.value} 动作={action.name} 状态=诊断"
                )
                self.runtime.click(action.point, action.name)
            return self.machine.completed_cycles

        state_started = self.now()
        absolute_started = state_started
        stable = StableObservation(required=2)
        recovered = False
        last_action_name: Optional[str] = None
        last_action_clicked_at: Optional[float] = None
        retry_wait_logged = False
        action_attempts = 0
        while max_cycles is None or self.machine.completed_cycles < max_cycles:
            state_before = self.machine.state
            cycles_before = self.machine.completed_cycles
            screen = self.runtime.capture()
            if self.runtime.diagnostic_dir is not None:
                self.runtime.save_current_frame(screen)
            try:
                preview_action, outcome = self.machine.preview(screen)
            except StaminaExhausted as error:
                self.resource_exhausted = True
                self.runtime.log(f"模式=主线 停止=生命之叶耗尽 详情={error}")
                return self.machine.completed_cycles
            except RuntimeError as error:
                if isinstance(error, UnrecognizedScreen):
                    wake_result = self.unknown_screen_wake.handle(
                        screen,
                        context=f"story:{self.machine.state.value}",
                    )
                    if wake_result in {
                        UnknownWakeResult.WAITING,
                        UnknownWakeResult.CLICKED,
                    }:
                        if wake_result is UnknownWakeResult.CLICKED:
                            state_started = self.now()
                        self.sleep(self.poll_seconds)
                        continue
                elapsed = self.now() - state_started
                if elapsed >= self._TIMEOUT_SECONDS[self.machine.state]:
                    if self.recovery is not None and not recovered:
                        recovered = True
                        self.runtime.log(
                            f"模式=主线 页面={self.machine.state.value} 恢复=回大厅重新导航"
                        )
                        self.recovery()
                        self.machine.state = StoryState.STAGE
                        self.machine.auto_enabled = False
                        state_started = self.now()
                        absolute_started = state_started
                        last_action_name = None
                        last_action_clicked_at = None
                        retry_wait_logged = False
                        action_attempts = 0
                        stable.reset()
                        continue
                    diagnostic = self.runtime.save_diagnostic(
                        f"timeout_{self.machine.state.value}", screen
                    )
                    self.runtime.log(
                        f"timeout state={self.machine.state.value} elapsed={elapsed:.1f}s diagnostic={diagnostic}"
                    )
                    raise RuntimeError(
                        f"no progress: {error}; stopped safely, saved {diagnostic}"
                    ) from error
                self.sleep(self.poll_seconds)
                continue

            self.unknown_screen_wake.reset()
            signature = (
                preview_action.name if preview_action is not None
                else f"settled:{outcome[0].value}:{outcome[1]}"
            )
            if not stable.update(signature):
                self.sleep(self.poll_seconds)
                continue
            action = self.machine.next_action(screen)
            stable.reset()

            if self.machine.completed_cycles > cycles_before:
                recovered = False
                self.runtime.log(f"complete-story cycles={self.machine.completed_cycles}")
                state_started = self.now()
                if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
                    return self.machine.completed_cycles

            if action is not None:
                if action.name == last_action_name:
                    since_click = (
                        self.now() - last_action_clicked_at
                        if last_action_clicked_at is not None
                        else self._ACTION_RETRY_SECONDS
                    )
                    if since_click < self._ACTION_RETRY_SECONDS:
                        if not retry_wait_logged:
                            remaining = self._ACTION_RETRY_SECONDS - since_click
                            self.runtime.log(
                                f"模式=主线 轮次={self.machine.completed_cycles + 1}/{max_cycles or '?'} "
                                f"动作={action.name} 等待=点击后确认转场 剩余={remaining:.1f}秒"
                            )
                            retry_wait_logged = True
                        self.sleep(self.poll_seconds)
                        continue
                    action_attempts += 1
                else:
                    last_action_name = action.name
                    action_attempts = 1
                if action_attempts > 2:
                    if self.recovery is not None and not recovered:
                        recovered = True
                        self.runtime.log(
                            f"模式=主线 动作={action.name} 恢复=两次点击未转场，回大厅重新导航"
                        )
                        self.recovery()
                        self.machine.state = StoryState.STAGE
                        self.machine.auto_enabled = False
                        state_started = self.now()
                        absolute_started = state_started
                        last_action_name = None
                        last_action_clicked_at = None
                        retry_wait_logged = False
                        action_attempts = 0
                        stable.reset()
                        continue
                    diagnostic = self.runtime.save_diagnostic(
                        f"retry_exhausted_{action.name}", screen
                    )
                    raise RuntimeError(
                        f"action {action.name} failed after 2 attempts; saved {diagnostic}"
                    )
                self.runtime.log(
                    f"模式=主线 轮次={self.machine.completed_cycles + 1}/{max_cycles or '?'} "
                    f"页面={state_before.value} 动作={action.name} 尝试={action_attempts}/2"
                )
                self.runtime.click(action.point, action.name)
                last_action_clicked_at = self.now()
                state_started = last_action_clicked_at
                absolute_started = last_action_clicked_at
                retry_wait_logged = False
                if action.name == "start_mission":
                    self._run_committed_battle(
                        cycle=self.machine.completed_cycles + 1,
                    )
                    state_started = self.now()
                    absolute_started = state_started
                    last_action_name = None
                    last_action_clicked_at = None
                    action_attempts = 0
                    stable.reset()
                    continue
            else:
                last_action_name = None
                last_action_clicked_at = None
                retry_wait_logged = False
                action_attempts = 0
            if (
                action is None
                and self.now() - state_started >= self._TIMEOUT_SECONDS[self.machine.state]
            ):
                diagnostic = self.runtime.save_diagnostic(
                    f"timeout_{self.machine.state.value}", screen
                )
                self.runtime.log(
                    f"timeout state={self.machine.state.value} no_progress "
                    f"diagnostic={diagnostic}"
                )
                raise RuntimeError(
                    f"no progress while waiting in {self.machine.state.value}; "
                    f"stopped safely, saved {diagnostic}"
                )

            if self.machine.state != state_before:
                state_started = self.now()
                absolute_started = state_started
            if self.now() - absolute_started >= 180:
                diagnostic = self.runtime.save_diagnostic(
                    f"absolute_{self.machine.state.value}", screen
                )
                raise RuntimeError(
                    f"absolute timeout in {self.machine.state.value}; stopped safely, saved {diagnostic}"
                )
            self.sleep(self.poll_seconds)

        return self.machine.completed_cycles

