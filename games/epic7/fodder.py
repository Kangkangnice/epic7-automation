"""Fixed Episode 3-7 side-story farming workflow."""

from dataclasses import asdict, dataclass
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
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.pre_battle import (
    PreBattleMode,
    QuickBattleDetector,
    load_simulator_quick_battle_detector,
    observe_pre_battle,
)
from auto_game_unified.games.epic7.stamina import (
    STAMINA_REGIONS,
    load_stamina_templates,
    next_stamina_decision,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class FodderState(Enum):
    STAGE = "stage"
    ASSISTANT = "assistant"
    TEAM = "team"
    BATTLE = "battle"
    RESULTS = "results"
    REPLAY = "replay"


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    FodderState.STAGE: "关卡地图",
    FodderState.ASSISTANT: "准备战斗",
    FodderState.TEAM: "队伍选择",
    FodderState.BATTLE: "战斗中",
    FodderState.RESULTS: "结算",
    FodderState.REPLAY: "重新进行",
}


def state_label(state: FodderState) -> str:
    return STATE_LABELS.get(state, state.value)


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
    stamina_popup: np.ndarray
    stamina_material: np.ndarray
    stamina_confirm: np.ndarray
    threshold: float = 0.82
    quick_battle: QuickBattleDetector | None = None


def build_fodder_templates(template_dir: Path) -> FodderTemplates:
    template_root = template_dir.parent
    story = template_root / "story"
    navigation = template_root / "navigation"
    return FodderTemplates(
        stage_title=load_template(str(navigation / "fodder_stage_title.png")),
        prepare_battle=load_template(str(template_dir / "prepare_battle.png")),
        select_team=load_template(str(template_dir / "select_team.png")),
        battle_start=load_template(str(template_dir / "battle_start.png")),
        clear=load_template(str(template_dir / "clear.png")),
        results_confirm=load_template(str(template_dir / "results_confirm.png")),
        replay=load_template(str(template_dir / "replay.png")),
        **asdict(load_stamina_templates(story)),
        quick_battle=load_simulator_quick_battle_detector(template_dir),
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
        **STAMINA_REGIONS,
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

    def _handle_stamina(self, screen: np.ndarray) -> Optional[FodderAction]:
        decision = next_stamina_decision(
            screen, self._locate, material_clicked=self._stamina_material_clicked
        )
        if decision.status == "idle":
            if self._stamina_material_clicked:
                self.stamina_replenished += 1
                self._stamina_material_clicked = False
            return None
        if decision.status == "material":
            self._stamina_material_clicked = True
            return FodderAction("stamina_material", decision.point)
        if decision.status == "waiting":
            raise StaminaExhausted("生命之叶购买按钮不可用")
        return FodderAction("stamina_confirm", decision.point)

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        controls = observe_battle_controls(screen)
        battle_start = self._locate(screen, "battle_start")
        pre_battle = observe_pre_battle(
            self.templates.quick_battle,
            screen,
            normal_start=battle_start,
        )
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
            pre_battle_visible=pre_battle.mode is not PreBattleMode.UNKNOWN,
            battle_visible=battle_scene_visible(screen),
            result_visible=result_visible,
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_evidence=f"布局={controls.value} 自动关图标=未使用(狗粮路线不看图标)",
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
                ("switch-to-normal-battle", pre_battle.switch_point)
                if pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
                else ("start_battle", battle_start.center)
                if pre_battle.mode is PreBattleMode.NORMAL
                and battle_start is not None
                else None
            ),
            pre_battle_business_visible=stamina_popup is not None,
        )

    def next_action(self, screen: np.ndarray) -> Optional[FodderAction]:
        stamina = self._handle_stamina(screen)
        if stamina is not None:
            return stamina

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
            pre_battle = observe_pre_battle(
                self.templates.quick_battle,
                screen,
                normal_start=battle_start,
            )
            if (
                pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
            ):
                self.state = FodderState.BATTLE
                return FodderAction("start_battle", pre_battle.switch_point)
            if pre_battle.mode is PreBattleMode.NORMAL and battle_start is not None:
                self.state = FodderState.BATTLE
                return FodderAction("start_battle", battle_start.center)
        if self.state is FodderState.BATTLE:
            controls = observe_battle_controls(screen)
            if controls is not BattleControls.TRANSITION:
                return None

        raise UnrecognizedScreen(
            f"狗粮画面[{state_label(self.state)}]未识别"
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


class FodderRunner(ModeRunnerBase):
    """两帧确认的狗粮固定循环 Runner（主循环协议见 ModeRunnerBase）。"""

    _MODE_LABEL = "狗粮"
    _TIMEOUT_SECONDS = {
        FodderState.STAGE: 45,
        FodderState.ASSISTANT: 45,
        FodderState.TEAM: 45,
        FodderState.BATTLE: 120,
        FodderState.RESULTS: 45,
        FodderState.REPLAY: 45,
    }
    _BATTLE_ENTRY_ACTION = "start_battle"
    _CLICK_BEFORE_BATTLE = False  # 战斗开始由 BattleSupervisor 代点
    _SETTLED_BATTLE_STATE = FodderState.BATTLE

    def __init__(
        self,
        machine: FodderStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(mode="fodder", mode_label="狗粮"),
            now=self.now,
            sleep=sleep,
        )

    def _state_label(self, state: FodderState) -> str:
        return state_label(state)

    def _on_battle_entry(
        self,
        action: FodderAction,
        state_before: FodderState,
        max_cycles: int | None,
    ) -> None:
        self.runtime.log(
            f"模式=狗粮 轮次={self.machine.completed_cycles + 1}/"
            f"{max_cycles or '?'} 页面={state_before.value} "
            "动作=start_battle 处理=交由战斗监督"
        )

    def _run_committed_battle(self, *, cycle: int) -> None:
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = FodderState.BATTLE
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"狗粮战斗出现意外结果：{outcome.value}")
        self.machine.state = FodderState.RESULTS

    def _on_action_exhausted(self, action: FodderAction, screen) -> bool:
        if action.name == "stamina_confirm":
            self.resource_exhausted = True
            self.runtime.log("模式=狗粮 停止=生命之叶确认多次未生效")
            return True
        return False
