"""英雄合成里「只看画面、不做决策」的那一半。

## 为什么单独成模块（2026-09-30）

`hero_synthesis.py` 原本 2317 行，其中一个 `HeroSynthStateMachine` 就占 1577 行 —— 读的人
要在一屏几十个方法里找「哪一段在决策、哪一段只是在看画面」。这里收的是**只看画面**的部分：

- `FilterObservation`：筛选面板观察到哪一步（纯观测枚举）；
- 四个模块级视觉函数（`imprint_button_saturation` / `hero_tab_blue_pixel_counts` /
  `hero_information_tab_selected` / `hero_equipment_tab_selected`）—— `navigation.py` 也在用
  前两个，所以由 `hero_synthesis` 继续对外再导出；
- `HeroVisionMixin`：`_mask_dot` … `_filter_evidence_summary` 共 50 个方法，它们只做
  「从这一帧读出事实」，**不做任何决策**（决策、事务与 Runner 留在 `hero_synthesis`）。

⚠️ 为什么是 mixin 而不是搬成一个独立对象：这些方法全部依赖状态机的实例状态
（`self.templates` / `self._last_filter_scores` / `self.transmit_*` …）以及 29 个类常量。
拆成独立对象等于把 29 个常量和十几处实例状态一起搬家 —— 那是**重写**，不是拆分。
mixin 让「方法在哪、`self` 是哪一份」都不变，所以整块是**逐字搬运**，行为不可能漂。

⚠️ 有 6 个视觉常量按「同一控件只保留一个来源」的规矩定义在**这里**（四个模块级函数要用），
`HeroSynthStateMachine` 里改成**别名**而不是复制值 —— 见那边的注释。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import cv2
import numpy as np

from auto_game_unified.core.matcher import (
    Match,
    best_match,
    find_template,
)
from auto_game_unified.games.epic7.evidence.hero_synthesis import (
    REFERENCE_SIZE as HERO_REFERENCE_SIZE,
)
from auto_game_unified.games.epic7.hero_transition import SafetyClass


# ---- 视觉常量（唯一来源；HeroSynthStateMachine 里是别名）----
REFERENCE_SIZE = HERO_REFERENCE_SIZE
BUTTON_CENTER = (1098, 995)
BUTTON_DISC_RADIUS = 58
HERO_INFO_TAB_ZONE = (0, 150, 127, 105)
EQUIPMENT_TAB_ZONE = (0, 255, 127, 105)
SELECTED_TAB_BLUE_MIN = 1000


class FilterObservation(Enum):
    HERO_LIST_FILTER_CLOSED = "hero_list_filter_closed"
    FILTER_OPEN_STAR3_SELECTED = "filter_open_star3_selected"
    FILTER_OPEN_STAR3_UNSELECTED = "filter_open_star3_unselected"
    UNKNOWN = "unknown"


def imprint_button_saturation(screen: np.ndarray) -> float:
    """刻印按钮圆盘的中位饱和度。

    置灰按钮有两种深浅（实测 S=39~73），正常蓝色按钮 S=112~120；
    饱和度不受亮度变化影响，是灰/蓝状态的可靠分类依据。
    英雄合成状态机与导航的页面识别共用。
    """
    scale_x = screen.shape[1] / REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / REFERENCE_SIZE[1]
    cx = round(BUTTON_CENTER[0] * scale_x)
    cy = round(BUTTON_CENTER[1] * scale_y)
    r = max(8, round(BUTTON_DISC_RADIUS * scale_x))
    crop = screen[cy - r : cy + r, cx - r : cx + r]
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    h, w = crop.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    disc = (xx - w // 2) ** 2 + (yy - h // 2) ** 2 <= r**2
    return float(np.median(hsv[:, :, 1][disc]))


def hero_tab_blue_pixel_counts(screen: np.ndarray) -> tuple[int, int]:
    """Return blue-pixel evidence for the information and equipment tabs."""

    def count(zone: tuple[int, int, int, int]) -> int:
        reference_width, reference_height = REFERENCE_SIZE
        x, y, width, height = zone
        scaled = (
            round(x * screen.shape[1] / reference_width),
            round(y * screen.shape[0] / reference_height),
            round(width * screen.shape[1] / reference_width),
            round(height * screen.shape[0] / reference_height),
        )
        sx, sy, sw, sh = scaled
        crop = screen[sy : sy + sh, sx : sx + sw]
        if (sw, sh) != (width, height):
            crop = cv2.resize(crop, (width, height), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        return int((cv2.inRange(hsv, (90, 80, 80), (130, 255, 255)) > 0).sum())

    return (
        count(HERO_INFO_TAB_ZONE),
        count(EQUIPMENT_TAB_ZONE),
    )


def hero_information_tab_selected(screen: np.ndarray) -> bool:
    information, equipment = hero_tab_blue_pixel_counts(screen)
    threshold = SELECTED_TAB_BLUE_MIN
    return information >= threshold and equipment < threshold


def hero_equipment_tab_selected(screen: np.ndarray) -> bool:
    information, equipment = hero_tab_blue_pixel_counts(screen)
    threshold = SELECTED_TAB_BLUE_MIN
    return equipment >= threshold and information < threshold


class HeroVisionMixin:
    """只看画面、不做决策的那一半（`HeroSynthStateMachine` 混入它）。

    方法一律只读画面与实例状态，返回事实（bool / 分数 / 枚举 / 坐标），**不返回动作** ——
    需要「下一步点哪里」的都在 `hero_synthesis.HeroSynthStateMachine` 里。
    """

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
        score, location = best_match(crop, template)
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
            self._threshold(name) if threshold is None else threshold,
            region=self._region(name) if region_override is None else region_override,
            reference_size=self._REFERENCE_SIZE,
        )

    def _region(self, name: str) -> tuple[int, int, int, int]:
        return self._REGIONS[name]

    def _threshold(self, name: str) -> float:
        return self._THRESHOLDS.get(name, self.templates.threshold)

    def _scaled_point(
        self, screen: np.ndarray, point: tuple[int, int]
    ) -> tuple[int, int]:
        return (
            round(point[0] * screen.shape[1] / self._REFERENCE_SIZE[0]),
            round(point[1] * screen.shape[0] / self._REFERENCE_SIZE[1]),
        )

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
        return self._locate(screen, "rating_sss") is not None

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
            100,
            max_area=1200,
            morph=3,
        )
        extra = self._blobs(
            screen,
            zone,
            (165, 120, 120),
            (180, 255, 255),
            100,
            max_area=1200,
            morph=3,
        )
        return any(is_centered_dot(blob) for blob in (*blobs, *extra))

    def _sss_material_region_score(
        self, screen: np.ndarray, region: tuple[int, int, int, int]
    ) -> float:
        """给「SSS 材料」徽记在指定区域里打分：**候选模板 × 尺度档位**逐对匹配，取最高分。

        为什么要多张候选：同一枚徽记有不同长相 —— 排在材料列表后面的卡上，整张
        卡连同徽记一起被缩小、压暗。语义与 ``NavigationTemplates.lobby_shop_entry``
        一致：**任一候选过阈即算命中**。

        为什么要多档尺度：这张列表**在第几位就画多大**，而列表里有几张材料取决于
        当时开到哪儿 ⇒ 尺寸档位不是固定的两三种，**补模板补不完**。2026-10-04
        08:36 现场：只按原尺寸匹配量到 0.5928，正好落进 0.55~0.80 的不确定带，
        判据**静默失效**（不出手、不打分、不报警），刻印页干等 90 秒超时。
        实测同一张徽记至少被画成核心宽 56 / 50 / 45 三档。

        内缩 ``_SSS_TEMPLATE_INSET`` 是为了去掉模板边缘的卡片背景，避免普通传送卡在
        背景纹理上蹭到 0.55+。返回 -1.0 是哨兵值，含义是「一个候选位置都没匹配上」，
        不是「分数低」。

        成本：候选数 × 尺度数 次匹配。实测 2 × 6 档共 12 次约 73ms（单尺度 15ms）。
        没有做「先按 1.00 倍量、落死区才展开」的省时优化 —— 那样会在
        「原尺寸量到 ≤0.55（判 NON_SSS）、换个尺度其实过阈」时**漏判**，
        而漏判 NON_SSS 会让 SSS 材料卡被当成普通材料点下去（合成消耗材料，不可逆）。
        """
        inset = self._SSS_TEMPLATE_INSET
        best = -1.0
        for candidate in self.templates.sss_material:
            core = candidate[inset:-inset, inset:-inset]
            height, width = core.shape[:2]
            for scale in self._SSS_TEMPLATE_SCALES:
                shaped = core
                if scale != 1.0:
                    shaped = cv2.resize(
                        core,
                        (max(2, round(width * scale)), max(2, round(height * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                match = find_template(
                    screen,
                    shaped,
                    -1.0,
                    region=region,
                    reference_size=self._REFERENCE_SIZE,
                )
                if match is not None and match.score > best:
                    best = match.score
        return best

    def _material_page_sss_score(self, screen: np.ndarray) -> float:
        return self._sss_material_region_score(screen, self._region("sss_material"))

    def _classify_material_page(self, screen: np.ndarray) -> SafetyClass:
        """先对整列材料做 SSS 安全分类；不确定时禁止点击任何卡。

        ⚠️ 「模板缺失」**不再**走这条路径 —— 那种情况在构造期就被拦下了
        （``HeroSynthStateMachine._assert_anchor_templates``）。这里只剩下
        「量到了，但分数落在不确定区间」。
        """
        score = self._material_page_sss_score(screen)
        if score < 0:
            return SafetyClass.UNKNOWN
        if score >= self._threshold("sss_material"):
            return SafetyClass.SSS
        if score <= self._SSS_MATERIAL_CLEAR_MAX:
            return SafetyClass.NON_SSS
        return SafetyClass.UNKNOWN

    def _sss_material_present(self, screen: np.ndarray) -> bool:
        return self._classify_material_page(screen) is SafetyClass.SSS

    def _sss_material_warning_close(self, screen: np.ndarray) -> Optional[Match]:
        """返回 SSS 材料风险提示层的关闭控件，避免点击覆盖层下的按钮。

        ⚠️ 这两张模板**曾经是可选的**，缺了就直接 ``return None`` —— 于是
        「提示层必须先关掉」这条覆盖层优先级**静默消失**，可能点到提示层底下的
        材料卡（合成消耗材料，不可逆）。现在它们是必需模板，缺失在构造期被拦下。
        """
        title = self._locate(screen, "sss_material_warning_title")
        close = self._locate(screen, "sss_material_warning_close")
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
        information, equipment = hero_tab_blue_pixel_counts(screen)
        if zone == self._HERO_INFO_TAB_ZONE:
            return information
        if zone == self._EQUIPMENT_TAB_ZONE:
            return equipment
        raise ValueError(f"不支持的英雄子页标签区域：{zone}")

    def _equipment_tab_selected(self, screen: np.ndarray) -> bool:
        return hero_equipment_tab_selected(screen)

    def _hero_info_tab_selected(self, screen: np.ndarray) -> bool:
        return hero_information_tab_selected(screen)

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

    def _find_up_card(self, screen: np.ndarray) -> Optional[tuple[int, int, str]]:
        """返回最上方的普通 Up 材料卡，SSS 材料永远不可点击。"""
        # Up 窄区可能被英雄武器动画扫过。没有右侧橙色材料卡轮廓时，
        # 橙色行只能算动画噪声，不能生成点击动作。
        if self._find_visible_material_card(screen) is None:
            return None
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
        start, end = row
        material_region = self._region("sss_material")
        region = region_override or (
            material_region[0],
            max(material_region[1], start - 45),
            material_region[2],
            min(material_region[3], end - start + 90),
        )
        return self._sss_material_region_score(screen, region)

    def _classify_material_row(
        self, screen: np.ndarray, row: tuple[int, int]
    ) -> SafetyClass:
        score = self._material_sss_score(screen, row)
        if score < 0:
            return SafetyClass.UNKNOWN
        if score >= self._threshold("sss_material"):
            return SafetyClass.SSS
        if score <= self._SSS_MATERIAL_CLEAR_MAX:
            return SafetyClass.NON_SSS
        return SafetyClass.UNKNOWN

    def _unknown_up_material_present(self, screen: np.ndarray) -> bool:
        return any(
            self._classify_material_row(screen, row) is SafetyClass.UNKNOWN
            for row in self._up_badge_rows(screen)
        )

    def _find_visible_material_card(
        self, screen: np.ndarray
    ) -> Optional[tuple[int, int, str]]:
        """定位右侧橙色材料卡，供初始空槽时兜底。

        兜底只负责证明“有卡”和给出点击点；能否点击仍由整页 SSS
        分类决定，且仅在槽位为空、费用为 0 时使用，避免重复点击已选材料。
        """
        cards = [
            blob
            for blob in self._blobs(
                screen,
                self._MATERIAL_CARD_ZONE,
                (5, 100, 120),
                (30, 255, 255),
                min_area=5000,
                morph=7,
            )
            if blob[2] >= 180 and blob[3] >= 70
        ]
        if not cards:
            return None
        top = min(cards, key=lambda blob: blob[1])
        return (self._UP_CARD_X, top[1] + min(48, top[3] // 2), "card")

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
        """传送奖励覆盖层是否出现。

        ⚠️ 曾经两张模板可选，缺了直接 ``return False`` —— 等于「奖励层没出现」，
        于是 ``next_action`` 会跳过「先关奖励层」直接去点下面的东西。
        现在它们必需，缺了在构造期就被拦下。
        """
        title = self._locate(screen, "transmit_reward_title")
        close = self._locate(screen, "transmit_reward_close")
        return (
            title is not None
            and close is not None
            and self._reward_strip_present(screen)
        )

    def _imprint_result_present(self, screen: np.ndarray) -> bool:
        """合成结果覆盖层是否出现。

        ⚠️ 同上：模板可选时缺了会返回 False，于是
        「合成结果覆盖层必须先关闭，不能点击覆盖层下的返回箭头」这条保护**静默消失**。
        现在必需。
        """
        title = self._locate(screen, "imprint_result_title")
        close = self._locate(screen, "imprint_result_close")
        return title is not None and close is not None

    def _transmit_grid_filled(self, screen: np.ndarray) -> bool:
        gray = self._zone_gray(screen, self._TRANSMIT_GRID_ZONE)
        return int((gray > 120).sum()) > 5000

    def _transmit_grid_present(self, screen: np.ndarray) -> bool:
        gray = self._zone_gray(screen, self._TRANSMIT_GRID_ZONE)
        return int((gray > 45).sum()) > 5000

    def _transmit_page_ready(self, screen: np.ndarray) -> bool:
        return bool(
            self._locate(screen, "auto_select_label")
            and self._transmit_target_card(screen) is not None
            and self._transmit_grid_present(screen)
            and self._transmit_green_present(screen)
        )

    def _transmit_target_card(self, screen: np.ndarray) -> Optional[tuple[int, int, str]]:
        """传送选择界面：在卡片右侧的蓝色高亮行内定位当前卡。"""
        hsv = self._zone_hsv(screen, self._TRANSMIT_HIGHLIGHT_ZONE)
        mask = cv2.inRange(hsv, (95, 120, 140), (125, 255, 255))
        rows = mask.sum(axis=1)
        raw_segments, in_seg = [], False
        for i, v in enumerate(rows):
            if v > 60 and not in_seg:
                start, in_seg = i, True
            elif v <= 60 and in_seg:
                raw_segments.append((start, i))
                in_seg = False
        if in_seg:
            raw_segments.append((start, len(rows)))
        segs: list[tuple[int, int]] = []
        for start, end in raw_segments:
            if segs and start - segs[-1][1] <= 8:
                segs[-1] = (segs[-1][0], end)
            else:
                segs.append((start, end))
        segs = [segment for segment in segs if 50 <= segment[1] - segment[0] <= 350]
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
        if card is None:
            return SafetyClass.UNKNOWN
        _, y, _ = card
        region = (1500, max(200, y - 70), 480, 140)
        score = self._material_sss_score(
            screen,
            (y - 25, y + 25),
            region_override=region,
        )
        if score < 0:
            return SafetyClass.UNKNOWN
        if score >= self._threshold("sss_material"):
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
            best is not None and best.score >= self._button_struct_min
        ) or self._is_max_rating(screen) or self._red_dot_present(screen)
        return base_ready and (
            self._detail_content_present(screen)
        )

    def _observe_filter(self, screen: np.ndarray) -> FilterObservation:
        """Classify only filter states backed by explicit simulator evidence.

        ⚠️ 两张筛选模板曾经可选，缺了直接返回 ``UNKNOWN`` —— 表现是筛选面板永远
        认不出、于是反复点漏斗直到超时（不点错，但卡死）。现在必需。
        """
        keys = (
            "filter_level_label",
            "filter_attribute_label",
            "filter_star3_selected",
            "filter_star3_unselected",
        )
        self._last_filter_scores = {}
        for key in keys:
            match = self._locate(screen, key, 0.0)
            self._last_filter_scores[key] = (
                match.score if match is not None else -1.0
            )

        scale = min(
            screen.shape[1] / self._REFERENCE_SIZE[0],
            screen.shape[0] / self._REFERENCE_SIZE[1],
        )
        attribute_min = (
            self._filter_attribute_small_min
            if scale <= 0.55
            else self._threshold("filter_attribute_label")
        )
        level_present = (
            self._last_filter_scores["filter_level_label"]
            >= self._threshold("filter_level_label")
        )
        attribute_present = (
            self._last_filter_scores["filter_attribute_label"] >= attribute_min
        )
        panel_open = level_present and attribute_present
        if panel_open:
            if (
                self._last_filter_scores["filter_star3_selected"]
                >= self._threshold("filter_star3_selected")
            ):
                return FilterObservation.FILTER_OPEN_STAR3_SELECTED
            if (
                self._last_filter_scores["filter_star3_unselected"]
                >= self._threshold("filter_star3_unselected")
            ):
                return FilterObservation.FILTER_OPEN_STAR3_UNSELECTED
            return FilterObservation.UNKNOWN
        if level_present or attribute_present:
            return FilterObservation.UNKNOWN
        if self._hero_info_tab_selected(screen) and self._hero_list_ready(screen):
            return FilterObservation.HERO_LIST_FILTER_CLOSED
        return FilterObservation.UNKNOWN

    def _filter_evidence_summary(self) -> str:
        def item(label: str, key: str) -> str:
            return (
                f"{label}={self._last_filter_scores.get(key, -1.0):.3f}/"
                f"{self._threshold(key):.2f}"
            )

        return " ".join(
            (
                item("级别", "filter_level_label"),
                item("属性", "filter_attribute_label"),
                item("三星已选", "filter_star3_selected"),
                item("三星未选", "filter_star3_unselected"),
            )
        )

