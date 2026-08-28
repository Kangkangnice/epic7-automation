"""Fail-closed automation for Epic Seven expeditions."""

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
    battle_scene_visible,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.pre_battle import (
    PreBattleMode,
    QuickBattleDetector,
    load_simulator_quick_battle_detector,
    observe_pre_battle,
)
from auto_game_unified.games.epic7.unknown_screen import (
    UnrecognizedScreen,
    UnknownScreenWake,
    UnknownWakeResult,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile
from auto_game_unified.games.epic7.evidence.expedition import (
    REFERENCE_SIZE as EXPEDITION_REFERENCE_SIZE,
    REGIONS as EXPEDITION_REGIONS,
    THRESHOLDS as EXPEDITION_THRESHOLDS,
    build_expedition_evidence,
)


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


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    ExpeditionState.HOME: "远征主页",
    ExpeditionState.POSTERS: "通缉传单列表",
    ExpeditionState.DIFFICULTY: "难度选择",
    ExpeditionState.DIFFICULTY_CONFIRM: "难度确认",
    ExpeditionState.READY: "准备战斗",
    ExpeditionState.TEAM: "队伍选择",
    ExpeditionState.BATTLE: "战斗中",
    ExpeditionState.RESULT: "战斗结果",
    ExpeditionState.OUTCOME: "公开招募结果",
    ExpeditionState.RECRUIT_CONFIRM: "招募确认",
    ExpeditionState.RECRUIT_RETURN: "招募后返回",
    ExpeditionState.RETURNING: "返回主页",
}


def state_label(state: ExpeditionState) -> str:
    return STATE_LABELS.get(state, state.value)


class PostersExhausted(StaminaExhausted):
    """No card-level wanted-poster departure action remains."""


@dataclass(frozen=True)
class ExpeditionAction:
    name: str
    point: tuple[int, int]
    source_page: str = ""
    target_pages: tuple[str, ...] = ()
    reason: str = ""
    source_state: ExpeditionState | None = None
    target_states: tuple[ExpeditionState, ...] = ()


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
    quick_battle: QuickBattleDetector | None = None
    evidence: EvidenceProfile | None = None


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
        quick_battle=load_simulator_quick_battle_detector(template_dir),
        evidence=build_expedition_evidence(template_dir),
    )


