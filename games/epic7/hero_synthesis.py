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
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class HeroSynthState(Enum):
    HERO_LIST = "hero_list"
    FILTER = "filter"
    IMPRINT_ADD = "imprint_add"
    IMPRINT_CONFIRM = "imprint_confirm"
    IMPRINT_REWARD = "imprint_reward"
    TRANSMIT_SELECT = "transmit_select"
    TRANSMIT_CONFIRM = "transmit_confirm"
    TRANSMIT_REWARD = "transmit_reward"


STATE_LABELS = {
    HeroSynthState.HERO_LIST: "英雄列表",
    HeroSynthState.FILTER: "筛选面板",
    HeroSynthState.IMPRINT_ADD: "刻印加材料",
    HeroSynthState.IMPRINT_CONFIRM: "合成确认",
    HeroSynthState.IMPRINT_REWARD: "合成结果",
    HeroSynthState.TRANSMIT_SELECT: "传送选择",
    HeroSynthState.TRANSMIT_CONFIRM: "传送确认",
    HeroSynthState.TRANSMIT_REWARD: "传送奖励",
}


def state_label(state: HeroSynthState) -> str:
    return STATE_LABELS.get(state, state.value)


@dataclass(frozen=True)
class HeroAction:
    name: str
    point: tuple[int, int]


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
    sss_material: Optional[np.ndarray] = None
    imprint_result_title: Optional[np.ndarray] = None
    imprint_result_close: Optional[np.ndarray] = None
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
    return HeroTemplates(
        filter_button=load_template(str(hero / "filter_button.png")),
        filter_level_label=load_template(str(hero / "filter_level_label.png")),
        filter_star3_selected=load_template(str(hero / "filter_star3_selected.png")),
        imprint_normal=load_template(str(hero / "imprint_button_normal.png")),
        imprint_grey=load_template(str(hero / "imprint_button_grey.png")),
        auto_select_label=load_template(str(hero / "auto_select_label.png")),
        story_back=load_template(str(navigation / "story_back.png")),
        rating_sss=load_template(str(hero / "rating_sss.png")),
        sss_material=(load_template(str(sss_material)) if sss_material.exists() else None),
        imprint_result_title=(load_template(str(result_title)) if result_title.exists() else None),
        imprint_result_close=(load_template(str(result_close)) if result_close.exists() else None),
        pc_client=is_pc,
        assume_non_max_rating=is_pc,
    )


