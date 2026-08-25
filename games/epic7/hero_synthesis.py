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

from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.runner_base import NOT_STABLE, ModeRunnerBase
from auto_game_unified.games.epic7.hero_transition import (
    CardSwitchMotionObserver,
    SafetyClass,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


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


class FilterObservation(Enum):
    HERO_LIST_FILTER_CLOSED = "hero_list_filter_closed"
    FILTER_OPEN_STAR3_SELECTED = "filter_open_star3_selected"
    FILTER_OPEN_STAR3_UNSELECTED = "filter_open_star3_unselected"
    UNKNOWN = "unknown"


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
class HeroAction:
    name: str
    point: tuple[int, int]
    source_page: str = ""
    target_pages: tuple[str, ...] = ()
    reason: str = ""
    source_observation: str = ""
    transition_kind: str = ""


def imprint_button_saturation(screen: np.ndarray) -> float:
    """刻印按钮圆盘的中位饱和度。

    置灰按钮有两种深浅（实测 S=39~73），正常蓝色按钮 S=112~120；
    饱和度不受亮度变化影响，是灰/蓝状态的可靠分类依据。
    英雄合成状态机与导航的页面识别共用。
    """
    scale_x = screen.shape[1] / HeroSynthStateMachine._REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / HeroSynthStateMachine._REFERENCE_SIZE[1]
    cx = round(HeroSynthStateMachine._BUTTON_CENTER[0] * scale_x)
    cy = round(HeroSynthStateMachine._BUTTON_CENTER[1] * scale_y)
    r = max(8, round(HeroSynthStateMachine._BUTTON_DISC_RADIUS * scale_x))
    crop = screen[cy - r : cy + r, cx - r : cx + r]
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    h, w = crop.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    disc = (xx - w // 2) ** 2 + (yy - h // 2) ** 2 <= r**2
    return float(np.median(hsv[:, :, 1][disc]))


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
    filter_attribute_label: Optional[np.ndarray] = None
    filter_star3_unselected: Optional[np.ndarray] = None
    sss_material: Optional[np.ndarray] = None
    sss_material_warning_title: Optional[np.ndarray] = None
    sss_material_warning_close: Optional[np.ndarray] = None
    imprint_result_title: Optional[np.ndarray] = None
    imprint_result_close: Optional[np.ndarray] = None
    transmit_reward_title: Optional[np.ndarray] = None
    transmit_reward_close: Optional[np.ndarray] = None
    threshold: float = 0.80
    pc_client: bool = False
    assume_non_max_rating: bool = False


def build_hero_templates(template_root: Path) -> HeroTemplates:
    hero = template_root / "hero"
    navigation = template_root / "navigation"
    is_pc = template_root.name == "templates_pc"
    result_title = hero / "imprint_result_title.png"
    result_close = hero / "imprint_result_close.png"
    sss_material = hero / "sss_material.png"
    sss_material_warning_title = hero / "sss_material_warning_title.png"
    sss_material_warning_close = hero / "sss_material_warning_close.png"
    filter_attribute = hero / "filter_attribute_label.png"
    filter_star3_unselected = hero / "filter_star3_unselected.png"
    transmit_reward_title = hero / "transmit_reward_title.png"
    transmit_reward_close = hero / "transmit_reward_close.png"
    return HeroTemplates(
        filter_button=load_template(str(hero / "filter_button.png")),
        filter_level_label=load_template(str(hero / "filter_level_label.png")),
        filter_star3_selected=load_template(str(hero / "filter_star3_selected.png")),
        imprint_normal=load_template(str(hero / "imprint_button_normal.png")),
        imprint_grey=load_template(str(hero / "imprint_button_grey.png")),
        auto_select_label=load_template(str(hero / "auto_select_label.png")),
        story_back=load_template(str(navigation / "story_back.png")),
        rating_sss=load_template(str(hero / "rating_sss.png")),
        filter_attribute_label=(
            load_template(str(filter_attribute))
            if not is_pc and filter_attribute.exists()
            else None
        ),
        filter_star3_unselected=(
            load_template(str(filter_star3_unselected))
            if not is_pc and filter_star3_unselected.exists()
            else None
        ),
        sss_material=(load_template(str(sss_material)) if sss_material.exists() else None),
        sss_material_warning_title=(
            load_template(str(sss_material_warning_title))
            if not is_pc and sss_material_warning_title.exists()
            else None
        ),
        sss_material_warning_close=(
            load_template(str(sss_material_warning_close))
            if not is_pc and sss_material_warning_close.exists()
            else None
        ),
        imprint_result_title=(load_template(str(result_title)) if result_title.exists() else None),
        imprint_result_close=(load_template(str(result_close)) if result_close.exists() else None),
        transmit_reward_title=(
            load_template(str(transmit_reward_title))
            if not is_pc and transmit_reward_title.exists()
            else None
        ),
        transmit_reward_close=(
            load_template(str(transmit_reward_close))
            if not is_pc and transmit_reward_close.exists()
            else None
        ),
        pc_client=is_pc,
        assume_non_max_rating=is_pc,
    )


class HeroSynthStateMachine:
    """英雄合成流程的纯视觉决策状态机。"""

    _REFERENCE_SIZE = (1982, 1132)

    _REGIONS = {
        "filter_button": (1450, 160, 200, 60),
        "filter_level_label": (600, 500, 200, 120),
        "filter_attribute_label": (630, 250, 220, 90),
        "filter_star3_selected": (1050, 590, 180, 90),
        "filter_star3_unselected": (1050, 590, 180, 90),
        "auto_select_label": (780, 990, 260, 100),
        "story_back": (0, 40, 120, 160),
    }
    # 颜色检测区（x, y, w, h）
    _BUTTON_ZONE = (1000, 900, 250, 200)
    _BUTTON_TL = (1028, 925)  # 140x140 按钮模板的标准落位左上角
    _DOT_MASK = (1030, 935, 50, 50)  # 红点角标区（刻印按钮左上角），匹配时双向屏蔽
    _PC_BUTTON_TL = (1045, 920)
    _PC_DOT_MASK = (1065, 935, 32, 32)
    _BUTTON_CENTER = (1098, 995)
    _BUTTON_DISC_RADIUS = 58
    _BUTTON_STRUCT_MIN = 0.50  # 结构匹配下限：确认按钮存在（不限颜色）
    # 评级字符 SSS 在左侧详情面板的中部位置（参考坐标）
    _RATING_REGION = (130, 435, 180, 130)
    _RATING_SSS_MIN = 0.90  # 紧裁剪 SSS 模板：避免把 SS 误判为 SSS
    _REDDOT_ZONE = (1030, 942, 32, 35)  # 模拟器按用户标框收紧的刻印按钮红点区
    _PC_REDDOT_ZONE = (1030, 935, 50, 50)  # PC 保留原红点区
    _MATERIAL_SSS_REGION = (1750, 350, 230, 650)
    _CARD_BELOW_ZONE = (1450, 537, 520, 83)
    _DETAIL_CONTENT_ZONE = (150, 350, 550, 300)
    _HERO_INFO_TAB_ZONE = (0, 150, 127, 105)
    _EQUIPMENT_TAB_ZONE = (0, 255, 127, 105)
    _IMPRINT_SLOT_ZONES = (
        (600, 605, 370, 110),
        (970, 605, 370, 110),
        (600, 725, 370, 110),
        (970, 725, 370, 110),
        (600, 845, 370, 110),
        (970, 845, 370, 110),
    )
    _UP_BADGE_ZONE = (1370, 390, 95, 600)
    _UP_STRIP_ZONE = (1880, 380, 50, 620)
    _IMPRINT_COST_ZONE = (1020, 1025, 75, 50)
    _GREEN_BTN_ZONE = (900, 1020, 500, 90)
    _TRANSMIT_GREEN_ZONE = (1000, 1000, 400, 110)
    _BLUE_BAND_ZONE = (900, 700, 450, 120)
    _GOLD_BAND_ZONE = (650, 700, 330, 120)
    _REWARD_STRIP_ZONE = (880, 825, 160, 35)
    _REWARD_TITLE_REGION = (760, 220, 460, 170)
    _REWARD_CLOSE_REGION = (760, 740, 460, 230)
    _IMPRINT_RESULT_TITLE_REGION = (650, 180, 700, 300)
    _IMPRINT_RESULT_CLOSE_REGION = (650, 730, 700, 300)
    _SSS_WARNING_TITLE_REGION = (500, 420, 1000, 250)
    _SSS_WARNING_CLOSE_REGION = (700, 650, 550, 220)
    _TRANSMIT_STRIP_ZONE = (1400, 200, 250, 800)
    _TRANSMIT_GRID_ZONE = (50, 305, 620, 405)
    _DETAIL_FP_ZONE = (150, 350, 550, 300)
    _SIMULATOR_DETAIL_FP_ZONE = (150, 180, 550, 170)
    _LIST_FP_ZONE = (1450, 200, 532, 780)
    _HERO_IDENTITY_ZONE = (145, 165, 280, 145)

    # 点击点（参考尺寸坐标）
    _FUNNEL_POINT = (1540, 191)
    _STAR3_POINT = (1110, 636)
    # 模拟器截图是 1920x1080 渲染画面上方补 52px 的旧画布；
    # 点击下一张卡的主体区域，不点击战力数字或卡片边界。
    _NEXT_CARD_POINT = (1800, 591)
    _PC_NEXT_CARD_POINT = (1710, 570)
    _IMPRINT_BUTTON_POINT = (1098, 995)  # 刻印按钮硬编码坐标：模板匹配失败时的兜底
    _UP_CARD_X = 1710
    _GREEN_BTN_POINT = (1149, 1078)
    _CONFIRM_FALLBACK_POINT = (1144, 750)
    _TRANSMIT_CARD_X = 1720
    _TRANSMIT_GREEN_POINT = (1203, 1057)
    _REWARD_CLOSE_POINT = (960, 843)
    _IMPRINT_RESULT_CLOSE_POINT = (991, 850)
    _TRANSMIT_ENTRY_POINT = (1735, 1060)
    _HERO_INFO_TAB_POINT = (65, 200)
    _BACK_OFFSET = (-26, -6)
    _PC_FUNNEL_POINT = (1612, 141)
    _PC_STAR3_POINT = (1148, 613)
    _PC_IMPRINT_BUTTON_POINT = (1115, 991)
    _PC_GREEN_BTN_POINT = (1200, 1041)
    _PC_BACK_OFFSET = (11, -4)
    _CARD_BELOW_BRIGHT_MIN = 2000
    _DETAIL_CONTENT_BRIGHT_MIN = 5000
    _SELECTED_TAB_BLUE_MIN = 1000
    _REWARD_STRIP_RANGE = (300, 1500)
    _SSS_MATERIAL_MIN = 0.80  # 材料卡保留少量背景，阈值略低于评级模板
    _SSS_MATERIAL_CLEAR_MAX = 0.55
    _SSS_TEMPLATE_INSET = 4
    _NON_SSS_BUTTON_SATURATION_MIN = 90.0
    _FILTER_ATTRIBUTE_MIN = 0.82
    _FILTER_ATTRIBUTE_SMALL_MIN = 0.75
    _UP_BADGE_MIN_PIXELS = 300
    _FILLED_SLOT_ORANGE_MIN = 5000
    _NONZERO_COST_YELLOW_MIN = 300
    _TRANSMIT_HIGHLIGHT_ZONE = (1600, 200, 380, 800)
    _READINESS_OBSERVATIONS = 2

    def __init__(
        self,
        templates: HeroTemplates,
        initial_state: HeroSynthState = HeroSynthState.HERO_LIST,
    ) -> None:
        self.templates = templates
        self.state = initial_state
        self.completed_cycles = 0
        self.filter_verified = False
        self.prev_card_grey = False
        self._button_tl = self._PC_BUTTON_TL if templates.pc_client else self._BUTTON_TL
        self._dot_mask = self._PC_DOT_MASK if templates.pc_client else self._DOT_MASK
        self._reddot_zone = (
            self._PC_REDDOT_ZONE if templates.pc_client else self._REDDOT_ZONE
        )
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
        self._confirmed_page: str = ""
        self.transmit_phase = TransmitPhase.NONE
        self.transmit_target_observation: Optional[str] = None
        self.transmit_continuity_intact = False
        self._active_card_observation: Optional[str] = None
        self._transmit_reward_confirmed = False
        self._imprint_empty_observations = 0
        self._list_end_observations = 0
        self._list_end_fingerprint: Optional[str] = None
        self._current_card_observation: Optional[str] = None

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
        if self.templates.pc_client:
            return
        self._confirmed_page = label

    def _simulator_transition_action(
        self,
        name: str,
        point: tuple[int, int],
        *,
        source_page: str,
        target_pages: tuple[str, ...],
        reason: str,
        source_observation: str = "",
        transition_kind: str = "",
    ) -> HeroAction:
        if self.templates.pc_client:
            return HeroAction(name, point)
        return HeroAction(
            name,
            point,
            source_page,
            target_pages,
            reason,
            source_observation,
            transition_kind,
        )

    def _mask_dot(self, template: np.ndarray) -> np.ndarray:
        """把模板上红点角标区置零，匹配时与画面同区域一起忽略。"""
        masked = template.copy()
        x = self._dot_mask[0] - self._button_tl[0]
        y = self._dot_mask[1] - self._button_tl[1]
        masked[y : y + self._dot_mask[3], x : x + self._dot_mask[2]] = 0
        return masked

    def _locate_button(
        self, screen: np.ndarray, masked_template: np.ndarray, threshold: float
    ) -> Optional[Match]:
        """按钮区模板匹配；红点角标区双向置零，有/无红点均能稳定匹配。

        在屏幕坐标系内匹配（模板随窗口缩放），返回屏幕局部坐标。
        """
        x, y, w, h = self._scaled_zone(screen, self._BUTTON_ZONE)
        crop = screen[y : y + h, x : x + w].copy()
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        tw = max(1, round(masked_template.shape[1] * scale_x))
        th = max(1, round(masked_template.shape[0] * scale_y))
        interpolation = cv2.INTER_AREA if scale_x < 1 else cv2.INTER_CUBIC
        template = cv2.resize(masked_template, (tw, th), interpolation=interpolation)
        mx = round(self._dot_mask[0] * scale_x) - x
        my = round(self._dot_mask[1] * scale_y) - y
        mw = max(1, round(self._dot_mask[2] * scale_x))
        mh = max(1, round(self._dot_mask[3] * scale_y))
        crop[my : my + mh, mx : mx + mw] = 0
        result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score < threshold:
            return None
        return Match(
            (x + location[0] + tw // 2, y + location[1] + th // 2), float(score)
        )

    # ---- 基础工具 ----

    def _locate(
        self,
        screen: np.ndarray,
        name: str,
        threshold: float | None = None,
        *,
        region_override: tuple[int, int, int, int] | None = None,
    ) -> Optional[Match]:
        return find_template(
            screen,
            getattr(self.templates, name),
            threshold or self.templates.threshold,
            region=region_override or self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def _scaled_point(
        self, screen: np.ndarray, point: tuple[int, int]
    ) -> tuple[int, int]:
        return (
            round(point[0] * screen.shape[1] / self._REFERENCE_SIZE[0]),
            round(point[1] * screen.shape[0] / self._REFERENCE_SIZE[1]),
        )

    def _point(
        self,
        emulator_point: tuple[int, int],
        pc_point: tuple[int, int],
    ) -> tuple[int, int]:
        return pc_point if self.templates.pc_client else emulator_point

    def _scaled_zone(
        self, screen: np.ndarray, zone: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, w, h = zone
        return (
            round(x * scale_x),
            round(y * scale_y),
            round(w * scale_x),
            round(h * scale_y),
        )

    def _zone_hsv(self, screen: np.ndarray, zone: tuple[int, int, int, int]):
        """把限定区缩放到参考尺寸后返回 HSV，保证阈值与坐标都在参考坐标系。"""
        x, y, w, h = self._scaled_zone(screen, zone)
        crop = screen[y : y + h, x : x + w]
        if (w, h) != (zone[2], zone[3]):
            crop = cv2.resize(crop, (zone[2], zone[3]), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)

    def _zone_gray(self, screen: np.ndarray, zone: tuple[int, int, int, int]):
        x, y, w, h = self._scaled_zone(screen, zone)
        crop = screen[y : y + h, x : x + w]
        if (w, h) != (zone[2], zone[3]):
            crop = cv2.resize(crop, (zone[2], zone[3]), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)

    def _blobs(
        self,
        screen: np.ndarray,
        zone: tuple[int, int, int, int],
        lower,
        upper,
        min_area: int,
        max_area: int = 10**9,
        morph: int = 7,
    ) -> list[tuple[int, int, int, int]]:
        """返回限定区内满足颜色的色块（参考坐标系 x,y,w,h）。"""
        hsv = self._zone_hsv(screen, zone)
        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (morph, morph))
        )
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            if min_area <= w * h <= max_area:
                out.append((x + zone[0], y + zone[1], w, h))
        return out

    # ---- 视觉判定 ----

    def _is_max_rating(self, screen: np.ndarray) -> bool:
        """当前选中英雄是否已满级（SSS）。

        只判这一档：红色菱形+SSS 字符模板匹配高分即认定满级，
        其他非满级评级（无评级/C/B/A/S/SS）均允许合成。
        """
        if self.templates.assume_non_max_rating:
            return False
        return (
            self._locate(
                screen, "rating_sss", self._RATING_SSS_MIN, region_override=self._RATING_REGION
            )
            is not None
        )

    def _is_max_rating_safe(self) -> bool:
        """给 runner 层日志用的安全包装：无画面返回 False。"""
        if self._last_screen is None:
            return False
        return self._is_max_rating(self._last_screen)

    def _classify_current_hero(self, screen: np.ndarray) -> SafetyClass:
        if self.templates.assume_non_max_rating:
            return SafetyClass.NON_SSS
        if self._is_max_rating(screen):
            return SafetyClass.SSS
        if (
            imprint_button_saturation(screen)
            >= self._NON_SSS_BUTTON_SATURATION_MIN
        ):
            return SafetyClass.NON_SSS
        return SafetyClass.UNKNOWN

    def _red_dot_present(self, screen: np.ndarray) -> bool:
        # 红点角标实际是橙红色（H 0~25 或 H 170~180），不是纯红
        zone = self._reddot_zone
        zx, zy, zw, zh = zone

        def is_centered_dot(blob: tuple[int, int, int, int]) -> bool:
            x, y, w, h = blob
            local_x, local_y = x - zx, y - zy
            return (
                10 <= w <= 28
                and 10 <= h <= 28
                and 3 <= local_x
                and local_x + w <= zw - 3
                and 3 <= local_y
                and local_y + h <= zh - 3
            )

        blobs = self._blobs(
            screen,
            zone,
            (0, 120, 120),
            (25, 255, 255),
            min_area=20 if self.templates.pc_client else 100,
            max_area=1200,
            morph=3,
        )
        extra = self._blobs(
            screen,
            zone,
            (165, 120, 120),
            (180, 255, 255),
            min_area=20 if self.templates.pc_client else 100,
            max_area=1200,
            morph=3,
        )
        if self.templates.pc_client:
            return bool(blobs or extra)
        return any(is_centered_dot(blob) for blob in (*blobs, *extra))

    def _sss_material_present(self, screen: np.ndarray) -> bool:
        if self.templates.pc_client or self.templates.sss_material is None:
            return False
        inset = self._SSS_TEMPLATE_INSET
        template = self.templates.sss_material[inset:-inset, inset:-inset]
        return find_template(
            screen,
            template,
            self._SSS_MATERIAL_MIN,
            region=self._MATERIAL_SSS_REGION,
            reference_size=self._REFERENCE_SIZE,
        ) is not None

    def _sss_material_warning_close(self, screen: np.ndarray) -> Optional[Match]:
        """返回 SSS 材料风险提示层的关闭控件，避免点击覆盖层下的按钮。"""
        if (
            self.templates.pc_client
            or self.templates.sss_material_warning_title is None
            or self.templates.sss_material_warning_close is None
        ):
            return None
        title = self._locate(
            screen,
            "sss_material_warning_title",
            0.82,
            region_override=self._SSS_WARNING_TITLE_REGION,
        )
        close = self._locate(
            screen,
            "sss_material_warning_close",
            0.82,
            region_override=self._SSS_WARNING_CLOSE_REGION,
        )
        return close if title is not None and close is not None else None

    def _card_below_present(self, screen: np.ndarray) -> bool:
        gray = self._zone_gray(screen, self._CARD_BELOW_ZONE)
        return int((gray > 120).sum()) > self._CARD_BELOW_BRIGHT_MIN

    def _detail_content_present(self, screen: np.ndarray) -> bool:
        gray = self._zone_gray(screen, self._DETAIL_CONTENT_ZONE)
        return int((gray > 45).sum()) > self._DETAIL_CONTENT_BRIGHT_MIN

    def _selected_tab_blue_pixels(
        self, screen: np.ndarray, zone: tuple[int, int, int, int]
    ) -> int:
        hsv = self._zone_hsv(screen, zone)
        return int((cv2.inRange(hsv, (90, 80, 80), (130, 255, 255)) > 0).sum())

    def _equipment_tab_selected(self, screen: np.ndarray) -> bool:
        return bool(
            self._selected_tab_blue_pixels(screen, self._EQUIPMENT_TAB_ZONE)
            >= self._SELECTED_TAB_BLUE_MIN
            and self._selected_tab_blue_pixels(screen, self._HERO_INFO_TAB_ZONE)
            < self._SELECTED_TAB_BLUE_MIN
        )

    def _hero_info_tab_selected(self, screen: np.ndarray) -> bool:
        return bool(
            self._selected_tab_blue_pixels(screen, self._HERO_INFO_TAB_ZONE)
            >= self._SELECTED_TAB_BLUE_MIN
            and self._selected_tab_blue_pixels(screen, self._EQUIPMENT_TAB_ZONE)
            < self._SELECTED_TAB_BLUE_MIN
        )

    def _up_badge_rows(self, screen: np.ndarray) -> list[tuple[int, int]]:
        """返回右侧材料卡左边真实 Up! 标记的纵向范围。

        卡片最右侧会被不同角色立绘遮住，不能用于判断。Up! 标记位于卡片
        左侧固定窄区；同一标记的橙色像素可能被文字间隙分成数段，因此按
        纵向间隔聚类。
        """
        hsv = self._zone_hsv(screen, self._UP_BADGE_ZONE)
        mask = cv2.inRange(hsv, (0, 110, 140), (30, 255, 255))
        row_counts = (mask > 0).sum(axis=1)
        active_rows = np.flatnonzero(row_counts >= 3)
        if active_rows.size == 0:
            return []

        groups: list[tuple[int, int]] = []
        start = previous = int(active_rows[0])
        for value in active_rows[1:]:
            current = int(value)
            if current - previous > 30:
                groups.append((start, previous + 1))
                start = current
            previous = current
        groups.append((start, previous + 1))

        zone_y = self._UP_BADGE_ZONE[1]
        return [
            (start + zone_y, end + zone_y)
            for start, end in groups
            if int((mask[start:end] > 0).sum()) >= self._UP_BADGE_MIN_PIXELS
        ]

    def _up_strip_blobs(self, screen: np.ndarray) -> list[tuple[int, int, int, int]]:
        """PC 版右侧卡片条；其布局不会与中间材料槽重叠。"""
        blobs = self._blobs(
            screen,
            self._UP_STRIP_ZONE,
            (5, 120, 160),
            (25, 255, 255),
            min_area=100,
            morph=5,
        )
        return [blob for blob in blobs if blob[3] >= 60]

    def _find_up_card(self, screen: np.ndarray) -> Optional[tuple[int, int, str]]:
        """返回最上方的普通 Up 材料卡，SSS 材料永远不可点击。"""
        if self.templates.pc_client:
            cards = self._up_strip_blobs(screen)
            if not cards:
                return None
            top = min(cards, key=lambda blob: blob[1])
            return (self._UP_CARD_X, top[1] + top[3] // 2, str(len(cards)))

        ordinary_rows = self._ordinary_up_rows(screen)
        if not ordinary_rows:
            return None
        top = min(ordinary_rows)
        return (self._UP_CARD_X, top[0] + 4, str(len(ordinary_rows)))

    def _ordinary_up_rows(
        self, screen: np.ndarray
    ) -> list[tuple[int, int]]:
        return [
            row
            for row in self._up_badge_rows(screen)
            if self._classify_material_row(screen, row) is SafetyClass.NON_SSS
        ]

    @staticmethod
    def _material_observation(
        filled_slots: int, rows: list[tuple[int, int]]
    ) -> str:
        centers = ",".join(str((start + end) // 2) for start, end in rows)
        return f"slots={filled_slots};rows={centers}"

    def _row_is_sss_material(
        self, screen: np.ndarray, row: tuple[int, int]
    ) -> bool:
        """在同一张材料卡的评级区检查 SSS，避免把其它卡的 SSS 串到当前卡。"""
        return self._classify_material_row(screen, row) is SafetyClass.SSS

    def _material_sss_score(
        self,
        screen: np.ndarray,
        row: tuple[int, int],
        *,
        region_override: tuple[int, int, int, int] | None = None,
    ) -> float:
        if self.templates.pc_client or self.templates.sss_material is None:
            return -1.0
        start, end = row
        region = region_override or (
            self._MATERIAL_SSS_REGION[0],
            max(self._MATERIAL_SSS_REGION[1], start - 45),
            self._MATERIAL_SSS_REGION[2],
            min(self._MATERIAL_SSS_REGION[3], end - start + 90),
        )
        inset = self._SSS_TEMPLATE_INSET
        # 去掉模板边缘的卡片背景，避免普通传送卡在背景纹理上得到 0.55+。
        template = self.templates.sss_material[
            inset:-inset, inset:-inset
        ]
        match = find_template(
            screen,
            template,
            -1.0,
            region=region,
            reference_size=self._REFERENCE_SIZE,
        )
        return match.score if match is not None else -1.0

    def _classify_material_row(
        self, screen: np.ndarray, row: tuple[int, int]
    ) -> SafetyClass:
        score = self._material_sss_score(screen, row)
        if score >= self._SSS_MATERIAL_MIN:
            return SafetyClass.SSS
        if score <= self._SSS_MATERIAL_CLEAR_MAX:
            return SafetyClass.NON_SSS
        return SafetyClass.UNKNOWN

    def _unknown_up_material_present(self, screen: np.ndarray) -> bool:
        return any(
            self._classify_material_row(screen, row) is SafetyClass.UNKNOWN
            for row in self._up_badge_rows(screen)
        )

    def _green_button_present(self, screen: np.ndarray) -> bool:
        blobs = self._blobs(
            screen,
            self._GREEN_BTN_ZONE,
            (40, 80, 100),
            (90, 255, 255),
            min_area=3000,
        )
        return any(w > 300 for _, _, w, _ in blobs)

    def _imprint_slots_present(self, screen: np.ndarray) -> bool:
        """确认刻印页的六个材料槽已经渲染，避免绿按钮先出现时误判。"""
        for zone in self._IMPRINT_SLOT_ZONES:
            gray = self._zone_gray(screen, zone)
            edges = cv2.Canny(gray, 50, 150)
            if int((edges > 0).sum()) < 700:
                return False
        return True

    def _imprint_filled_slot_count(self, screen: np.ndarray) -> int:
        """统计中间真正放入材料卡的槽位；空槽轮廓不算材料。"""
        filled = 0
        for zone in self._IMPRINT_SLOT_ZONES:
            hsv = self._zone_hsv(screen, zone)
            orange = cv2.inRange(hsv, (5, 100, 120), (30, 255, 255))
            if int((orange > 0).sum()) >= self._FILLED_SLOT_ORANGE_MIN:
                filled += 1
        return filled

    def _imprint_cost_nonzero(self, screen: np.ndarray) -> bool:
        """费用由 0 变为 900/1800…，作为材料已入槽的第二个独立证据。"""
        hsv = self._zone_hsv(screen, self._IMPRINT_COST_ZONE)
        yellow = cv2.inRange(hsv, (15, 100, 150), (40, 255, 255))
        return int((yellow > 0).sum()) >= self._NONZERO_COST_YELLOW_MIN

    def _transmit_green_present(self, screen: np.ndarray) -> bool:
        blobs = self._blobs(
            screen,
            self._TRANSMIT_GREEN_ZONE,
            (40, 80, 100),
            (90, 255, 255),
            min_area=3000,
        )
        return any(w > 250 for _, _, w, _ in blobs)

    def _confirm_button(self, screen: np.ndarray) -> Optional[tuple[int, int]]:
        """弹窗确认按钮：必须同时存在蓝色确认带和金色取消带（联合锚点）。

        只认蓝色带会在列表等画面上误判（实测误点过英雄立绘），金色取消
        带是弹窗独有结构，两者同时出现才认定为确认弹窗。
        """
        blobs = self._blobs(
            screen,
            self._BLUE_BAND_ZONE,
            (95, 100, 130),
            (125, 255, 255),
            min_area=150 * 15,
        )
        bands = [b for b in blobs if b[2] >= 150 and 15 <= b[3] <= 70]
        if not bands:
            return None
        gold = self._blobs(
            screen,
            self._GOLD_BAND_ZONE,
            (10, 80, 100),
            (30, 255, 255),
            min_area=100,
        )
        if not any(w >= 120 and 12 <= h <= 70 for _, _, w, h in gold):
            return None
        band = max(bands, key=lambda b: b[2])
        return (band[0] + band[2] // 2, band[1] + band[3] // 2)

    def _reward_strip_present(self, screen: np.ndarray) -> bool:
        gray = self._zone_gray(screen, self._REWARD_STRIP_ZONE)
        count = int((gray > 130).sum())
        low, high = self._REWARD_STRIP_RANGE
        return low <= count <= high

    def _transmit_reward_present(self, screen: np.ndarray) -> bool:
        if self.templates.pc_client:
            return self._reward_strip_present(screen)
        if (
            self.templates.transmit_reward_title is None
            or self.templates.transmit_reward_close is None
        ):
            return False
        title = self._locate(
            screen,
            "transmit_reward_title",
            0.90,
            region_override=self._REWARD_TITLE_REGION,
        )
        close = self._locate(
            screen,
            "transmit_reward_close",
            0.92,
            region_override=self._REWARD_CLOSE_REGION,
        )
        return (
            title is not None
            and close is not None
            and self._reward_strip_present(screen)
        )

    def _imprint_result_present(self, screen: np.ndarray) -> bool:
        if (
            self.templates.imprint_result_title is None
            or self.templates.imprint_result_close is None
        ):
            return False
        title = self._locate(
            screen,
            "imprint_result_title",
            0.82,
            region_override=self._IMPRINT_RESULT_TITLE_REGION,
        )
        close = self._locate(
            screen,
            "imprint_result_close",
            0.78,
            region_override=self._IMPRINT_RESULT_CLOSE_REGION,
        )
        return title is not None and close is not None

    def _transmit_grid_filled(self, screen: np.ndarray) -> bool:
        gray = self._zone_gray(screen, self._TRANSMIT_GRID_ZONE)
        return int((gray > 120).sum()) > 5000

    def _transmit_grid_present(self, screen: np.ndarray) -> bool:
        gray = self._zone_gray(screen, self._TRANSMIT_GRID_ZONE)
        return int((gray > 45).sum()) > 5000

    def _transmit_page_ready(self, screen: np.ndarray) -> bool:
        return bool(
            self._locate(screen, "auto_select_label", 0.85)
            and self._transmit_target_card(screen) is not None
            and self._transmit_grid_present(screen)
            and self._transmit_green_present(screen)
        )

    def _transmit_target_card(self, screen: np.ndarray) -> Optional[tuple[int, int, str]]:
        """传送选择界面：在卡片右侧的蓝色高亮行内定位当前卡。"""
        hsv = self._zone_hsv(screen, self._TRANSMIT_HIGHLIGHT_ZONE)
        mask = cv2.inRange(hsv, (95, 120, 140), (125, 255, 255))
        rows = mask.sum(axis=1)
        segs, in_seg = [], False
        for i, v in enumerate(rows):
            if v > 60 and not in_seg:
                start, in_seg = i, True
            elif v <= 60 and in_seg:
                if 50 <= i - start <= 350:
                    segs.append((start, i))
                in_seg = False
        if in_seg and 50 <= len(rows) - start <= 350:
            segs.append((start, len(rows)))
        if not segs:
            return None
        start, end = max(segs, key=lambda segment: segment[1] - segment[0])
        y = self._TRANSMIT_HIGHLIGHT_ZONE[1] + (start + end) // 2
        return (self._TRANSMIT_CARD_X, y, str(y))

    def _transmit_target_is_sss(
        self, screen: np.ndarray, card: tuple[int, int, str]
    ) -> bool:
        """只检查当前高亮行，禁止把其它列表卡片的 SSS 当成目标。"""
        return self._classify_transmit_target(screen, card) is SafetyClass.SSS

    def _classify_transmit_target(
        self,
        screen: np.ndarray,
        card: tuple[int, int, str] | None,
    ) -> SafetyClass:
        if self.templates.pc_client:
            return SafetyClass.NON_SSS
        if card is None:
            return SafetyClass.UNKNOWN
        _, y, _ = card
        region = (1500, max(200, y - 70), 480, 140)
        score = self._material_sss_score(
            screen,
            (y - 25, y + 25),
            region_override=region,
        )
        if score >= self._SSS_MATERIAL_MIN:
            return SafetyClass.SSS
        if score <= self._SSS_MATERIAL_CLEAR_MAX:
            return SafetyClass.NON_SSS
        return SafetyClass.UNKNOWN

    def _hero_list_ready(self, screen: np.ndarray) -> bool:
        """确认返回动画已结束，避免把刻印页过渡帧当成英雄列表。"""
        struct_n = self._locate_button(screen, self._masked_normal, 0.0)
        struct_g = (
            None
            if self.templates.assume_non_max_rating
            else self._locate_button(screen, self._masked_grey, 0.0)
        )
        best = max(
            (m for m in (struct_n, struct_g) if m is not None),
            key=lambda m: m.score,
            default=None,
        )
        base_ready = bool(
            best is not None and best.score >= self._BUTTON_STRUCT_MIN
        ) or self._is_max_rating(screen) or self._red_dot_present(screen)
        return base_ready and (
            self.templates.pc_client or self._detail_content_present(screen)
        )

    def _observe_filter(self, screen: np.ndarray) -> FilterObservation:
        """Classify only filter states backed by explicit simulator evidence."""
        if (
            self.templates.filter_attribute_label is None
            or self.templates.filter_star3_unselected is None
        ):
            return FilterObservation.UNKNOWN

        scale = min(
            screen.shape[1] / self._REFERENCE_SIZE[0],
            screen.shape[0] / self._REFERENCE_SIZE[1],
        )
        attribute_min = (
            self._FILTER_ATTRIBUTE_SMALL_MIN
            if scale <= 0.55
            else self._FILTER_ATTRIBUTE_MIN
        )
        level = self._locate(screen, "filter_level_label", 0.80)
        attribute = self._locate(screen, "filter_attribute_label", attribute_min)
        panel_open = level is not None and attribute is not None
        if panel_open:
            if self._locate(screen, "filter_star3_selected", 0.90) is not None:
                return FilterObservation.FILTER_OPEN_STAR3_SELECTED
            if self._locate(screen, "filter_star3_unselected", 0.90) is not None:
                return FilterObservation.FILTER_OPEN_STAR3_UNSELECTED
            return FilterObservation.UNKNOWN
        if level is not None or attribute is not None:
            return FilterObservation.UNKNOWN
        if (
            self._locate(screen, "filter_button", 0.80) is not None
            and self._hero_list_ready(screen)
        ):
            return FilterObservation.HERO_LIST_FILTER_CLOSED
        return FilterObservation.UNKNOWN

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
                reason="级别与属性锚点存在，三星深色按钮存在",
            )

        if observation is FilterObservation.FILTER_OPEN_STAR3_SELECTED:
            self.state = HeroSynthState.FILTER
            self._filter_close_pending = True
            return True, HeroAction(
                "close_filter",
                self._scaled_point(screen, self._FUNNEL_POINT),
                source_page="筛选面板（三星已选中）",
                target_pages=("英雄列表",),
                reason="级别与属性锚点存在，三星白底按钮存在",
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
                    reason="漏斗与刻印按钮存在，筛选面板锚点均消失",
                )
            return False, None

        if self.state is HeroSynthState.FILTER or self._filter_close_pending:
            return True, None
        return False, None

    def _back_action(self, screen: np.ndarray) -> Optional[HeroAction]:
        back = self._locate(screen, "story_back", 0.90)
        if back is None:
            return None
        # match.center 已是屏幕坐标，仅做箭头热区向左偏移
        offset = self._point(self._BACK_OFFSET, self._PC_BACK_OFFSET)
        point = (back.center[0] + offset[0], back.center[1] + offset[1])
        return HeroAction("back_to_list", point)

    # ---- 遍历决策 ----

    def _detail_fingerprint(self, screen: np.ndarray) -> str:
        """模拟器用标题和选中卡列表确认确实翻到了下一张；PC 保持原指纹。"""
        if self.templates.pc_client:
            gray = self._zone_gray(screen, self._DETAIL_FP_ZONE)
            gray = cv2.GaussianBlur(gray, (11, 11), 0)
            small = cv2.resize(gray, (5, 3), interpolation=cv2.INTER_AREA)
            return hashlib.sha1((small // 32).astype(np.uint8).tobytes()).hexdigest()[:8]

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
        dot = "D" if self._red_dot_present(screen) else "N"
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
                screen, self._point(self._NEXT_CARD_POINT, self._PC_NEXT_CARD_POINT)
            ),
            source_page="" if self.templates.pc_client else "英雄列表",
            target_pages=() if self.templates.pc_client else ("英雄列表",),
            reason=(
                ""
                if self.templates.pc_client
                else f"{skip_reason}，详情指纹={fp}，等待下一英雄或列表末尾"
            ),
            source_observation=(
                "" if self.templates.pc_client else self._hero_identity_fingerprint(screen)
            ),
            transition_kind="" if self.templates.pc_client else "card_change",
        )

    # ---- 主决策 ----

    def next_action(self, screen: np.ndarray) -> Optional[HeroAction]:
        self._last_screen = screen
        if not self.templates.pc_client:
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
            transmit_ctx = self._locate(screen, "auto_select_label", 0.85) is not None
            if transmit_ctx or self.state.value.startswith("transmit"):
                if (
                    not self.templates.pc_client
                    and (
                        self.transmit_phase is not TransmitPhase.SELECTING
                        or not self.transmit_continuity_intact
                    )
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
        if self.state is HeroSynthState.IMPRINT_ABORTING:
            if (
                self._green_button_present(screen)
                or self._sss_material_present(screen)
                or self._find_up_card(screen) is not None
            ):
                return None
            if not self._hero_list_ready(screen):
                return None
            self.state = HeroSynthState.HERO_LIST

        if (
            self.transmit_phase is TransmitPhase.RETURNING
            or self.state is HeroSynthState.TRANSMIT_RETURNING
        ):
            self.state = HeroSynthState.TRANSMIT_RETURNING
            if self._locate(screen, "auto_select_label", 0.85):
                self._confirm_page("传送选择")
                back = self._back_action(screen)
                if back is not None:
                    return self._simulator_transition_action(
                        "back_to_list",
                        back.point,
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
        if self._locate(screen, "auto_select_label", 0.85):
            if not self.templates.pc_client and (
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
            target_class = self._classify_transmit_target(screen, card)
            if target_class is SafetyClass.SSS:
                back = self._back_action(screen)
                if back is None:
                    raise UnrecognizedScreen("传送高亮卡为 SSS 且缺少返回箭头")
                self.transmit_phase = TransmitPhase.RETURNING
                self.state = HeroSynthState.TRANSMIT_RETURNING
                return self._simulator_transition_action(
                    "abort_transmit_sss_target",
                    back.point,
                    source_page="传送选择",
                    target_pages=("英雄列表",),
                    reason="传送高亮目标为SSS，禁止传送并返回列表",
                )
            if target_class is SafetyClass.UNKNOWN:
                return None
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
                    source_observation="grid=1",
                )
            if card is not None:
                x, y, tag = card
                return self._simulator_transition_action(
                    f"select_transmit_card_{tag}",
                    self._scaled_point(screen, (x, y)),
                    source_page="传送选择",
                    target_pages=("传送选择",),
                    reason="高亮目标已确认但传送格尚未填入",
                    source_observation="grid=0",
                    transition_kind="transmit_selection",
                )
            return None

        if (
            self.state is HeroSynthState.IMPRINT_CONFIRM
            and not self.templates.pc_client
            and self._back_action(screen) is not None
        ):
            raise UnrecognizedScreen("合成结果覆盖层未完整识别，禁止点击底层返回")

        # 6. 刻印界面（绿色刻印按钮与完整材料槽共同作为页面证据）
        green_button_present = self._green_button_present(screen)
        complete_imprint_page = (
            green_button_present and self._imprint_slots_present(screen)
        )
        if (
            not self.templates.pc_client
            and self.state is HeroSynthState.IMPRINT_REWARD
        ):
            if complete_imprint_page:
                self._confirm_page("合成后刻印页")
                back = self._back_action(screen)
                if back is None:
                    return None
                return self._simulator_transition_action(
                    "back_to_list",
                    back.point,
                    source_page="合成后刻印页",
                    target_pages=("英雄列表",),
                    reason="结果覆盖层消失且刻印页返回箭头存在",
                )
            if not self._hero_list_ready(screen):
                return None
            self._confirm_page("英雄列表")
            self.state = HeroSynthState.HERO_LIST

        sss_material_present = False
        up = None
        if complete_imprint_page:
            if (
                not self.templates.pc_client
                and self.state is HeroSynthState.HERO_LIST
            ):
                self.state = HeroSynthState.IMPRINT_ADD
            sss_material_present = self._sss_material_present(screen)
            if sss_material_present:
                self._confirm_page("刻印SSS材料")
            else:
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
            back = self._back_action(screen)
            if back is None:
                raise UnrecognizedScreen("发现 SSS 材料但刻印页面缺少返回箭头")
            self.state = HeroSynthState.IMPRINT_ABORTING
            return self._simulator_transition_action(
                "abort_imprint_to_transmit",
                back.point,
                source_page="刻印SSS材料",
                target_pages=("英雄列表",),
                reason="发现SSS材料，保存当前英雄身份并中止刻印",
            )
        if (
            self.state is HeroSynthState.IMPRINT_ABORTING
            and complete_imprint_page
            and sss_material_present
        ):
            back = self._back_action(screen)
            if back is None:
                raise UnrecognizedScreen("发现 SSS 材料但刻印页面缺少返回箭头")
            return self._simulator_transition_action(
                "abort_imprint_to_transmit",
                back.point,
                source_page="刻印SSS材料",
                target_pages=("英雄列表",),
                reason="SSS材料页仍存在，继续请求返回英雄列表",
            )
        if self.state is HeroSynthState.IMPRINT_ADD and not complete_imprint_page:
            self._imprint_empty_observations = 0
            return None
        if (
            not self.templates.pc_client
            and green_button_present
            and not complete_imprint_page
        ):
            return None
        if green_button_present and (
            self.templates.pc_client or complete_imprint_page
        ):
            filled_slots = self._imprint_filled_slot_count(screen)
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
                    source_observation=material_observation,
                    transition_kind="material_change",
                )
            if self.state is HeroSynthState.IMPRINT_ADD:
                # “没看到 Up”只表示识别结果为空，不表示材料已加完。必须看到
                # 中间槽内已有材料，且费用从 0 变为非 0，才允许进入合成。
                if filled_slots == 0 or not self._imprint_cost_nonzero(screen):
                    self._imprint_empty_observations = 0
                    return None
                self._imprint_empty_observations += 1
                if (
                    self._imprint_empty_observations
                    < self._READINESS_OBSERVATIONS
                ):
                    return None
                if self.templates.pc_client:
                    self._imprint_empty_observations = 0
                    self.state = HeroSynthState.IMPRINT_CONFIRM
                else:
                    self._imprint_empty_observations = self._READINESS_OBSERVATIONS
                return self._simulator_transition_action(
                    "start_synthesis",
                    self._scaled_point(
                        screen, self._point(self._GREEN_BTN_POINT, self._PC_GREEN_BTN_POINT)
                    ),
                    source_page="刻印加材料",
                    target_pages=("合成确认", "合成结果"),
                    reason=(
                        "Up材料已清空，"
                        f"已填槽位={filled_slots}，费用非零，连续确认=2"
                    ),
                    source_observation=self._material_observation(
                        filled_slots, []
                    ),
                )
            back = self._back_action(screen)
            if back is None:
                raise UnrecognizedScreen("刻印画面缺少返回箭头")
            self.state = HeroSynthState.HERO_LIST
            return back

        # 7. 筛选面板（级别标签为锚点）
        # 一次性入场：close_filter 后置 _filter_session_done=True，
        # 之后无论模板是否误识别 filter_level_label，都不再进此分支。
        if not self.templates.pc_client:
            handled, filter_action = self._next_simulator_filter_action(screen)
            if handled:
                return filter_action
            if self._equipment_tab_selected(screen):
                if self._locate(screen, "filter_button", 0.80) is None:
                    return None
                self._confirm_page("英雄装备页")
                return HeroAction(
                    "select_hero_info_tab",
                    self._scaled_point(screen, self._HERO_INFO_TAB_POINT),
                    source_page="英雄装备页",
                    target_pages=("英雄列表",),
                    reason="左侧装备标签为蓝色选中态，先切回英雄信息页",
                )
            if not self._hero_info_tab_selected(screen):
                return None

        filter_level = self._locate(screen, "filter_level_label")
        star3_selected = self._locate(screen, "filter_star3_selected", 0.90)
        if (
            self.templates.pc_client
            and not self._filter_session_done
            and self._awaiting_star3_confirmation
        ):
            self.state = HeroSynthState.FILTER
            if star3_selected is not None:
                self._awaiting_star3_confirmation = False
                self.filter_verified = True
                self._filter_session_done = True
                return HeroAction(
                    "close_filter",
                    self._scaled_point(
                        screen, self._point(self._FUNNEL_POINT, self._PC_FUNNEL_POINT)
                    ),
                )
            if filter_level is None:
                return None
            return HeroAction(
                "select_star3",
                self._scaled_point(
                    screen, self._point(self._STAR3_POINT, self._PC_STAR3_POINT)
                ),
            )
        if (
            self.templates.pc_client
            and not self._filter_session_done
            and (filter_level or star3_selected)
        ):
            self.state = HeroSynthState.FILTER
            if star3_selected is None:
                self._awaiting_star3_confirmation = True
                self.filter_verified = False
                return HeroAction(
                    "select_star3",
                    self._scaled_point(
                        screen, self._point(self._STAR3_POINT, self._PC_STAR3_POINT)
                    ),
                )
            if not self.filter_verified:
                # 首次确认星3已选，关闭筛选面板（一次性入场标志，关闭后永远不再进筛选分支）
                self.filter_verified = True
                self._filter_session_done = True
                return HeroAction(
                    "close_filter",
                    self._scaled_point(
                        screen, self._point(self._FUNNEL_POINT, self._PC_FUNNEL_POINT)
                    ),
                )
            # filter_level_label 仍然匹配：toggle_filter 已发过，重复点击会让漏斗
            # 切换回 open；不再相信筛选面板分支，直接落到英雄列表。
            self._filter_session_done = True
            self.filter_verified = False
            self.state = HeroSynthState.HERO_LIST

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
                source_observation=card_observation,
            )
        if not self.templates.pc_client and self._hero_list_ready(screen):
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
        if best is not None and best.score >= self._BUTTON_STRUCT_MIN:
            if not self.filter_verified:
                return HeroAction(
                    "open_filter",
                    self._scaled_point(
                        screen, self._point(self._FUNNEL_POINT, self._PC_FUNNEL_POINT)
                    ),
                    source_observation=(
                        self._hero_identity_fingerprint(screen)
                        if not self.templates.pc_client
                        else ""
                    ),
                )
            if hero_class is SafetyClass.SSS:
                self.prev_card_grey = True
                return self._advance_or_finish(screen)
            if hero_class is SafetyClass.UNKNOWN:
                return None
            if self._red_dot_present(screen):
                self.prev_card_grey = False
                if self.templates.pc_client:
                    self.state = HeroSynthState.IMPRINT_ADD
                self._imprint_empty_observations = 0
                return HeroAction(
                    "open_imprint",
                    best.center,
                    source_page="" if self.templates.pc_client else "英雄列表",
                    target_pages=(
                        ()
                        if self.templates.pc_client
                        else ("刻印加材料", "刻印SSS材料")
                    ),
                    reason=(
                        ""
                        if self.templates.pc_client
                        else "当前英雄非SSS且刻印按钮红点存在"
                    ),
                    source_observation=(
                        self._hero_identity_fingerprint(screen)
                        if not self.templates.pc_client
                        else ""
                    ),
                )
            self.prev_card_grey = False
            return self._advance_or_finish(screen)

        # 按钮结构匹配不上（视觉变种如绿色菱形）时，模拟器只接受明确
        # 的 SSS/普通证据；未知帧停等。PC 保持原来的线索门槛。
        if not self.templates.pc_client and not self._hero_list_ready(screen):
            raise UnrecognizedScreen(
                f"英雄合成画面[{state_label(self.state)}]未识别"
            )
        if self.templates.pc_client and not (
            self._is_max_rating(screen) or self._red_dot_present(screen)
        ):
            raise UnrecognizedScreen(
                f"英雄合成画面[{state_label(self.state)}]未识别"
            )
        if hero_class is SafetyClass.UNKNOWN:
            return None
        if not self.filter_verified:
            return HeroAction(
                "open_filter",
                self._scaled_point(
                    screen, self._point(self._FUNNEL_POINT, self._PC_FUNNEL_POINT)
                ),
                source_observation=(
                    self._detail_fingerprint(screen)
                    if not self.templates.pc_client
                    else ""
                ),
            )
        if hero_class is SafetyClass.SSS:
            self.prev_card_grey = True
            return self._advance_or_finish(screen)
        if not self._red_dot_present(screen):
            self.prev_card_grey = False
            return self._advance_or_finish(screen)
        self.prev_card_grey = False
        if self.templates.pc_client:
            self.state = HeroSynthState.IMPRINT_ADD
        self._imprint_empty_observations = 0
        return HeroAction(
            "open_imprint",
            self._scaled_point(
                screen,
                self._point(
                    self._IMPRINT_BUTTON_POINT, self._PC_IMPRINT_BUTTON_POINT
                ),
            ),
            source_page="" if self.templates.pc_client else "英雄列表",
            target_pages=(
                ()
                if self.templates.pc_client
                else ("刻印加材料", "刻印SSS材料")
            ),
            reason=(
                ""
                if self.templates.pc_client
                else "当前英雄非SSS且刻印按钮红点存在"
            ),
            source_observation=(
                self._hero_identity_fingerprint(screen)
                if not self.templates.pc_client
                else ""
            ),
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
                self._last_screen,
            ) = snapshot


class HeroSynthRunner(ModeRunnerBase):
    """两帧确认的英雄合成 Runner（主循环协议见 ModeRunnerBase）。"""

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
        recovery: Callable[[], None] | None = None,
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
            recovery=recovery,
            recovery_gate=recovery_gate,
        )
        self._needs_navigation_settle = machine.templates.pc_client
        self._card_switch_motion_confirmed = False
        self._card_switch_motion_observer: CardSwitchMotionObserver | None = None
        self._last_imprint_abort_wait_log_at: float | None = None
        # 本次安全策略只作用于模拟器；PC 保持既有未知画面唤醒行为。
        if machine.templates.pc_client:
            self._BLACK_SCREEN_TIMEOUT_SECONDS = None
        self._ALLOW_UNKNOWN_SCREEN_WAKE = machine.templates.pc_client

    def _is_black_screen(self, screen: np.ndarray) -> bool:
        if self.machine.templates.pc_client:
            return False
        render = screen[52:] if screen.shape[:2] == (1132, 1982) else screen
        gray = cv2.cvtColor(render, cv2.COLOR_RGB2GRAY)
        return float(gray.mean()) <= 8.0 and float((gray <= 12).mean()) >= 0.985

    def _state_label(self, state: HeroSynthState) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if not self.machine.templates.pc_client and action_name in self._FILTER_ACTIONS:
            return 5
        if action_name == "abort_imprint_to_transmit":
            return 12
        if action_name.startswith("add_material"):
            return self._MATERIAL_RETRY_SECONDS
        if action_name.startswith("next_card"):
            return self._NEXT_CARD_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _apply_recovery_state(self) -> None:
        self.machine.state = HeroSynthState.HERO_LIST
        self.machine.filter_verified = False
        self.machine.prev_card_grey = False
        self.machine._filter_session_done = False  # 恢复后允许重新进入筛选流程
        self.machine._awaiting_star3_confirmation = False
        self.machine._filter_close_pending = False
        self.machine._confirmed_page = ""
        self._needs_navigation_settle = self.machine.templates.pc_client
        self._card_switch_motion_confirmed = False
        self._card_switch_motion_observer = None
        if self.machine.pending_transmit_target:
            self.machine.transmit_continuity_intact = False

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
        if self.machine.state is HeroSynthState.IMPRINT_ABORTING and result in (
            NOT_STABLE,
            None,
        ):
            now = self.now()
            if (
                self._last_imprint_abort_wait_log_at is None
                or now - self._last_imprint_abort_wait_log_at >= 10
            ):
                self._log_imprint_abort_evidence(screen, prefix="中止返回等待")
                self._last_imprint_abort_wait_log_at = now
        else:
            self._last_imprint_abort_wait_log_at = None
        return result

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

    def _log_settled_timeout(self, state: HeroSynthState, diagnostic) -> None:
        if (
            state is HeroSynthState.IMPRINT_ABORTING
            and self.machine._last_screen is not None
        ):
            self._log_imprint_abort_evidence(
                self.machine._last_screen,
                prefix=f"中止返回超时 诊断={diagnostic}",
            )

    def _is_instant_action(self, action_name: Optional[str]) -> bool:
        return self.machine.templates.pc_client and action_name == "close_filter"

    def _stable_action_signature(self, preview_action: Any, outcome: Any) -> str:
        if (
            not self.machine.templates.pc_client
            and preview_action is not None
            and preview_action.name.startswith("next_card_")
        ):
            decision = (
                "sss" if "当前英雄为SSS" in preview_action.reason else "non_sss"
            )
            return (
                f"next_card:{decision}:"
                f"{preview_action.source_observation}"
            )
        if (
            not self.machine.templates.pc_client
            and preview_action is not None
            and preview_action.source_page == "英雄列表"
            and preview_action.source_observation
        ):
            return (
                f"{preview_action.name}:"
                f"{preview_action.source_observation}"
            )
        return super()._stable_action_signature(preview_action, outcome)

    def _after_action_click(self, action: HeroAction) -> None:
        if (
            self.machine.templates.pc_client
            or action.transition_kind != "card_change"
            or self.machine._last_screen is None
        ):
            return
        self.runtime.log(
            f"模式=英雄合成 切换开始 旧身份={action.source_observation or '无法读取'} "
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
                if final_observation == action.source_observation
                else "已变化"
            )
        )
        self.runtime.log(
            f"模式=英雄合成 切换观察 静态身份={identity_status} "
            f"旧身份={action.source_observation or '无法读取'} "
            f"当前身份={final_observation or '无法读取'}"
        )
        if (
            not self._card_switch_motion_confirmed
            or not final_observation
            or final_observation == action.source_observation
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
    def _parse_material_observation(
        action: HeroAction | None,
    ) -> tuple[int, tuple[int, ...]] | None:
        observation = getattr(action, "source_observation", "")
        if not observation.startswith("slots=") or ";rows=" not in observation:
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

    def _material_transition_completed(
        self, previous_action: HeroAction, current_action: HeroAction | None
    ) -> bool:
        previous = self._parse_material_observation(previous_action)
        current = self._parse_material_observation(current_action)
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
            previous_action.source_observation == "grid=0"
            and current_action is not None
            and current_action.source_observation == "grid=1"
        )

    def _card_transition_completed(self, previous_action, current_action) -> bool:
        if self._card_switch_motion_confirmed:
            self._card_switch_motion_confirmed = False
            return True
        previous_observation = getattr(previous_action, "source_observation", "")
        current_observation = getattr(current_action, "source_observation", "")
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
            )
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
                getattr(current_action, "source_observation", "")
                if current_action is not None
                else getattr(self.machine, "_current_card_observation", None)
            )
            evidence = (
                "静态身份变化并连续稳定"
                if observation
                and observation != previous_action.source_observation
                else "静态身份相同，仅由动态证据确认"
            )
            return (
                f"业务切换成功 证据={evidence}；"
                f"旧身份={previous_action.source_observation} "
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
