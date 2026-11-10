# -*- coding: utf-8 -*-
"""主线补星（2026-11-09，PC 端路线）。

## 业务闭环（用户 2026-11-09 口述，当天实机逐步核对）

```
关卡列表页 →（底部左起第三个图标：蓝色树状）→「选取Episode」面板
  左列 8 项：第6时代 / Episode 1~5 / 外传 / Episode 6 —— **只补前 6 项**
  对每个 Episode：
      滚轮推到最左（滚不动为止）
      逐屏看篇章卡片：左上角写「23/30」
          满星（30/30）→ 跳过
          未满        → 点进去
                          逐个看小节徽章右下角有没有绿勾
                              有勾 → 跳过
                              没勾 → 点它 → 准备战斗 → 战斗开始
                                      → 跳过剧情 → 结算「确认」
                                      → 自动回到小节列表，再看这一关
                                           有勾 → 继续
                                           没勾 → 报「配置可能不满足通关条件」，跳过
                          全都有勾 → ESC 回篇章面板
      本 Episode 所有篇章都满 → 点左列下一个 Episode
六章扫完 → 收工
```

**开场两步是硬约束（2026-11-10 用户纠正）**：无论从大厅干净启动、还是停在小节列表 /
外层面板接力，开跑第一件事都是点底部时间轴回「选取Episode」，再**显式选中左列第 1 项**
（第6时代），然后才扫篇章。否则游戏停在「外传 / Episode 6」时会直接在那儿找绿勾开打，
越过补星范围；准备 / 结算页也不再就地接力 —— 认不出它属于哪个 Episode，接着打同样越界。

**打完一关点「确认」是直接回小节列表的**（2026-11-09 真打验证），没有「下一关」拦路 ——
所以这条路线不需要主线的 ``next_stage`` 那一段。

## 三个判据（都在 ``evidence/story_star.py``）

1. 页面身份：``episode_title``（选取Episode）/ ``stage_help``+``timeline_icon``（关卡列表）
2. 篇章满星：星标定位 + **左右两串数字形状比对**（不识别具体数值，见 evidence 的 docstring）
3. 小节满星：徽章右下角的绿勾（模板，满星 1.0000 / 未满 0.5376）

## 横向滚动只能用滚轮

2026-11-09 实测：篇章时间轴**拖拽完全无效**（卡片上、两排空隙、时间轴线上都试过，
画面差 2.4~3.9），只有滚轮能滚（每格约 15 px）。见 ``core/pc_window.py::wheel``。

## 体力：完全复用主线

``stamina.py`` 那套（点生命之叶 → 确认），**不设补充次数上限**
（用户 2026-11-09 拍板：「不限次数，补体力没有那么多」）。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

from auto_game_unified.core.matcher import (
    MATCH_MODE_WHITE_MASK,
    SCALE_FALLBACK_STEPS,
    Match,
    find_all_templates,
    find_best_template,
    load_template,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile
from auto_game_unified.games.epic7.evidence.story_star import (
    REFERENCE_SIZE,
    REGIONS,
    STAGE_CHECK_MERGE_GAP,
    STAGE_CHECK_TEMPLATES,
    STAGE_CHECK_THRESHOLD,
    STAGE_LIST_REGION,
    STAGE_ROW_FIRST_FALLBACK,
    STAGE_ROW_MIN_GAP,
    STAGE_ROW_PITCH,
    STAGE_ROW_TOLERANCE,
    build_story_star_evidence,
    chapter_is_full,
    stage_is_full,
)
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.story import (
    StoryStateMachine,
    build_story_templates,
)
from auto_game_unified.games.epic7.template_paths import is_pc
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

# ---- 布局常量（全部量自 2026-11-09 的真机帧，基准画布 1982x1132）----------

# 左列 6 个要补的 Episode 的行中心（第6时代 + Episode 1~5）。
# 实测：(184,432) ⇒ Episode 1、(184,637) ⇒ Episode 3，行距 102.5。
EPISODE_ROW_POINTS: tuple[tuple[int, int], ...] = (
    (184, 330),
    (184, 432),
    (184, 535),
    (184, 637),
    (184, 740),
    (184, 842),
)
# 只补前 6 项：外传与 Episode 6 明确不补（用户 2026-11-09 口径）。
EPISODE_COUNT = 6

# 篇章卡片的滚动落点：上下两排之间的空白处（卡片上不行，会点开它）。
SCROLL_POINT = (1100, 760)
# 一次滚 25 格 ≈ 375 px ≈ 一张卡片宽。滚太多会跳过整张卡片。
SCROLL_NOTCHES = 25

# 小节列表：行网格不写死 —— 这一章的列表会按小节数量自适应（4 个和 5 个的行距
# 实测是 150 vs 156），所以首行与行距都用「已出现的绿勾」反推（见 _stage_action）。
# 点小节时落在文字区，避开徽章上的星级进度环。
STAGE_CLICK_X = 220
# 判定「这一屏滚不动了」的画面差阈值：滚动成功时约 40~60，到底时 < 5。
SCROLL_STUCK_DIFF = 6.0

# CLEAR 页右下「继续」的落点（页面内固定控件，不随关卡内容变）。
# 为什么不用模板：那颗箭头是淡入动画，离线帧上模板 1.0000、实跑中间帧够不到 0.85。
CLEAR_CONTINUE_POINT = (1810, 1050)

STATE_LABELS = {
    "episode": "篇章面板",
    "stage_list": "小节列表",
    "prepare": "准备战斗",
    "results": "结算确认",
    "done": "已完成",
}


class StoryStarState(Enum):
    EPISODE = "episode"
    STAGE_LIST = "stage_list"
    PREPARE = "prepare"
    # ⚠️ 战斗打完不是直接回到小节列表：先过「结算 / 完成故事 / 额外奖励」这几页，
    # 每一页都要点一下才走。不认这一段的话，主循环拿到结算页就会抛
    # ``UnrecognizedScreen`` 干等到超时 —— 2026-11-10 00:09:53 实跑即此
    # （日志写着「阶段=结算 状态=已确认」紧接着「认不出当前页面」）。
    RESULTS = "results"
    DONE = "done"


def state_label(state: StoryStarState) -> str:
    return STATE_LABELS.get(getattr(state, "value", state), str(state))


# 开局接力只允许停在最外层「选取Episode」或关卡列表（小节列表）。
# ⚠️ 准备战斗 / 结算页刻意**不接**：画面认不出属于哪个 Episode，接着打会把
# 外传 / Episode 6 这些不在补星范围内的关卡也打掉（2026-11-10 用户纠正）。
# ``DONE`` 不是一页画面，也不在名单里。
_RESUMABLE_STATES = frozenset(
    {
        StoryStarState.EPISODE,
        StoryStarState.STAGE_LIST,
    }
)

# 关卡列表页在导航链上（大厅 → 主线 → 关卡列表），停在它上面时把 ``entry``
# 交还给导航，能省掉「回大厅 → 再进主线」那一趟。
STORY_STAR_ENTRY_PAGE = "story_ready"


def detect_story_star_resume_point(
    machine: "StoryStarStateMachine",
    screen: np.ndarray,
):
    """主线补星开局接力：只接最外层「选取Episode」与关卡列表（小节列表）。

    准备 / 结算页不接 —— 画面认不出属于哪个 Episode，接着打可能越过补星范围。
    从关卡列表接力时 ``entry=story_ready`` 只省掉「回大厅再进主线」那一趟，
    开场两步（回最外层 + 选左列第 1 项）仍由 Runner 强制走完。

    **判据与运行期同源** —— 直接调状态机自己的 ``observe_page``，不另定阈值、
    不加新锚点。落点状态恒为 ``None``（本状态机每帧重判页面，拨了也没意义）。
    """
    from auto_game_unified.games.epic7.resume_probe import observe_page_probe

    return observe_page_probe(
        machine,
        screen,
        resumable=_RESUMABLE_STATES,
        label=state_label,
        entry_page=StoryStarState.STAGE_LIST,
        entry=STORY_STAR_ENTRY_PAGE,
    )


@dataclass(frozen=True)
class StoryStarTemplates:
    # 「选取Episode」标题有两套 PC 渲染（UI 画小约 3% 时字形会变），
    # 实测同一张原模板在两帧上分别 1.0000 / 0.8040（阈 0.85 ⇒ 后者漏判，
    # 2026-11-10 08:15 实跑就停在篇章面板上「认不出当前页面」干等到超时）。
    # 两张候选任一过阈即算命中，阈值不动；反例（关卡列表 0.638 / 准备页 0.518）都不命中。
    episode_title: np.ndarray
    episode_title_alt: np.ndarray
    stage_help: np.ndarray
    timeline_icon: np.ndarray
    star_marker: np.ndarray
    stage_check: np.ndarray
    stage_check_small: np.ndarray
    battle_start: np.ndarray
    # 战斗画面右上角的固定 HUD（白掩膜判据），只在共享战斗判据失手时补正。
    battle_hud: np.ndarray
    # 战斗链路一律复用主线：准备战斗 / 战斗开始 / 跳过 / 结算都在里面。
    story: object
    evidence: EvidenceProfile
    pc: bool = False


def build_story_star_templates(template_root: Path) -> StoryStarTemplates:
    """载入模板。缺一张直接抛错（判据型模板缺了会静默失效）。"""
    base = template_root / "story_star"
    evidence = build_story_star_evidence(base)

    def one(key: str) -> np.ndarray:
        return load_template(str(base / f"{key}.png"))

    return StoryStarTemplates(
        episode_title=one("episode_title"),
        episode_title_alt=one("episode_title_alt"),
        stage_help=one("stage_help"),
        timeline_icon=one("timeline_icon"),
        star_marker=one("star_marker"),
        stage_check=one("stage_check"),
        stage_check_small=one("stage_check_small"),
        battle_start=one("battle_start"),
        battle_hud=one("battle_hud"),
        story=build_story_templates(template_root / "story"),
        evidence=evidence,
        pc=is_pc(template_root),
    )


class StoryStarStateMachine:
    """纯视觉决策：给一帧，回答「下一步点哪里 / 滚哪里」或「已经补完了」。

    状态记忆只有三样，都是**跨帧必须记住**的（其余每帧从画面重判）：
    ``episode_index``（补到第几个 Episode）、``episode_done``（本 Episode 已扫到底）、
    ``scroll_signature``（上一次滚动前的画面指纹，用来判「滚不动了」）。
    """

    _REGIONS = REGIONS
    _STAGE_CLICK_X = STAGE_CLICK_X
    # 同一行两次开打的间隔保护：打完回来若这一关还是没勾，就不再重复进。
    _MAX_STAGE_ATTEMPTS = 1

    def __init__(
        self,
        templates: StoryStarTemplates,
        *,
        story_machine: StoryStateMachine | None = None,
        initial_state: StoryStarState | None = None,
    ) -> None:
        self.templates = templates
        self.evidence = templates.evidence
        # 战斗与准备页的判据**复用主线那一套**（同一页、同一颗按钮）。
        self.story = story_machine or StoryStateMachine(templates.story)
        self.episode_index = 0
        self.episode_done = False
        self.scroll_signature: Optional[np.ndarray] = None
        self.stage_scroll_signature: Optional[np.ndarray] = None
        self._stage_attempts: dict[int, int] = {}
        # 点完小节之后，下一帧要先点「准备战斗」再谈别的 —— 点小节只是「选中」，
        # 页面不换，不记住这件事的话下一帧会接着去点下一个小节（永远进不了战斗）。
        # 用**计数**而不是布尔：点完「准备战斗」页面要一两秒才切过去，
        # 期间抓到的仍是关卡页，凭一帧就放弃会退回去点别的行（23:45 实跑即此）。
        self._pending_prepare = 0
        # 点完「准备战斗」之后是两页：先「选择辅助英雄」、再「队伍」。
        # 这一步过渡期同样抓不到稳定页面，用标记把它桥接过去。
        self._pending_select = False
        # 开场两步：先回最外层「选取Episode」，再显式选中左列第 1 项（第6时代）。
        # 默认 False 是为了让状态机单测能直接喂稳态帧；只有 Runner 开跑时 begin()
        # 才置 True。否则从大厅干净启动会直接从当前章节的小节开始找绿勾。
        self._need_open_episode_panel = False
        self._need_select_first_episode = False
        # 主循环（含干跑）会读这个计数；本路线「一轮 = 扫完 6 章」，
        # 没有逐轮的战斗计数，收工时按「补完的章节数」回填一次即可。
        self.completed_cycles = 0
        self.finished = False
        # 起始状态只是给 ModeSpec 的元数据用 —— 本状态机每帧从画面重判页面，
        # 拨状态没有意义（拨了下一帧就被覆盖）。
        self.state = initial_state or StoryStarState.EPISODE

    def begin(self) -> None:
        """Runner 开跑前调用：武装开场两步，保证先回外层再选范围内的第 1 项。"""
        self._need_open_episode_panel = True
        self._need_select_first_episode = True

    # ---- 判据 -------------------------------------------------------------
    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        from auto_game_unified.core.matcher import find_best_template

        atom = self.evidence.atom(name)
        candidates = (getattr(self.templates, name),)
        if name == "episode_title":
            candidates = (
                self.templates.episode_title,
                self.templates.episode_title_alt,
            )
        best: Optional[Match] = None
        for template in candidates:
            match = find_best_template(
                screen, template, atom.region, atom.reference_size
            )
            if match is not None and (best is None or match.score > best.score):
                best = match
        if best is None or best.score < atom.threshold:
            return None
        return best

    def observe_page(self, screen: np.ndarray) -> Optional[StoryStarState]:
        """认页面。

        顺序：**结算页最先判** —— 它是半透明遮罩，底下的关卡页元素仍然能命中，
        顺序反了会对着被盖住的按钮点（与成就领取的弹窗同一条教训）。
        然后准备页 → 篇章面板 → 小节列表。
        """
        if self._results_visible(screen):
            return StoryStarState.RESULTS
        if self._prepare_visible(screen):
            return StoryStarState.PREPARE
        if self._locate(screen, "episode_title") is not None:
            return StoryStarState.EPISODE
        if self._locate(screen, "stage_help") is not None and self._locate(
            screen, "timeline_icon"
        ) is not None:
            return StoryStarState.STAGE_LIST
        return None

    # 结算阶段的三页：结算成绩（右下「确认」）、完成故事弹窗（底部「点击关闭」）、
    # 额外奖励弹窗。三者的名字复用主线的模板，点击点也用模板中心。
    _RESULTS_ANCHORS = ("clear", "results_confirm", "complete", "reward")

    def _results_visible(self, screen: np.ndarray) -> bool:
        return any(
            self.story._locate(screen, name) is not None
            for name in self._RESULTS_ANCHORS
        )

    def _prepare_visible(self, screen: np.ndarray) -> bool:
        """准备阶段：队伍页的「战斗开始」或选辅助页的「选择队伍」任一命中。

        ⚠️ 「准备战斗」点下去之后是**两页**：先「选择辅助英雄」（右下是「选择队伍」），
        再「队伍」（右下才是「战斗开始」）。只认 ``start_mission`` 的话，中间那页
        会判成「认不出当前页面」—— 2026-11-09 23:40 实跑就卡在这一步。
        """
        return (
            self._locate(screen, "battle_start") is not None
            or self.story._locate(screen, "select_team") is not None
        )

    def star_points(self, screen: np.ndarray) -> list[tuple[int, int]]:
        """这一屏所有篇章卡片的星标中心。"""
        matches = find_all_templates(
            screen,
            self.templates.star_marker,
            0.90,
            region=(300, 380, 1680, 700),
            reference_size=REFERENCE_SIZE,
            min_gap=120,
        )
        return [match.center for match in matches]

    def stage_checks(self, screen: np.ndarray) -> list[tuple[int, int]]:
        """这一屏所有「已满星」小节的绿勾中心。

        勾有两种大小（同页第 1 行大一圈、其余小一圈），两张候选模板各扫一遍再合并。
        """
        points: list[tuple[int, int]] = []
        for key in STAGE_CHECK_TEMPLATES:
            for match in find_all_templates(
                screen,
                getattr(self.templates, key),
                STAGE_CHECK_THRESHOLD,
                region=STAGE_LIST_REGION,
                reference_size=REFERENCE_SIZE,
                min_gap=STAGE_ROW_MIN_GAP,
            ):
                center = match.center
                if any(
                    abs(center[0] - x) + abs(center[1] - y) < STAGE_CHECK_MERGE_GAP
                    for x, y in points
                ):
                    continue
                points.append(center)
        return points

    # ---- 决策 -------------------------------------------------------------
    def next_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        # 过渡期优先：刚点过「准备战斗」的话，先认「选择队伍」——
        # 这一两秒里关卡页可能还在，不能拿它去判断「该点哪一行」。
        if self._pending_select:
            select = self.story._locate(screen, "select_team")
            if select is not None:
                self._pending_select = False
                self._confirmed_page = StoryStarState.PREPARE.value
                return RouteAction(
                    "select-team",
                    select.center,
                    source_page=StoryStarState.PREPARE.value,
                    in_page_evidence="队伍页已出现（右下按钮换成「战斗开始」）",
                    reason="「选择队伍」已识别，进入队伍页",
                )
        page = self.observe_page(screen)
        if page is None:
            raise UnrecognizedScreen("主线补星：认不出当前页面")
        self.state = page
        # ⚠️ 主循环靠这个字段做转场验收（`runner_base._transition_completed` 拿它
        # 和上一个动作的 ``target_pages`` 对账）。不设的话「点了没换页」永远成立，
        # 每个带 target_pages 的动作都会干等到超时 —— 2026-11-09 23:48 实跑即此。
        self._confirmed_page = page.value

        # 开场两步：先把游戏拉回业务闭环的起点，再按前 6 项扫。
        # 直接从小节列表开打，会让「外传 / Episode 6」也进补星范围（2026-11-10 用户纠正）。
        if not self.finished:
            if (
                page is StoryStarState.STAGE_LIST
                and self._need_open_episode_panel
            ):
                self._need_open_episode_panel = False
                icon = self._locate(screen, "timeline_icon")
                if icon is None:
                    raise UnrecognizedScreen(
                        "主线补星：开场找不到底部时间轴图标，无法回最外层"
                    )
                return RouteAction(
                    "open-episode-panel",
                    icon.center,
                    source_page=StoryStarState.STAGE_LIST.value,
                    target_pages=(StoryStarState.EPISODE.value,),
                    reason="开场先回最外层「选取Episode」面板，确认补星范围",
                )
            if (
                page is StoryStarState.EPISODE
                and self._need_select_first_episode
            ):
                # 外层面板可能正停在「外传 / Episode 6」那一列；显式点回第 1 项。
                self._need_open_episode_panel = False
                self._need_select_first_episode = False
                return RouteAction(
                    "select-first-episode",
                    EPISODE_ROW_POINTS[0],
                    source_page=StoryStarState.EPISODE.value,
                    in_page_evidence="左列第 1 项「第6时代」已选中，篇章切到范围内第一章",
                    reason="开局显式切到补星范围内的第 1 项，再扫篇章",
                )

        if page is StoryStarState.RESULTS:
            return self._results_action(screen)
        if page is StoryStarState.PREPARE:
            return self._prepare_action(screen)
        if page is StoryStarState.EPISODE:
            return self._episode_action(screen)
        return self._stage_action(screen)

    def _results_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        """结算阶段：按「CLEAR → 结算成绩 → 完成故事 → 额外奖励」的顺序一页页点掉。

        ⚠️ **找不到按钮时必须抛 ``UnrecognizedScreen``，绝不能 return None** ——
        主循环把 ``next_action`` 返回 ``None`` 读作「状态机宣布收工」，
        当场结束整条路线回家。2026-11-10 07:36 那轮就是这么死的：
        战斗刚打完（监督日志「阶段=结算 状态=已确认」）同一秒就开始导航回大厅。
        """
        # CLEAR 页（战斗刚结束那一下）不会自己过去 —— 必须先点右下那颗「>」。
        #
        # ⚠️ 这里用**页面内固定落点**，不拿模板定位那颗箭头：它在 CLEAR 页上是
        # 淡入的动画元素，离线帧上模板 1.0000，实跑抓到的中间帧却够不到 0.85
        # ⇒ 2026-11-10 07:45 那轮就停在「CLEAR 页认得出、箭头没定位到」，干等到超时。
        # 落点与主线 `STORY_CLICK_POINT` 同一路做法（那一页的固定控件，不随内容变）。
        if self.story._locate(screen, "clear") is not None:
            return RouteAction(
                "dismiss-clear",
                CLEAR_CONTINUE_POINT,
                source_page=StoryStarState.RESULTS.value,
                in_page_evidence="CLEAR 页已推进（出现结算成绩或回收）",
                reason="CLEAR 页已识别，点右下「继续」的固定落点",
            )
        for name in ("results_confirm", "complete", "reward"):
            match = self.story._locate(screen, name)
            if match is not None:
                return RouteAction(
                    f"dismiss-{name.replace('_', '-')}",
                    match.center,
                    source_page=StoryStarState.RESULTS.value,
                    in_page_evidence=f"「{name}」已点掉，页面继续往回收",
                    reason=f"结算阶段：{name}",
                )
        raise UnrecognizedScreen("主线补星：判成结算页，但四个锚点一个都没定位到")

    def _prepare_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        # 队伍页的「战斗开始」用**补星自己的 PC 覆盖图**：主线那张
        # ``start_mission_updated`` 在这页只有 0.8011（阈 0.80，擦边），
        # 环境一抖就掉；这张实测 1.0000、关卡页最高 0.5842。
        match = self._locate(screen, "battle_start")
        if match is not None:
            return RouteAction(
                "start-mission",
                match.center,
                source_page=StoryStarState.PREPARE.value,
                in_page_evidence="战斗已开始（交给战斗监督）",
                reason="队伍页右下「战斗开始」已识别",
            )
        select = self.story._locate(screen, "select_team")
        if select is not None:
            return RouteAction(
                "select-team",
                select.center,
                source_page=StoryStarState.PREPARE.value,
                in_page_evidence="队伍页已出现（右下按钮换成「战斗开始」）",
                reason="「选择队伍」已识别，进入队伍页",
            )
        prepare = self.story._locate(screen, "prepare_battle")
        if prepare is not None:
            return RouteAction(
                "prepare-battle",
                prepare.center,
                source_page=StoryStarState.STAGE_LIST.value,
                target_pages=(StoryStarState.PREPARE.value,),
                reason="关卡列表底部「准备战斗」已识别",
            )
        # 稳定确认期间会走到这里（页面正在切）—— 抛「认不出」让主循环继续等，
        # **不能 return None**：那等于宣布收工回家。
        raise UnrecognizedScreen("主线补星：判成准备页，但三个按钮都没定位到")

    def _episode_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        if self.finished:
            return None
        # 先把这一屏里「未满」的篇章逐个点开。
        for center in self.star_points(screen):
            full, _detail = chapter_is_full(screen, center)
            if not full:
                self.scroll_signature = None
                return RouteAction(
                    "open-chapter",
                    (center[0] + 150, center[1] + 90),
                    source_page=StoryStarState.EPISODE.value,
                    target_pages=(StoryStarState.STAGE_LIST.value,),
                    reason=f"篇章未满（星标 {center}）",
                )
        # 这一屏都满星 ⇒ 继续往右滚；滚不动说明本 Episode 扫完了。
        if self.scroll_signature is not None:
            from auto_game_unified.core.supervisor import meaningful_change

            if not meaningful_change(self.scroll_signature, screen):
                return self._next_episode(screen)
        self.scroll_signature = screen.copy()
        return RouteAction(
            "scroll-chapters",
            SCROLL_POINT,
            source_page=StoryStarState.EPISODE.value,
            in_page_evidence="篇章卡片已横向平移",
            reason=f"本屏都满，向右滚 {SCROLL_NOTCHES} 格",
        )

    def _next_episode(self, screen: np.ndarray) -> Optional[RouteAction]:
        self.episode_index += 1
        self.episode_done = False
        self.scroll_signature = None
        if self.episode_index >= EPISODE_COUNT:
            self.finished = True
            self.state = StoryStarState.DONE
            self.completed_cycles = EPISODE_COUNT
            return None
        point = EPISODE_ROW_POINTS[self.episode_index]
        return RouteAction(
            "next-episode",
            point,
            source_page=StoryStarState.EPISODE.value,
            in_page_evidence="右侧篇章内容已切换",
            reason=f"切到第 {self.episode_index + 1} 个章节",
        )

    def _stage_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        # 上一步刚点过某个小节：接下来几帧先把「准备战斗」点掉，不能再选下一关。
        if self._pending_prepare > 0:
            prepare = self.story._locate(screen, "prepare_battle")
            if prepare is not None:
                self._pending_prepare = 0
                self._pending_select = True
                return RouteAction(
                    "prepare-battle",
                    prepare.center,
                    source_page=StoryStarState.STAGE_LIST.value,
                    target_pages=(StoryStarState.PREPARE.value,),
                    reason="小节已选中，点底部「准备战斗」",
                )
            self._pending_prepare -= 1
            if self._pending_prepare == 0:
                # 连续几帧都找不到那颗按钮 ⇒ 放弃这次，重新看整页（不能 return None）。
                raise UnrecognizedScreen("主线补星：等「准备战斗」按钮超时，重新观察")
        checks = self.stage_checks(screen)
        ys = sorted({y for _x, y in checks})
        # 行距与首行都用实测的勾反推：这一章的列表会按行数自适应，
        # 4 个小节和 5 个小节的行距/首行位置都不一样（实测 150 vs 156）。
        if len(ys) >= 2:
            diffs = [b - a for a, b in zip(ys, ys[1:], strict=False)]
            pitch = int(round(sum(diffs) / len(diffs)))
        else:
            pitch = STAGE_ROW_PITCH
        if ys:
            first = ys[0]
            while first - pitch >= 330:
                first -= pitch
        else:
            # 一屏一个勾都没有 ⇒ 只能按兜底网格（列表在顶部、5 行）。
            first = STAGE_ROW_FIRST_FALLBACK
        rows: list[int] = []
        y = first
        while y <= 1010:
            rows.append(y)
            y += pitch

        for row in rows:
            if stage_is_full(
                screen, checks, row, row_tolerance=STAGE_ROW_TOLERANCE
            ):
                continue
            attempts = self._stage_attempts.get(row, 0)
            if attempts >= self._MAX_STAGE_ATTEMPTS:
                continue
            self._stage_attempts[row] = attempts + 1
            self.stage_scroll_signature = None
            self._pending_prepare = 3
            return RouteAction(
                "open-stage",
                (self._STAGE_CLICK_X, row - 20),
                source_page=StoryStarState.STAGE_LIST.value,
                in_page_evidence="右侧故事内容已切换（该小节被选中）",
                reason=f"第 y={row} 行没有绿勾，判定未满星",
            )
        # 可见的都有勾 ⇒ 往下滚看更多；滚不动说明本章清完了。
        if self.stage_scroll_signature is not None:
            from auto_game_unified.core.supervisor import meaningful_change

            if not meaningful_change(self.stage_scroll_signature, screen):
                self._stage_attempts.clear()
                # ⚠️ 「回篇章面板」**不能按 ESC**：实测 2026-11-10 07:31 从关卡页按 ESC
                # 直接退回了**大厅**（不是篇章面板），页面认不出 → 超时；
                # 左上角那个「< Episode」箭头和篇章面板的返回箭头长得一模一样
                # （同一模板互命中 0.9965），也没法当判据。
                # 可靠的路只有一条：**点底部那颗蓝色树状图标**，它就地打开篇章面板
                # （进来的时候也是点它）。
                back = self._locate(screen, "timeline_icon")
                if back is None:
                    raise UnrecognizedScreen(
                        "主线补星：本章已清完，但底部时间轴图标没定位到"
                    )
                return RouteAction(
                    "back-to-episode",
                    back.center,
                    source_page=StoryStarState.STAGE_LIST.value,
                    target_pages=(StoryStarState.EPISODE.value,),
                    reason="本章小节已全满，点底部时间轴图标回篇章面板",
                )
        self.stage_scroll_signature = screen.copy()
        return RouteAction(
            "scroll-stages",
            (200, 700),
            source_page=StoryStarState.STAGE_LIST.value,
            in_page_evidence="小节列表已纵向平移",
            reason="可见小节都有勾，往下滚看更多",
        )

    def preview(self, screen: np.ndarray):
        """稳定确认用的「试算」入口：算完把业务进度**原样还回去**。

        主循环每帧都会先调 ``preview`` 做两帧稳定确认；``next_action`` 会推进
        ``episode_index`` / ``_stage_attempts`` / ``scroll_signature`` ——
        不还原的话，「试算」自己就把遍历进度推着走了（实测会跳章、重复开小节）。
        """
        snapshot = (
            self.state,
            self.completed_cycles,
            self.finished,
            self.episode_index,
            self.episode_done,
            self.scroll_signature,
            self.stage_scroll_signature,
            dict(self._stage_attempts),
            self._pending_prepare,
            self._pending_select,
            self._need_open_episode_panel,
            self._need_select_first_episode,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.finished,
                self.episode_index,
                self.episode_done,
                self.scroll_signature,
                self.stage_scroll_signature,
                self._stage_attempts,
                self._pending_prepare,
                self._pending_select,
                self._need_open_episode_panel,
                self._need_select_first_episode,
            ) = snapshot

    def _battle_hud_visible(self, screen: np.ndarray) -> bool:
        """这一帧是不是战斗画面：右上角固定 HUD 的白掩膜锚点。

        客户端两次启动之间会把整套 UI 画小约 3%（``PC_TEMPLATE_MIGRATION.md``
        §2.4b）。那种档位下共享判据的三项读数同时擦边：四格底座圆心上移 31 px
        （容差 30）、右上控制区白占比 0.065（下限 0.08）、左侧行动条 0.104
        （下限 0.12）⇒ 五项全假，监督等满 45 秒报 ``battle_unrecognized``。

        共享判据是所有 PC 战斗路线共用的、被验证过的结论，不许为一张帧放宽它的
        阈值或容差。这里按世界首领战的同款做法（``world_boss.py`` 用本路线锚点
        补 ``battle_visible``），只给补星自己补一条证据：右上角那组固定图标
        ``? / ×2 / 自动 / 暂停`` 走**白掩膜**，亮背景、暗技能演出都成立。

        尺度按 ``SCALE_FALLBACK_STEPS`` 逐档扫：另一档 UI 尺寸上原尺寸只有
        0.80，扫描后 0.96。名单不登记进共享 ``SCALE_FALLBACK_ANCHORS``，因为这颗
        锚点只服务本路线，登记会把全局名单和它的护栏测试一起拖进来。
        """
        atom = self.evidence.atom("battle_hud")
        for scale in (1.0, *SCALE_FALLBACK_STEPS):
            match = find_best_template(
                screen,
                self.templates.battle_hud,
                atom.region,
                atom.reference_size,
                mode=MATCH_MODE_WHITE_MASK,
                template_scale=scale,
            )
            if match is not None and match.score >= atom.threshold:
                return True
        return False

    def observe_battle(self, screen: np.ndarray, previous_screen):
        """本路线交给战斗监督的观察入口：主线判据 + 本路线一条战斗 HUD 证据。

        只在共享判据判不出、且帧有效时补正；结算页与无效帧一律保持原结论，
        不许把「认不出」粉饰成「战斗还在打」。
        """
        observation = self.story.observe_battle(screen, previous_screen)
        if (
            observation.battle_visible
            or observation.result_visible
            or not observation.frame_valid
        ):
            return observation
        if self._battle_hud_visible(screen):
            return replace(observation, battle_visible=True)
        return observation


class StoryStarRunner(ModeRunnerBase):
    """主线补星 Runner。战斗链路整段复用主线的 ``StoryStateMachine.observe_battle``。"""

    _MODE_LABEL = "主线补星"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        StoryStarState.EPISODE: 45,
        StoryStarState.STAGE_LIST: 45,
        StoryStarState.PREPARE: 60,
        StoryStarState.RESULTS: 45,
    }
    _BATTLE_ENTRY_ACTION = "start-mission"
    _ALLOW_UNKNOWN_SCREEN_WAKE = False
    # 滚动与开篇章都是页内动作，点完一两秒就能看出结果，不给 45 秒白等。
    _SHORT_RETRY_ACTIONS = frozenset(
        {
            "scroll-chapters",
            "scroll-stages",
            "open-episode-panel",
            "select-first-episode",
            "open-chapter",
            "open-stage",
            "dismiss-results-confirm",
            "dismiss-complete",
            "dismiss-reward",
            "dismiss-clear",
            "back-to-episode",
        }
    )
    _SHORT_RETRY_SECONDS = 6.0
    # 一次运行最多开多少次章节/小节 —— 有界保护：万一判据把某个满星篇章看成未满，
    # 也只是多开几次，不会无限循环。取 200 足够覆盖 6 章 × 10 篇章 × 若干小节。
    _MAX_ACTIONS = 200

    def __init__(self, machine: StoryStarStateMachine, runtime, **kwargs):
        super().__init__(machine, runtime, **kwargs)
        # 每次开跑都先武装开场两步：回最外层「选取Episode」+ 选左列第 1 项。
        machine.begin()
        self._actions = 0

    def _state_label(self, state: StoryStarState) -> str:
        return STATE_LABELS.get(getattr(state, "value", state), str(state))

    def _perform_action(self, action: RouteAction) -> None:
        """滚轮与返回键在这里换发 —— 它们不是「点一下」。

        ⚠️ 要覆写的是基类的 ``_perform_action``（第 185 行，主循环真正调用的那个）。
        2026-11-10 07:23 那一轮覆写成了 ``_click_action`` —— 基类里**确实还有**
        一个同名方法，但它没有任何调用点（死代码），于是三个动作全被当成普通点击发出去：
        「往下滚」变成在列表中间点一下、「退回篇章面板」变成点左上角 (60,100)
        ⇒ 画面变成认不出的状态，实跑 07:24 / 07:28 两轮都死在这里。
        """
        self._actions += 1
        if self._actions > self._MAX_ACTIONS:
            raise RuntimeError(
                f"主线补星已执行 {self._actions} 个动作仍未收工，判定为异常循环"
            )
        if action.name == "scroll-chapters":
            # 向下滚 = 篇章卡片往右走（向上滚是往左）。方向反了就会一直在原地打转：
            # 每帧判「这一屏都满」→ 往上滚回同一个位置 → 永远扫不到右边那些篇章。
            self.runtime.wheel(action.point, -SCROLL_NOTCHES, action.name)
            return
        if action.name == "scroll-stages":
            self.runtime.wheel(action.point, -SCROLL_NOTCHES, action.name)
            return
        super()._perform_action(action)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._SHORT_RETRY_ACTIONS:
            return self._SHORT_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _run_committed_battle(self, *, cycle: int) -> None:
        """战斗整段交给本路线的观察入口（主线判据 + 补星自己的 HUD 补正）。"""
        from auto_game_unified.core.battle_supervisor import (
            BattleConfig,
            BattleOutcome,
            BattleSupervisor,
        )

        supervisor = BattleSupervisor(
            self.runtime,
            self.recovery_gate,
            BattleConfig(mode="story_star", mode_label="主线补星"),
            now=self.now,
            sleep=self.sleep,
        )
        outcome = supervisor.run(self.machine.observe_battle, cycle=cycle)
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"主线补星战斗出现意外结果：{outcome.value}")
