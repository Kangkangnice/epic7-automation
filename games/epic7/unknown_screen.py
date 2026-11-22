from enum import Enum

import numpy as np

from auto_game_unified.core.battle_supervisor import valid_game_frame
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
)


_CANVAS_SIZE = (1132, 1982)
_RENDER_TOP = 52
_RENDER_RIGHT = 1920


# ---- 大厅观赏模式（2026-11-22）----------------------------------------------
#
# 用户实跑反馈：大厅静置几秒会切入「观赏模式」—— 整屏换成当前英雄的立绘动效，
# 左右菜单、底部图标、顶部 HUD **全部消失**。此时导航层所有大厅锚点同时归零，
# ``observe()`` 报 ``unknown``（真机帧实测 confidence=0.0000），等大厅那一步会一路
# 干等到 90 帧上限，报「导航开始前应处于[大厅]」。
#
# 关键口径：**不认背景长什么样**。用户同一台机器上换英雄/换皮肤，观赏模式的背景
# 就换一张 ⇒ 任何「认背景」的模板明天就会失效。观赏模式的可证伪特征是三件事叠加：
#
#   1. 是有效游戏帧（``valid_game_frame``）—— 排除黑屏 / 加载；
#   2. 画面还在动（``meaningful_change``）—— 真机相邻帧平均差 14~15，排除静止页；
#   3. 不是战斗画面（``battle_scene_visible`` 为假）—— 排除局内动画这种同样「在动、
#      认不出」的页。
#
# 再叠加**调用方给的两条上下文**：只在「等大厅 / 回家」路径、且 ``observe()`` 已经
# 稳定报 ``unknown``（所有已知页都不认）。这五条同时成立才可能是观赏模式 —— 少一条
# 都不点。点与不点的分界不在阈值上，而在「该出现的大厅 UI 一个都没有」这个否定证据。
#
# ⚠️ 与 2026-09-26 删掉的「认不出就点屏幕中央」的区别：那版没有任何判据、任何上下文，
# 对着赛季卡片这种「认不出但能点」的页会误开卡片；本版只在等大厅的 unknown 分支、
# 三重画面判据全过时才点，且点完必须重新认出大厅才算成功（见 LobbySpectatorWake）。


def is_lobby_spectator(
    screen: np.ndarray, previous: np.ndarray | None = None
) -> bool:
    """这一帧像不像「大厅观赏模式」——只做画面级判断，不认具体背景。

    ``previous`` 是相邻上一帧，用来确认立绘确实在动；首次调用传 None 时返回 False，
    等下一帧有了对比再说（宁可晚一帧，不在单帧上下结论）。
    """
    if not valid_game_frame(screen):
        return False
    if battle_scene_visible(screen):
        return False
    return meaningful_change(previous, screen)


def _valid_render_canvas(screen: np.ndarray) -> bool:
    if screen.shape[:2] != _CANVAS_SIZE:
        return False
    return (
        float(np.mean(screen[:_RENDER_TOP])) <= 2.0
        and float(np.mean(screen[:, _RENDER_RIGHT:])) <= 2.0
    )


class UnrecognizedScreen(RuntimeError):
    """The current mode cannot recognize the page required by its state."""


class UnknownWakeResult(Enum):
    WAITING = "waiting"
    SKIPPED = "skipped"
    EXHAUSTED = "exhausted"
    # ⚠️ 这里原来有一个 ``CLICKED``（认不出画面就去点屏幕中央），2026-09-26 删掉了。
    # 用户当场抓包的现象就是「眼睛瞎了一直点中间」—— 点中央既没有判据、也常常
    # 落在列表空白处，纯粹是瞎猜。认不出画面现在只等、到点交给上层超时收尾。


class SpectatorWakeResult(Enum):
    SKIPPED = "skipped"     # 上下文不对 / 干跑 / 锁定 / 判据没过 —— 不点
    WAITING = "waiting"     # 还在攒「确实在动」的两帧证据，下一帧再看
    CLICKED = "clicked"     # 刚点了一次中心，交还调用方重新认页面
    EXHAUSTED = "exhausted"  # 点满次数仍未恢复 UI —— 不再点，交上层超时收尾


