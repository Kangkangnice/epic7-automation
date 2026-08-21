"""Assist auto-repeat battle workflow.

Monitors the game's built-in auto-repeat battle (up to 30 per round). When the
"重复战斗已结束" popup appears at STOPPED, walks 确认 -> 重新进行(PROLOGUE)
-> 选择队伍(ASSISTANT) -> TEAM -> 战斗开始 to start the next round. Stamina is
replenished with leaves when the stamina popup appears after clicking 战斗开始.
"""

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.battle_supervisor import valid_game_frame
from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.stamina import (
    STAMINA_REGIONS,
    load_stamina_templates,
    next_stamina_decision,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase, NOT_STABLE
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class AssistAutoState(Enum):
    TEAM = "team"
    BATTLE = "battle"
    STOPPED = "stopped"
    PROLOGUE = "prologue"
    ASSISTANT = "assistant"


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    AssistAutoState.TEAM: "队伍选择",
    AssistAutoState.BATTLE: "自动战斗中",
    AssistAutoState.STOPPED: "结算确认",
    AssistAutoState.PROLOGUE: "战斗胜利",
    AssistAutoState.ASSISTANT: "准备战斗",
}


def state_label(state: AssistAutoState) -> str:
    return STATE_LABELS.get(state, state.value)


@dataclass(frozen=True)
class AssistAutoAction:
    name: str
    point: tuple[int, int]


@dataclass(frozen=True)
class AssistAutoTemplates:
    auto_stopped: np.ndarray
    replay: np.ndarray
    victory_confirm: np.ndarray
    auto_switch: np.ndarray
    auto_repeat_active: np.ndarray
    select_team: np.ndarray
    battle_start: np.ndarray
    stamina_popup: np.ndarray
    stamina_material: np.ndarray
    stamina_confirm: np.ndarray
    results_confirm: np.ndarray
    threshold: float = 0.82


def build_assist_auto_templates(template_dir: Path) -> AssistAutoTemplates:
    """Load assist-auto templates plus reused fodder/story assets."""
    template_root = template_dir.parent
    fodder = template_root / "fodder"
    story = template_root / "story"
    return AssistAutoTemplates(
        auto_stopped=load_template(str(template_dir / "auto_stopped.png")),
        replay=load_template(str(fodder / "replay.png")),
        victory_confirm=load_template(str(template_dir / "victory_confirm.png")),
        auto_switch=load_template(str(template_dir / "auto_switch.png")),
        auto_repeat_active=load_template(str(template_dir / "auto_repeat_active.png")),
        select_team=load_template(str(fodder / "select_team.png")),
        battle_start=load_template(str(fodder / "battle_start.png")),
        **asdict(load_stamina_templates(story)),
        results_confirm=load_template(str(fodder / "results_confirm.png")),
    )


