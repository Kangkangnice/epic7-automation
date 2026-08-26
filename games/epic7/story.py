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
    observe_battle_controls,
)
from auto_game_unified.games.epic7.pre_battle import (
    PreBattleMode,
    QuickBattleDetector,
    load_simulator_quick_battle_detector,
    observe_pre_battle,
)
# 友情点数弹窗识别已迁至全局弹窗守卫（global_popups），此处保留导出以兼容旧引用。
from auto_game_unified.games.epic7.global_popups import (
    find_friendship_points_popup_close,
)
from auto_game_unified.games.epic7.stamina import (
    STAMINA_REGIONS,
    load_stamina_templates,
    next_stamina_decision,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


_WATCH_STORY_REFERENCE_SIZE = (1982, 1132)
_WATCH_STORY_REGION = (1450, 930, 470, 202)
_STORY_SKIP_REGION = (1700, 0, 240, 200)
_STORY_SKIP_CONFIRM_REGION = (850, 600, 600, 300)
_BATTLE_GUIDE_TITLE_REGION = (780, 250, 420, 180)
_BATTLE_GUIDE_DONT_SHOW_REGION = (1080, 760, 420, 190)


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


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    StoryState.STAGE: "关卡入口",
    StoryState.TEAM: "队伍选择",
    StoryState.WAIT_SKIP_CONFIRM: "跳过确认",
    StoryState.WAIT_BATTLE: "等待战斗",
    StoryState.ACTIVE: "战斗进行中",
    StoryState.WAIT_RESULTS: "等待结算",
    StoryState.WAIT_COMPLETE: "等待通关",
    StoryState.WAIT_NEXT_STAGE: "等待下一关",
}


def state_label(state: StoryState) -> str:
    return STATE_LABELS.get(state, state.value)


@dataclass(frozen=True)
class StoryAction:
    name: str
    point: tuple[int, int]


@dataclass(frozen=True)
class StoryTemplates:
    battle_guide_title: np.ndarray
    battle_guide_dont_show: np.ndarray
    watch_story: np.ndarray
    prepare_battle: np.ndarray
    prepare_battle_updated: np.ndarray
    select_team: np.ndarray
    start_mission: np.ndarray
    skip: np.ndarray
    skip_confirm: np.ndarray
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
    quick_battle: QuickBattleDetector | None = None


def build_story_templates(template_dir: Path) -> StoryTemplates:
    return StoryTemplates(
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
        auto_off=load_template(str(template_dir / "auto_off.png")),
        auto_on=load_template(str(template_dir / "auto_on.png")),
        reward=load_template(str(template_dir / "reward.png")),
        clear=load_template(str(template_dir / "clear.png")),
        results_confirm=load_template(str(template_dir / "results_confirm.png")),
        complete=load_template(str(template_dir / "complete.png")),
        bonus_reward=load_template(str(template_dir / "bonus_reward.png")),
        next_stage=load_template(str(template_dir / "next_stage.png")),
        **asdict(load_stamina_templates(template_dir)),
        quick_battle=load_simulator_quick_battle_detector(template_dir),
    )