class LobbySpectatorWake:
    """大厅观赏模式的**有界**唤醒：点一次中心安全区，让它退出观赏模式恢复 UI。

    只在**等大厅**这条上下文里启用（``context`` 必须是调用方约定的字面量），
    其余一律 ``SKIPPED``。与 2026-09-26 删掉的那版「认不出就点中间」的根本区别：
    - 那版：任何 unknown 页都点、无判据、最多 4 次 —— 会对着赛季卡片误开入口；
    - 这版：只在等大厅的 unknown 分支，且 ``is_lobby_spectator`` 三条件全过才点；

    ⚠️ **次数与远征营地待机唤醒一致 = 2 次**（``EXTENDING.md``：「萤火待机只点中央
    安全区域，验证真正 UI 出现，最多两次」）。点完不在这里等结果 —— 把帧交还调用方
    重新 ``observe()``：认出大厅就说明这一下生效了；仍是 unknown 才会再来一次。
    这样「点完是否真的恢复 UI」由调用方的正常识别链路验收，本类不另造判据。
    """

    # 安全区：真机观赏模式帧上这点落在角色立绘中央、没有任何按钮；与远征唤醒
    # (1000, 600) 同一坐标。观赏模式下点任意处都会退出展示、恢复完整 UI。
    CENTER = (1000, 600)
    MAX_ATTEMPTS = 2  # 与远征 wake-campfire-ui 一致

    def __init__(
        self,
        runtime: Runtime,
        *,
        recovery_gate: RecoveryGate | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.runtime = runtime
        self.recovery_gate = recovery_gate
        self.max_attempts = max_attempts
        self.reset()

    def reset(self) -> None:
        self._context: str | None = None
        self._previous: np.ndarray | None = None
        self._attempts = 0

    def handle(self, screen: np.ndarray, *, context: str) -> SpectatorWakeResult:
        """每帧调一次；``context`` 非约定的等大厅字面量时直接跳过。"""
        if context != "等大厅":
            return SpectatorWakeResult.SKIPPED
        if context != self._context:
            self.reset()
            self._context = context

        if (
            self.runtime.dry_run
            or (self.recovery_gate is not None and self.recovery_gate.locked)
            or not _valid_render_canvas(screen)
        ):
            return SpectatorWakeResult.SKIPPED

        if self._attempts >= self.max_attempts:
            return SpectatorWakeResult.EXHAUSTED

        is_spectator = is_lobby_spectator(screen, self._previous)
        self._previous = screen.copy()
        if not is_spectator:
            return SpectatorWakeResult.WAITING

        self._attempts += 1
        # 诊断目录未配置时不能让兜底点击一起失败（与 UnknownScreenWake 同口径）。
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_diagnostic(
                f"lobby_spectator_before_click_{self._attempts}", screen
            )
        self.runtime.click(self.CENTER, "唤醒大厅观赏模式")
        self.runtime.log(
            f"页面=大厅观赏模式 状态=点击中心安全区退出展示 "
            f"次数={self._attempts}/{self.max_attempts} 坐标={self.CENTER} "
            "说明=点完将重新认页面，认出大厅才算成功"
        )
        return SpectatorWakeResult.CLICKED


class UnknownScreenWake:
    """认不出的静止画面：**只观察、不动手**，把结论交还上层。

    ⚠️ 2026-09-26 起不再「点屏幕中央试着唤醒」了（用户抓包的「眼睛瞎了一直点中间」）：
    点中央没有判据、常常落在列表空白处，是瞎猜不是处理。现在只做三件事 ——
    ① 画面还在变 ⇒ WAITING 等它稳定；② 变化超过 ``max_waiting_frames`` ⇒ 按「带动画的
    未知页」交还上层；③ 画面静止但仍认不出 ⇒ 记一张诊断图 + 一条日志，然后交还上层
    （由上层按超时收尾，回家由 ``main`` 负责）。
    """

    def __init__(
        self,
        runtime: Runtime,
        *,
        recovery_gate: RecoveryGate | None = None,
        max_waiting_frames: int = 15,
    ) -> None:
        self.runtime = runtime
        self.recovery_gate = recovery_gate
        # 带动画的页面（如英雄详情立绘）画面永远在变，若无限等待 WAITING
        # 会卡死上层循环；超过该帧数按未知画面交给上层按超时收尾。
        self.max_waiting_frames = max_waiting_frames
        self.reset()

    def reset(self) -> None:
        self._context: str | None = None
        self._previous: np.ndarray | None = None
        self._waiting_frames = 0
        self._exhausted_reported = False

    def handle(self, screen: np.ndarray, *, context: str) -> UnknownWakeResult:
        if context != self._context:
            self.reset()
            self._context = context

        if (
            self.runtime.dry_run
            or (self.recovery_gate is not None and self.recovery_gate.locked)
            or not _valid_render_canvas(screen)
            or not valid_game_frame(screen)
            or observe_battle_controls(screen) is not BattleControls.TRANSITION
        ):
            self._previous = None
            self._waiting_frames = 0
            return UnknownWakeResult.SKIPPED

        if self._previous is None:
            self._previous = screen.copy()
            return self._waiting(screen)

        if self._previous.shape != screen.shape or meaningful_change(
            self._previous, screen
        ):
            self._previous = screen.copy()
            return self._waiting(screen)

        # 画面静止了、还是认不出这是哪一页 ⇒ **不点任何地方**，直接交还上层
        # （上层会按「这一页认不出来」超时收尾，回家由 main 负责）。
        # ⚠️ 2026-09-26：以前这里会去点屏幕中央最多 4 次，已删，理由见
        # ``UnknownWakeResult`` 与类 docstring。
        # 刻意**不清空账本**：一旦判定「认不出」就一直保持 EXHAUSTED，否则下一帧又会
        # 从头记基准 ⇒ 表现为 WAITING / EXHAUSTED 来回横跳。上层换页时会调 ``reset()``。
        if not self._exhausted_reported:
            self._save_diagnostic("unknown_screen_unresolved", screen)
            self.runtime.log(
                f"页面={context} 状态=画面已静止但仍认不出是哪一页 "
                "动作=不点任何地方，交给上层超时收尾"
            )
            self._exhausted_reported = True
        return UnknownWakeResult.EXHAUSTED

    def _waiting(self, screen: np.ndarray) -> UnknownWakeResult:
        """画面仍在变化：先等待稳定，超过上限则放弃等待（页面本身带动画）。

        EXHAUSTED 后保持状态不重置，让上层一直报 EXHAUSTED，由上层按超时收尾。
        """
        self._waiting_frames += 1
        if self._waiting_frames < self.max_waiting_frames:
            return UnknownWakeResult.WAITING
        if not self._exhausted_reported:
            self._save_diagnostic("unknown_animated_page", screen)
            self.runtime.log(
                f"页面={self._context} 画面持续变化超过{self.max_waiting_frames}帧"
                "=按未知画面交给上层按超时收尾"
            )
            self._exhausted_reported = True
        return UnknownWakeResult.EXHAUSTED

    def _save_diagnostic(self, label: str, screen: np.ndarray) -> None:
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_diagnostic(label, screen)
