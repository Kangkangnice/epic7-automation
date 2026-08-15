"""Fixed Episode 3-7 side-story farming workflow."""

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
from auto_game_unified.games.epic7.story import find_friendship_points_popup_close
from auto_game_unified.games.epic7.unknown_screen import (
    UnrecognizedScreen,
    UnknownScreenWake,
    UnknownWakeResult,
)


class FodderState(Enum):
    STAGE = "stage"
    ASSISTANT = "assistant"
    TEAM = "team"
    BATTLE = "battle"
    RESULTS = "results"
    REPLAY = "replay"


@dataclass(frozen=True)
class FodderAction:
    name: str
    point: tuple[int, int]


@dataclass(frozen=True)
class FodderTemplates:
    stage_title: np.ndarray
    prepare_battle: np.ndarray
    select_team: np.ndarray
    battle_start: np.ndarray
    clear: np.ndarray
    results_confirm: np.ndarray
    replay: np.ndarray
    friendship_points_title: np.ndarray
    friendship_points_close: np.ndarray
    friend_request_title: np.ndarray
    friend_request_cancel: np.ndarray
    stamina_popup: np.ndarray
    stamina_material: np.ndarray
    stamina_confirm: np.ndarray
    threshold: float = 0.82


def build_fodder_templates(template_dir: Path) -> FodderTemplates:
    template_root = template_dir.parent
    story = template_root / "story"
    global_templates = template_root / "global"
    navigation = template_root / "navigation"
    return FodderTemplates(
        stage_title=load_template(str(navigation / "fodder_stage_title.png")),
        prepare_battle=load_template(str(template_dir / "prepare_battle.png")),
        select_team=load_template(str(template_dir / "select_team.png")),
        battle_start=load_template(str(template_dir / "battle_start.png")),
        clear=load_template(str(template_dir / "clear.png")),
        results_confirm=load_template(str(template_dir / "results_confirm.png")),
        replay=load_template(str(template_dir / "replay.png")),
        friendship_points_title=load_template(
            str(global_templates / "friendship_points_title.png")
        ),
        friendship_points_close=load_template(
            str(global_templates / "friendship_points_close.png")
        ),
        friend_request_title=load_template(str(story / "friend_request_title.png")),
        friend_request_cancel=load_template(str(story / "friend_request_cancel.png")),
        stamina_popup=load_template(str(story / "stamina_popup.png")),
        stamina_material=load_template(str(story / "stamina_material.png")),
        stamina_confirm=load_template(str(story / "stamina_confirm.png")),
    )