class AssistAutoStateMachine:
    """Pure visual decisions for the assist auto-repeat cycle.

    The cycle starts at TEAM (user parks there). Each round: click 战斗开始 ->
    BATTLE (monitor) -> STOPPED popup -> PROLOGUE (重新进行) -> ASSISTANT
    (选择队伍) -> TEAM -> 战斗开始 -> ...
    """

    _REFERENCE_SIZE = (1982, 1132)
    _REGIONS = {
        **STAMINA_REGIONS,
        "auto_stopped": (740, 230, 440, 60),
        "replay": (1625, 990, 275, 120),
        "victory_confirm": (1650, 950, 320, 160),
        "auto_switch": (1500, 960, 120, 90),
        "auto_repeat_active": (620, 160, 470, 90),
        "select_team": (1380, 990, 520, 120),
        "battle_start": (1380, 990, 520, 120),
        "results_confirm": (1610, 990, 280, 120),
    }
    _THRESHOLDS = {
        "auto_stopped": 0.85,
        "replay": 0.85,
        "victory_confirm": 0.85,
        "select_team": 0.80,
        "battle_start": 0.70,
        "results_confirm": 0.85,
    }

    def __init__(
        self,
        templates: AssistAutoTemplates,
        *,
        initial_state: AssistAutoState = AssistAutoState.TEAM,
    ) -> None:
        self.templates = templates
        self.state = initial_state
        self.completed_cycles = 0
        self._stamina_material_clicked = False

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        threshold = self._THRESHOLDS.get(name, self.templates.threshold)
        return find_template(
            screen,
            getattr(self.templates, name),
            threshold,
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def _handle_stamina(self, screen: np.ndarray) -> Optional[AssistAutoAction]:
        decision = next_stamina_decision(
            screen, self._locate, material_clicked=self._stamina_material_clicked
        )
        if decision.status == "idle":
            self._stamina_material_clicked = False
            return None
        if decision.status == "material":
            self._stamina_material_clicked = True
            return AssistAutoAction("stamina_material", decision.point)
        if decision.status == "waiting":
            raise StaminaExhausted("生命之叶购买按钮不可用")
        return AssistAutoAction("stamina_confirm", decision.point)

    def is_stopped(self, screen: np.ndarray) -> bool:
        return self._locate(screen, "auto_stopped") is not None

    def is_repeat_active(self, screen: np.ndarray) -> bool:
        return self._locate(screen, "auto_repeat_active") is not None

    def next_action(self, screen: np.ndarray) -> AssistAutoAction:
        stamina = self._handle_stamina(screen)
        if stamina is not None:
            return stamina

        if self.state == AssistAutoState.STOPPED:
            confirm = self._locate(screen, "results_confirm")
            if confirm is not None:
                self.state = AssistAutoState.PROLOGUE
                return AssistAutoAction("confirm_results", confirm.center)

        if self.state == AssistAutoState.PROLOGUE:
            # 战斗胜利画面：右下角可能是"重新进行"(replay)，也可能是
            # 位置略偏右的"确认"(victory_confirm)，两种都尝试。
            replay = self._locate(screen, "replay")
            if replay is not None:
                self.state = AssistAutoState.ASSISTANT
                return AssistAutoAction("replay", replay.center)
            confirm = self._locate(screen, "victory_confirm")
            if confirm is not None:
                self.state = AssistAutoState.ASSISTANT
                return AssistAutoAction("confirm_victory", confirm.center)
            raise UnrecognizedScreen(
                f"辅助自动画面[{state_label(self.state)}]未识别"
            )

        if self.state == AssistAutoState.ASSISTANT:
            # 准备战斗界面：右下角"选择队伍"(select_team)，点它进入队伍选择界面。
            select_team = self._locate(screen, "select_team")
            if select_team is not None:
                self.state = AssistAutoState.TEAM
                return AssistAutoAction("select_team", select_team.center)

        if self.state == AssistAutoState.TEAM:
            battle_start = self._locate(screen, "battle_start")
            if battle_start is not None:
                self.state = AssistAutoState.BATTLE
                return AssistAutoAction("start_battle", battle_start.center)

        raise UnrecognizedScreen(
            f"辅助自动画面[{state_label(self.state)}]未识别"
        )

    def preview(self, screen: np.ndarray):
        snapshot = (
            self.state,
            self.completed_cycles,
            self._stamina_material_clicked,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self._stamina_material_clicked,
            ) = snapshot


class AssistAutoRunner(ModeRunnerBase):
    """辅助自动循环 Runner（主循环协议见 ModeRunnerBase）。

    战斗阶段不复用 BattleSupervisor，而是用自带的一轮 30 次重复战斗
    监控循环（_monitor_auto_repeat）。
    """

    _MODE_LABEL = "辅助自动"
    _TIMEOUT_SECONDS = {
        AssistAutoState.TEAM: 60,
        AssistAutoState.STOPPED: 45,
        AssistAutoState.PROLOGUE: 45,
        AssistAutoState.ASSISTANT: 45,
    }
    _ABSOLUTE_TIMEOUT_SECONDS = None  # 战斗轮自身有 1800 秒绝对上限
    _BATTLE_ENTRY_ACTION = "start_battle"
    _SETTLE_SECONDS = 1.5
    _BATTLE_HEARTBEAT_SECONDS = 30
    _BATTLE_NO_ACTIVITY_SECONDS = 180
    _BATTLE_ABSOLUTE_SECONDS = 1800

    def __init__(
        self,
        machine: AssistAutoStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery: Callable[[], None] | None = None,
        recovery_gate: RecoveryGate | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery=recovery,
            recovery_gate=recovery_gate,
        )

    def _state_label(self, state: AssistAutoState) -> str:
        return state_label(state)

    def _timeout_for(self, state: AssistAutoState) -> float:
        return self._TIMEOUT_SECONDS.get(state, 60)

    def _apply_recovery_state(self) -> None:
        self.machine.state = AssistAutoState.TEAM

    def _run_committed_battle(self, *, cycle: int) -> None:
        self._monitor_auto_repeat(cycle=cycle)

    def _after_battle(self, max_cycles: int | None) -> bool:
        self._recovered = False
        if self.resource_exhausted:
            return True
        return (
            max_cycles is not None
            and self.machine.completed_cycles >= max_cycles
        )

    def _timeout_error_message(self, error: Exception, diagnostic) -> str:
        return f"{error}；已保存诊断 {diagnostic}"

    def _stable_next_action(self, screen, stable):
        preview_action, _ = self.machine.preview(screen)
        if preview_action is None:
            return NOT_STABLE
        if not stable.update(preview_action.name):
            return NOT_STABLE
        action = self.machine.next_action(screen)
        self.unknown_screen_wake.reset()
        return action

    def _monitor_auto_repeat(self, *, cycle: int) -> None:
        """Monitor one 30-battle auto-repeat round until the stop popup appears."""
        self.recovery_gate.lock(mode="assist_auto", cycle=cycle)
        started = active_at = heartbeat = self.now()
        previous: Optional[np.ndarray] = None
        left_team = False
        team_streak = 0
        try:
            while True:
                screen = self.runtime.capture()
                if self.runtime.diagnostic_dir is not None:
                    self.runtime.save_current_frame(screen)
                # 开场前置业务：点击"战斗开始"后若体力不足会弹体力框，
                # 必须在进入战斗监控前处理（沿用 fodder 的两步逻辑）。
                try:
                    stamina = self.machine._handle_stamina(screen)
                except StaminaExhausted as error:
                    self.resource_exhausted = True
                    self.runtime.log(
                        f"模式=辅助自动 停止=生命之叶耗尽 详情={error}"
                    )
                    return
                if stamina is not None:
                    self.runtime.click(stamina.point, stamina.name)
                    active_at = self.now()
                    self.sleep(self.poll_seconds)
                    continue
                if self.machine.is_stopped(screen):
                    self.runtime.log(
                        f"模式=辅助自动 轮次={cycle} 状态=重复战斗已结束"
                    )
                    self.machine.completed_cycles += 1
                    self.machine.state = AssistAutoState.STOPPED
                    return
                # 一轮也可能在结束弹窗被外部点掉后直接回到队伍界面：
                # 画面真正离开过队伍界面后再次稳定见到"战斗开始"，
                # 说明本轮已结束并回到稳定入口，同样计入完成。
                team_entry = self.machine._locate(screen, "battle_start")
                if left_team and team_entry is not None:
                    team_streak += 1
                    if team_streak >= 2:
                        self.runtime.log(
                            f"模式=辅助自动 轮次={cycle} 状态=回到队伍界面"
                        )
                        self.machine.completed_cycles += 1
                        self.machine.state = AssistAutoState.TEAM
                        return
                else:
                    team_streak = 0
                    if team_entry is None:
                        left_team = True
                if meaningful_change(previous, screen):
                    active_at = self.now()
                previous = screen
                current = self.now()
                if not valid_game_frame(screen):
                    if current - active_at >= self._BATTLE_NO_ACTIVITY_SECONDS:
                        diag = self.runtime.save_diagnostic(
                            "auto_black_timeout", screen
                        )
                        raise RuntimeError(
                            f"自动战斗画面持续黑屏超时；已保存诊断 {diag}"
                        )
                elif current - active_at >= self._BATTLE_NO_ACTIVITY_SECONDS:
                    diag = self.runtime.save_diagnostic("auto_no_activity", screen)
                    raise RuntimeError(f"自动战斗画面无变化超时；已保存诊断 {diag}")
                if current - started >= self._BATTLE_ABSOLUTE_SECONDS:
                    diag = self.runtime.save_diagnostic(
                        "auto_absolute_timeout", screen
                    )
                    raise RuntimeError(f"自动战斗绝对超时；已保存诊断 {diag}")
                if current - heartbeat >= self._BATTLE_HEARTBEAT_SECONDS:
                    self.runtime.log(
                        f"模式=辅助自动 轮次={cycle} 阶段=战斗 状态=心跳 "
                        f"已耗时={current - started:.0f}秒 "
                        f"距上次画面变化={current - active_at:.0f}秒"
                    )
                    heartbeat = current
                self.sleep(self.poll_seconds)
        finally:
            self.recovery_gate.unlock()
