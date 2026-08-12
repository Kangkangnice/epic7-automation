"""Fail-closed automation for Epic Seven expeditions."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import monotonic, sleep as default_sleep
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
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation, meaningful_change


class ExpeditionState(Enum):
    HOME = "home"
    POSTERS = "posters"
    DIFFICULTY = "difficulty"
    DIFFICULTY_CONFIRM = "difficulty_confirm"
    READY = "ready"
    TEAM = "team"
    BATTLE = "battle"
    RESULT = "result"
    OUTCOME = "outcome"
    RECRUIT_CONFIRM = "recruit_confirm"
    RECRUIT_RETURN = "recruit_return"
    RETURNING = "returning"


class PostersExhausted(RuntimeError):
    """No card-level wanted-poster departure action remains."""


@dataclass(frozen=True)
class ExpeditionAction:
    name: str
    point: tuple[int, int]


@dataclass(frozen=True)
class ExpeditionTemplates:
    home: np.ndarray
    poster_embark: np.ndarray
    empty_posters: Optional[np.ndarray]
    difficulty_title: np.ndarray
    difficulty_3_selected: np.ndarray
    difficulty_confirm: np.ndarray
    prepare_battle: np.ndarray
    battle_start: np.ndarray
    auto_off: np.ndarray
    battle_anchor: np.ndarray
    result_confirm: np.ndarray
    victory_title: np.ndarray
    victory_close: np.ndarray
    defeated_confirm: Optional[np.ndarray]
    public_recruit: np.ndarray
    public_title: np.ndarray
    public_confirm: np.ndarray
    public_recruited: np.ndarray
    campfire_idle: np.ndarray
    expedition_list: np.ndarray
    back: np.ndarray


def build_expedition_templates(template_dir: Path) -> ExpeditionTemplates:
    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    def load_optional(name: str) -> Optional[np.ndarray]:
        path = template_dir / f"{name}.png"
        return load_template(str(path)) if path.exists() else None

    return ExpeditionTemplates(
        home=load("home"),
        poster_embark=load("poster_embark"),
        empty_posters=load_optional("empty_posters"),
        difficulty_title=load("difficulty_title"),
        difficulty_3_selected=load("difficulty_3_selected"),
        difficulty_confirm=load("difficulty_confirm"),
        prepare_battle=load("prepare_battle"),
        battle_start=load("battle_start"),
        auto_off=load_template(str(template_dir.parent / "story" / "auto_off.png")),
        battle_anchor=load("battle_anchor"),
        result_confirm=load("result_confirm"),
        victory_title=load("victory_title"),
        victory_close=load("victory_close"),
        defeated_confirm=load_optional("defeated_confirm"),
        public_recruit=load("public_recruit"),
        public_title=load("public_title"),
        public_confirm=load("public_confirm"),
        public_recruited=load("public_recruited"),
        campfire_idle=load("campfire_idle"),
        expedition_list=load("expedition_list"),
        back=load("back"),
    )


class ExpeditionStateMachine:
    _REFERENCE_SIZE = (1982, 1132)
    _THRESHOLD = 0.88
    _REGIONS = {
        "home": (1350, 850, 632, 282),
        # Deliberately excludes the bottom-right global "Embark" button.
        "poster_embark": (250, 280, 1400, 570),
        "empty_posters": (550, 250, 900, 550),
        "difficulty_title": (650, 120, 700, 300),
        "difficulty_3_selected": (900, 580, 450, 300),
        "difficulty_confirm": (800, 780, 500, 300),
        "prepare_battle": (1450, 850, 532, 282),
        "battle_start": (1300, 900, 682, 232),
        "auto_off": (1550, 0, 300, 200),
        "battle_anchor": (1400, 0, 582, 320),
        "result_confirm": (1450, 850, 532, 282),
        "victory_title": (750, 250, 500, 250),
        "victory_close": (700, 650, 600, 300),
        "defeated_confirm": (650, 700, 700, 432),
        "public_recruit": (800, 900, 500, 232),
        "public_title": (700, 250, 600, 300),
        "public_confirm": (650, 650, 700, 482),
        "public_recruited": (750, 850, 650, 282),
        "campfire_idle": (650, 80, 700, 420),
        "expedition_list": (1100, 100, 500, 260),
        "back": (0, 0, 220, 230),
    }

    def __init__(
        self,
        templates: ExpeditionTemplates | Path,
        *,
        initial_state: ExpeditionState = ExpeditionState.HOME,
    ) -> None:
        self.templates = (
            build_expedition_templates(templates)
            if isinstance(templates, Path)
            else templates
        )
        self.state = initial_state
        self.completed_cycles = 0
        self.auto_click_attempted = False

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        template = getattr(self.templates, name)
        if template is None:
            return None
        if name == "auto_off":
            x, y, width, height = self._scaled_region(screen, name)
            white = (np.array([180, 180, 180]), np.array([255, 255, 255]))
            search_mask = cv2.inRange(screen[y : y + height, x : x + width], *white)
            template_mask = cv2.inRange(template, *white)
            match = find_template(
                search_mask,
                template_mask,
                0.80,
                reference_size=(width, height),
            )
            if match is None:
                return None
            return Match((x + match.center[0], y + match.center[1]), match.score)
        if name == "public_recruit":
            return self._locate_bright_foreground(screen, template, name)
        return find_template(
            screen,
            template,
            self._THRESHOLD,
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def _scaled_region(self, screen: np.ndarray, name: str) -> tuple[int, int, int, int]:
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, width, height = self._REGIONS[name]
        return (
            round(x * scale_x),
            round(y * scale_y),
            round(width * scale_x),
            round(height * scale_y),
        )

    def _locate_bright_foreground(
        self, screen: np.ndarray, template: np.ndarray, name: str
    ) -> Optional[Match]:
        lower = np.array([0, 0, 145])
        upper = np.array([179, 105, 255])
        screen_mask = cv2.inRange(cv2.cvtColor(screen, cv2.COLOR_RGB2HSV), lower, upper)
        template_mask = cv2.inRange(
            cv2.cvtColor(template, cv2.COLOR_RGB2HSV), lower, upper
        )
        return find_template(
            screen_mask,
            template_mask,
            0.85,
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def _required(self, screen: np.ndarray, name: str) -> Match:
        match = self._locate(screen, name)
        if match is None:
            raise RuntimeError(f"expected expedition {name} anchor was not recognized")
        return match

    def _defeated_action(self, screen: np.ndarray) -> Optional[ExpeditionAction]:
        match = self._locate(screen, "defeated_confirm")
        if match is None:
            return None
        self.state = ExpeditionState.RETURNING
        return ExpeditionAction("confirm-defeated", match.center)

    def is_in_state(self, screen: np.ndarray, state: ExpeditionState) -> bool:
        if state == ExpeditionState.HOME:
            return self._locate(screen, "home") is not None
        if state == ExpeditionState.POSTERS:
            return any(
                self._locate(screen, name) is not None
                for name in ("poster_embark", "empty_posters")
            )
        if state == ExpeditionState.DIFFICULTY:
            return self._locate(screen, "difficulty_title") is not None
        if state == ExpeditionState.DIFFICULTY_CONFIRM:
            return (
                self._locate(screen, "difficulty_3_selected") is not None
                and self._locate(screen, "difficulty_confirm") is not None
            )
        if state == ExpeditionState.READY:
            return self._locate(screen, "prepare_battle") is not None
        if state == ExpeditionState.TEAM:
            return self._locate(screen, "battle_start") is not None
        if state == ExpeditionState.BATTLE:
            return any(
                self._locate(screen, name) is not None
                for name in ("battle_anchor", "result_confirm")
            )
        if state == ExpeditionState.RESULT:
            return self._locate(screen, "result_confirm") is not None
        if state == ExpeditionState.OUTCOME:
            return any(
                self._locate(screen, name) is not None
                for name in (
                    "defeated_confirm",
                    "victory_title",
                    "public_recruit",
                    "campfire_idle",
                )
            )
        if state == ExpeditionState.RECRUIT_CONFIRM:
            return (
                self._locate(screen, "defeated_confirm") is not None
                or (
                    self._locate(screen, "public_title") is not None
                    and self._locate(screen, "public_confirm") is not None
                )
            )
        if state == ExpeditionState.RECRUIT_RETURN:
            return (
                self._locate(screen, "defeated_confirm") is not None
                or self._locate(screen, "campfire_idle") is not None
                or (
                    self._locate(screen, "public_recruited") is not None
                    and self._locate(screen, "back") is not None
                )
            )
        if state == ExpeditionState.RETURNING:
            return (
                self._locate(screen, "home") is not None
                or (
                    self._locate(screen, "expedition_list") is not None
                    and self._locate(screen, "back") is not None
                )
            )
        return False

    def is_campfire_idle(self, screen: np.ndarray) -> bool:
        return self._locate(screen, "campfire_idle") is not None

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        auto = self._locate(screen, "auto_off")
        battle = self._locate(screen, "battle_anchor")
        result = self._locate(screen, "result_confirm")
        progressing = valid_game_frame(screen) and meaningful_change(
            previous_screen,
            screen,
        )
        return BattleObservation(
            pre_battle_visible=self._locate(screen, "battle_start") is not None,
            battle_visible=battle is not None or auto is not None or progressing,
            result_visible=result is not None,
            frame_valid=valid_game_frame(screen),
            auto_state=(
                AutoBattleState.MANUAL
                if auto is not None
                else AutoBattleState.AUTO
                if progressing
                else AutoBattleState.UNKNOWN
            ),
            auto_point=None if auto is None else auto.center,
            business_progress=progressing,
        )

    def next_action(self, screen: np.ndarray) -> Optional[ExpeditionAction]:
        if self.state in {
            ExpeditionState.OUTCOME,
            ExpeditionState.RECRUIT_CONFIRM,
            ExpeditionState.RECRUIT_RETURN,
        }:
            defeated = self._defeated_action(screen)
            if defeated is not None:
                return defeated

        if self.state == ExpeditionState.HOME:
            match = self._required(screen, "home")
            self.state = ExpeditionState.POSTERS
            return ExpeditionAction("open-my-posters", match.center)

        if self.state == ExpeditionState.POSTERS:
            if self._locate(screen, "empty_posters") is not None:
                raise PostersExhausted("no wanted poster is available")
            match = self._locate(screen, "poster_embark")
            if match is None:
                raise RuntimeError("no expedition embark button was found inside the poster card area")
            self.state = ExpeditionState.DIFFICULTY
            return ExpeditionAction("select-first-poster", match.center)

        if self.state == ExpeditionState.DIFFICULTY:
            title = self._required(screen, "difficulty_title")
            self.state = ExpeditionState.DIFFICULTY_CONFIRM
            return ExpeditionAction(
                "select-difficulty-3",
                (title.center[0] + 155, title.center[1] + 495),
            )

        if self.state == ExpeditionState.DIFFICULTY_CONFIRM:
            self._required(screen, "difficulty_3_selected")
            confirm = self._required(screen, "difficulty_confirm")
            self.state = ExpeditionState.READY
            return ExpeditionAction("confirm-difficulty-3", confirm.center)

        if self.state == ExpeditionState.READY:
            match = self._required(screen, "prepare_battle")
            self.state = ExpeditionState.TEAM
            return ExpeditionAction("prepare-battle", match.center)

        if self.state == ExpeditionState.TEAM:
            match = self._required(screen, "battle_start")
            self.state = ExpeditionState.BATTLE
            return ExpeditionAction("battle-start", match.center)

        if self.state in {ExpeditionState.BATTLE, ExpeditionState.RESULT}:
            result = self._locate(screen, "result_confirm")
            if result is not None:
                self.state = ExpeditionState.OUTCOME
                return ExpeditionAction("confirm-result", result.center)
            auto_off = self._locate(screen, "auto_off")
            if auto_off is not None:
                if self.auto_click_attempted:
                    return None
                self.auto_click_attempted = True
                return ExpeditionAction("enable-auto-battle", auto_off.center)
            if self.state == ExpeditionState.BATTLE and self._locate(screen, "battle_anchor"):
                return None
            raise RuntimeError("expedition battle/result screen was not recognized")

        if self.state == ExpeditionState.OUTCOME:
            victory_title = self._locate(screen, "victory_title")
            victory_close = self._locate(screen, "victory_close")
            if victory_title is not None and victory_close is not None:
                self.state = ExpeditionState.RETURNING
                return ExpeditionAction(
                    "close-expedition-victory", victory_close.center
                )
            if self._locate(screen, "campfire_idle") is not None:
                return ExpeditionAction("wake-campfire-ui", (1000, 600))
            recruit = self._required(screen, "public_recruit")
            self.state = ExpeditionState.RECRUIT_CONFIRM
            return ExpeditionAction("public-recruit", recruit.center)

        if self.state == ExpeditionState.RECRUIT_CONFIRM:
            self._required(screen, "public_title")
            confirm = self._required(screen, "public_confirm")
            self.state = ExpeditionState.RECRUIT_RETURN
            return ExpeditionAction("confirm-public-recruit", confirm.center)

        if self.state == ExpeditionState.RECRUIT_RETURN:
            if self._locate(screen, "campfire_idle") is not None:
                return ExpeditionAction("wake-campfire-ui", (1000, 600))
            self._required(screen, "public_recruited")
            back = self._required(screen, "back")
            self.state = ExpeditionState.RETURNING
            return ExpeditionAction("return-from-expedition", back.center)

        if self.state == ExpeditionState.RETURNING:
            if self._locate(screen, "home") is not None:
                self.completed_cycles += 1
                self.state = ExpeditionState.HOME
                return None
            self._required(screen, "expedition_list")
            back = self._required(screen, "back")
            return ExpeditionAction("return-to-expedition-home", back.center)

        raise RuntimeError(f"unsupported expedition state {self.state.value}")

    def preview(self, screen: np.ndarray):
        snapshot = self.state, self.completed_cycles, self.auto_click_attempted
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            self.state, self.completed_cycles, self.auto_click_attempted = snapshot


class ExpeditionRunner:
    _STATE_TIMEOUT_SECONDS = 45
    _TRANSITION_NO_PROGRESS_SECONDS = 45
    _TRANSITION_ABSOLUTE_SECONDS = 180

    def __init__(
        self,
        machine: ExpeditionStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        now: Callable[[], float] = monotonic,
        recovery: Callable[[], None] | None = None,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        self.machine = machine
        self.runtime = runtime
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.now = now
        self.recovery_gate = recovery_gate or RecoveryGate(recovery)
        self.recovery = self.recovery_gate.recover if recovery is not None else None
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(
                mode="expedition",
                absolute_seconds=20 * 60,
                no_business_progress_seconds=20 * 60,
            ),
            now=now,
            sleep=sleep,
        )
        self.resource_exhausted = False

    def _run_committed_battle(self, *, cycle: int) -> None:
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(
                f"unexpected expedition battle outcome: {outcome.value}"
            )
        self.machine.state = ExpeditionState.RESULT

    def run(self, max_cycles: int | None = None) -> int:
        if self.runtime.dry_run:
            screen = self.runtime.capture()
            action = self.machine.next_action(screen)
            if action is not None:
                self.runtime.log(
                    f"模式=远征 页面={self.machine.state.value} 动作={action.name} 状态=诊断"
                )
                self.runtime.click(action.point, action.name)
            return self.machine.completed_cycles

        stable = StableObservation(required=2)
        state_started = self.now()
        recovered = False
        failed_action: Optional[str] = None
        action_attempts = 0

        while max_cycles is None or self.machine.completed_cycles < max_cycles:
            screen = self.runtime.capture()
            if self.runtime.diagnostic_dir is not None:
                self.runtime.save_current_frame(screen)
            state_before = self.machine.state
            cycles_before = self.machine.completed_cycles

            try:
                preview_action, outcome = self.machine.preview(screen)
            except PostersExhausted as error:
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式=远征 停止=通缉传单耗尽 已完成={self.machine.completed_cycles} 详情={error}"
                )
                return self.machine.completed_cycles
            except RuntimeError as error:
                if self.now() - state_started < self._STATE_TIMEOUT_SECONDS:
                    self.sleep(self.poll_seconds)
                    continue
                if self._can_recover(state_before) and self.recovery is not None and not recovered:
                    recovered = True
                    self.runtime.log(
                        f"模式=远征 页面={state_before.value} 恢复=回大厅重新导航"
                    )
                    self.recovery()
                    self.machine.state = ExpeditionState.HOME
                    state_started = self.now()
                    stable.reset()
                    failed_action = None
                    action_attempts = 0
                    continue
                diagnostic = self._diagnostic(f"timeout_{state_before.value}", screen)
                raise RuntimeError(
                    f"no progress in {state_before.value}: {error}; saved {diagnostic}"
                ) from error

            signature = (
                preview_action.name
                if preview_action is not None
                else f"settled:{outcome[0].value}:{outcome[1]}"
            )
            if not stable.update(signature):
                self.sleep(self.poll_seconds)
                continue

            action = self.machine.next_action(screen)
            stable.reset()
            if self.machine.completed_cycles > cycles_before:
                recovered = False
                self.runtime.log(
                    f"模式=远征 状态=本轮完成 已完成={self.machine.completed_cycles}"
                )
                if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
                    return self.machine.completed_cycles

            if action is None:
                if self.machine.state != state_before:
                    state_started = self.now()
                self.sleep(self.poll_seconds)
                continue

            expected_state = self.machine.state
            if failed_action == action.name:
                action_attempts += 1
            else:
                failed_action = action.name
                action_attempts = 1
            self.runtime.log(
                f"模式=远征 轮次={self.machine.completed_cycles + 1}/{max_cycles or '?'} "
                f"页面={state_before.value} 动作={action.name} 尝试={action_attempts}/2"
            )
            self.runtime.click(action.point, action.name)

            if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
                return self.machine.completed_cycles
            if action.name == "battle-start":
                self._run_committed_battle(
                    cycle=self.machine.completed_cycles + 1,
                )
                state_started = self.now()
                failed_action = None
                action_attempts = 0
                stable.reset()
                continue
            if self._wait_until_in_state(expected_state, action.name):
                failed_action = None
                action_attempts = 0
                state_started = self.now()
                continue

            self.machine.state = state_before
            if action_attempts < 2:
                state_started = self.now()
                continue
            if self._can_recover(state_before) and self.recovery is not None and not recovered:
                recovered = True
                self.runtime.log(
                    f"模式=远征 动作={action.name} 恢复=两次点击未转场，回大厅重新导航"
                )
                self.recovery()
                self.machine.state = ExpeditionState.HOME
                state_started = self.now()
                failed_action = None
                action_attempts = 0
                stable.reset()
                continue
            diagnostic = self._diagnostic(f"retry_exhausted_{action.name}", screen)
            raise RuntimeError(
                f"action {action.name} failed after 2 attempts; saved {diagnostic}"
            )

        return self.machine.completed_cycles

    def _wait_until_in_state(
        self, state: ExpeditionState, action_name: str | None = None
    ) -> bool:
        started = self.now()
        progressed = started
        previous: Optional[np.ndarray] = None
        stable = StableObservation(required=2)
        while self.now() - started < self._TRANSITION_ABSOLUTE_SECONDS:
            screen = self.runtime.capture()
            if self.runtime.diagnostic_dir is not None:
                self.runtime.save_current_frame(screen)
            is_target = self.machine.is_in_state(screen, state)
            if action_name == "wake-campfire-ui":
                is_campfire_idle = getattr(self.machine, "is_campfire_idle", None)
                if is_campfire_idle is not None and is_campfire_idle(screen):
                    is_target = False
            if stable.update("target" if is_target else "other"):
                if is_target:
                    return True
            changed = meaningful_change(previous, screen)
            if changed:
                progressed = self.now()
            previous = screen
            if self.now() - progressed >= self._TRANSITION_NO_PROGRESS_SECONDS:
                return False
            self.sleep(self.poll_seconds)
        return False

    @staticmethod
    def _can_recover(state: ExpeditionState) -> bool:
        return state in {
            ExpeditionState.HOME,
            ExpeditionState.POSTERS,
            ExpeditionState.DIFFICULTY,
            ExpeditionState.READY,
        }

    def _diagnostic(self, label: str, screen: np.ndarray):
        if self.runtime.diagnostic_dir is None:
            return "not-configured"
        return self.runtime.save_diagnostic(label, screen)