class HeroSynthStateMachine:
    """英雄合成流程的纯视觉决策状态机。"""

    _REFERENCE_SIZE = (1982, 1132)

    _REGIONS = {
        "filter_button": (1450, 160, 200, 60),
        "filter_level_label": (600, 500, 200, 120),
        "filter_star3_selected": (1050, 590, 180, 90),
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
    _RATING_REGION = (90, 460, 200, 130)
    _RATING_SSS_MIN = 0.82  # 满级 SSS 模板匹配阈值：超过即认定为满级
    _REDDOT_ZONE = (1030, 935, 50, 50)  # 刻印按钮左上角红点角标区（不与觉醒按钮重叠）
    _MATERIAL_SSS_REGION = (1750, 350, 230, 650)
    _CARD_BELOW_ZONE = (1450, 537, 520, 83)
    _UP_STRIP_ZONE = (1880, 380, 50, 620)
    _GREEN_BTN_ZONE = (900, 1020, 500, 90)
    _TRANSMIT_GREEN_ZONE = (1000, 1000, 400, 110)
    _BLUE_BAND_ZONE = (900, 700, 450, 120)
    _GOLD_BAND_ZONE = (650, 700, 330, 120)
    _REWARD_STRIP_ZONE = (880, 825, 160, 35)
    _IMPRINT_RESULT_TITLE_REGION = (650, 180, 700, 300)
    _IMPRINT_RESULT_CLOSE_REGION = (650, 730, 700, 300)
    _TRANSMIT_STRIP_ZONE = (1400, 200, 250, 800)
    _TRANSMIT_GRID_ZONE = (50, 305, 620, 405)
    _DETAIL_FP_ZONE = (150, 350, 550, 300)

    # 点击点（参考尺寸坐标）
    _FUNNEL_POINT = (1540, 191)
    _STAR3_POINT = (1110, 636)
    # 模拟器截图是 1920x1080 渲染画面上方补 52px 的旧画布；
    # 点击落在用户标出的下一张卡数值区域内，换算后为 (1559, 591)。
    _NEXT_CARD_POINT = (1559, 591)
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
    _BACK_OFFSET = (-26, -6)
    _PC_FUNNEL_POINT = (1612, 141)
    _PC_STAR3_POINT = (1148, 613)
    _PC_IMPRINT_BUTTON_POINT = (1115, 991)
    _PC_GREEN_BTN_POINT = (1200, 1041)
    _PC_BACK_OFFSET = (11, -4)
    _CARD_BELOW_BRIGHT_MIN = 2000
    _REWARD_STRIP_RANGE = (300, 1500)

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
        self.pending_transmit_target = False

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

    def _red_dot_present(self, screen: np.ndarray) -> bool:
        # 红点角标实际是橙红色（H 0~25 或 H 170~180），不是纯红
        blobs = self._blobs(
            screen,
            self._REDDOT_ZONE,
            (0, 80, 100),
            (25, 255, 255),
            min_area=20,
            max_area=1200,
            morph=3,
        )
        extra = self._blobs(
            screen,
            self._REDDOT_ZONE,
            (165, 80, 100),
            (180, 255, 255),
            min_area=20,
            max_area=1200,
            morph=3,
        )
        return bool(blobs or extra)

    def _sss_material_present(self, screen: np.ndarray) -> bool:
        if self.templates.pc_client or self.templates.sss_material is None:
            return False
        return self._locate(
            screen,
            "sss_material",
            0.78,
            region_override=self._MATERIAL_SSS_REGION,
        ) is not None

    def _card_below_present(self, screen: np.ndarray) -> bool:
        gray = self._zone_gray(screen, self._CARD_BELOW_ZONE)
        return int((gray > 120).sum()) > self._CARD_BELOW_BRIGHT_MIN

    def _up_strip_blobs(self, screen: np.ndarray) -> list[tuple[int, int, int, int]]:
        blobs = self._blobs(
            screen,
            self._UP_STRIP_ZONE,
            (5, 120, 160),
            (25, 255, 255),
            min_area=100,
            morph=5,
        )
        return [b for b in blobs if b[3] >= 60]

    def _find_up_card(self, screen: np.ndarray) -> Optional[tuple[int, int, str]]:
        """返回最上方的 Up 材料卡（点击点, 带计数的动作指纹）。"""
        tall = self._up_strip_blobs(screen)
        if not tall:
            return None
        top = min(tall, key=lambda b: b[1])
        return (self._UP_CARD_X, top[1] + top[3] // 2, str(len(tall)))

    def _green_button_present(self, screen: np.ndarray) -> bool:
        blobs = self._blobs(
            screen,
            self._GREEN_BTN_ZONE,
            (40, 80, 100),
            (90, 255, 255),
            min_area=3000,
        )
        return any(w > 300 for _, _, w, _ in blobs)

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

    def _transmit_target_card(self, screen: np.ndarray) -> Optional[tuple[int, int, str]]:
        """传送选择界面：蓝色高亮竖条定位当前卡（行段 100-350px）。"""
        hsv = self._zone_hsv(screen, self._TRANSMIT_STRIP_ZONE)
        mask = cv2.inRange(hsv, (95, 120, 140), (125, 255, 255))
        rows = mask.sum(axis=1)
        segs, in_seg = [], False
        for i, v in enumerate(rows):
            if v > 60 and not in_seg:
                start, in_seg = i, True
            elif v <= 60 and in_seg:
                if 100 <= i - start <= 350:
                    segs.append((start, i))
                in_seg = False
        if not segs:
            return None
        start, end = segs[0]
        y = self._TRANSMIT_STRIP_ZONE[1] + (start + end) // 2
        return (self._TRANSMIT_CARD_X, y, str(y))

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
        """左侧详情面板的稳定视觉指纹，用于区分连续翻到的英雄。"""
        gray = self._zone_gray(screen, self._DETAIL_FP_ZONE)
        # 详情立绘存在轻微动态，直接对缩小后的原始像素做哈希会导致
        # 同一张卡每帧得到不同指纹，Runner 因而永远无法确认 next_card 稳定。
        gray = cv2.GaussianBlur(gray, (11, 11), 0)
        small = cv2.resize(gray, (5, 3), interpolation=cv2.INTER_AREA)
        quantized = (small // 32).astype(np.uint8)
        return hashlib.sha1(quantized.tobytes()).hexdigest()[:8]

    def _advance_or_finish(self, screen: np.ndarray) -> Optional[HeroAction]:
        if not self._card_below_present(screen):
            self.completed_cycles += 1
            self.filter_verified = False  # 新一轮 cycle 重新筛选
            self._filter_session_done = False  # 新一轮允许重新进入筛选面板
            self._awaiting_star3_confirmation = False
            self.prev_card_grey = False
            return None

        # Runner 会用动作名做两帧确认；指纹用于让动画过渡中的不同英雄
        # 产生不同动作名，从而不会被误判为稳定。
        rating = "S" if self._is_max_rating(screen) else "X"
        dot = "D" if self._red_dot_present(screen) else "N"
        fp = self._detail_fingerprint(screen)
        sig = f"{rating}{dot}{fp}"
        return HeroAction(
            f"next_card_{sig}",
            self._scaled_point(
                screen, self._point(self._NEXT_CARD_POINT, self._PC_NEXT_CARD_POINT)
            ),
        )

    # ---- 主决策 ----

    def next_action(self, screen: np.ndarray) -> Optional[HeroAction]:
        self._last_screen = screen
        # 1. 合成结果覆盖层必须先关闭，不能点击覆盖层下的返回箭头。
        if self._imprint_result_present(screen):
            self.state = HeroSynthState.IMPRINT_REWARD
            return HeroAction(
                "close_imprint_result",
                self._scaled_point(screen, self._IMPRINT_RESULT_CLOSE_POINT),
            )

        # 2. 确认弹窗（合成/传送共用的蓝色按钮）
        confirm = self._confirm_button(screen)
        if confirm is not None:
            transmit_ctx = self._locate(screen, "auto_select_label", 0.85) is not None
            if transmit_ctx or self.state.value.startswith("transmit"):
                self.state = HeroSynthState.TRANSMIT_CONFIRM
                return HeroAction(
                    "confirm_transmit", self._scaled_point(screen, confirm)
                )
            self.state = HeroSynthState.IMPRINT_CONFIRM
            return HeroAction("confirm_synthesis", self._scaled_point(screen, confirm))

        # 3. 传送奖励弹窗（仅在传送流程中判定，防止列表误触）
        if self.state.value.startswith("transmit") and self._reward_strip_present(screen):
            self.state = HeroSynthState.TRANSMIT_SELECT
            return HeroAction("close_reward", self._scaled_point(screen, self._REWARD_CLOSE_POINT))

        # 4. 传送选择界面（自动选择标签为锚点，需先于绿钮判定）
        if self._locate(screen, "auto_select_label", 0.85):
            self.pending_transmit_target = False
            self.state = HeroSynthState.TRANSMIT_SELECT
            if (
                self._transmit_green_present(screen)
                and self._transmit_grid_filled(screen)
            ):
                self.state = HeroSynthState.TRANSMIT_CONFIRM
                return HeroAction(
                    "start_transmit", self._scaled_point(screen, self._TRANSMIT_GREEN_POINT)
                )
            card = self._transmit_target_card(screen)
            if card is not None:
                x, y, tag = card
                return HeroAction(
                    f"select_transmit_card_{tag}",
                    self._scaled_point(screen, (x, y)),
                )
            back = self._back_action(screen)
            if back is not None:
                self.state = HeroSynthState.HERO_LIST
                return back
            raise UnrecognizedScreen("传送选择画面缺少可选卡片与返回箭头")

        if (
            self.state is HeroSynthState.IMPRINT_CONFIRM
            and not self.templates.pc_client
            and self._back_action(screen) is not None
        ):
            raise UnrecognizedScreen("合成结果覆盖层未完整识别，禁止点击底层返回")

        # 5. 刻印界面（绿色刻印按钮为锚点）
        if self.state is HeroSynthState.IMPRINT_ADD and self._sss_material_present(screen):
            self.pending_transmit_target = True
            back = self._back_action(screen)
            if back is None:
                raise UnrecognizedScreen("发现 SSS 材料但刻印页面缺少返回箭头")
            self.state = HeroSynthState.HERO_LIST
            return HeroAction("abort_imprint_to_transmit", back.point)
        if self._green_button_present(screen):
            up = self._find_up_card(screen)
            if up is not None:
                self.state = HeroSynthState.IMPRINT_ADD
                x, y, tag = up
                return HeroAction(
                    f"add_material_{tag}", self._scaled_point(screen, (x, y))
                )
            if self.state is HeroSynthState.IMPRINT_ADD:
                self.state = HeroSynthState.IMPRINT_CONFIRM
                return HeroAction(
                    "start_synthesis",
                    self._scaled_point(
                        screen, self._point(self._GREEN_BTN_POINT, self._PC_GREEN_BTN_POINT)
                    ),
                )
            back = self._back_action(screen)
            if back is None:
                raise UnrecognizedScreen("刻印画面缺少返回箭头")
            self.state = HeroSynthState.HERO_LIST
            return back

        # 6. 筛选面板（级别标签为锚点）
        # 一次性入场：close_filter 后置 _filter_session_done=True，
        # 之后无论模板是否误识别 filter_level_label，都不再进此分支。
        filter_level = self._locate(screen, "filter_level_label")
        star3_selected = self._locate(screen, "filter_star3_selected", 0.90)
        if not self._filter_session_done and self._awaiting_star3_confirmation:
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
        if not self._filter_session_done and (filter_level or star3_selected):
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

        # 7. 英雄列表：评级是唯一决策依据（SSS 满级 → 跳过，否则看是否有红点）
        # 上一版靠"按钮灰/蓝颜色"和"上一张是不是 SSS"的双保险推断都被颜色变种击穿；
        # 直接看左侧详情面板上的评级字符更稳。
        self.state = HeroSynthState.HERO_LIST
        if self.pending_transmit_target:
            return HeroAction(
                "open_transmit_for_current_card",
                self._scaled_point(screen, self._TRANSMIT_ENTRY_POINT),
            )
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
        if best is not None and best.score >= self._BUTTON_STRUCT_MIN:
            if not self.filter_verified:
                return HeroAction(
                    "open_filter",
                    self._scaled_point(
                        screen, self._point(self._FUNNEL_POINT, self._PC_FUNNEL_POINT)
                    ),
                )
            if self._is_max_rating(screen):
                self.prev_card_grey = True
                return self._advance_or_finish(screen)
            if self._red_dot_present(screen):
                self.prev_card_grey = False
                self.state = HeroSynthState.IMPRINT_ADD
                return HeroAction("open_imprint", best.center)
            self.prev_card_grey = False
            return self._advance_or_finish(screen)

        # 按钮结构匹配不上（视觉变种如绿色菱形）：
        # 用"是否有任何线索"判定：只要红点或评级能识别，就按业务逻辑走；
        # 都没有 → 当前画面根本不是英雄列表，抛 UnrecognizedScreen 让主循环回收。
        if self._is_max_rating(screen) or self._red_dot_present(screen):
            if not self.filter_verified:
                return HeroAction(
                    "open_filter",
                    self._scaled_point(
                        screen, self._point(self._FUNNEL_POINT, self._PC_FUNNEL_POINT)
                    ),
                )
            if self._is_max_rating(screen):
                self.prev_card_grey = True
                return self._advance_or_finish(screen)
            self.prev_card_grey = False
            self.state = HeroSynthState.IMPRINT_ADD
            return HeroAction(
                "open_imprint",
                self._scaled_point(
                    screen,
                    self._point(
                        self._IMPRINT_BUTTON_POINT, self._PC_IMPRINT_BUTTON_POINT
                    ),
                ),
            )
        raise UnrecognizedScreen(
            f"英雄合成画面[{state_label(self.state)}]未识别"
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
            self.pending_transmit_target,
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
                self.pending_transmit_target,
                self._last_screen,
            ) = snapshot


class HeroSynthRunner(ModeRunnerBase):
    """两帧确认的英雄合成 Runner（主循环协议见 ModeRunnerBase）。"""

    _MODE_LABEL = "英雄合成"
    _TIMEOUT_SECONDS = {
        HeroSynthState.HERO_LIST: 60,
        HeroSynthState.FILTER: 45,
        HeroSynthState.IMPRINT_ADD: 90,
        HeroSynthState.IMPRINT_CONFIRM: 60,
        HeroSynthState.IMPRINT_REWARD: 45,
        HeroSynthState.TRANSMIT_SELECT: 60,
        HeroSynthState.TRANSMIT_CONFIRM: 45,
        HeroSynthState.TRANSMIT_REWARD: 45,
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

    def _state_label(self, state: HeroSynthState) -> str:
        return state_label(state)

    def _apply_recovery_state(self) -> None:
        self.machine.state = HeroSynthState.HERO_LIST
        self.machine.filter_verified = False
        self.machine.prev_card_grey = False
        self.machine._filter_session_done = False  # 恢复后允许重新进入筛选流程
        self.machine._awaiting_star3_confirmation = False
        self.machine.pending_transmit_target = False
        self._needs_navigation_settle = self.machine.templates.pc_client

    def _stable_next_action(self, screen: np.ndarray, stable: Any):
        if self._needs_navigation_settle:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 状态=导航后稳定等待 "
                f"秒={self._SETTLE_AFTER_NAVIGATION_SECONDS}"
            )
            self.sleep(self._SETTLE_AFTER_NAVIGATION_SECONDS)
            self._needs_navigation_settle = False
            return super()._stable_next_action(self.runtime.capture(), stable)
        return super()._stable_next_action(screen, stable)

    def _is_instant_action(self, action_name: Optional[str]) -> bool:
        """close_filter 是一次性副作用，状态机决定关就立刻关——跳过 stable 2 帧确认。
        否则稳定窗口会让 close_filter 与 open_filter 的动作名不同而被取消，关闭永远失败。
        """
        return action_name == "close_filter"

    def _decision_hint(self, action_name: str, state: Any) -> str:
        """让日志解释当前动作的决策原因（评级/红点/选星/状态切换）。"""
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