class FodderStateMachine:
    """Pure visual decisions for the fixed side-story farming cycle."""

    _REFERENCE_SIZE = (1982, 1132)
    _REGIONS = {
        "stage_title": (850, 760, 225, 90),
        "prepare_battle": (1365, 990, 385, 120),
        "select_team": (1380, 990, 520, 120),
        "battle_start": (1380, 990, 520, 120),
        "clear": (770, 420, 390, 130),
        "results_confirm": (1610, 990, 280, 120),
        "replay": (1625, 990, 275, 120),
        "friend_request_title": (650, 240, 700, 160),
        "friend_request_cancel": (550, 720, 500, 230),
        "stamina_popup": (400, 200, 1200, 700),
        "stamina_material": (400, 200, 700, 700),
        "stamina_confirm": (850, 750, 650, 250),
    }
    _AUTO_CLICK_POINT = (1690, 96)

    def __init__(
        self,
        templates: FodderTemplates,
        initial_state: FodderState = FodderState.STAGE,
    ) -> None:
        self.templates = templates
        self.state = initial_state
        self.completed_cycles = 0
        self.stamina_replenished = 0
        self._stamina_material_clicked = False

    def _locate(self, screen: np.ndarray, name: str, threshold: float | None = None):
        if name in {"prepare_battle", "select_team", "battle_start"}:
            ref_x, ref_y, ref_width, ref_height = self._REGIONS[name]
            scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
            scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
            x, y, width, height = (
                round(ref_x * scale_x),
                round(ref_y * scale_y),
                round(ref_width * scale_x),
                round(ref_height * scale_y),
            )
            search_hsv = cv2.cvtColor(
                screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
            )
            template_hsv = cv2.cvtColor(
                getattr(self.templates, name), cv2.COLOR_RGB2HSV
            )
            lower = np.array([0, 0, 150])
            upper = np.array([179, 90, 255])
            match = find_template(
                cv2.inRange(search_hsv, lower, upper),
                cv2.inRange(template_hsv, lower, upper),
                threshold or 0.70,
                reference_size=(ref_width, ref_height),
            )
            if match is None:
                return None
            return Match((x + match.center[0], y + match.center[1]), match.score)
        return find_template(
            screen,
            getattr(self.templates, name),
            threshold or self.templates.threshold,
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def _scaled_point(
        self, screen: np.ndarray, point: tuple[int, int]
    ) -> tuple[int, int]:
        return (
            round(point[0] * screen.shape[1] / self._REFERENCE_SIZE[0]),
            round(point[1] * screen.shape[0] / self._REFERENCE_SIZE[1]),
        )

    def _friend_request_cancel(self, screen: np.ndarray) -> Optional[Match]:
        title = self._locate(screen, "friend_request_title")
        cancel = self._locate(screen, "friend_request_cancel")
        if title is None or cancel is None:
            return None
        return Match(cancel.center, min(title.score, cancel.score))

    def _handle_stamina(self, screen: np.ndarray) -> Optional[FodderAction]:
        popup = self._locate(screen, "stamina_popup")
        if popup is None:
            if self._stamina_material_clicked:
                self.stamina_replenished += 1
            self._stamina_material_clicked = False
            return None
        material = self._locate(screen, "stamina_material")
        if material is None:
            raise StaminaExhausted("生命之叶已耗尽或生命之叶选项不可用")
        if not self._stamina_material_clicked:
            self._stamina_material_clicked = True
            return FodderAction("stamina_material", material.center)
        confirm = self._locate(screen, "stamina_confirm")
        if confirm is None:
            raise StaminaExhausted("生命之叶购买按钮不可用")
        return FodderAction("stamina_confirm", confirm.center)

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        controls = observe_battle_controls(screen)
        battle_start = self._locate(screen, "battle_start")
        stamina_popup = self._locate(screen, "stamina_popup")
        auto_state = {
            BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
            BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
            BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
        }[controls]
        result_visible = any(
            self._locate(screen, name) is not None
            for name in ("clear", "results_confirm", "replay")
        )
        return BattleObservation(
            pre_battle_visible=battle_start is not None,
            battle_visible=controls is not BattleControls.TRANSITION,
            result_visible=result_visible,
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_point=(
                self._scaled_point(screen, self._AUTO_CLICK_POINT)
                if auto_state is AutoBattleState.MANUAL
                else None
            ),
            business_progress=(
                auto_state is AutoBattleState.AUTO
                and meaningful_change(previous_screen, screen)
            ),
            allowed_action=(
                ("start_battle", battle_start.center)
                if battle_start is not None
                else None
            ),
            pre_battle_business_visible=stamina_popup is not None,
        )

    def next_action(self, screen: np.ndarray) -> Optional[FodderAction]:
        popup_close = find_friendship_points_popup_close(
            screen,
            self.templates.friendship_points_title,
            self.templates.friendship_points_close,
        )
        if popup_close is not None:
            return FodderAction("close_friendship_points_popup", popup_close.center)

        stamina = self._handle_stamina(screen)
        if stamina is not None:
            return stamina

        friend_cancel = self._friend_request_cancel(screen)
        if friend_cancel is not None:
            return FodderAction("cancel_friend_request", friend_cancel.center)

        replay = self._locate(screen, "replay")
        if replay is not None:
            if self.state is not FodderState.ASSISTANT:
                self.completed_cycles += 1
                self.state = FodderState.ASSISTANT
            return FodderAction("replay", replay.center)

        results = self._locate(screen, "results_confirm")
        if results is not None:
            self.state = FodderState.REPLAY
            return FodderAction("confirm_results", results.center)

        clear = self._locate(screen, "clear")
        if clear is not None:
            self.state = FodderState.RESULTS
            return FodderAction("dismiss_clear", clear.center)

        if self.state in (FodderState.STAGE, FodderState.ASSISTANT):
            title = self._locate(screen, "stage_title")
            prepare = self._locate(screen, "prepare_battle")
            if title is not None and prepare is not None:
                self.state = FodderState.ASSISTANT
                return FodderAction("prepare_battle", prepare.center)
        if self.state in (FodderState.ASSISTANT, FodderState.TEAM):
            select_team = self._locate(screen, "select_team")
            if select_team is not None:
                self.state = FodderState.TEAM
                return FodderAction("select_team", select_team.center)
        if self.state in (FodderState.TEAM, FodderState.BATTLE):
            battle_start = self._locate(screen, "battle_start")
            if battle_start is not None:
                self.state = FodderState.BATTLE
                return FodderAction("start_battle", battle_start.center)
        if self.state is FodderState.BATTLE:
            controls = observe_battle_controls(screen)
            if controls is not BattleControls.TRANSITION:
                return None

        raise UnrecognizedScreen(
            f"expected {self.state.value} fodder screen was not recognized"
        )

    def preview(self, screen: np.ndarray):
        snapshot = (
            self.state,
            self.completed_cycles,
            self.stamina_replenished,
            self._stamina_material_clicked,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.stamina_replenished,
                self._stamina_material_clicked,
            ) = snapshot


class FodderRunner:
    """Two-frame-confirmed runner for the fixed Episode 3-7 cycle."""

    _ACTION_RETRY_SECONDS = 45
    _TIMEOUT_SECONDS = {
        FodderState.STAGE: 45,
        FodderState.ASSISTANT: 45,
        FodderState.TEAM: 45,
        FodderState.BATTLE: 120,
        FodderState.RESULTS: 45,
        FodderState.REPLAY: 45,
    }

    def __init__(
        self,
        machine: FodderStateMachine,
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
            BattleConfig(mode="fodder"),
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
            self.machine.state = FodderState.BATTLE
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"unexpected fodder battle outcome: {outcome.value}")
        self.machine.state = FodderState.RESULTS

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
                    f"dry-run did not recognize {self.machine.state.value}; "
                    f"saved {diagnostic}"
                ) from error
            if action is not None:
                self.runtime.log(
                    f"模式=狗粮 页面={self.machine.state.value} "
                    f"动作={action.name} 状态=诊断"
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
                self.runtime.log(f"模式=狗粮 停止=生命之叶耗尽 详情={error}")
                return self.machine.completed_cycles
            except RuntimeError as error:
                if isinstance(error, UnrecognizedScreen):
                    wake_result = self.unknown_screen_wake.handle(
                        screen,
                        context=f"fodder:{self.machine.state.value}",
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
                            f"模式=狗粮 页面={self.machine.state.value} "
                            "恢复=回大厅重新导航"
                        )
                        self.recovery()
                        self.machine.state = FodderState.STAGE
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
                    raise RuntimeError(
                        f"no progress: {error}; stopped safely, saved {diagnostic}"
                    ) from error
                self.sleep(self.poll_seconds)
                continue

            self.unknown_screen_wake.reset()
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
                    f"模式=狗粮 状态=完成一轮 cycles={self.machine.completed_cycles}"
                )
                state_started = self.now()
                if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
                    return self.machine.completed_cycles

            if action is None and self.machine.state is FodderState.BATTLE:
                self._run_committed_battle(
                    cycle=self.machine.completed_cycles + 1,
                )
                state_started = self.now()
                absolute_started = state_started
                last_action_name = None
                last_action_clicked_at = None
                retry_wait_logged = False
                action_attempts = 0
                stable.reset()
                continue

            if action is not None and action.name == "start_battle":
                self.runtime.log(
                    f"模式=狗粮 轮次={self.machine.completed_cycles + 1}/"
                    f"{max_cycles or '?'} 页面={state_before.value} "
                    "动作=start_battle 处理=交由战斗监督"
                )
                self._run_committed_battle(
                    cycle=self.machine.completed_cycles + 1,
                )
                state_started = self.now()
                absolute_started = state_started
                last_action_name = None
                last_action_clicked_at = None
                retry_wait_logged = False
                action_attempts = 0
                stable.reset()
                continue

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
                                f"模式=狗粮 轮次={self.machine.completed_cycles + 1}/"
                                f"{max_cycles or '?'} 动作={action.name} "
                                f"等待=点击后确认转场 剩余={remaining:.1f}秒"
                            )
                            retry_wait_logged = True
                        self.sleep(self.poll_seconds)
                        continue
                    action_attempts += 1
                else:
                    last_action_name = action.name
                    action_attempts = 1

                if action_attempts > 2:
                    if action.name == "stamina_confirm":
                        self.resource_exhausted = True
                        self.runtime.log(
                            "模式=狗粮 停止=生命之叶确认两次未生效"
                        )
                        return self.machine.completed_cycles
                    if self.recovery is not None and not recovered:
                        recovered = True
                        self.runtime.log(
                            f"模式=狗粮 动作={action.name} "
                            "恢复=两次点击未转场，回大厅重新导航"
                        )
                        self.recovery()
                        self.machine.state = FodderState.STAGE
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
                    f"模式=狗粮 轮次={self.machine.completed_cycles + 1}/"
                    f"{max_cycles or '?'} 页面={state_before.value} "
                    f"动作={action.name} 尝试={action_attempts}/2"
                )
                self.runtime.click(action.point, action.name)
                last_action_clicked_at = self.now()
                state_started = last_action_clicked_at
                absolute_started = last_action_clicked_at
                retry_wait_logged = False
            else:
                last_action_name = None
                last_action_clicked_at = None
                retry_wait_logged = False
                action_attempts = 0

            if (
                action is None
                and self.now() - state_started
                >= self._TIMEOUT_SECONDS[self.machine.state]
            ):
                diagnostic = self.runtime.save_diagnostic(
                    f"timeout_{self.machine.state.value}", screen
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
                    f"absolute timeout in {self.machine.state.value}; "
                    f"stopped safely, saved {diagnostic}"
                )
            self.sleep(self.poll_seconds)

        return self.machine.completed_cycles