class ExpeditionStateMachine:
    _REFERENCE_SIZE = EXPEDITION_REFERENCE_SIZE
    _THRESHOLD = 0.88
    # 实机画面会动画/色彩漂移：远征“营地待机”锚点在实时帧最低约 0.835
    # （见 runtime_diagnostics 实机帧 20260826_081022），故对其单独放宽到 0.82；
    # 其余锚点沿用 0.88（出发按钮在实时帧稳定命中 1.0，无需放宽）。
    _THRESHOLDS = EXPEDITION_THRESHOLDS
    _REGIONS = EXPEDITION_REGIONS

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
        if self.templates.evidence is not None:
            self._REGIONS = {
                key: atom.region for key, atom in self.templates.evidence.atoms.items()
            }
            self._THRESHOLDS = {
                key: atom.threshold
                for key, atom in self.templates.evidence.atoms.items()
            }
        self.completed_cycles = 0
        self.auto_click_attempted = False
        self._confirmed_page = ""

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
            self._THRESHOLDS.get(name, self._THRESHOLD),
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
            raise UnrecognizedScreen(
                f"远征锚点 {name} 未识别"
            )
        return match

    def _on_posters_list(self, screen: np.ndarray) -> bool:
        """通缉传单列表已稳定出现。

        实机帧中“出发”按钮会随列表滑入动画延迟出现（runtime_diagnostics
        20260826_081147 中出发按钮低于阈值、但列表标题+返回键稳定命中 ~0.99），
        故同时接受“出发按钮已就位”或“列表标题+返回键齐备”两种信号，使列表
        动画期间也能被识别为通缉传单列表。
        """
        if self._locate(screen, "poster_embark") is not None:
            return True
        return (
            self._locate(screen, "expedition_list") is not None
            and self._locate(screen, "back") is not None
        )

    def _defeated_action(self, screen: np.ndarray) -> Optional[ExpeditionAction]:
        match = self._locate(screen, "defeated_confirm")
        if match is None:
            return None
        return self._action(
            "confirm-defeated", match.center,
            source_page="公开招募结果",
            target_states=(ExpeditionState.RETURNING,),
            reason="识别到战败确认，点击返回",
        )

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
            ) or battle_scene_visible(screen)
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

    def _confirm_page(self, label: str) -> None:
        self._confirmed_page = label

    def _action(
        self,
        name: str,
        point: tuple[int, int],
        *,
        source_page: str,
        target_states: tuple[ExpeditionState, ...],
        reason: str,
    ) -> ExpeditionAction:
        return ExpeditionAction(
            name,
            point,
            source_page=source_page,
            target_pages=tuple(state_label(item) for item in target_states),
            reason=reason,
            source_state=self.state,
            target_states=target_states,
        )

    def commit(self, action: ExpeditionAction, target: ExpeditionState) -> None:
        if action.source_state is not self.state:
            raise RuntimeError("远征动作来源状态与当前状态不一致")
        if target not in action.target_states:
            raise RuntimeError("远征动作目标状态不在合同中")
        self.state = target
        if action.name == "return-to-expedition-home" and target is ExpeditionState.HOME:
            self.completed_cycles += 1
        if target is ExpeditionState.BATTLE:
            self.auto_click_attempted = False

    def action_source_visible(self, screen: np.ndarray, action: ExpeditionAction) -> bool:
        if action.name == "wake-campfire-ui":
            return self.is_campfire_idle(screen)
        if action.name == "enable-auto-battle":
            return self._locate(screen, "auto_off") is not None
        return (
            action.source_state is not None
            and self.is_in_state(screen, action.source_state)
        )

    def action_target_state(
        self, screen: np.ndarray, action: ExpeditionAction
    ) -> ExpeditionState | None:
        if action.name == "wake-campfire-ui":
            if self.is_campfire_idle(screen):
                return None
            if action.source_state is not None and self.is_in_state(screen, action.source_state):
                return action.source_state
            return None
        if action.name == "enable-auto-battle":
            if self._locate(screen, "auto_off") is None and self._locate(screen, "battle_anchor") is not None:
                return ExpeditionState.BATTLE
            return None
        for target in action.target_states:
            if self.is_in_state(screen, target):
                return target
        return None

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
        auto_state = {
            BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
            BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
            BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
        }[controls]
        auto = self._locate(screen, "auto_off")
        if auto is not None and self.templates.quick_battle is not None:
            auto_state = AutoBattleState.MANUAL
        battle = self._locate(screen, "battle_anchor")
        result = self._locate(screen, "result_confirm")
        progressing = valid_game_frame(screen) and meaningful_change(
            previous_screen,
            screen,
        )
        return BattleObservation(
            pre_battle_visible=pre_battle.mode is not PreBattleMode.UNKNOWN,
            battle_visible=(
                battle is not None
                or battle_scene_visible(screen)
            ),
            result_visible=result is not None,
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_point=(
                auto.center
                if auto is not None and auto_state is AutoBattleState.MANUAL
                else None
            ),
            business_progress=progressing,
            allowed_action=(
                ("switch-to-normal-battle", pre_battle.switch_point)
                if pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
                else ("battle-start", battle_start.center)
                if pre_battle.mode is PreBattleMode.NORMAL
                and battle_start is not None
                else None
            ),
        )

    def _posters_action(self, screen: np.ndarray) -> Optional[ExpeditionAction]:
        if self._locate(screen, "empty_posters") is not None:
            raise PostersExhausted("没有可用的通缉传单")
        match = self._locate(screen, "poster_embark")
        if match is not None:
            return self._action(
                "select-first-poster", match.center,
                source_page="通缉传单列表",
                target_states=(ExpeditionState.DIFFICULTY,),
                reason="识别到首个通缉传单，点击出发",
            )
        # 通缉传单列表已稳定出现（列表标题+返回键命中），但“出发”按钮还在滑入
        # 动画中未就位：不报错，返回 None 让主循环重新轮询，等按钮就位后再点。
        if self._on_posters_list(screen):
            return None
        raise RuntimeError("传单卡片区域内未找到远征队出发按钮")

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
            match = self._locate(screen, "home")
            if match is None and self._on_posters_list(screen):
                # 远征主页未识别，但画面已是通缉传单列表（如上一轮返回落点偏差、
                # 或转场动画中状态尚未同步到主页）。直接按 POSTERS 处理，避免被
                # 误判为未知画面而进入唤醒死循环。
                self.state = ExpeditionState.POSTERS
                return self._posters_action(screen)
            if match is None:
                raise UnrecognizedScreen("远征主页未识别")
            return self._action(
                "open-my-posters", match.center,
                source_page="远征主页",
                target_states=(ExpeditionState.POSTERS,),
                reason="识别到远征主页，点击我的通缉传单",
            )

        if self.state == ExpeditionState.POSTERS:
            return self._posters_action(screen)

        if self.state == ExpeditionState.DIFFICULTY:
            title = self._required(screen, "difficulty_title")
            selected = self._locate(screen, "difficulty_3_selected")
            confirm = self._locate(screen, "difficulty_confirm")
            if selected is not None and confirm is not None:
                return self._action(
                    "confirm-difficulty-3", confirm.center,
                    source_page="难度三已选中",
                    target_states=(ExpeditionState.READY,),
                    reason="难度三与确认按钮已同时识别，跳过重复选择",
                )
            return self._action(
                "select-difficulty-3",
                (title.center[0] + 155, title.center[1] + 495),
                source_page="难度选择",
                target_states=(ExpeditionState.DIFFICULTY_CONFIRM,),
                reason="识别到难度标题，点击第3难度",
            )

        if self.state == ExpeditionState.DIFFICULTY_CONFIRM:
            self._required(screen, "difficulty_3_selected")
            confirm = self._required(screen, "difficulty_confirm")
            return self._action(
                "confirm-difficulty-3", confirm.center,
                source_page="难度确认",
                target_states=(ExpeditionState.READY,),
                reason="确认第3难度",
            )

        if self.state == ExpeditionState.READY:
            match = self._required(screen, "prepare_battle")
            return self._action(
                "prepare-battle", match.center,
                source_page="准备战斗",
                target_states=(ExpeditionState.TEAM,),
                reason="识别到准备战斗，进入队伍选择",
            )

        if self.state == ExpeditionState.TEAM:
            match = self._locate(screen, "battle_start")
            pre_battle = observe_pre_battle(
                self.templates.quick_battle,
                screen,
                normal_start=match,
            )
            if (
                pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
            ):
                return self._action(
                    "battle-start", pre_battle.switch_point,
                    source_page="队伍选择",
                    target_states=(ExpeditionState.BATTLE,),
                    reason="快速战斗，点击切换为普通战斗并开始",
                )
            if pre_battle.mode is not PreBattleMode.NORMAL or match is None:
                raise UnrecognizedScreen("远征队伍页未识别普通或快速战斗入口")
            return self._action(
                "battle-start", match.center,
                source_page="队伍选择",
                target_states=(ExpeditionState.BATTLE,),
                reason="普通战斗，点击开始战斗",
            )

        if self.state in {ExpeditionState.BATTLE, ExpeditionState.RESULT}:
            result = self._locate(screen, "result_confirm")
            if result is not None:
                return self._action(
                    "confirm-result", result.center,
                    source_page="战斗结果",
                    target_states=(ExpeditionState.OUTCOME,),
                    reason="识别到结算确认，点击领取结果",
                )
            auto_off = self._locate(screen, "auto_off")
            if auto_off is not None:
                if self.auto_click_attempted:
                    return None
                self.auto_click_attempted = True
                return self._action(
                    "enable-auto-battle", auto_off.center,
                    source_page="战斗结果",
                    target_states=(ExpeditionState.BATTLE,),
                    reason="识别到自动战斗关闭，开启自动战斗",
                )
            if self.state == ExpeditionState.BATTLE and self._locate(screen, "battle_anchor"):
                return None
            raise UnrecognizedScreen("远征战斗/结算画面未识别")

        if self.state == ExpeditionState.OUTCOME:
            victory_title = self._locate(screen, "victory_title")
            victory_close = self._locate(screen, "victory_close")
            if victory_title is not None and victory_close is not None:
                return self._action(
                    "close-expedition-victory", victory_close.center,
                    source_page="公开招募结果",
                    target_states=(ExpeditionState.RETURNING,),
                    reason="识别到胜利结算，关闭远征胜利",
                )
            if self._locate(screen, "campfire_idle") is not None:
                return self._action(
                    "wake-campfire-ui", (1000, 600),
                    source_page="公开招募结果",
                    target_states=(ExpeditionState.OUTCOME,),
                    reason="营地UI未推进，尝试唤醒",
                )
            recruit = self._required(screen, "public_recruit")
            return self._action(
                "public-recruit", recruit.center,
                source_page="公开招募结果",
                target_states=(ExpeditionState.RECRUIT_CONFIRM,),
                reason="识别到公开招募，点击招募",
            )

        if self.state == ExpeditionState.RECRUIT_CONFIRM:
            self._required(screen, "public_title")
            confirm = self._required(screen, "public_confirm")
            return self._action(
                "confirm-public-recruit", confirm.center,
                source_page="招募确认",
                target_states=(ExpeditionState.RECRUIT_RETURN,),
                reason="确认公开招募",
            )

        if self.state == ExpeditionState.RECRUIT_RETURN:
            if self._locate(screen, "campfire_idle") is not None:
                return self._action(
                    "wake-campfire-ui", (1000, 600),
                    source_page="招募后返回",
                    target_states=(ExpeditionState.RECRUIT_RETURN,),
                    reason="营地UI未推进，尝试唤醒",
                )
            self._required(screen, "public_recruited")
            back = self._required(screen, "back")
            return self._action(
                "return-from-expedition", back.center,
                source_page="招募后返回",
                target_states=(ExpeditionState.RETURNING,),
                reason="识别到招募完成，返回远征",
            )

        if self.state == ExpeditionState.RETURNING:
            self._required(screen, "expedition_list")
            back = self._required(screen, "back")
            return self._action(
                "return-to-expedition-home", back.center,
                source_page="返回主页",
                target_states=(ExpeditionState.HOME,),
                reason="识别到远征列表，返回主页",
            )

        raise RuntimeError(f"远征状态机遇到不支持的状态：{self.state.value}")

    def preview(self, screen: np.ndarray):
        snapshot = (
            self.state,
            self.completed_cycles,
            self.auto_click_attempted,
            self._confirmed_page,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.auto_click_attempted,
                self._confirmed_page,
            ) = snapshot


