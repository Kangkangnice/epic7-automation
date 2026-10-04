"""Fail-closed automation for Epic Seven expeditions."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    valid_game_frame,
)
from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.runtime import StaminaExhausted
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
from auto_game_unified.games.epic7.resume_probe import ResumePoint
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.transactional_runner_base import (
    TransactionalRunnerBase,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile
from auto_game_unified.games.epic7.template_paths import is_template_root
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
    """No card-level wanted-poster departure action remains.

    ``stop_label`` 要自己给：继承来的是 ``StaminaExhausted`` 的「生命之叶耗尽」，
    但远征缺的是**通缉传单** —— 主循环统一把 ``停止=`` 后面的文案取异常自带的那一个
    （见 ``core.runtime.ResourceExhausted`` 的约定），写错东西会被日志带偏。
    """

    stop_label = "通缉传单耗尽"


@dataclass(frozen=True)
class ExpeditionAction(RouteAction):
    """远征的一个动作。

    公共字段见 ``route_action.RouteAction``；``source_state`` / ``target_states`` 是
    事务型主循环（``TransactionalRunnerBase._execute_transition``）认的那一份契约。
    """

    source_state: ExpeditionState | None = None
    target_states: tuple[ExpeditionState, ...] = ()


@dataclass(frozen=True)
class ExpeditionTemplates:
    home: np.ndarray
    poster_embark: np.ndarray
    # ⚠️ 不是 Optional：这是「传单用完该收工」的判据，缺了整条路线会在空列表上
    # 空等到超时（2026-09-19~10-03 实测 6 次）。缺文件必须在加载期就炸。
    empty_posters: np.ndarray
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
        empty_posters=load("empty_posters"),
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

    # 允许为 ``None`` 的模板 —— **只放这一条白名单里的**，其余一律视为配置错误。
    #
    # 背景：`_locate()` 原本对**任何** ``None`` 模板都静默返回 ``None``，于是
    # 「模板文件缺失」和「画面上没有这个控件」在代码里长得一模一样 —— 判据悄悄
    # 失效，没人看得出来。远征就栽在这上面：`empty_posters` 文件不存在，收工判据
    # 整个失灵，空等超时 6 次（2026-09-19~10-03）才被发现。
    #
    # ⚠️ 本集合必须与 `evidence/expedition.py` 的 `_OPTIONAL_TEMPLATES` **逐字一致**
    # （`test_expedition_evidence` 里钉住）。目前只剩 `defeated_confirm`：它还没有
    # 真机图，拿到图后从两处一起删掉，别只改一边。
    _OPTIONAL_TEMPLATES = frozenset({"defeated_confirm"})

    def __init__(
        self,
        templates: ExpeditionTemplates | Path,
        *,
        initial_state: ExpeditionState = ExpeditionState.HOME,
    ) -> None:
        self.templates = (
            build_expedition_templates(templates)
            if is_template_root(templates)
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
        # 「接力」进来的落点；None = 本轮是正常从远征主页开始的。
        self.resumed_from: Optional[ExpeditionState] = None

    def resume_from(self, state: ExpeditionState) -> None:
        """拨到用户停下的那一步，原样接管进度继续往下跑。

        远征的 ``next_action`` 是**纯状态驱动**的（按 ``self.state`` 分派，不像主线那样
        从锚点自己推页面），所以接力必须把状态拨准，否则第一帧就会走到 ``_required``
        失败或点错按钮。

        ``auto_click_attempted`` 必须复位：接力进来的这一局不是本进程点开的，
        带着上一局的账本会让「开自动战斗」这一次点击被跳过。
        """
        self.state = state
        self.resumed_from = state
        self.auto_click_attempted = False
        self._confirmed_page = ""

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        template = getattr(self.templates, name)
        if template is None:
            # 只有白名单里的模板才允许缺席；其余是**配置错误**，必须出声。
            # 静默返回 None 会把「模板没了」伪装成「画面上没这个控件」。
            if name not in self._OPTIONAL_TEMPLATES:
                raise RuntimeError(
                    f"模板 {name} 缺失且未登记为可选：判据会静默失效。"
                    f"要么补上模板文件，要么把它加进 "
                    f"{type(self).__name__}._OPTIONAL_TEMPLATES 并说明理由"
                )
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
            if self._locate(screen, "battle_start") is not None:
                return True
            # 2026-09-18：队伍页有「快速战斗」变体，普通「战斗开始」会被宽按钮盖掉
            # （全库夹具上 battle_start 只剩 0.13），只剩右侧切换控件是排他证据
            # （快速页 0.9883~1.0000，非快速页最高 0.5577）。不认这一页，TEAM 就永远
            # 进不去，下面已有的「切回普通战斗」分支也就永远走不到 —— 死等到超时。
            return self.is_quick_battle_team_page(screen)
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

    def is_quick_battle_team_page(self, screen: np.ndarray) -> bool:
        """队伍页是否处于「快速战斗」变体。

        只看切换控件：`normal_start=None` 让共享分类器退化成「切换控件单独成立即判
        QUICK」（见 `evidence/pre_battle.py`），不引入新阈值。探针
        `runtime_logs/_audit_exp_quick.py` 实测：197 张夹具里只有 2 张过阈
        （0.9883 / 1.0000），其余最高 0.5577，零误报。
        """
        observation = observe_pre_battle(
            self.templates.quick_battle,
            screen,
            normal_start=None,
        )
        return observation.mode is PreBattleMode.QUICK

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
        auto_score = "无" if auto is None else f"{auto.score:.4f}"
        auto_evidence = f"布局={controls.value} 自动关图标={auto_score}"
        # 「右上角关自动图标 ⇒ 判定为手动」：按钮布局判成 transition（看不出长相）
        # 时靠这个图标兜底 —— 否则那一帧会停在「未知」，而「未知」按安全设计是
        # 不许点自动的，战斗就会干等到超时。图标认不到就不覆盖上面的布局判定。
        if auto is not None:
            auto_state = AutoBattleState.MANUAL
            auto_evidence += " 来源=右上角自动关闭图标"
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
            auto_evidence=auto_evidence,
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
                # 2026-09-18：这一下点击**可能直接落到战斗页**（队伍已保存时游戏跳过队伍
                # 选择），实测 19:42/20:00/20:16/09-17 23:39 四次崩溃的收尾帧全是局内，
                # 而 `battle_scene_visible=True` 在四帧上都成立——判据认得出，是契约漏了
                # 「战斗中」，于是白等 45 秒队伍页。补进契约即可，不加新锚点、不放宽阈值。
                target_states=(ExpeditionState.TEAM, ExpeditionState.BATTLE),
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


# 导航链上可以接力的三页（= `navigation.page_label()` 里的名字）。
# 远征的导航是一条四级链：大厅 → 战斗菜单 → 赛季菜单 → 远征主页。
# 站在其中任何一级都能接着往下走，所以三页都要开放接力，不能只开放终点。
EXPEDITION_BATTLE_MENU_PAGE = "battle_menu"
EXPEDITION_SEASON_PAGE = "season_menu"
EXPEDITION_ENTRY_PAGE = "expedition_home"
EXPEDITION_RESUME_PAGES = frozenset(
    {
        EXPEDITION_BATTLE_MENU_PAGE,
        EXPEDITION_SEASON_PAGE,
        EXPEDITION_ENTRY_PAGE,
    }
)





# 「接力」探测顺序 —— **顺序即优先级**，不能改。远征的 `is_in_state` 判据互相包含得
# 比较厉害（下面每条都有夹具实测撑腰），顺序排错就会拨到错状态：
#
# - **HOME 必须排在 RETURNING 前面**：RETURNING 的判据第一项就是「远征主页可见」，
#   反过来不成立。先判 RETURNING 会把远征主页拨成 RETURNING，而它的动作要求
#   `expedition_list`，在主页上找不到 → 直接抛错。
# - **DIFFICULTY_CONFIRM 排在 DIFFICULTY 前面**：`difficulty_3_selected.png` 两个判据
#   同时成立（标题+第3难度+确认按钮都在），项目里 `test_recorded_current_client_pages_match_their_states`
#   把它登记为 DIFFICULTY_CONFIRM，这里跟着走。
# - **OUTCOME 必须排在 READY 前面**：`outcome_public*.png`（公开招募结果）上
#   `prepare_battle` 竟然也是可见的，所以 READY 判据同样成立。先判 READY 就会去点
#   「准备战斗」，把**还没领取的公开招募白扔掉**。先判 OUTCOME 才会点公开招募。
# - **READY 排在 RECRUIT_RETURN 前面**：`ready.png` 与 `recruited.png` 是同一张营火页
#   （点开图看，两张只差左侧排名面板的内容），锚点集合完全一样
#   （都是 prepare_battle + public_recruited + back），机器**没法区分**这两页。
#   跟着竞技场那条「停在准备战斗就直接打、不退回重选」的口径，统一按 READY 落点：
#   点准备战斗直接进队伍选择开打。认错的代价也只是多打一局，不会丢奖励、不会按错 Back。
# - 其余各项在夹具上互斥，相对顺序不影响结果。
_EXPEDITION_RESUME_ORDER: tuple[ExpeditionState, ...] = (
    ExpeditionState.HOME,
    ExpeditionState.RETURNING,
    ExpeditionState.POSTERS,
    ExpeditionState.DIFFICULTY_CONFIRM,
    ExpeditionState.DIFFICULTY,
    ExpeditionState.OUTCOME,
    ExpeditionState.RECRUIT_CONFIRM,
    ExpeditionState.READY,
    ExpeditionState.RECRUIT_RETURN,
    ExpeditionState.TEAM,
    ExpeditionState.RESULT,
    ExpeditionState.BATTLE,
)


def detect_resume_point(
    machine: "ExpeditionStateMachine",
    screen: np.ndarray,
    *,
    observed_page: Optional[str] = None,
) -> Optional[ResumePoint]:
    """远征开局接力：认出用户停在远征一环里的哪一页。

    识别不到返回 None，调用方回退到「回大厅 → 从战斗菜单重新导航」（失败关闭，
    行为与加这个功能之前一致）。

    ``observed_page`` 传导航器认出来的页面名（``Epic7Navigator.observe().name``）。
    战斗菜单 / 赛季菜单这两页**只有导航器认得出来**（它们不在远征状态机里），
    所以这个参数对这两页是必需的。
    """
    if observed_page in (
        EXPEDITION_BATTLE_MENU_PAGE,
        EXPEDITION_SEASON_PAGE,
    ):
        return ResumePoint(
            "战斗菜单" if observed_page == EXPEDITION_BATTLE_MENU_PAGE else "赛季菜单",
            None,
            observed_page,
        )
    if battle_scene_visible(screen):
        # 已经在打的那一局最先接手。`ExpeditionRunner` 本来就有
        # 「无动作 + 状态是 BATTLE → 交战斗监督」那一支，所以只要把状态拨对就能接上。
        return ResumePoint("战斗中", ExpeditionState.BATTLE)
    for state in _EXPEDITION_RESUME_ORDER:
        if not machine.is_in_state(screen, state):
            continue
        entry = (
            EXPEDITION_ENTRY_PAGE if state is ExpeditionState.HOME else None
        )
        return ResumePoint(state_label(state), state, entry)
    return None


class ExpeditionRunner(TransactionalRunnerBase):
    """远征 Runner：**事务型主循环**（见 ``transactional_runner_base``）。

    ⚠️ 2026-09-26 之前，本类是「自带独立主循环」的裸定义（``super()`` 0 次）——
    与 ``ArenaRunner`` **各抄了一份**主循环、转场验收、失败诊断、收尾回首页、
    战斗看护接线（约 750 行重复），而且两份已经开始各改各的（超时口径
    40/40/60/60/120/45 对 45 秒一刀切、失败诊断函数两个名字）。
    现在这些都来自 ``TransactionalRunnerBase``，本类只剩**远征自己的业务规则**。

    ⚠️ 收尾回首页的注入契约**没变**：``finish_home`` 仍是实例属性
    （基类 ``__init__`` 里赋值），由 ``main._install_finish_home`` 注入。
    ⚠️ 它**不是** ``ModeRunnerBase`` 的子类 —— 那是另一套主循环，理由见基类模块
    docstring 与 ``modes.TRANSITION_EXEMPT`` / ``CONCLUSION_GATE_DECLARATION`` 里的表态。
    """

    _MODE_LABEL = "远征"
    # 一个 45 秒走天下（不分页面档）。
    _STATE_TIMEOUT_SECONDS = 45
    # 状态 → 状态机里的落点，供基类判「战斗有没有打起来」「有没有打到结算页」。
    _BATTLE_STATE = ExpeditionState.BATTLE
    _RESULT_STATE = ExpeditionState.RESULT
    # 停在局内、状态机又没有别的活要干 ⇒ 直接把这一局交给战斗监督等结算。
    _SETTLED_BATTLE_STATE = ExpeditionState.BATTLE
    # 转场确认**落到战斗页** ⇒ 交战斗监督。
    # ⚠️ 为什么要认两个动作名、而不是只认 ``battle-start``：``prepare-battle`` 也可能
    # **直接**落到战斗页（游戏跳过队伍选择）。漏了它会让状态卡在 BATTLE 却没人驱动，
    # 白等到状态超时再走恢复。
    _HANDOFF_AFTER_TRANSITION_ACTIONS = frozenset({"battle-start", "prepare-battle"})

    def _battle_config(self) -> BattleConfig:
        """战斗看护的两条时限按远征的实际节奏放宽到 20 分钟。

        远征一局比竞技场长得多（难度三还要算上战败重来），用 ``BattleConfig``
        的默认值会在打到一半时被判「无业务进展」而收手。
        """
        return BattleConfig(
            mode="expedition",
            absolute_seconds=20 * 60,
            no_business_progress_seconds=20 * 60,
        )

    def _state_label(self, state: ExpeditionState) -> str:
        """用远征自己的中文页面名，别退回枚举的 ``value``（日志和诊断都靠它）。"""
        return state_label(state)