class StoryStateMachine:
    """Story workflow in the game window's local coordinate space."""

    _THRESHOLDS = {
        "skip": 0.75,
    }
    _REFERENCE_SIZE = (1982, 1132)
    _REGIONS = {
        "watch_story": (1450, 930, 470, 202),
        "select_team": (1400, 930, 520, 202),
        "start_mission": (1400, 930, 520, 202),
        "skip": (1700, 0, 240, 200),
        "skip_confirm": (850, 600, 600, 300),
        "auto_off": (1550, 0, 300, 200),
        "auto_on": (1550, 0, 300, 200),
        "reward": (700, 400, 650, 400),
        "clear": (500, 150, 900, 700),
        "results_confirm": (1500, 930, 420, 202),
        "complete": (650, 150, 700, 700),
        "bonus_reward": (350, 150, 1200, 850),
        "next_stage": (1450, 930, 470, 202),
        **STAMINA_REGIONS,
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
        start = self._locate(screen, "start_mission")
        pre_battle = observe_pre_battle(
            self.templates.quick_battle,
            screen,
            normal_start=start,
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
        if allowed_action is None:
            if (
                pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
            ):
                allowed_action = (
                    "switch-to-normal-battle",
                    pre_battle.switch_point,
                )
            elif pre_battle.mode is PreBattleMode.NORMAL and start is not None:
                allowed_action = ("start_mission", start.center)
        progressing = (
            auto_state is AutoBattleState.AUTO
            and meaningful_change(previous_screen, screen)
        )
        return BattleObservation(
            pre_battle_visible=pre_battle.mode is not PreBattleMode.UNKNOWN,
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

    def _handle_stamina(self, screen: np.ndarray) -> Optional[StoryAction]:
        """体力不足时用生命之叶补充；达到上限后抛 StaminaExhausted 干净收尾。

        与狗粮/辅助自动共用两段式决策（stamina.py），主线独有：
        补充次数上限、确认按钮未渲染时等待（返回 None）而非报错。
        """
        if self.templates.stamina_popup is None:
            return None
        if self._locate(screen, "stamina_popup") is None:
            self._stamina_material_clicked = False
            return None
        if (
            self.stamina_replenish_max is not None
            and self.stamina_replenished >= self.stamina_replenish_max
        ):
            raise StaminaExhausted(
                f"生命之叶已补充{self.stamina_replenished}次"
                f"（上限{self.stamina_replenish_max}次），停止运行"
            )
        if (
            self.templates.stamina_material is None
            or self.templates.stamina_confirm is None
        ):
            raise RuntimeError("体力弹窗已出现但缺少生命之叶补充模板")
        decision = next_stamina_decision(
            screen, self._locate, material_clicked=self._stamina_material_clicked
        )
        if decision.status == "material":
            self._stamina_material_clicked = True
            return StoryAction("stamina_material", decision.point)
        if decision.status == "waiting":
            return None
        self._stamina_material_clicked = False
        self.stamina_replenished += 1
        return StoryAction("stamina_confirm", decision.point)

    def next_action(self, screen: np.ndarray) -> Optional[StoryAction]:
        stamina_action = self._handle_stamina(screen)
        if stamina_action is not None:
            return stamina_action

        if self.state is StoryState.TEAM:
            pre_battle = observe_pre_battle(
                self.templates.quick_battle,
                screen,
                normal_start=self._locate(screen, "start_mission"),
            )
            if (
                pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
            ):
                self.state = StoryState.WAIT_BATTLE
                self.auto_enabled = False
                self.auto_click_attempted = False
                self.battle_controls = BattleControls.TRANSITION
                return StoryAction("start_mission", pre_battle.switch_point)

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
            f"主线画面[{state_label(self.state)}]未识别"
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


class StoryRunner(ModeRunnerBase):
    """主线短轮询、失败即停 Runner（主循环协议见 ModeRunnerBase）。"""

    _MODE_LABEL = "主线"
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
    _BATTLE_ENTRY_ACTION = "start_mission"

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
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery=recovery,
            recovery_gate=recovery_gate,
        )
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(mode="story", mode_label="主线"),
            now=self.now,
            sleep=sleep,
        )

    def _state_label(self, state: StoryState) -> str:
        return state_label(state)

    def _apply_recovery_state(self) -> None:
        self.machine.state = StoryState.STAGE
        self.machine.auto_enabled = False

    def _run_committed_battle(self, *, cycle: int) -> None:
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = StoryState.WAIT_BATTLE
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"主线战斗出现意外结果：{outcome.value}")
        self.machine.state = StoryState.WAIT_RESULTS

    def _log_cycle_completed(self) -> None:
        self.runtime.log(
            f"模式=主线 状态=完成一轮 累计完成={self.machine.completed_cycles}轮"
        )

    def _log_state_timeout(self, state: StoryState, elapsed: float, diagnostic) -> None:
        self.runtime.log(
            f"模式=主线 页面={state_label(state)} "
            f"状态=超时无进展 已耗时={elapsed:.1f}秒 诊断={diagnostic}"
        )

    def _log_settled_timeout(self, state: StoryState, diagnostic) -> None:
        self.runtime.log(
            f"模式=主线 页面={state_label(state)} "
            f"状态=等待超时无进展 诊断={diagnostic}"
        )