class ExpeditionRunner:
    """远征专用事务循环：稳定观察目标页面后才提交状态。"""

    _STATE_TIMEOUT_SECONDS = 45

    def __init__(
        self,
        machine: ExpeditionStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        now: Callable[[], float] | None = None,
        recovery: Callable[[], None] | None = None,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        self.machine = machine
        self.runtime = runtime
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.now = now or runtime.now
        self.recovery_gate = recovery_gate or RecoveryGate(recovery)
        self.recovery = self.recovery_gate.recover if recovery is not None else None
        self.unknown_screen_wake = UnknownScreenWake(
            runtime, recovery_gate=self.recovery_gate
        )
        self.resource_exhausted = False
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(
                mode="expedition",
                absolute_seconds=20 * 60,
                no_business_progress_seconds=20 * 60,
            ),
            now=self.now,
            sleep=sleep,
        )

    def _run_committed_battle(self, *, cycle: int) -> None:
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = ExpeditionState.BATTLE
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"远征战斗出现意外结果：{outcome.value}")
        self.machine.state = ExpeditionState.RESULT

    def _save_frame(self, screen: np.ndarray) -> None:
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_current_frame(screen)

    def _diagnostic(self, label: str, screen: np.ndarray):
        if self.runtime.diagnostic_dir is None:
            return "not-configured"
        return self.runtime.save_diagnostic(label, screen)

    def _execute_transition(self, action: ExpeditionAction) -> None:
        if action.source_state is None or not action.target_states:
            raise RuntimeError(f"远征动作[{action.name}]缺少来源/目标合同")
        attempts = 1
        source_stable = StableObservation(required=2)
        target_stable = StableObservation(required=2)
        source_left = False
        started = self.now()
        self.runtime.log(
            f"模式=远征 当前页面={action.source_page} 判断依据={action.reason}"
        )
        self.runtime.log(
            f"模式=远征 执行点击 动作={action.name} 尝试={attempts}/4 "
            f"坐标={action.point} 目标页面={'/'.join(action.target_pages)}"
        )
        self.runtime.click(action.point, action.name)
        while self.now() - started < self._STATE_TIMEOUT_SECONDS:
            self.sleep(self.poll_seconds)
            screen = self.runtime.capture()
            self._save_frame(screen)
            target = self.machine.action_target_state(screen, action)
            if target_stable.update(target.value if target is not None else "other") and target is not None:
                self.machine.commit(action, target)
                self.runtime.log(
                    f"模式=远征 转场确认 动作={action.name} "
                    f"从={action.source_page} 到={state_label(target)} 目标连续=2"
                )
                return
            source_visible = self.machine.action_source_visible(screen, action)
            if source_stable.update("source" if source_visible else "other") and source_visible:
                if source_left:
                    continue
                if attempts < 4:
                    attempts += 1
                    self.runtime.log(
                        f"模式=远征 转场重试 动作={action.name} 来源={action.source_page}仍在 "
                        f"尝试={attempts}/4 坐标={action.point}"
                    )
                    self.runtime.click(action.point, action.name)
                    source_stable.reset()
                    continue
            elif not source_visible and not source_left:
                source_left = True
                self.runtime.log(
                    f"模式=远征 等待转场 动作={action.name} 来源={action.source_page}已离开 "
                    f"目标={'/'.join(action.target_pages)}待稳定"
                )
        diagnostic = self._diagnostic(f"no_transition_{action.name}", screen)
        raise RuntimeError(
            f"动作[{action.name}]未稳定进入[{'/'.join(action.target_pages)}]；"
            f"已保存诊断 {diagnostic}"
        )

    def run(self, max_cycles: int | None = None) -> int:
        if self.runtime.dry_run:
            screen = self.runtime.capture()
            action = self.machine.next_action(screen)
            if action is not None:
                self.runtime.log(f"模式=远征 动作={action.name} 状态=诊断")
            return self.machine.completed_cycles
        stable = StableObservation(required=2)
        state_started = self.now()
        recovered = False
        while max_cycles is None or self.machine.completed_cycles < max_cycles:
            screen = self.runtime.capture()
            self._save_frame(screen)
            state_before = self.machine.state
            cycles_before = self.machine.completed_cycles
            try:
                preview, _ = self.machine.preview(screen)
                signature = preview.name if preview is not None else f"settled:{state_before.value}"
                if not stable.update(signature):
                    self.sleep(self.poll_seconds)
                    continue
                action = self.machine.next_action(screen)
                stable.reset()
            except StaminaExhausted as error:
                self.resource_exhausted = True
                self.runtime.log(f"模式=远征 停止=通缉传单耗尽 详情={error}")
                return self.machine.completed_cycles
            except UnrecognizedScreen as error:
                wake = self.unknown_screen_wake.handle(
                    screen, context=f"远征:{state_label(state_before)}"
                )
                if wake in {UnknownWakeResult.WAITING, UnknownWakeResult.CLICKED}:
                    self.sleep(self.poll_seconds)
                    continue
                if self.now() - state_started < self._STATE_TIMEOUT_SECONDS:
                    self.sleep(self.poll_seconds)
                    continue
                raise RuntimeError(f"远征未知页面：{error}") from error
            if action is None:
                if self.machine.state is ExpeditionState.BATTLE:
                    self._run_committed_battle(cycle=self.machine.completed_cycles + 1)
                    state_started = self.now()
                    continue
                self.sleep(self.poll_seconds)
                continue
            self._execute_transition(action)
            state_started = self.now()
            if action.name == "battle-start":
                self._run_committed_battle(cycle=self.machine.completed_cycles + 1)
                state_started = self.now()
            if self.machine.completed_cycles > cycles_before:
                recovered = False
                self.runtime.log(f"模式=远征 业务完成 cycles={self.machine.completed_cycles}")
                if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
                    return self.machine.completed_cycles
            if self.now() - state_started >= self._STATE_TIMEOUT_SECONDS and self.recovery and not recovered:
                recovered = True
                self.recovery()
                self.machine.state = ExpeditionState.HOME
        return self.machine.completed_cycles
