# -*- coding: utf-8 -*-
"""成就领取（2026-11-08，**PC 端首条路线**）。

## 业务闭环（用户 2026-11-08 口述，本机实跑逐步核对）

```
快捷菜单 → 「成就」图标（第 4 排第 1 个，红点 + 数字代表有待领）
成就页（右栏 5 个分类，**只处理前 4 个**；第 5 个要解锁、领取形式也不同）
  ├ 每个分类：右下「全部领取」变绿 ⇒ 点它 ⇒ 弹「获得成就奖励」⇒ 点「点击关闭」
  │   └ 领完可能**还有**（一个成就给 10 个、另一个给 20 个，一轮一轮来）⇒ 循环到按钮转灰
  └ 该分类按钮转灰后：若左下冒出「持续效果上升」⇒ 点它 ⇒ 过剧情（跳过）
      ⇒ 「点击关闭」关掉升级弹窗 ⇒ 再回头看看有没有新的可领
结束标志：**4 个分类全部没有角标红点**
```

## 三条来自实测的硬约束

1. **弹窗必须排在成就页前面判**：奖励弹窗是半透明遮罩，底下成就页的
   `page_title` / `claim_all` 实测仍有 **0.9999 / 0.9987** —— 顺序反了就会对着
   被盖住的按钮点。
2. **「全部领取」的亮/灰不能用模板分**：两态形状完全相同，互相命中 0.96~1.00
   （TM_CCOEFF_NORMED 去均值归一化，不看绝对亮度）⇒ 用绿色像素占比
   （亮 0.2643 / 灰 0.0000）。
3. **效果升级的剧情直接复用主线**：用户原话「跟主线里面那种剧情一模一样的」。
   实测主线那套 `skip` / `skip_confirm` 在这条链路上 0.7464 / 0.9200 都能命中。

## 平台

模板只有 `templates/achievement/pc/`。业务代码里**没有**平台分支 —— 模拟器要跑
这条路线时补同名图即可（用户口径：先放 PC，以后模拟器要用再补）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.games.epic7.evidence.achievement import (
    CLASS_COUNT,
    CLASS_ICON_POINTS,
    CLAIM_ALL_GREEN_MIN,
    REGIONS,
    THRESHOLDS,
    build_achievement_evidence,
    claim_all_green_ratio,
    class_dots,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile
from auto_game_unified.games.epic7.resume_probe import ResumePoint, observe_page_probe
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.story import (
    find_story_skip_button,
    find_story_skip_confirm,
)
from auto_game_unified.games.epic7.template_paths import is_pc
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

REFERENCE_SIZE = (1982, 1132)


class AchievementState(Enum):
    PAGE = "page"
    REWARD_POPUP = "reward_popup"
    EFFECT_POPUP = "effect_popup"
    STORY = "story"
    STORY_CONFIRM = "story_confirm"
    DONE = "done"


STATE_LABELS = {
    AchievementState.PAGE: "成就页",
    AchievementState.REWARD_POPUP: "获得成就奖励",
    AchievementState.EFFECT_POPUP: "效果升级",
    AchievementState.STORY: "剧情播放",
    AchievementState.STORY_CONFIRM: "跳过剧情确认",
    AchievementState.DONE: "已全部领完",
}


@dataclass(frozen=True)
class AchievementTemplates:
    page_title: np.ndarray
    claim_all: np.ndarray
    effect_upgrade: np.ndarray
    reward_title: np.ndarray
    popup_close_reward: np.ndarray
    popup_close_effect: np.ndarray
    # 剧情跳过复用主线的两张图（同一控件只维护一份）。
    story_skip: np.ndarray
    story_skip_confirm: np.ndarray
    evidence: EvidenceProfile
    pc: bool = False


def build_achievement_templates(template_root: Path) -> AchievementTemplates:
    """载入全部模板。缺一张就直接抛错（判据型模板缺了会静默失效）。"""
    achievement = template_root / "achievement"
    evidence = build_achievement_evidence(achievement)
    story = template_root / "story"

    def one(key: str) -> np.ndarray:
        return load_template(str(achievement / f"{key}.png"))

    return AchievementTemplates(
        page_title=one("page_title"),
        claim_all=one("claim_all"),
        effect_upgrade=one("effect_upgrade"),
        reward_title=one("reward_title"),
        popup_close_reward=one("popup_close_reward"),
        popup_close_effect=one("popup_close_effect"),
        story_skip=load_template(str(story / "skip.png")),
        story_skip_confirm=load_template(str(story / "skip_confirm.png")),
        evidence=evidence,
        pc=is_pc(template_root),
    )


class AchievementStateMachine:
    """纯视觉决策：给一帧，回答「下一步点哪里」或「已经做完了」。"""

    _REGIONS = REGIONS
    _THRESHOLDS = THRESHOLDS
    # 切分类的最多次数。正常 4 个分类每轮点 1 次、多轮也就 8~12 次；
    # 给到 20 是留足「领完一个分类让别的分类冒出红点」这种连锁，同时仍然有界。
    _MAX_SWITCHES = 20

    def __init__(
        self,
        templates: AchievementTemplates,
        initial_state: AchievementState = AchievementState.PAGE,
    ) -> None:
        self.templates = templates
        self.state = initial_state
        # 业务进度：只在「4 个分类全都没有角标」那一刻 +1，且只加一次
        # （主循环每帧都会再问一次 next_action，不加锁会重复计数）。
        self.completed_cycles = 0
        self._finished = False
        # 「视觉确认我现在站在哪一页」，供主循环对账转场契约。
        # 只在 next_action 开头按 observe_page 的结果写，不在动作构造里写。
        self._confirmed_page = ""
        self._last_class: Optional[int] = None
        self._switches = 0
        self._claims = 0
        self._effects = 0

    # -- 判据 ---------------------------------------------------------------
    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        atom = self.templates.evidence.atom(name)
        template = getattr(self.templates, name)
        return find_template(
            screen,
            template,
            atom.threshold,
            region=atom.region,
            reference_size=atom.reference_size,
        )

    def observe_page(self, screen: np.ndarray) -> Optional[AchievementState]:
        """弹窗优先于整页 —— 半透明遮罩下整页元素照样能命中高分。"""
        if self._locate(screen, "reward_title") is not None:
            return AchievementState.REWARD_POPUP
        if self._locate(screen, "popup_close_effect") is not None:
            return AchievementState.EFFECT_POPUP
        if find_story_skip_button(screen, self.templates.story_skip) is not None:
            return AchievementState.STORY
        if find_story_skip_confirm(screen, self.templates.story_skip_confirm) is not None:
            return AchievementState.STORY_CONFIRM
        if self._locate(screen, "page_title") is not None:
            return AchievementState.PAGE
        return None

    # -- 决策 ---------------------------------------------------------------
    def preview(self, screen: np.ndarray):
        """稳定确认用的「试算」入口：算完把业务进度**原样还回去**。

        主循环每帧都会先调 ``preview`` 做两帧稳定确认；``next_action`` 会推进
        ``completed_cycles`` 和几个计数器，不还原就会把「一次点击」记成两次、
        甚至提前一帧宣布收工。
        """
        snapshot = (
            self.state,
            self.completed_cycles,
            self._finished,
            self._confirmed_page,
            self._last_class,
            self._switches,
            self._claims,
            self._effects,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self._finished,
                self._confirmed_page,
                self._last_class,
                self._switches,
                self._claims,
                self._effects,
            ) = snapshot

    def next_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        page = self.observe_page(screen)
        if page is None:
            raise UnrecognizedScreen(
                "成就画面未识别（既不是成就页，也不是奖励/升级弹窗，更不是剧情）"
            )
        self.state = page
        self._confirmed_page = STATE_LABELS[page]

        if page is AchievementState.REWARD_POPUP:
            match = self._locate(screen, "popup_close_reward")
            if match is None:  # pragma: no cover - observe_page 已经保证命中
                raise UnrecognizedScreen("奖励弹窗认到了但关闭键定位失败")
            return RouteAction(
                "close-reward-popup",
                match.center,
                source_page="获得成就奖励",
                target_pages=("成就页", "效果升级"),
                reason="关掉成就奖励弹窗",
            )

        if page is AchievementState.EFFECT_POPUP:
            match = self._locate(screen, "popup_close_effect")
            if match is None:  # pragma: no cover
                raise UnrecognizedScreen("升级弹窗认到了但关闭键定位失败")
            return RouteAction(
                "close-effect-popup",
                match.center,
                source_page="效果升级",
                target_pages=("成就页", "剧情播放"),
                reason="关掉效果升级弹窗",
            )

        if page is AchievementState.STORY:
            match = find_story_skip_button(screen, self.templates.story_skip)
            if match is None:  # pragma: no cover
                raise UnrecognizedScreen("剧情页认到了但跳过键定位失败")
            return RouteAction(
                "skip-story",
                match.center,
                source_page="剧情播放",
                target_pages=("跳过剧情确认", "效果升级"),
                reason="跳过效果升级的剧情",
            )

        if page is AchievementState.STORY_CONFIRM:
            match = find_story_skip_confirm(screen, self.templates.story_skip_confirm)
            if match is None:  # pragma: no cover
                raise UnrecognizedScreen("跳过确认认到了但确认键定位失败")
            return RouteAction(
                "confirm-skip-story",
                match.center,
                source_page="跳过剧情确认",
                target_pages=("效果升级", "成就页"),
                reason="确认跳过剧情",
            )

        return self._page_action(screen)

    def _page_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        # ① 领取优先（用户口径：先把所有红点领完，再看效果升级）
        green = claim_all_green_ratio(screen)
        if green >= CLAIM_ALL_GREEN_MIN:
            match = self._locate(screen, "claim_all")
            if match is not None:
                self._claims += 1
                return RouteAction(
                    "claim-all",
                    match.center,
                    source_page="成就页",
                    target_pages=("获得成就奖励", "成就页"),
                    in_page_evidence=f"全部领取可点（绿色占比 {green:.3f}）",
                    reason=f"当前分类还有成就可领（绿色占比 {green:.3f}）",
                )

        # ② 效果升级：按钮出现就说明有档位没领
        effect = self._locate(screen, "effect_upgrade")
        if effect is not None:
            self._effects += 1
            return RouteAction(
                "claim-effect-upgrade",
                effect.center,
                source_page="成就页",
                target_pages=("剧情播放", "效果升级", "成就页"),
                in_page_evidence=f"持续效果上升可点（{effect.score:.3f}）",
                reason="成就点数跨档，有一个效果升级没领",
            )

        # ③ 都做完就切分类；全都没有红点就是收工
        dots = class_dots(screen)
        if not dots or self._switches >= self._MAX_SWITCHES:
            self.state = AchievementState.DONE
            if not self._finished:
                self._finished = True
                self.completed_cycles += 1
            return None

        index = self._pick_class(dots)
        self._last_class = index
        self._switches += 1
        return RouteAction(
            "switch-class",
            CLASS_ICON_POINTS[index],
            source_page="成就页",
            in_page_evidence=f"第 {index + 1} 个分类仍有角标 {dots}",
            reason=f"切到第 {index + 1} 个分类（还有角标）",
        )

    def _pick_class(self, dots: dict[int, tuple[int, int]]) -> int:
        """优先挑「不是刚点过的那一个」，避免在原地反复点。

        ⚠️ 领完成就会让**别的**分类冒出红点（实测：领完分类 2 后四个分类全有角标），
        所以「优先换一个」比「从小到大」收敛得快。
        """
        candidates = [index for index in sorted(dots) if index != self._last_class]
        if candidates:
            return candidates[0]
        return sorted(dots)[0]


def state_label(state: AchievementState) -> str:
    return STATE_LABELS.get(state, str(state))


# 开局接力允许停靠的画面：成就页与三个弹窗/剧情都会接着往下跑；
# ``DONE`` 是「已经领完了」的记号，不是画面，所以不在名单里。
_RESUMABLE_STATES = frozenset(
    {
        AchievementState.PAGE,
        AchievementState.REWARD_POPUP,
        AchievementState.EFFECT_POPUP,
        AchievementState.STORY,
        AchievementState.STORY_CONFIRM,
    }
)

# 成就页在导航链上（大厅 → 快捷菜单 → 成就页），停在它上面时把 ``entry``
# 交还给导航，能省掉「回大厅 → 再走一遍快捷菜单」那一趟。
ACHIEVEMENT_PAGE = "achievement"


def detect_achievement_resume_point(
    machine: "AchievementStateMachine",
    screen: np.ndarray,
) -> Optional[ResumePoint]:
    """成就领取开局接力：停在成就页或任一弹窗上都就地接管。

    **判据与运行期同源** —— 直接调状态机自己的 ``observe_page``，不另定阈值、
    不加新锚点（项目硬要求，见 ``docs/TRANSITION_CONTRACTS.md`` 接力契约）。

    **不拨状态**：本状态机每帧都从画面重判页面，拨了下一帧就被覆盖，
    留着只会制造「日志说拨到了 A、实际画面是 B」的假象。
    """
    return observe_page_probe(
        machine,
        screen,
        resumable=_RESUMABLE_STATES,
        label=state_label,
        entry_page=AchievementState.PAGE,
        entry=ACHIEVEMENT_PAGE,
    )


class AchievementRunner(ModeRunnerBase):
    """成就领取 Runner。主循环协议见 ``ModeRunnerBase``。"""

    _MODE_LABEL = "成就领取"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        AchievementState.PAGE: 45,
        AchievementState.REWARD_POPUP: 45,
        AchievementState.EFFECT_POPUP: 45,
        AchievementState.STORY: 60,
        AchievementState.STORY_CONFIRM: 45,
        AchievementState.DONE: 45,
    }
    # 这条路线不打架。
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 「全部领取」「关闭弹窗」点完一两秒就能看出生效（按钮转灰 / 弹窗消失），
    # 不给 45 秒白等。
    _SHORT_RETRY_ACTIONS = frozenset(
        {"claim-all", "close-reward-popup", "close-effect-popup", "skip-story", "confirm-skip-story"}
    )
    _SHORT_RETRY_SECONDS = 8.0

    def _state_label(self, state: AchievementState) -> str:
        """日志/诊断里的页面名用中文（基类默认会输出 ``state.value`` 那种英文）。"""
        return STATE_LABELS.get(state, str(state))
