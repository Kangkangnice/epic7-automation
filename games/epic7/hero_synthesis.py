"""英雄合成：三星英雄自动合成（刻印记忆）状态机和 Runner。

流程：大厅 → 英雄列表 → 筛选3星 → 自上而下遍历卡片：
- 刻印按钮置灰（3S 已满级）→ 跳过；
- 刻印按钮有红点且非 3S → 进入刻印界面，加入全部 Up 材料 → 合成 → 确认 → 返回；
- 无红点 → 跳过；列表底部无更多卡片时完成一轮。

当前规则只看当前卡：SSS 跳过，非 SSS 且有红点才合成。
"""

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import numpy as np

from auto_game_unified.core.matcher import load_template
from auto_game_unified.games.epic7.template_paths import is_pc
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import NOT_STABLE, ModeRunnerBase
from auto_game_unified.games.epic7.hero_vision import (
    BUTTON_CENTER,
    BUTTON_DISC_RADIUS,
    EQUIPMENT_TAB_ZONE,
    FilterObservation,
    HERO_INFO_TAB_ZONE,
    REFERENCE_SIZE,
    SELECTED_TAB_BLUE_MIN,
    HeroVisionMixin,
    hero_equipment_tab_selected,
    hero_information_tab_selected,
    hero_tab_blue_pixel_counts,
    # ⚠️ 这条是**再导出**，不是「导进来没用」：`navigation.py` 按
    # `hero_synthesis.imprint_button_saturation` 取它（历史上它定义在本模块）。
    # 别让 ruff 的 F401 自动修复把它删掉 —— 2026-09-30 在 `story.py` 已经踩过一次同类坑。
    imprint_button_saturation,  # noqa: F401
)
from auto_game_unified.games.epic7.hero_transition import (
    CardSwitchMotionObserver,
    SafetyClass,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile
from auto_game_unified.games.epic7.evidence.hero_synthesis import (
    FILTER_ATTRIBUTE_SMALL_THRESHOLD,
    REGIONS as HERO_REGIONS,
    THRESHOLDS as HERO_THRESHOLDS,
    build_hero_evidence,
)


HERO_INFORMATION_TAB_POINT = (65, 200)


class HeroSynthState(Enum):
    HERO_LIST = "hero_list"
    FILTER = "filter"
    IMPRINT_ADD = "imprint_add"
    IMPRINT_ABORTING = "imprint_aborting"
    IMPRINT_CONFIRM = "imprint_confirm"
    IMPRINT_REWARD = "imprint_reward"
    TRANSMIT_SELECT = "transmit_select"
    TRANSMIT_CONFIRM = "transmit_confirm"
    TRANSMIT_REWARD = "transmit_reward"
    TRANSMIT_RETURNING = "transmit_returning"



class TransmitPhase(Enum):
    NONE = "none"
    PENDING = "pending"
    OPENING = "opening"
    SELECTING = "selecting"
    CONFIRMING = "confirming"
    TRANSMITTED = "transmitted"
    RETURNING = "returning"


STATE_LABELS = {
    HeroSynthState.HERO_LIST: "英雄列表",
    HeroSynthState.FILTER: "筛选面板",
    HeroSynthState.IMPRINT_ADD: "刻印加材料",
    HeroSynthState.IMPRINT_ABORTING: "中止刻印等待返回",
    HeroSynthState.IMPRINT_CONFIRM: "合成确认",
    HeroSynthState.IMPRINT_REWARD: "合成结果",
    HeroSynthState.TRANSMIT_SELECT: "传送选择",
    HeroSynthState.TRANSMIT_CONFIRM: "传送确认",
    HeroSynthState.TRANSMIT_REWARD: "传送奖励",
    HeroSynthState.TRANSMIT_RETURNING: "传送后返回列表",
}


def state_label(state: HeroSynthState) -> str:
    return STATE_LABELS.get(state, state.value)


@dataclass(frozen=True)
class HeroAction(RouteAction):
    """英雄合成的一个动作。

    ✅ **字段名已对齐**（2026-10-04）：同页动作的出口验收原来写在自造的
    ``source_observation`` 里，而契约认的字段名是基类的 ``in_page_evidence`` ——
    两个名字指同一件事。名字不齐的代价是这条路线一直进 ``TRANSITION_EXEMPT``：
    开关打开也管不到它（``_REQUIRE_TRANSITION_CONTRACT`` 读的就是
    ``in_page_evidence``）。现在直接复用基类字段，自造字段整个删掉。
    """

    transition_kind: str = ""



@dataclass(frozen=True)
class HeroTemplates:
    filter_button: np.ndarray
    filter_level_label: np.ndarray
    filter_star3_selected: np.ndarray
    imprint_normal: np.ndarray
    imprint_grey: np.ndarray
    auto_select_label: np.ndarray
    story_back: np.ndarray
    rating_sss: np.ndarray
    rating_sss_list: Optional[np.ndarray]
    # ⚠️ 下面 9 张**曾经是 `Optional[...] = None`**，缺文件就静默跳过。后果分三档：
    #   - `sss_material`：缺失 → 判 UNKNOWN → 不点任何材料卡（fail-closed，还有救）
    #   - `filter_attribute_label` / `filter_star3_unselected`：筛选面板认不出 →
    #     反复点漏斗直到超时（不点错，但卡死）
    #   - `sss_material_warning_title`/`_close`、`imprint_result_title`/`_close`、
    #     `transmit_reward_title`/`_close`：**这三组是 fail-open** —— 覆盖层判据
    #     缺失时 `_xxx_present()` 返回 False，于是「覆盖层必须先关掉」这条保护
    #     **静默消失**，可能点到覆盖层底下的材料卡 / 返回箭头（合成消耗材料，不可逆）。
    # 判据型模板缺一张就是配置故障，必须在**开跑前**报错，不许降级 ——
    # 所以这里全是必需字段，配套门槛见 `HeroSynthStateMachine._assert_anchor_templates`。
    filter_attribute_label: np.ndarray
    filter_star3_unselected: np.ndarray
    # ⚠️ **元组**：同一个「SSS 材料」徽记有**两种长相**（判据语义 = 任一候选过阈即命中，
    # 取过阈候选里的最高分，与 `NavigationTemplates.lobby_shop_entry` 同一套做法）：
    #   - 前排展开的大卡上按 100% 画
    #   - 排在后面、被压暗的小卡上整张缩到约 90%
    # 只留前排那张时，后排形态只量到 0.5957，掉进 0.55~0.80 的不确定带 ⇒ 判据**静默失效**、
    # 流程停在刻印页（2026-10-04 07:22 现场，同形态最早见 2026-09-03 14:05）。
    # 候选几张同样必需，缺一张在构造期报错（见 `_assert_anchor_templates`）。
    sss_material: tuple[np.ndarray, ...]
    sss_material_warning_title: np.ndarray
    sss_material_warning_close: np.ndarray
    imprint_result_title: np.ndarray
    imprint_result_close: np.ndarray
    transmit_reward_title: np.ndarray
    transmit_reward_close: np.ndarray
    # 证据画像（提供区域表与阈值表）。**必需** —— 它若是 None，
    # `HeroSynthStateMachine._REGIONS` 压根不会被赋值，判据要等到第一次
    # `_locate()` 才以 AttributeError 炸出来：晚、且现场难查。
    evidence: EvidenceProfile
    threshold: float = 0.80
    assume_non_max_rating: bool = False
    pc: bool = False


def build_hero_templates(template_root: Path) -> HeroTemplates:
    """加载英雄合成全部模板。**模板缺一张就直接抛错**，不做任何降级。

    这里**不许**再写 ``load_template(...) if path.exists() else None`` —— 那会让判据
    静默消失（详见 ``HeroTemplates`` 里那段说明）。``load_template`` 文件不在时本来就
    会 ``FileNotFoundError``，这正好是我们要的 fail closed：开跑前起不来，
    而不是带着一个悄悄失效的判据跑到真机上。
    """
    hero = template_root / "hero"
    navigation = template_root / "navigation"
    evidence = build_hero_evidence(template_root)
    # 「SSS 材料」徽记的候选模板从证据画像里取，不再手写路径 —— 路径只留一个来源，
    # 免得「画像说有两张、加载器只读一张」这种口径漂移（本路线踩过同类坑）。
    sss_material = evidence.atom("sss_material")
    rating_sss_list_path = hero / "rating_sss_list.png"
    rating_sss_list = (
        load_template(str(rating_sss_list_path))
        if Path(rating_sss_list_path).is_file()
        else None
    )
    return HeroTemplates(
        filter_button=load_template(str(hero / "filter_button.png")),
        filter_level_label=load_template(str(hero / "filter_level_label.png")),
        filter_star3_selected=load_template(str(hero / "filter_star3_selected.png")),
        imprint_normal=load_template(str(hero / "imprint_button_normal.png")),
        imprint_grey=load_template(str(hero / "imprint_button_grey.png")),
        auto_select_label=load_template(str(hero / "auto_select_label.png")),
        story_back=load_template(str(navigation / "story_back.png")),
        rating_sss=load_template(str(hero / "rating_sss.png")),
        rating_sss_list=rating_sss_list,
        filter_attribute_label=load_template(
            str(hero / "filter_attribute_label.png")
        ),
        filter_star3_unselected=load_template(
            str(hero / "filter_star3_unselected.png")
        ),
        sss_material=tuple(
            load_template(str(template_root / path))
            for path in (
                sss_material.template_path,
                *sss_material.alt_template_paths,
            )
        ),
        sss_material_warning_title=load_template(
            str(hero / "sss_material_warning_title.png")
        ),
        sss_material_warning_close=load_template(
            str(hero / "sss_material_warning_close.png")
        ),
        imprint_result_title=load_template(
            str(hero / "imprint_result_title.png")
        ),
        imprint_result_close=load_template(
            str(hero / "imprint_result_close.png")
        ),
        transmit_reward_title=load_template(
            str(hero / "transmit_reward_title.png")
        ),
        transmit_reward_close=load_template(
            str(hero / "transmit_reward_close.png")
        ),
        evidence=evidence,
        threshold=evidence.atom("filter_button").threshold,
        assume_non_max_rating=False,
        pc=is_pc(template_root),
    )


class HeroSynthStateMachine(HeroVisionMixin):
    """英雄合成流程的纯视觉决策状态机。"""

    # ⚠️ 这 6 个视觉常量定义在 `hero_vision`（那边的四个模块级视觉函数要用），这里只做
    # **别名**、不复制值 —— 同一个控件/阈值只保留一个来源（项目硬约束）。
    _REFERENCE_SIZE = REFERENCE_SIZE

    _REGIONS = HERO_REGIONS
    _THRESHOLDS = HERO_THRESHOLDS
    # 兼容既有测试与诊断脚本；值只引用统一 profile，不再重复定义。
    _RATING_REGION = HERO_REGIONS["rating_sss"]
    _RATING_SSS_MIN = HERO_THRESHOLDS["rating_sss"]
    _MATERIAL_SSS_REGION = HERO_REGIONS["sss_material"]
    _SSS_MATERIAL_MIN = HERO_THRESHOLDS["sss_material"]
    _REWARD_TITLE_REGION = HERO_REGIONS["transmit_reward_title"]
    _REWARD_CLOSE_REGION = HERO_REGIONS["transmit_reward_close"]
    # 颜色检测区（x, y, w, h）
    _BUTTON_ZONE = (1000, 900, 250, 200)
    _BUTTON_TL = (1028, 925)  # 140x140 按钮模板的标准落位左上角
    _DOT_MASK = (1030, 935, 50, 50)  # 红点角标区（刻印按钮左上角），匹配时双向屏蔽
    _BUTTON_CENTER = BUTTON_CENTER
    _BUTTON_DISC_RADIUS = BUTTON_DISC_RADIUS
    _BUTTON_STRUCT_MIN = 0.50  # 结构匹配下限：确认按钮存在（不限颜色）
    _REDDOT_ZONE = (1030, 942, 32, 35)  # 模拟器按用户标框收紧的刻印按钮红点区
    _MATERIAL_CARD_ZONE = (1460, 390, 522, 610)
    _CARD_BELOW_ZONE = (1450, 537, 520, 83)
    _DETAIL_CONTENT_ZONE = (150, 350, 550, 300)
    _HERO_INFO_TAB_ZONE = HERO_INFO_TAB_ZONE
    _EQUIPMENT_TAB_ZONE = EQUIPMENT_TAB_ZONE
    _IMPRINT_SLOT_ZONES = (
        (600, 605, 370, 110),
        (970, 605, 370, 110),
        (600, 725, 370, 110),
        (970, 725, 370, 110),
        (600, 845, 370, 110),
        (970, 845, 370, 110),
    )
    _UP_BADGE_ZONE = (1370, 390, 95, 600)
    # 右侧卡片条区域。⚠️ 生产判据已改成「Up 角标行 + 可见材料卡轮廓」
    # （``_up_badge_rows`` / ``_find_visible_material_card``），不再靠这块区域找卡片；
    # 现在只有测试用它构造「右边缘被遮住」的画面，别当成死常量删掉。
    _UP_STRIP_ZONE = (1880, 380, 50, 620)
    _IMPRINT_COST_ZONE = (1020, 1025, 75, 50)
    _GREEN_BTN_ZONE = (900, 1020, 500, 90)
    _TRANSMIT_GREEN_ZONE = (1000, 1000, 400, 110)
    _BLUE_BAND_ZONE = (900, 700, 450, 120)
    _GOLD_BAND_ZONE = (650, 700, 330, 120)
    _REWARD_STRIP_ZONE = (880, 825, 160, 35)
    _TRANSMIT_STRIP_ZONE = (1400, 200, 250, 800)
    _TRANSMIT_GRID_ZONE = (50, 305, 620, 405)
    _SIMULATOR_DETAIL_FP_ZONE = (150, 180, 550, 170)
    _LIST_FP_ZONE = (1450, 200, 532, 780)
    _HERO_IDENTITY_ZONE = (145, 165, 280, 145)

    # 点击点（参考尺寸坐标）
    _FUNNEL_POINT = (1540, 191)
    _STAR3_POINT = (1110, 636)
    # 模拟器截图是 1920x1080 渲染画面上方补 52px 的旧画布；
    # 点击下一张卡的主体区域，不点击战力数字或卡片边界。
    _NEXT_CARD_POINT = (1800, 591)
    _IMPRINT_BUTTON_POINT = (1098, 995)  # 刻印按钮硬编码坐标：模板匹配失败时的兜底
    _UP_CARD_X = 1710
    _GREEN_BTN_POINT = (1149, 1078)
    _CONFIRM_FALLBACK_POINT = (1144, 750)
    _TRANSMIT_CARD_X = 1720
    _TRANSMIT_GREEN_POINT = (1203, 1057)
    _REWARD_CLOSE_POINT = (960, 843)
    _IMPRINT_RESULT_CLOSE_POINT = (991, 850)
    _TRANSMIT_ENTRY_POINT = (1735, 1060)
    _HERO_INFO_TAB_POINT = HERO_INFORMATION_TAB_POINT
    _BACK_OFFSET = (-26, -6)
    _CARD_BELOW_BRIGHT_MIN = 2000
    _DETAIL_CONTENT_BRIGHT_MIN = 5000
    _SELECTED_TAB_BLUE_MIN = SELECTED_TAB_BLUE_MIN
    _REWARD_STRIP_RANGE = (300, 1500)
    _SSS_MATERIAL_CLEAR_MAX = 0.55
    _SSS_TEMPLATE_INSET = 4
    # 「SSS 材料」徽记在页面上会被画成**多档尺寸**：同一枚徽记，排在材料列表
    # 越靠后的卡上就越小。已实测到的核心宽有 56 / 50 / 45 三档（相对模板
    # 1.00 / 0.90 / 0.80 倍），而卡片排第几位由页面当时有几张材料决定 ⇒ 档位
    # 不是固定的两三种，补模板补不完（2026-10-04 08:36 现场：只按 1.00 倍
    # 匹配量到 0.5928，落进 0.55~0.80 死区 ⇒ 判据沉默、一帧动作都不出）。
    # 因此在基准尺寸之外再做一组相对缩放，逐档取最高分。
    # 范围只向下扩：所有已实测帧的最佳档都 ≤ 1.00（不需要更大的画法）。
    _SSS_TEMPLATE_SCALES: tuple[float, ...] = (1.00, 0.95, 0.90, 0.85, 0.80, 0.75)
    _NON_SSS_BUTTON_SATURATION_MIN = 90.0
    _FILTER_ATTRIBUTE_SMALL_MIN = FILTER_ATTRIBUTE_SMALL_THRESHOLD
    _UP_BADGE_MIN_PIXELS = 300
    _FILLED_SLOT_ORANGE_MIN = 5000
    _NONZERO_COST_YELLOW_MIN = 300
    _TRANSMIT_HIGHLIGHT_ZONE = (1600, 200, 380, 800)
    _READINESS_OBSERVATIONS = 2
    # 连续多少次「点了加材料、槽位数却没变」就判定这个英雄加不进材料、换下一个。
    # 2026-11-03 PC 实测：英雄刻印已满时游戏提示「已达最高献身技能级别，
    # 无法继续刻印记忆。」，点了之后右侧材料列表与绿色按钮会**短暂消失**，
    # 但**槽位数始终不变** ⇒ 只认 Up 卡会一直空点下去。
    _IMPRINT_ADD_NO_PROGRESS_LIMIT = 3
    # 刻印页「既不能加料也不能合成」连续确认多少次就返回英雄列表换下一个。
    _IMPRINT_ESCAPE_OBSERVATIONS = 3

    @staticmethod
    def _assert_anchor_templates(templates: HeroTemplates) -> None:
        """登记在证据画像里的判据锚点必须都有模板，缺了当场报错。

        与 ``Epic7Navigator._assert_anchor_templates`` 同一套规矩（2026-10-03）。
        判据型模板缺一张，判据**不会报错、只会静默消失**：轻则页面认不出、反复
        点同一个按钮直到超时；重则「覆盖层必须先关掉」这类保护悄悄失效，
        点到覆盖层底下的材料卡 —— 而合成会消耗材料，不可逆。

        名册取 ``evidence.atoms`` 而不是自己再列一份：``_REGIONS`` / ``_THRESHOLDS``
        本来就是从它派生的，它才是「本路线有哪些判据锚点」的权威来源。
        """
        missing = []
        for anchor in templates.evidence.atoms:
            value = getattr(templates, anchor, None)
            # None = 没加载；空元组 = 候选图一张都没有。两者都是「判据不存在」。
            if value is None or (isinstance(value, tuple) and not value):
                missing.append(anchor)
        if missing:
            raise ValueError(
                "英雄合成判据锚点缺少模板（该判据会静默失效）："
                + "、".join(sorted(missing))
            )

    def __init__(
        self,
        templates: HeroTemplates,
        initial_state: HeroSynthState = HeroSynthState.HERO_LIST,
    ) -> None:
        self.templates = templates
        self.state = initial_state
        # 开跑前先确认判据锚点都在，再拿它建区域表/阈值表。
        self._assert_anchor_templates(templates)
        self._REGIONS = {
            key: atom.region for key, atom in templates.evidence.atoms.items()
        }
        self._THRESHOLDS = {
            key: atom.threshold for key, atom in templates.evidence.atoms.items()
        }
        self.completed_cycles = 0
        self.filter_verified = False
        self.prev_card_grey = False
        # 结构匹配下限只有模拟器基线一套；平台差异收敛到图片。
        self._button_struct_min = self._BUTTON_STRUCT_MIN
        self._filter_attribute_small_min = FILTER_ATTRIBUTE_SMALL_THRESHOLD
        self._button_tl = self._BUTTON_TL
        self._dot_mask = self._DOT_MASK
        self._reddot_zone = self._REDDOT_ZONE
        grey_template = (
            templates.imprint_normal
            if templates.assume_non_max_rating
            else templates.imprint_grey
        )
        self._masked_grey = self._mask_dot(grey_template)
        self._masked_normal = self._mask_dot(templates.imprint_normal)
        self._last_screen: Optional[np.ndarray] = None
        # 筛选面板一次性入场 flag：close_filter 后置 True，之后永远不再进筛选分支
        self._filter_session_done: bool = False
        # 已点击 3 星后，必须先从截图确认选中态；确认前禁止回点筛选漏斗。
        self._awaiting_star3_confirmation: bool = False
        # 模拟器筛选关闭请求只表示“正在等待目标页”，不能代表筛选已完成。
        self._filter_close_pending: bool = False
        self._last_filter_scores: dict[str, float] = {}
        self._confirmed_page: str = ""
        self.transmit_phase = TransmitPhase.NONE
        self.transmit_target_observation: Optional[str] = None
        self.transmit_continuity_intact = False
        self._active_card_observation: Optional[str] = None
        self._transmit_reward_confirmed = False
        self._imprint_empty_observations = 0
        if templates.pc:
            # 「加材料」的进展跟踪：上一次动作时的已填槽位数，以及连续无进展的次数。
            # 槽位数始终不增加 ⇒ 这个英雄加不进材料（多半是刻印已满），换下一个。
            self._imprint_add_last_slots = -1
            self._imprint_add_no_progress = 0
            # 刻印页「既不能加料也不能合成」的连续确认次数（逃生门用）。
            self._imprint_escape_observations = 0
        self._list_end_observations = 0
        self._list_end_fingerprint: Optional[str] = None
        self._current_card_observation: Optional[str] = None
        self._previous_card_context: Optional[tuple[str, SafetyClass]] = None
        # 「刻印加材料」页**每帧现算**的观察值（``slots=N;rows=…``），与动作对象
        # 解耦 —— 见 `_material_transition_completed`。
        self._current_material_observation: Optional[str] = None

    @property
    def pending_transmit_target(self) -> bool:
        return self.transmit_phase is not TransmitPhase.NONE

    @pending_transmit_target.setter
    def pending_transmit_target(self, value: bool) -> None:
        if value:
            if self.transmit_phase is TransmitPhase.NONE:
                self.transmit_phase = TransmitPhase.PENDING
            self.transmit_continuity_intact = True
        elif not value:
            self.transmit_phase = TransmitPhase.NONE
            self.transmit_target_observation = None
            self.transmit_continuity_intact = False

    def _confirm_page(self, label: str) -> None:
        self._confirmed_page = label

    def _simulator_transition_action(
        self,
        name: str,
        point: tuple[int, int],
        *,
        source_page: str,
        target_pages: tuple[str, ...],
        reason: str,
        # 同页动作的出口验收依据 —— **用基类字段名**（原 `source_observation`）。
        # 改名是为了让 `_REQUIRE_TRANSITION_CONTRACT` 真能读到它：那个开关查的
        # 就是 `in_page_evidence`，名字不齐时这 12 个同页动作只是「形式合规」
        # （靠 target_pages 里塞当前页过检查），实质没有验收依据。
        in_page_evidence: str = "",
        transition_kind: str = "",
    ) -> HeroAction:
        return HeroAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            reason=reason,
            in_page_evidence=in_page_evidence,
            transition_kind=transition_kind,
        )


    def _next_simulator_filter_action(
        self, screen: np.ndarray
    ) -> tuple[bool, Optional[HeroAction]]:
        # SSS 材料中止后必须先处理当前待传送英雄；不能被首次筛选抢占。
        if self.pending_transmit_target:
            return False, None

        observation = self._observe_filter(screen)
        labels = {
            FilterObservation.HERO_LIST_FILTER_CLOSED: "英雄列表",
            FilterObservation.FILTER_OPEN_STAR3_SELECTED: "筛选面板（三星已选中）",
            FilterObservation.FILTER_OPEN_STAR3_UNSELECTED: "筛选面板（三星未选中）",
        }
        label = labels.get(observation)
        if label is not None:
            self._confirm_page(label)

        if observation is FilterObservation.FILTER_OPEN_STAR3_UNSELECTED:
            self.state = HeroSynthState.FILTER
            self._filter_close_pending = False
            return True, HeroAction(
                "select_star3",
                self._scaled_point(screen, self._STAR3_POINT),
                source_page="筛选面板（三星未选中）",
                target_pages=("筛选面板（三星已选中）",),
                reason=(
                    "级别与属性锚点存在，三星深色按钮存在；"
                    f"{self._filter_evidence_summary()}"
                ),
            )

        if observation is FilterObservation.FILTER_OPEN_STAR3_SELECTED:
            self.state = HeroSynthState.FILTER
            self._filter_close_pending = True
            return True, HeroAction(
                "close_filter",
                self._scaled_point(screen, self._FUNNEL_POINT),
                source_page="筛选面板（三星已选中）",
                target_pages=("英雄列表",),
                reason=(
                    "级别与属性锚点存在，三星白底按钮存在；"
                    f"{self._filter_evidence_summary()}"
                ),
            )

        if observation is FilterObservation.HERO_LIST_FILTER_CLOSED:
            self._active_card_observation = self._hero_identity_fingerprint(screen)
            if self._filter_close_pending:
                self._filter_close_pending = False
                self.filter_verified = True
                self._filter_session_done = True
                self.state = HeroSynthState.HERO_LIST
                return True, None
            if not self.filter_verified:
                # 记录“正在等待筛选面板”；半加载 UNKNOWN 只能等待，
                # 不能落回英雄列表分支再次点击漏斗。
                self.state = HeroSynthState.FILTER
                return True, HeroAction(
                    "open_filter",
                    self._scaled_point(screen, self._FUNNEL_POINT),
                    source_page="英雄列表",
                    target_pages=(
                        "筛选面板（三星已选中）",
                        "筛选面板（三星未选中）",
                    ),
                    reason=(
                        "英雄信息页已确认，打开三星筛选；"
                        f"{self._filter_evidence_summary()}"
                    ),
                )
            return False, None

        if self.state is HeroSynthState.FILTER or self._filter_close_pending:
            return True, None
        return False, None

    def _back_point(self, screen: np.ndarray) -> Optional[tuple[int, int]]:
        """页内返回箭头的点击点。**只给坐标，不给动作。**

        为什么只给坐标：``HeroAction`` 的 ``source_page`` / ``target_pages`` 是转场
        契约（见 ``docs/TRANSITION_CONTRACTS.md``），而「返回」在不同位置的含义不同
        （传送选择→列表、合成后刻印页→列表、刻印页→列表），只有调用方知道，所以契约
        必须由调用方声明。历史上这里直接返回一个**裸 ``HeroAction``**，于是有调用点
        顺手 ``return back`` —— 那个「返回」点完不回头看，成没成功根本没人验收。
        改成只返回坐标后，「裸动作」在本路线里就构造不出来了。
        """
        back = self._locate(screen, "story_back")
        if back is None:
            return None
        # match.center 已是屏幕坐标，仅做箭头热区向左偏移
        offset = self._BACK_OFFSET
        return (back.center[0] + offset[0], back.center[1] + offset[1])

    # ---- 遍历决策 ----

    def _detail_fingerprint(self, screen: np.ndarray) -> str:
        """用标题和选中卡列表确认确实翻到了下一张。"""
        parts = []
        for zone, size in (
            (self._SIMULATOR_DETAIL_FP_ZONE, (8, 3)),
            (self._LIST_FP_ZONE, (8, 10)),
        ):
            gray = self._zone_gray(screen, zone)
            gray = cv2.GaussianBlur(gray, (11, 11), 0)
            small = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
            parts.append((small // 32).astype(np.uint8).tobytes())
        return hashlib.sha1(b"".join(parts)).hexdigest()[:8]

    def _hero_identity_fingerprint(self, screen: np.ndarray) -> str:
        """用英雄名称等静态白色文字确认返回后仍是同类英雄。"""
        hsv = self._zone_hsv(screen, self._HERO_IDENTITY_ZONE)
        white = cv2.inRange(hsv, (0, 0, 150), (179, 70, 255))
        white = cv2.morphologyEx(
            white,
            cv2.MORPH_OPEN,
            np.ones((2, 2), dtype=np.uint8),
        )
        small = cv2.resize(white, (32, 12), interpolation=cv2.INTER_AREA)
        return hashlib.sha1((small // 64).astype(np.uint8).tobytes()).hexdigest()[:8]

    def _adjacent_sss_duplicate_transmit_action(
        self, screen: np.ndarray
    ) -> Optional[HeroAction]:
        """仅把紧邻同名 SSS 本体后的无红点副本送入既有传送流程。"""
        previous_context = self._previous_card_context
        current_identity = self._active_card_observation
        self._previous_card_context = None
        if (
            previous_context is None
            or previous_context[1] is not SafetyClass.SSS
            or previous_context[0] != current_identity
        ):
            return None
        self.transmit_phase = TransmitPhase.OPENING
        self.transmit_target_observation = current_identity
        self.transmit_continuity_intact = True
        return self._simulator_transition_action(
            "open_transmit_for_current_card",
            self._scaled_point(screen, self._TRANSMIT_ENTRY_POINT),
            source_page="英雄列表",
            target_pages=("传送选择",),
            reason="上一张=SSS，名称指纹同名=是，当前无红点副本；打开传送并复用目标SSS保护",
            in_page_evidence=current_identity,
        )

    def arm_adjacent_sss_context(self, action: HeroAction) -> None:
        """只在翻卡动态证据已确认后，记录刚离开的 SSS 卡。"""
        if (
            action.transition_kind != "card_change"
            or "当前英雄为SSS" not in action.reason
            or not action.in_page_evidence
        ):
            return
        self._previous_card_context = (action.in_page_evidence, SafetyClass.SSS)

    def _advance_or_finish(self, screen: np.ndarray) -> Optional[HeroAction]:
        self._current_card_observation = self._detail_fingerprint(screen)
        if not self._hero_list_ready(screen):
            self._current_card_observation = None
            self._list_end_fingerprint = None
            self._list_end_observations = 0
            return None
        self._confirm_page("英雄列表")
        if not self._card_below_present(screen):
            fingerprint = self._current_card_observation
            if self._list_end_fingerprint != fingerprint:
                self._list_end_fingerprint = fingerprint
                self._list_end_observations = 0
            self._list_end_observations += 1
            if self._list_end_observations < self._READINESS_OBSERVATIONS:
                return None
            self.completed_cycles += 1
            self._previous_card_context = None
            self._list_end_observations = 0
            self._list_end_fingerprint = None
            self.filter_verified = False  # 新一轮 cycle 重新筛选
            self._filter_session_done = False  # 新一轮允许重新进入筛选面板
            self._awaiting_star3_confirmation = False
            self.prev_card_grey = False
            return None
        self._list_end_observations = 0
        self._list_end_fingerprint = None

        # Runner 会用动作名做两帧确认；指纹用于让动画过渡中的不同英雄
        # 产生不同动作名，从而不会被误判为稳定。
        rating = "S" if self._is_max_rating(screen) else "X"
        fp = self._current_card_observation
        if fp is None:
            return None
        # 动作名保留动态详情指纹用于诊断；重试契约只使用静态英雄身份，
        # 避免立绘动画变化后在错误英雄上重试旧动作。
        sig = fp
        skip_reason = (
            "当前英雄为SSS，跳过"
            if rating == "S"
            else "当前英雄非SSS但刻印按钮无红点，跳过"
        )
        return HeroAction(
            f"next_card_{sig}",
            self._scaled_point(
                screen, self._NEXT_CARD_POINT
            ),
            source_page="英雄列表",
            target_pages=("英雄列表",),
            reason=f"{skip_reason}，详情指纹={fp}，等待下一英雄或列表末尾",
            in_page_evidence=(
                self._hero_identity_fingerprint(screen)
            ),
            transition_kind="card_change",
        )

    # ---- 主决策 ----

    def next_action(self, screen: np.ndarray) -> Optional[HeroAction]:
        self._last_screen = screen
        self._confirmed_page = ""
        # 1. SSS 材料风险提示层必须先关闭，不能点击覆盖层下的按钮。
        warning_close = self._sss_material_warning_close(screen)
        if warning_close is not None:
            self._confirm_page("刻印SSS警告")
            return self._simulator_transition_action(
                "close_sss_material_warning",
                warning_close.center,
                source_page="刻印SSS警告",
                target_pages=("刻印加材料", "刻印SSS材料"),
                reason="提示层标题与关闭控件同时存在，先关闭提示再继续观察刻印页",
            )

        # 2. 合成结果覆盖层必须先关闭，不能点击覆盖层下的返回箭头。
        if self._imprint_result_present(screen):
            self._confirm_page("合成结果")
            self.state = HeroSynthState.IMPRINT_REWARD
            self._imprint_empty_observations = 0
            return self._simulator_transition_action(
                "close_imprint_result",
                self._scaled_point(screen, self._IMPRINT_RESULT_CLOSE_POINT),
                source_page="合成结果",
                target_pages=("合成后刻印页", "英雄列表"),
                reason="结果标题与关闭控件同时存在",
            )

        # 3. 确认弹窗（合成/传送共用的蓝色按钮）
        confirm = self._confirm_button(screen)
        if confirm is not None:
            transmit_ctx = self._locate(screen, "auto_select_label") is not None
            if transmit_ctx or self.state.value.startswith("transmit"):
                if (
                    self.transmit_phase
                    not in (TransmitPhase.SELECTING, TransmitPhase.CONFIRMING)
                    or not self.transmit_continuity_intact
                ):
                    return None
                self._confirm_page("传送确认")
                self.state = HeroSynthState.TRANSMIT_CONFIRM
                self.transmit_phase = TransmitPhase.CONFIRMING
                return self._simulator_transition_action(
                    "confirm_transmit",
                    self._scaled_point(screen, confirm),
                    source_page="传送确认",
                    target_pages=("传送奖励",),
                    reason="传送确认弹窗的蓝色确认按钮与金色内容带同时存在",
                )
            self._confirm_page("合成确认")
            self.state = HeroSynthState.IMPRINT_CONFIRM
            self._imprint_empty_observations = 0
            return self._simulator_transition_action(
                "confirm_synthesis",
                self._scaled_point(screen, confirm),
                source_page="合成确认",
                target_pages=("合成结果",),
                reason="蓝色确认按钮带与金色内容带同时存在",
            )

        # 3. 传送奖励弹窗（仅在传送流程中判定，防止列表误触）
        if (
            self.transmit_phase is TransmitPhase.CONFIRMING
            or self.state.value.startswith("transmit")
        ) and self._transmit_reward_present(screen):
            self._confirm_page("传送奖励")
            self.transmit_phase = TransmitPhase.TRANSMITTED
            self._transmit_reward_confirmed = True
            self.state = HeroSynthState.TRANSMIT_RETURNING
            self.transmit_phase = TransmitPhase.RETURNING
            return self._simulator_transition_action(
                "close_reward",
                self._scaled_point(screen, self._REWARD_CLOSE_POINT),
                source_page="传送奖励",
                target_pages=("传送选择",),
                reason="传送奖励层已确认，关闭后只允许返回英雄列表",
            )

        # 4. 传送/刻印返回动画：只在确认列表已恢复后继续流程。
        imprint_abort_returned = False
        if self.state is HeroSynthState.IMPRINT_ABORTING:
            if not self._hero_list_ready(screen):
                return None
            self.state = HeroSynthState.HERO_LIST
            imprint_abort_returned = True

        if (
            self.transmit_phase is TransmitPhase.RETURNING
            or self.state is HeroSynthState.TRANSMIT_RETURNING
        ):
            self.state = HeroSynthState.TRANSMIT_RETURNING
            if self._locate(screen, "auto_select_label"):
                self._confirm_page("传送选择")
                back = self._back_point(screen)
                if back is not None:
                    return self._simulator_transition_action(
                        "back_to_list",
                        back,
                        source_page="传送选择",
                        target_pages=("英雄列表",),
                        reason="传送已完成，选择页只允许返回英雄列表",
                    )
                return None
            if not self._hero_list_ready(screen):
                return None
            self._confirm_page("英雄列表")
            self.transmit_phase = TransmitPhase.NONE
            self.transmit_target_observation = None
            self.transmit_continuity_intact = False
            self._transmit_reward_confirmed = False
            self.state = HeroSynthState.HERO_LIST

        # 5. 传送选择界面：四个锚点齐全才算真正进入。
        if self._locate(screen, "auto_select_label"):
            if (
                self.transmit_phase
                not in (TransmitPhase.OPENING, TransmitPhase.SELECTING)
                or self.transmit_target_observation is None
                or not self.transmit_continuity_intact
            ):
                return None
            if not self._transmit_page_ready(screen):
                return None
            self._confirm_page("传送选择")
            self.state = HeroSynthState.TRANSMIT_SELECT
            self.transmit_phase = TransmitPhase.SELECTING
            card = self._transmit_target_card(screen)
            if card is not None and (
                self._transmit_green_present(screen)
                and self._transmit_grid_filled(screen)
            ):
                self.state = HeroSynthState.TRANSMIT_CONFIRM
                return self._simulator_transition_action(
                    "start_transmit",
                    self._scaled_point(screen, self._TRANSMIT_GREEN_POINT),
                    source_page="传送选择",
                    target_pages=("传送确认",),
                    reason="目标已进入传送格且绿色传送按钮存在",
                    in_page_evidence="grid=1",
                )
            target_class = self._classify_transmit_target(screen, card)
            if target_class is SafetyClass.SSS:
                back = self._back_point(screen)
                if back is None:
                    raise UnrecognizedScreen("传送高亮卡为 SSS 且缺少返回箭头")
                self.transmit_phase = TransmitPhase.RETURNING
                self.state = HeroSynthState.TRANSMIT_RETURNING
                return self._simulator_transition_action(
                    "abort_transmit_sss_target",
                    back,
                    source_page="传送选择",
                    target_pages=("英雄列表",),
                    reason="传送高亮目标为SSS，禁止传送并返回列表",
                )
            if target_class is SafetyClass.UNKNOWN:
                return None
            if card is not None:
                x, y, tag = card
                return self._simulator_transition_action(
                    f"select_transmit_card_{tag}",
                    self._scaled_point(screen, (x, y)),
                    source_page="传送选择",
                    target_pages=("传送选择",),
                    reason="高亮目标已确认但传送格尚未填入",
                    in_page_evidence="grid=0",
                    transition_kind="transmit_selection",
                )
            return None

        if (
            self.state is HeroSynthState.IMPRINT_CONFIRM
            and self._back_point(screen) is not None
        ):
            raise UnrecognizedScreen("合成结果覆盖层未完整识别，禁止点击底层返回")

        # 6. 刻印界面（绿色刻印按钮与完整材料槽共同作为页面证据）
        pc = getattr(self.templates, "pc", False)
        green_button_present = self._green_button_present(screen)
        complete_imprint_page = (
            green_button_present and self._imprint_slots_present(screen)
        )
        if self.state is HeroSynthState.IMPRINT_REWARD:
            if complete_imprint_page:
                self._confirm_page("合成后刻印页")
                back = self._back_point(screen)
                if back is None:
                    return None
                return self._simulator_transition_action(
                    "back_to_list",
                    back,
                    source_page="合成后刻印页",
                    target_pages=("英雄列表",),
                    reason="结果覆盖层消失且刻印页返回箭头存在",
                )
            if not self._hero_list_ready(screen):
                return None
            self._confirm_page("英雄列表")
            self.state = HeroSynthState.HERO_LIST

        sss_material_present = False
        material_page_class = SafetyClass.NON_SSS
        up = None
        if complete_imprint_page:
            if self.state is HeroSynthState.HERO_LIST:
                self.state = HeroSynthState.IMPRINT_ADD
            # 每帧现算一次观察值，**不管后面走哪个分支**（含各条 `return None`）。
            #
            # 为什么要在这么早的位置算：转场验收（`_material_transition_completed`）
            # 过去是从**动作对象**里取这个值，于是「判据沉默 ⇒ 生不出动作 ⇒ 值取不到
            # ⇒ 永远判不出转场成功」—— 2026-10-04 07:22 那次卡死的另一半原因。
            # 槽位数与材料行位置**不依赖任何判据模板**（纯色块统计），所以哪怕
            # `_classify_material_page` 落死区、这里照样算得出真值。
            self._current_material_observation = self._material_observation(
                self._imprint_filled_slot_count(screen),
                self._ordinary_up_rows(screen),
            )
            sss_material_present = self._sss_material_present(screen)
            if sss_material_present:
                self._confirm_page("刻印SSS材料")
            else:
                material_page_class = self._classify_material_page(screen)
                if material_page_class is SafetyClass.UNKNOWN:
                    self._confirm_page("刻印加材料")
                    return None
                up = self._find_up_card(screen)
                if self._unknown_up_material_present(screen):
                    self._confirm_page("刻印加材料")
                    return None
                self._confirm_page("刻印加材料")

        if (
            self.state is HeroSynthState.IMPRINT_ADD
            and complete_imprint_page
            and sss_material_present
        ):
            self._imprint_empty_observations = 0
            target_observation = (
                self._active_card_observation or self._current_card_observation
            )
            if target_observation is None:
                raise UnrecognizedScreen("发现 SSS 材料但缺少当前英雄身份")
            self.transmit_phase = TransmitPhase.PENDING
            self.transmit_target_observation = target_observation
            self.transmit_continuity_intact = True
            back = self._back_point(screen)
            if back is None:
                raise UnrecognizedScreen("发现 SSS 材料但刻印页面缺少返回箭头")
            self.state = HeroSynthState.IMPRINT_ABORTING
            return self._simulator_transition_action(
                "abort_imprint_to_transmit",
                back,
                source_page="刻印SSS材料",
                target_pages=("英雄列表",),
                reason="发现SSS材料，保存当前英雄身份并中止刻印",
            )
        if (
            self.state is HeroSynthState.IMPRINT_ABORTING
            and complete_imprint_page
            and sss_material_present
        ):
            back = self._back_point(screen)
            if back is None:
                raise UnrecognizedScreen("发现 SSS 材料但刻印页面缺少返回箭头")
            return self._simulator_transition_action(
                "abort_imprint_to_transmit",
                back,
                source_page="刻印SSS材料",
                target_pages=("英雄列表",),
                reason="SSS材料页仍存在，继续请求返回英雄列表",
            )
        if self.state is HeroSynthState.IMPRINT_ADD and not complete_imprint_page:
            if pc:
                # ⚠️ 逃生门（2026-11-03 PC 实测补）：绿按钮不在（**不能合成**）+ 右侧既没有
                # Up 卡也没有可见材料卡（**不能加料**）⇒ 这一页代码处理不了，原来只会
                # ``return None`` 干等到转场超时（实测 55 秒），最后连 ESC 回家都失败。
                # 实测落到这儿的有两类：
                #   ① 英雄详情里的「刻印记忆材料」页（1 个圆形槽 + 专属材料如
                #      「伊利欧斯之力 3/1」，**不是**代码支持的 6 槽刻印页）；
                #   ② 刻印已满时点材料，右侧列表与绿按钮会**短暂消失**。
                # 连续确认若干次后就返回英雄列表换下一个 —— 这一页有返回箭头（实测 (30,92)）。
                if (
                    not green_button_present
                    and self._find_up_card(screen) is None
                    and self._find_visible_material_card(screen) is None
                ):
                    self._imprint_escape_observations += 1
                    if (
                        self._imprint_escape_observations
                        >= self._IMPRINT_ESCAPE_OBSERVATIONS
                    ):
                        back = self._back_point(screen)
                        if back is not None:
                            self._imprint_escape_observations = 0
                            return self._simulator_transition_action(
                                "back_to_list",
                                back,
                                source_page="刻印加材料",
                                target_pages=("英雄列表",),
                                reason=(
                                    "刻印页既不能加料也不能合成"
                                    "（连续确认 "
                                    f"{self._IMPRINT_ESCAPE_OBSERVATIONS} 次），"
                                    "返回英雄列表换下一个"
                                ),
                            )
                else:
                    self._imprint_escape_observations = 0
            self._imprint_empty_observations = 0
            return None
        if (
            green_button_present
            and not complete_imprint_page
            and not imprint_abort_returned
        ):
            return None
        if green_button_present and (
            complete_imprint_page
        ):
            filled_slots = self._imprint_filled_slot_count(screen)
            if pc:
                # ⚠️ 槽位满了就**不再加材料**（2026-11-03 PC 实测补的守卫）：
                # 这一页在材料加满时会显示「无法继续额外增加」，但右侧材料列表里的
                # Up 卡**照样能识别到** ⇒ 原逻辑只要 ``up is not None`` 就一直发
                # ``add_material``，槽满之后每一下都加不进去 ⇒ 转场超时
                # （现场：``add_material_6_1`` 反复超时，六个槽实测全为已填）。
                # 槽位计数本身是准的（PC 上已填槽橙色像素 2.2 万~2.7 万，阈值 5000），
                # 所以「槽满」可以直接作为停止加料、转入合成的依据。
                slots_full = filled_slots >= len(self._IMPRINT_SLOT_ZONES)
                if up is not None and not slots_full:
                    # ⚠️ 进展跟踪（2026-11-03 PC 实测补的守卫）：英雄**刻印已满**时，
                    # 游戏会提示「已达最高献身技能级别，无法继续刻印记忆。」，点了之后
                    # 右侧材料列表与绿色按钮会**短暂消失**，但**槽位数始终不变**；
                    # 而 Up 卡/材料卡照样能识别到 ⇒ 只靠 ``up is not None`` 会一直空点，
                    # 四次点完转场验收失败、整条路线报错收场。
                    # ⇒ 槽位数连续多次不增加，就判定这个英雄加不进材料，换下一个。
                    # 只在**已经加进过材料**（槽位非空）时才做无进展判定：槽位还是空的
                    # 说明连一个都没加进去，更可能是点击还没生效/页面在动，先让它重试，
                    # 别急着换英雄（否则游戏响应慢一点就会白白跳过一个本来能刻印的英雄）。
                    if filled_slots > 0:
                        if filled_slots == self._imprint_add_last_slots:
                            self._imprint_add_no_progress += 1
                        else:
                            self._imprint_add_no_progress = 0
                            self._imprint_add_last_slots = filled_slots
                        if (
                            self._imprint_add_no_progress
                            >= self._IMPRINT_ADD_NO_PROGRESS_LIMIT
                        ):
                            # ⚠️ 2026-11-03 PC 实测修正：**加不动 ≠ 不能刻印**。
                            # 一个三星英雄往往只有 1 张同名卡，加进槽之后右侧那张卡的
                            # Up 角标**还在**（对应槽位已使用），于是每轮都挑回它、每下
                            # 都加不进去。而此刻绿按钮还在、**费用非零**（= 游戏认为槽里的
                            # 材料够合成一次）⇒ 正确动作是**去合成**，不是换英雄。
                            # 现场（21:13 那轮）：`已填槽位=1 费用非零=1 Up材料=1`，
                            # 判成「无法继续刻印」直接返回列表，一整个英雄白跳过。
                            # 费用为 0 才是真的不能再刻印（已 SSS / 材料不成立）⇒ 换下一个。
                            if self._imprint_cost_nonzero(screen):
                                self._imprint_add_no_progress = 0
                                self._imprint_add_last_slots = -1
                                return self._simulator_transition_action(
                                    "start_synthesis",
                                    self._scaled_point(
                                        screen, self._GREEN_BTN_POINT
                                    ),
                                    source_page="刻印加材料",
                                    target_pages=("合成确认", "合成结果"),
                                    reason=(
                                        "材料加不动但费用非零 ⇒ 材料已够，"
                                        f"直接合成（已填槽位={filled_slots}）"
                                    ),
                                    in_page_evidence=self._material_observation(
                                        filled_slots, []
                                    ),
                                )
                            back = self._back_point(screen)
                            if back is not None:
                                self._imprint_add_no_progress = 0
                                self._imprint_add_last_slots = -1
                                return self._simulator_transition_action(
                                    "back_to_list",
                                    back,
                                    source_page="刻印加材料",
                                    target_pages=("英雄列表",),
                                    reason=(
                                        f"连续 {self._IMPRINT_ADD_NO_PROGRESS_LIMIT} 次"
                                        f"加材料后槽位仍为 {filled_slots} 且费用为 0，"
                                        "判定该英雄无法继续刻印，换下一个"
                                    ),
                                )
                    self._imprint_empty_observations = 0
                    self.state = HeroSynthState.IMPRINT_ADD
                    x, y, tag = up
                    material_observation = self._material_observation(
                        filled_slots, self._ordinary_up_rows(screen)
                    )
                    return self._simulator_transition_action(
                        f"add_material_{filled_slots}_{tag}",
                        self._scaled_point(screen, (x, y)),
                        source_page="刻印加材料",
                        target_pages=("刻印加材料", "刻印SSS材料"),
                        reason=(
                            f"发现普通Up材料，已填槽位={filled_slots}，目标={tag}"
                        ),
                        in_page_evidence=material_observation,
                        transition_kind="material_change",
                    )
                if self.state is HeroSynthState.IMPRINT_ADD:
                    # “没看到 Up”只表示识别结果为空，不表示材料已加完。必须看到
                    # 中间槽内已有材料，且费用从 0 变为非 0，才允许进入合成。
                    cost_nonzero = self._imprint_cost_nonzero(screen)
                    if filled_slots == 0 and not cost_nonzero:
                        self._imprint_empty_observations = 0
                        visible_card = self._find_visible_material_card(screen)
                        if (
                            visible_card is None
                            or material_page_class is not SafetyClass.NON_SSS
                        ):
                            return None
                        x, y, tag = visible_card
                        return self._simulator_transition_action(
                            f"add_material_{filled_slots}_{tag}",
                            self._scaled_point(screen, (x, y)),
                            source_page="刻印加材料",
                            target_pages=("刻印加材料", "刻印SSS材料"),
                            reason=(
                                "SSS评级已明确排除且检测到普通材料卡，"
                                "Up标记未识别，使用材料卡轮廓定位"
                            ),
                            in_page_evidence=self._material_observation(
                                filled_slots, []
                            ),
                            transition_kind="material_change",
                        )
                    # 槽满即视为材料齐备，**不再要求费用判据**（2026-11-03 PC 实测）：
                    # PC 上费用数字被半透明遮罩盖住，费用区实测黄色像素 **0**（阈值 300）
                    # ⇒ ``_imprint_cost_nonzero`` 恒为假 ⇒ 卡在这里永远合成不了。
                    # 槽满（六个槽全部已填）+ 绿按钮存在 + 连续确认，才是合成的依据。
                    if filled_slots == 0 or (not slots_full and not cost_nonzero):
                        self._imprint_empty_observations = 0
                        return None
                    self._imprint_empty_observations += 1
                    if (
                        self._imprint_empty_observations
                        < self._READINESS_OBSERVATIONS
                    ):
                        return None
                    self._imprint_empty_observations = self._READINESS_OBSERVATIONS
                    return self._simulator_transition_action(
                        "start_synthesis",
                        self._scaled_point(
                            screen, self._GREEN_BTN_POINT
                        ),
                        source_page="刻印加材料",
                        target_pages=("合成确认", "合成结果"),
                        reason=(
                            "Up材料已清空，"
                            f"已填槽位={filled_slots}，费用非零，连续确认=2"
                        ),
                        in_page_evidence=self._material_observation(
                            filled_slots, []
                        ),
                    )
            else:
                if up is not None:
                    self._imprint_empty_observations = 0
                    self.state = HeroSynthState.IMPRINT_ADD
                    x, y, tag = up
                    material_observation = self._material_observation(
                        filled_slots, self._ordinary_up_rows(screen)
                    )
                    return self._simulator_transition_action(
                        f"add_material_{filled_slots}_{tag}",
                        self._scaled_point(screen, (x, y)),
                        source_page="刻印加材料",
                        target_pages=("刻印加材料", "刻印SSS材料"),
                        reason=(
                            f"发现普通Up材料，已填槽位={filled_slots}，目标={tag}"
                        ),
                        in_page_evidence=material_observation,
                        transition_kind="material_change",
                    )
                if self.state is HeroSynthState.IMPRINT_ADD:
                    # “没看到 Up”只表示识别结果为空，不表示材料已加完。必须看到
                    # 中间槽内已有材料，且费用从 0 变为非 0，才允许进入合成。
                    cost_nonzero = self._imprint_cost_nonzero(screen)
                    if filled_slots == 0 and not cost_nonzero:
                        self._imprint_empty_observations = 0
                        visible_card = self._find_visible_material_card(screen)
                        if (
                            visible_card is None
                            or material_page_class is not SafetyClass.NON_SSS
                        ):
                            return None
                        x, y, tag = visible_card
                        return self._simulator_transition_action(
                            f"add_material_{filled_slots}_{tag}",
                            self._scaled_point(screen, (x, y)),
                            source_page="刻印加材料",
                            target_pages=("刻印加材料", "刻印SSS材料"),
                            reason=(
                                "SSS评级已明确排除且检测到普通材料卡，"
                                "Up标记未识别，使用材料卡轮廓定位"
                            ),
                            in_page_evidence=self._material_observation(
                                filled_slots, []
                            ),
                            transition_kind="material_change",
                        )
                    if filled_slots == 0 or not cost_nonzero:
                        self._imprint_empty_observations = 0
                        return None
                    self._imprint_empty_observations += 1
                    if (
                        self._imprint_empty_observations
                        < self._READINESS_OBSERVATIONS
                    ):
                        return None
                    self._imprint_empty_observations = self._READINESS_OBSERVATIONS
                    return self._simulator_transition_action(
                        "start_synthesis",
                        self._scaled_point(
                            screen, self._GREEN_BTN_POINT
                        ),
                        source_page="刻印加材料",
                        target_pages=("合成确认", "合成结果"),
                        reason=(
                            "Up材料已清空，"
                            f"已填槽位={filled_slots}，费用非零，连续确认=2"
                        ),
                        in_page_evidence=self._material_observation(
                            filled_slots, []
                        ),
                    )
            back = self._back_point(screen)
            if back is None:
                raise UnrecognizedScreen("刻印画面缺少返回箭头")
            # ⚠️ 这里**不**把 state 改成 HERO_LIST：点击还没发生、更没被验收。
            # 回到列表由第 8 段（识别到英雄列表）或者 IMPRINT_ABORTING 分支认账；
            # 提前宣布已回列表会在点击失灵时把下一帧的刻印页当成英雄列表，
            # 进而走到「材料已满 → 点合成」——那一步会消耗材料，不可逆。
            return self._simulator_transition_action(
                "back_to_list",
                back,
                source_page="刻印加材料",
                target_pages=("英雄列表",),
                reason="刻印页已无可加材料，请求返回英雄列表",
            )

        # 7. 筛选面板（级别标签为锚点）
        # 一次性入场：close_filter 后置 _filter_session_done=True，
        # 之后无论模板是否误识别 filter_level_label，都不再进此分支。
        handled, filter_action = self._next_simulator_filter_action(screen)
        if handled:
            return filter_action
        if self._equipment_tab_selected(screen):
            if (
                self._locate(screen, "filter_button") is None
                and not self._hero_list_ready(screen)
            ):
                return None
            self._confirm_page("英雄装备页")
            return HeroAction(
                "select_hero_info_tab",
                self._scaled_point(screen, self._HERO_INFO_TAB_POINT),
                source_page="英雄装备页",
                target_pages=("英雄列表",),
                reason="英雄装备标签为蓝色选中，先切回英雄信息页再开始筛选",
            )
        if not self._hero_info_tab_selected(screen):
            return None

        # 8. 英雄列表：评级是唯一决策依据（SSS 满级 → 跳过，否则看是否有红点）
        # 上一版靠"按钮灰/蓝颜色"和"上一张是不是 SSS"的双保险推断都被颜色变种击穿；
        # 直接看左侧详情面板上的评级字符更稳。
        self.state = HeroSynthState.HERO_LIST
        if self.pending_transmit_target:
            if not self._hero_list_ready(screen):
                return None
            self._confirm_page("英雄列表")
            if not self.transmit_continuity_intact:
                return None
            card_observation = self._hero_identity_fingerprint(screen)
            self._current_card_observation = card_observation
            if self.transmit_phase not in (
                TransmitPhase.PENDING,
                TransmitPhase.OPENING,
            ):
                return None
            if self.transmit_target_observation is None:
                return None
            saved_observation = self.transmit_target_observation
            identity_relation = (
                "一致"
                if card_observation == saved_observation
                else "不同（以未中断的页面返回为准）"
            )
            self._active_card_observation = card_observation
            self.transmit_phase = TransmitPhase.OPENING
            return self._simulator_transition_action(
                "open_transmit_for_current_card",
                self._scaled_point(screen, self._TRANSMIT_ENTRY_POINT),
                source_page="英雄列表",
                target_pages=("传送选择",),
                reason=(
                    "中止刻印后连续返回英雄列表，当前选中项即待传送副本；"
                    f"保存身份={saved_observation}，当前身份={card_observation}，"
                    f"身份关系={identity_relation}"
                ),
                in_page_evidence=card_observation,
            )
        if self._hero_list_ready(screen):
            self._active_card_observation = self._hero_identity_fingerprint(screen)
        struct_n = self._locate_button(screen, self._masked_normal, 0.0)
        struct_g = (
            None
            if self.templates.assume_non_max_rating
            else self._locate_button(screen, self._masked_grey, 0.0)
        )
        hero_class = self._classify_current_hero(screen)
        best = max(
            (m for m in (struct_n, struct_g) if m is not None),
            key=lambda m: m.score,
            default=None,
        )
        if best is not None and best.score >= self._button_struct_min:
            if not self.filter_verified:
                return HeroAction(
                    "open_filter",
                    self._scaled_point(
                        screen, self._FUNNEL_POINT
                    ),
                    source_page="英雄列表",
                    target_pages=(
                        "筛选面板（三星未选中）",
                        "筛选面板（三星已选中）",
                    ),
                    reason="评级按钮结构匹配达标，且本轮尚未确认筛选，打开筛选面板",
                    in_page_evidence=self._hero_identity_fingerprint(screen),
                )
            if hero_class is SafetyClass.SSS:
                self.prev_card_grey = True
                return self._advance_or_finish(screen)
            if hero_class is SafetyClass.UNKNOWN:
                return None
            if self._red_dot_present(screen):
                self.prev_card_grey = False
                self._previous_card_context = None
                self._imprint_empty_observations = 0
                return HeroAction(
                    "open_imprint",
                    best.center,
                    source_page="英雄列表",
                    target_pages=("刻印加材料", "刻印SSS材料"),
                    reason="当前英雄非SSS且刻印按钮红点存在",
                    in_page_evidence=self._hero_identity_fingerprint(screen),
                )
            transmit = self._adjacent_sss_duplicate_transmit_action(screen)
            if transmit is not None:
                return transmit
            self.prev_card_grey = False
            return self._advance_or_finish(screen)

        # 按钮结构匹配不上（视觉变种如绿色菱形）时，只接受明确的 SSS/普通证据；
        # 未知帧停等。
        if not self._hero_list_ready(screen):
            raise UnrecognizedScreen(
                f"英雄合成画面[{state_label(self.state)}]未识别"
            )
        if hero_class is SafetyClass.UNKNOWN:
            return None
        if not self.filter_verified:
            return HeroAction(
                "open_filter",
                self._scaled_point(
                    screen, self._FUNNEL_POINT
                ),
                source_page="英雄列表",
                target_pages=(
                    "筛选面板（三星未选中）",
                    "筛选面板（三星已选中）",
                ),
                reason="本轮尚未确认筛选，打开筛选面板",
                in_page_evidence=self._detail_fingerprint(screen),
            )
        if hero_class is SafetyClass.SSS:
            self.prev_card_grey = True
            return self._advance_or_finish(screen)
        if not self._red_dot_present(screen):
            transmit = self._adjacent_sss_duplicate_transmit_action(screen)
            if transmit is not None:
                return transmit
            self.prev_card_grey = False
            return self._advance_or_finish(screen)
        self.prev_card_grey = False
        self._previous_card_context = None
        self._imprint_empty_observations = 0
        return HeroAction(
            "open_imprint",
            self._scaled_point(screen, self._IMPRINT_BUTTON_POINT),
            source_page="英雄列表",
            target_pages=("刻印加材料", "刻印SSS材料"),
            reason="当前英雄非SSS且刻印按钮红点存在",
            in_page_evidence=self._hero_identity_fingerprint(screen),
        )

    def preview(self, screen: np.ndarray):
        # preview 仅用于 Runner 的两帧稳定判断，不能提交流程状态；正式执行
        # 必须通过下一次 next_action 才可改变筛选、翻卡或完成轮次。
        snapshot = (
            self.state,
            self.completed_cycles,
            self.filter_verified,
            self.prev_card_grey,
            self._filter_session_done,
            self._awaiting_star3_confirmation,
            self._filter_close_pending,
            self._confirmed_page,
            self.transmit_phase,
            self.transmit_target_observation,
            self.transmit_continuity_intact,
            self._active_card_observation,
            self._transmit_reward_confirmed,
            self._imprint_empty_observations,
            self._list_end_observations,
            self._list_end_fingerprint,
            self._current_card_observation,
            self._previous_card_context,
            self._last_screen,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.filter_verified,
                self.prev_card_grey,
                self._filter_session_done,
                self._awaiting_star3_confirmation,
                self._filter_close_pending,
                self._confirmed_page,
                self.transmit_phase,
                self.transmit_target_observation,
                self.transmit_continuity_intact,
                self._active_card_observation,
                self._transmit_reward_confirmed,
                self._imprint_empty_observations,
                self._list_end_observations,
                self._list_end_fingerprint,
                self._current_card_observation,
                self._previous_card_context,
                self._last_screen,
            ) = snapshot


class HeroSynthRunner(ModeRunnerBase):
    """两帧确认的英雄合成 Runner（主循环协议见 ModeRunnerBase）。

    ✅ **2026-10-04 打开转场契约开关**（继 `knights_donation` / `world_boss` /
    `sanctuary` / `labyrinth_stone` 之后的第五条）。开它需要的前置是**字段名对齐**：
    同页证据原先叫自造的 ``source_observation``，而开关读的是基类的
    ``in_page_evidence`` —— 名字不齐时开关开着也**管不到那 12 个同页动作**
    （它们靠 ``target_pages`` 里塞当前页过检查，契约「形式合规、实质没用」）。
    对齐后每个动作都必须带 ``source_page`` ＋ （``target_pages`` 或
    ``in_page_evidence``），少了在**发出前**直接报错。

    开关只管「缺声明会抛错」；判据**准不准**靠 `tests/test_hero_synthesis.py`
    的 AST 静态守 + 各页夹具跑一遍。
    """

    _REQUIRE_TRANSITION_CONTRACT = True
    _MODE_LABEL = "英雄合成"
    _NEXT_CARD_RETRY_SECONDS = 1
    _MATERIAL_RETRY_SECONDS = 5
    _FILTER_ACTIONS = {"open_filter", "select_star3", "close_filter"}
    _BLACK_SCREEN_TIMEOUT_SECONDS = 60.0
    _TIMEOUT_SECONDS = {
        HeroSynthState.HERO_LIST: 60,
        HeroSynthState.FILTER: 45,
        HeroSynthState.IMPRINT_ADD: 90,
        HeroSynthState.IMPRINT_ABORTING: 90,
        HeroSynthState.IMPRINT_CONFIRM: 60,
        HeroSynthState.IMPRINT_REWARD: 45,
        HeroSynthState.TRANSMIT_SELECT: 60,
        HeroSynthState.TRANSMIT_CONFIRM: 45,
        HeroSynthState.TRANSMIT_REWARD: 45,
        HeroSynthState.TRANSMIT_RETURNING: 45,
    }
    _SETTLE_AFTER_NAVIGATION_SECONDS = 3

    def __init__(
        self,
        machine: HeroSynthStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = None,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
    ) -> None:
        if sleep is None:
            from time import sleep as default_sleep

            sleep = default_sleep
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )
        self._needs_navigation_settle = False
        self._card_switch_motion_confirmed = False
        self._card_switch_motion_observer: CardSwitchMotionObserver | None = None
        self._last_imprint_abort_wait_log_at: float | None = None
        self._last_imprint_add_wait_log_at: float | None = None
        self._hero_subpage_wait_started_at: float | None = None
        self._last_hero_subpage_wait_log_at: float | None = None
        # 本次安全策略只作用于模拟器。
        self._ALLOW_UNKNOWN_SCREEN_WAKE = False

    def _is_black_screen(self, screen: np.ndarray) -> bool:
        render = screen[52:] if screen.shape[:2] == (1132, 1982) else screen
        gray = cv2.cvtColor(render, cv2.COLOR_RGB2GRAY)
        return float(gray.mean()) <= 8.0 and float((gray <= 12).mean()) >= 0.985

    def _state_label(self, state: HeroSynthState) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._FILTER_ACTIONS:
            return 5
        if action_name == "abort_imprint_to_transmit":
            return 12
        if action_name == "confirm_transmit":
            return 5
        if action_name.startswith("add_material"):
            return self._MATERIAL_RETRY_SECONDS
        if action_name.startswith("next_card"):
            return self._NEXT_CARD_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _stable_next_action(self, screen: np.ndarray, stable: Any):
        if self._needs_navigation_settle:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 状态=导航后稳定等待 "
                f"秒={self._SETTLE_AFTER_NAVIGATION_SECONDS}"
            )
            self.sleep(self._SETTLE_AFTER_NAVIGATION_SECONDS)
            self._needs_navigation_settle = False
            return super()._stable_next_action(self.runtime.capture(), stable)
        result = super()._stable_next_action(screen, stable)
        if (
            self.machine.state is HeroSynthState.HERO_LIST
            and result is None
        ):
            self._log_hero_subpage_wait(screen)
        elif result is not NOT_STABLE:
            self._hero_subpage_wait_started_at = None
            self._last_hero_subpage_wait_log_at = None
        if self.machine.state is HeroSynthState.IMPRINT_ABORTING and result in (
            NOT_STABLE,
            None,
        ):
            now = self.now()
            if self._last_imprint_abort_wait_log_at is None:
                # 同「刻印页等待」：等待期间不出手 ⇒ 不存帧就查不到现场。
                self._save_wait_frame("imprint_abort_wait_silent", screen)
            if (
                self._last_imprint_abort_wait_log_at is None
                or now - self._last_imprint_abort_wait_log_at >= 10
            ):
                self._log_imprint_abort_evidence(screen, prefix="中止返回等待")
                self._last_imprint_abort_wait_log_at = now
        else:
            self._last_imprint_abort_wait_log_at = None
        # 「刻印加材料」页判不出结果时同样不出手 —— 这里给它一条 10 秒心跳，
        # 否则从进页到 90 秒超时之间日志是完全空白的（2026-10-04 现场）。
        if self.machine.state is HeroSynthState.IMPRINT_ADD and result in (
            NOT_STABLE,
            None,
        ):
            now = self.now()
            if self._last_imprint_add_wait_log_at is None:
                # **首次**进入「等判据出货」时留一张现场帧。
                #
                # 为什么必须存：判据沉默的形态是「什么都不做」，不会走到任何超时
                # 分支 ⇒ 一张图都不会留。2026-10-04 那次能挖出 0.593 纯属侥幸
                # （它最后超时了）；若沉默发生在转场验收里（走「重试 4 次」的正常
                # 路径），我们就彻底盲了。
                # 只存首帧：`save_diagnostic` 自带裁剪，不会淹掉磁盘。
                self._save_wait_frame("imprint_add_judgement_silent", screen)
            if self._last_imprint_add_wait_log_at is None or now - self._last_imprint_add_wait_log_at >= 10:
                self._log_imprint_add_evidence(
                    screen, prefix="刻印页等待（判据没出货）"
                )
                self._last_imprint_add_wait_log_at = now
        else:
            self._last_imprint_add_wait_log_at = None
        return result

    def _log_hero_subpage_wait(self, screen: np.ndarray) -> None:
        now = self.now()
        if self._hero_subpage_wait_started_at is None:
            self._hero_subpage_wait_started_at = now
        if (
            self._last_hero_subpage_wait_log_at is not None
            and now - self._last_hero_subpage_wait_log_at < 10
        ):
            return
        information, equipment = hero_tab_blue_pixel_counts(screen)
        if hero_information_tab_selected(screen):
            subpage = "英雄信息"
        elif hero_equipment_tab_selected(screen):
            subpage = "英雄装备"
        else:
            subpage = "未确认"
        elapsed = now - self._hero_subpage_wait_started_at
        self.runtime.log(
            f"模式={self._MODE_LABEL} 英雄子页等待 "
            f"当前子页={subpage} "
            f"英雄信息蓝色像素={information} "
            f"装备蓝色像素={equipment} "
            f"英雄列表结构={int(self.machine._hero_list_ready(screen))} "
            f"已等待={elapsed:.0f}秒"
        )
        self._last_hero_subpage_wait_log_at = now

    def _log_imprint_abort_evidence(
        self, screen: np.ndarray, *, prefix: str
    ) -> None:
        ready = self.machine._hero_list_ready(screen)
        identity = (
            self.machine._hero_identity_fingerprint(screen) if ready else "未读取"
        )
        self.runtime.log(
            f"模式={self._MODE_LABEL} {prefix} "
            f"英雄列表就绪={int(ready)} "
            f"英雄信息页={int(self.machine._hero_info_tab_selected(screen))} "
            f"详情内容={int(self.machine._detail_content_present(screen))} "
            f"当前身份={identity} "
            f"保存身份={self.machine.transmit_target_observation or '缺失'} "
            f"传送阶段={self.machine.transmit_phase.value} "
            f"连续性={int(self.machine.transmit_continuity_intact)}"
        )

    def _save_wait_frame(self, label: str, screen: np.ndarray) -> None:
        """「等判据出货」时留一张现场帧；**存不下来也不许影响流程**。

        判据沉默的形态是「什么都不做」⇒ 不会走到任何超时分支 ⇒ 一张图都不会留，
        事后只能靠猜（2026-10-04 那次能挖出 0.593 纯属侥幸，它恰好超时了）。
        但诊断是**锦上添花**：没配目录、写盘失败都不该打断主循环，所以整段兜住。
        （先例：`_log_card_switch_diagnostics` 里「未配置诊断目录」的早退。）
        """
        if self.runtime.diagnostic_dir is None:
            return
        try:
            self.runtime.save_diagnostic(label, screen)
        except Exception as error:  # noqa: BLE001 - 诊断失败绝不打断主循环
            self.runtime.log(
                f"模式={self._MODE_LABEL} 等待现场帧保存失败（已忽略）"
                f" 标签={label} 原因={error}"
            )

    def _log_imprint_add_evidence(
        self, screen: np.ndarray, *, prefix: str
    ) -> None:
        """把「刻印加材料」页当前的**判据依据**打出来。

        同一份依据供两条路用，避免两处各写一遍：

        - **超时**（`_log_settled_timeout`）—— 事后定责；
        - **每 10 秒的等待心跳**（`_stable_next_action`）—— 让「一直不出动作」当场可见。

        ⚠️ 为什么必须有等待心跳：这一页判不出结果时 `next_action()` 返回 None，
        **不出手、不打分、不报警**，日志会整整空 90 秒才吐一行超时（2026-10-04
        08:34:30 进页 → 08:36:02 超时，中间一行都没有），人只能事后翻现场帧才知道
        卡在哪。有这行心跳，`SSS页评级=unknown` 这种「判据落进死区」10 秒内就能看出来。
        """
        green = self.machine._green_button_present(screen)
        slots = self.machine._imprint_slots_present(screen)
        up = self.machine._find_up_card(screen)
        visible_card = self.machine._find_visible_material_card(screen)
        self.runtime.log(
            f"模式={self._MODE_LABEL} {prefix} "
            f"完整页面={int(green and slots)} "
            f"绿色按钮={int(green)} 槽位结构={int(slots)} "
            f"已填槽位={self.machine._imprint_filled_slot_count(screen)} "
            f"费用非零={int(self.machine._imprint_cost_nonzero(screen))} "
            f"Up材料={up[2] if up is not None else '未识别'} "
            f"材料卡={visible_card[2] if visible_card is not None else '未识别'} "
            f"SSS页评级={self.machine._classify_material_page(screen).value} "
            f"SSS最高分={self.machine._material_page_sss_score(screen):.3f} "
            f"未知Up材料={int(self.machine._unknown_up_material_present(screen))}"
        )

    def _log_settled_timeout(self, state: HeroSynthState, diagnostic) -> None:
        screen = self.machine._last_screen
        if (
            state is HeroSynthState.IMPRINT_ABORTING
            and screen is not None
        ):
            self._log_imprint_abort_evidence(
                screen,
                prefix=f"中止返回超时 诊断={diagnostic}",
            )
        elif state is HeroSynthState.IMPRINT_ADD and screen is not None:
            self._log_imprint_add_evidence(
                screen, prefix=f"刻印页超时 诊断={diagnostic}"
            )

    def _log_transition_timeout(
        self, action: HeroAction, screen: np.ndarray, confirmed_page: str, diagnostic
    ) -> None:
        super()._log_transition_timeout(
            action, screen, confirmed_page, diagnostic
        )
        if action.name != "open_transmit_for_current_card":
            return
        auto_select = self.machine._locate(screen, "auto_select_label")
        card = self.machine._transmit_target_card(screen)
        auto_select_evidence = (
            f"{auto_select.score:.3f}"
            if auto_select is not None
            else "未识别"
        )
        self.runtime.log(
            f"模式={self._MODE_LABEL} 传送页证据 "
            f"自动选择={auto_select_evidence} "
            f"高亮卡={card[2] if card is not None else '未识别'} "
            f"格子={int(self.machine._transmit_grid_present(screen))} "
            f"绿色按钮={int(self.machine._transmit_green_present(screen))} "
            f"传送阶段={self.machine.transmit_phase.value} "
            f"保存身份={self.machine.transmit_target_observation or '缺失'} "
            f"连续性={int(self.machine.transmit_continuity_intact)}"
        )

    def _is_instant_action(self, action_name: Optional[str]) -> bool:
        # 没有任何动作是「点完立刻生效」的：一律等两帧稳定。
        return False

    def _stable_action_signature(self, preview_action: Any, outcome: Any) -> str:
        if (
            preview_action is not None
            and preview_action.name.startswith("next_card_")
        ):
            decision = (
                "sss" if "当前英雄为SSS" in preview_action.reason else "non_sss"
            )
            return (
                f"next_card:{decision}:"
                f"{preview_action.in_page_evidence}"
            )
        if (
            preview_action is not None
            and preview_action.source_page == "英雄列表"
            and preview_action.in_page_evidence
        ):
            return (
                f"{preview_action.name}:"
                f"{preview_action.in_page_evidence}"
            )
        return super()._stable_action_signature(preview_action, outcome)

    def _after_action_click(self, action: HeroAction) -> None:
        if (
            action.transition_kind != "card_change"
            or self.machine._last_screen is None
        ):
            return
        self.runtime.log(
            f"模式=英雄合成 切换开始 旧身份={action.in_page_evidence or '无法读取'} "
            f"点击={action.point}"
        )
        observer = CardSwitchMotionObserver(self.machine._last_screen)
        self._card_switch_motion_observer = observer
        self._card_switch_motion_confirmed = False
        for _ in range(36):
            self.sleep(1 / 12)
            if observer.update(self.runtime.capture()):
                self._card_switch_motion_confirmed = True
                break

        samples = observer.samples
        peak_dy = max((abs(sample.dy) for sample in samples), default=0.0)
        peak_difference = max(
            (sample.difference for sample in samples), default=0.0
        )
        final_baseline_difference = (
            samples[-1].baseline_difference if samples else 0.0
        )
        evidence = (
            "候选（尚未判定业务成功）"
            if self._card_switch_motion_confirmed
            else "未确认"
        )
        self.runtime.log(
            f"模式=英雄合成 动态证据={evidence} 阶段={observer.phase.value} "
            f"帧数={len(samples)} "
            f"阈值=单帧垂直>={observer.min_vertical_shift:.2f}px/"
            f"累计垂直>={observer.min_accumulated_shift:.2f}px/"
            f"帧差>={observer.departure_difference:.2f}/"
            f"稳定<={observer.settle_difference:.2f}x{observer.required_settle_frames} "
            f"实际=峰值垂直{peak_dy:.3f}px/"
            f"累计垂直{observer.accumulated_shift:.3f}px/"
            f"峰值帧差{peak_difference:.3f}/"
            f"最终基线差{final_baseline_difference:.3f}"
        )
        if self._card_switch_motion_confirmed:
            self.machine.arm_adjacent_sss_context(action)

        final_observation = (
            self.machine._hero_identity_fingerprint(observer.last_screen)
            if observer.last_screen is not None
            else ""
        )
        identity_status = (
            "无法读取"
            if not final_observation
            else (
                "未变化"
                if final_observation == action.in_page_evidence
                else "已变化"
            )
        )
        self.runtime.log(
            f"模式=英雄合成 切换观察 静态身份={identity_status} "
            f"旧身份={action.in_page_evidence or '无法读取'} "
            f"当前身份={final_observation or '无法读取'}"
        )
        if (
            not self._card_switch_motion_confirmed
            or not final_observation
            or final_observation == action.in_page_evidence
        ):
            self._save_card_switch_evidence(action, observer, identity_status)

    def _save_card_switch_evidence(
        self,
        action: HeroAction,
        observer: CardSwitchMotionObserver,
        identity_status: str,
    ) -> None:
        self.runtime.log(
            f"模式=英雄合成 切换诊断 静态身份={identity_status} "
            f"动作={action.name} 证据=逐帧数值与关键截图"
        )
        for sample in observer.samples:
            self.runtime.log(
                f"模式=英雄合成 切换证据帧={sample.frame} "
                f"phase={sample.phase_before.value}->{sample.phase_after.value} "
                f"dx={sample.dx:.3f} dy={sample.dy:.3f} "
                f"response={sample.response:.4f} "
                f"frame_diff={sample.difference:.3f} "
                f"baseline_diff={sample.baseline_difference:.3f} "
                f"accumulated={sample.accumulated_shift:.3f} "
                f"settle={sample.settle_frames} "
                f"vertical={int(sample.vertical)} departed={int(sample.departed)}"
            )
        if self.runtime.diagnostic_dir is None:
            self.runtime.log(
                "模式=英雄合成 切换诊断 截图=未保存 原因=未配置诊断目录"
            )
            return
        frames = (
            ("switch_before", observer.first_screen),
            ("switch_departure", observer.departure_screen),
            ("switch_peak", observer.peak_screen),
            ("switch_final", observer.last_screen),
        )
        for label, screen in frames:
            if screen is not None:
                self.runtime.save_diagnostic(label, screen)

    @staticmethod
    def _parse_observation_text(
        observation: str | None,
    ) -> tuple[int, tuple[int, ...]] | None:
        """解析 ``slots=N;rows=a,b`` 形式的材料观察串。

        抽成独立方法是为了让**两个来源**（动作对象 / 机器每帧现算的
        `_current_material_observation`）走同一套解析 —— 口径不一致会比没修更难查。
        """
        if not observation or not observation.startswith("slots=") or ";rows=" not in observation:
            return None
        slots_text, rows_text = observation.split(";rows=", 1)
        try:
            slots = int(slots_text.removeprefix("slots="))
            rows = tuple(
                int(value) for value in rows_text.split(",") if value
            )
        except ValueError:
            return None
        return slots, rows

    @staticmethod
    def _parse_material_observation(
        action: HeroAction | None,
    ) -> tuple[int, tuple[int, ...]] | None:
        return HeroSynthRunner._parse_observation_text(
            getattr(action, "in_page_evidence", "")
        )

    def _material_transition_completed(
        self, previous_action: HeroAction, current_action: HeroAction | None
    ) -> bool:
        """「材料进槽了没有」：比点击前后的槽位数与材料行位置。

        ⚠️ 当前观察值**不能只从动作对象取**（2026-10-04）。原实现只读
        ``current_action.in_page_evidence``，而这一帧若判据沉默（SSS 徽记落死区
        ⇒ ``next_action`` 返回 ``None``）就取不到值，转场**永远判不出成功** ——
        表现为点完材料后一路重试到超时。这正是 07:22 那次卡死的另一半原因。

        现在优先取动作对象（**保持原语义不变**，正常路径一字不差），取不到时回落到
        `_current_material_observation`（机器每帧现算、与判据解耦，见 `next_action`
        第 6 段）。两种来源解析出的字段完全同构，判定口径不变。
        """
        previous = self._parse_material_observation(previous_action)
        current = self._parse_material_observation(current_action)
        if current is None:
            # 动作对象里取不到（判据沉默 ⇒ 这一帧没生成动作）⇒ 回落到机器
            # 每帧现算的那份。两份串格式同构，走同一个解析方法。
            current = self._parse_observation_text(
                self.machine._current_material_observation
            )
        if previous is None or current is None:
            return False
        previous_slots, previous_rows = previous
        current_slots, current_rows = current
        if current_slots > previous_slots:
            return True
        return bool(previous_rows and min(previous_rows) not in current_rows)

    @staticmethod
    def _transmit_selection_completed(
        previous_action: HeroAction, current_action: HeroAction | None
    ) -> bool:
        return bool(
            previous_action.in_page_evidence == "grid=0"
            and current_action is not None
            and current_action.in_page_evidence == "grid=1"
        )

    def _card_transition_completed(self, previous_action, current_action) -> bool:
        if self._card_switch_motion_confirmed:
            self._card_switch_motion_confirmed = False
            return True
        previous_observation = getattr(previous_action, "in_page_evidence", "")
        current_observation = getattr(current_action, "in_page_evidence", "")
        return bool(
            previous_observation
            and current_observation
            and previous_observation != current_observation
        )

    def _transition_completed(
        self, previous_action, current_action, confirmed_page: str
    ) -> bool:
        if (
            getattr(previous_action, "transition_kind", "")
            == "transmit_selection"
        ):
            return self._transmit_selection_completed(
                previous_action, current_action
            ) or getattr(current_action, "name", "") == "abort_transmit_sss_target"
        if getattr(previous_action, "transition_kind", "") == "material_change":
            return self._material_transition_completed(
                previous_action, current_action
            )
        if getattr(previous_action, "transition_kind", "") == "card_change":
            if current_action is not None:
                if getattr(current_action, "source_page", "") != "英雄列表":
                    return False
            elif confirmed_page not in getattr(previous_action, "target_pages", ()):
                return False
            return self._card_transition_completed(previous_action, current_action)
        return super()._transition_completed(
            previous_action, current_action, confirmed_page
        )

    def _transition_retry_reason(self, previous_action, current_action) -> str:
        if getattr(previous_action, "transition_kind", "") == "card_change":
            return "未观察到右侧列表移动并重新稳定"
        return super()._transition_retry_reason(previous_action, current_action)

    def _transition_success_detail(self, previous_action, current_action) -> str:
        if getattr(previous_action, "transition_kind", "") == "card_change":
            observation = (
                getattr(current_action, "in_page_evidence", "")
                if current_action is not None
                else getattr(self.machine, "_current_card_observation", None)
            )
            evidence = (
                "静态身份变化并连续稳定"
                if observation
                and observation != previous_action.in_page_evidence
                else "静态身份相同，仅由动态证据确认"
            )
            return (
                f"业务切换成功 证据={evidence}；"
                f"旧身份={previous_action.in_page_evidence} "
                f"新身份={observation}"
            )
        return super()._transition_success_detail(previous_action, current_action)

    def _decision_hint(self, action_name: str, state: Any) -> str:
        """让日志解释当前动作的决策原因（评级/红点/选星/状态切换）。"""
        if action_name == "close_sss_material_warning":
            return "刻印页出现 SSS 材料风险提示 → 点关闭后重新观察当前页面"
        if action_name == "select_hero_info_tab":
            return "当前在装备子页 → 切回英雄信息页后再判断 SSS 与刻印红点"
        if action_name.startswith("open_filter"):
            return "筛选面板未开 → 点漏斗打开"
        if action_name == "select_star3":
            return "筛选面板里 3 星未选中 → 点 3 星标签"
        if action_name == "close_filter":
            return "筛选面板里 3 星已选中 → 点漏斗关闭"
        if action_name == "open_imprint":
            return "非满级 + 刻印按钮有红点 → 点刻印记忆按钮开始合成"
        if action_name == "abort_imprint_to_transmit":
            return "材料中发现 SSS → 中止合成，传送当前无等级副本"
        if action_name == "abort_transmit_sss_target":
            return "传送高亮卡检测为 SSS → 返回列表，禁止传送"
        if action_name == "open_transmit_for_current_card":
            return "当前副本待传送 → 打开传送英雄"
        if action_name.startswith("next_card"):
            m = self.machine
            if m._is_max_rating_safe():
                return "当前是 SSS 满级 → 跳到下一张"
            return "当前无红点 → 跳到下一张"
        if action_name == "back_to_list":
            return "合成结束 → 返回英雄列表"
        if action_name == "confirm_synthesis":
            return "确认材料无误 → 点合成按钮"
        if action_name == "close_imprint_result":
            return "合成结果已出现 → 先关闭结果覆盖层"
        if action_name == "start_synthesis":
            return "材料就位 → 启动合成"
        return ""

    def _run_committed_battle(self, *, cycle: int) -> None:
        raise NotImplementedError("英雄合成模式没有战斗阶段")
