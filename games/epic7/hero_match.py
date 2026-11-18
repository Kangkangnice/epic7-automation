"""竞技场对手队伍的英雄识别。

用途：判断竞技场对手列表里，每个对手的防守队是否包含用户指定的英雄，
从而支持「避开某些英雄」的选敌策略。

判据（四个条件必须同时满足，缺一即判未命中）：
    1. ORB good 匹配数 >= ``MIN_GOOD``
    2. RANSAC 内点数 >= ``MIN_INLIERS``
    3. 第二名 good <= 第一名 / ``RIVAL_RATIO``（能证伪：必须甩开同类候选）
    4. 单应变换后**中心区域**的像素相关 >= ``MIN_WARP_CORR``

不用绝对分数定阈值：不同英雄提取到的特征点数差异可达一倍（实测 468~1049），
绝对 good 数在英雄之间不可比，必须配相对优势条件。

为什么用 ORB 而不是模板匹配：
    图鉴头像与竞技场头像存在渲染差异（色调、光照）与尺度差异（150 vs 112）。
    实测模板匹配 ``TM_CCOEFF_NORMED`` 在这类图上基线过高——库内不同英雄之间
    相似度中位数就有 0.914，正确答案反而淹没其中。ORB 比的是局部特征点的
    几何关系，不受整体色调影响。

只加载用户指定要避开的英雄，避免每次都比对全库（385 个），把单次识别
控制在几十次匹配内。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# 竞技场对手列表页的头像网格（1982x1132 画布口径，实测标定）
OPPONENT_COLUMNS = (917, 1045, 1168, 1292)
OPPONENT_ROWS = (390, 583, 775)
OPPONENT_RADIUS = 56

MIN_GOOD = 40
MIN_INLIERS = 30
RIVAL_RATIO = 3.0

# 单应变换后的像素相关只在**中心区域**内算（2026-11-17 改）。
#
# ⚠️ 原来用整图算，被构图差异拖垮：图鉴库的图是方形、带边框与职业/属性角标，
# 换成外部图鉴的圆形裁切后，四角内容与游戏内头像毫无关系。实测同一名英雄、同一张
# 实机竞技场截图：整图相关 0.32~0.37（判未命中），只取中心 50% 是 0.95~0.99。
# 而错误英雄的中心相关最高只有 0.645、内点最高 7，正确样本内点 98 起 —— 取中心
# 不是放宽，反而更容易证伪。阈值随之从 0.60 提到 0.80，两头各留 0.12 以上余量。
CORR_CENTER_RATIO = 0.5
MIN_WARP_CORR = 0.80

ORB_FEATURES = 1500
RATIO_TEST = 0.75
RANSAC_REPROJ = 5.0


def _center_corr(warped: np.ndarray, target: np.ndarray) -> float:
    """把模板拉回目标视角后，只比中心区域的灰度相关。

    模板里的纯黑像素（圆形头像的透明四角）不计入，避免空区域把相关稀释掉。
    """

    gray_w = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    gray_t = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
    height, width = gray_w.shape[:2]
    side_h = int(height * CORR_CENTER_RATIO)
    side_w = int(width * CORR_CENTER_RATIO)
    if side_h <= 0 or side_w <= 0:
        return 0.0
    y0 = (height - side_h) // 2
    x0 = (width - side_w) // 2
    gray_w = gray_w[y0:y0 + side_h, x0:x0 + side_w]
    gray_t = gray_t[y0:y0 + side_h, x0:x0 + side_w]
    valid = gray_w > 0
    if valid.sum() < gray_w.size * 0.3:
        return 0.0
    return float(np.corrcoef(gray_w[valid], gray_t[valid])[0, 1])


def _imread(path: Path) -> np.ndarray | None:
    """读取图片，兼容中文路径（``cv2.imread`` 在 Windows 下不认非 ASCII 路径）。"""

    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


@dataclass
class HeroHit:
    """一个待判定头像对某个英雄模板的比对结果。"""

    name: str
    good: int
    inliers: int
    warp_corr: float
    rival_good: int

    @property
    def matched(self) -> bool:
        return (
            self.good >= MIN_GOOD
            and self.inliers >= MIN_INLIERS
            and self.rival_good <= self.good / RIVAL_RATIO
            and self.warp_corr >= MIN_WARP_CORR
        )


@dataclass
class OpponentTeam:
    """一个对手行的识别结果。"""

    index: int
    heroes: list[str] = field(default_factory=list)
    unknown: int = 0

    def contains(self, names: set[str]) -> bool:
        return bool(names & set(self.heroes))


class HeroMatcher:
    """在竞技场列表页识别对手队伍中的指定英雄。"""

    def __init__(self, library_dir: Path, watch_names: list[str]) -> None:
        self._dir = Path(library_dir)
        self._watch = [n for n in watch_names if n]
        self._orb = cv2.ORB_create(
            nfeatures=ORB_FEATURES, edgeThreshold=5, patchSize=31
        )
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._templates: list[tuple[str, np.ndarray]] = []
        self._desc: list[tuple[list, np.ndarray | None]] = []
        self._keypoints: list[tuple[list, np.ndarray | None]] = []
        self.missing_names: list[str] = []
        self._load()

    def _load(self) -> None:
        """只加载被点名的英雄，缺文件的记进 ``missing_names``（不静默跳过）。"""

        for name in self._watch:
            path = self._dir / f"{name}.png"
            if not path.exists():
                self.missing_names.append(name)
                continue
            image = _imread(path)
            if image is None:
                self.missing_names.append(name)
                continue
            keypoints, desc = self._orb.detectAndCompute(image, None)
            self._templates.append((name, image))
            self._keypoints.append((keypoints, desc))
        self._desc = self._keypoints

    @property
    def loaded_count(self) -> int:
        return len(self._templates)

    @property
    def loaded_names(self) -> list[str]:
        """已成功加载、会在识别时生效的英雄名（缺图的不在其中）。"""

        return [name for name, _ in self._templates]

    def _score(
        self,
        target: np.ndarray,
        target_keypoints,
        target_desc: np.ndarray | None,
        index: int,
    ) -> tuple[int, int, float]:
        """比对目标头像与第 ``index`` 个模板，返回 (good, 内点, 变换后相关)。

        ⚠️ 目标头像的特征点由调用方算好传进来 —— ``identify_one`` 要拿同一个头像
        比对**全部**模板，在 ``_score`` 里算会把同一张图的特征点重复算 N 遍
        （N 个被点名的英雄），识别一页（12 头像 x N 模板）时差 N 倍时间。
        """

        template = self._templates[index][1]
        kp_t, desc_t = self._keypoints[index]
        if desc_t is None or target_desc is None:
            return 0, 0, 0.0
        matches = self._bf.knnMatch(target_desc, desc_t, k=2)
        good = [
            pair[0]
            for pair in matches
            if len(pair) == 2 and pair[0].distance < RATIO_TEST * pair[1].distance
        ]
        if len(good) < 8:
            return len(good), 0, 0.0
        src = np.float32([target_keypoints[m.queryIdx].pt for m in good])
        dst = np.float32([kp_t[m.trainIdx].pt for m in good])
        homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_REPROJ)
        if homography is None:
            return len(good), 0, 0.0
        inliers = int(mask.sum())
        height, width = target.shape[:2]
        # homography 是 竞技场->模板 方向；把模板拉回竞技场视角要用逆变换。
        warped = cv2.warpPerspective(template, np.linalg.inv(homography), (width, height))
        corr = _center_corr(warped, target)
        return len(good), inliers, corr

    def identify_one(self, crop: np.ndarray) -> HeroHit | None:
        """判定单个头像是否命中被点名的英雄。"""

        if not self._templates:
            return None
        keypoints, desc = self._orb.detectAndCompute(crop, None)
        scored: list[tuple[int, int, float, int]] = []
        for index in range(len(self._templates)):
            good, inliers, corr = self._score(crop, keypoints, desc, index)
            scored.append((good, inliers, corr, index))
        scored.sort(key=lambda item: item[0], reverse=True)
        best = scored[0]
        rival = scored[1][0] if len(scored) > 1 else 0
        name = self._templates[best[3]][0]
        return HeroHit(name=name, good=best[0], inliers=best[1], warp_corr=best[2], rival_good=rival)

    def identify_screen(self, screen: np.ndarray) -> list[OpponentTeam]:
        """识别整页（3 个对手 x 4 个英雄）。"""

        teams: list[OpponentTeam] = []
        for row_index, cy in enumerate(OPPONENT_ROWS):
            team = OpponentTeam(index=row_index)
            for cx in OPPONENT_COLUMNS:
                y0, y1 = cy - OPPONENT_RADIUS, cy + OPPONENT_RADIUS
                x0, x1 = cx - OPPONENT_RADIUS, cx + OPPONENT_RADIUS
                if y0 < 0 or x0 < 0 or y1 > screen.shape[0] or x1 > screen.shape[1]:
                    team.unknown += 1
                    continue
                crop = screen[y0:y1, x0:x1]
                hit = self.identify_one(crop)
                if hit is None or not hit.matched:
                    team.unknown += 1
                    continue
                team.heroes.append(hit.name)
            teams.append(team)
        return teams


def library_names(library_dir: Path) -> list[str]:
    """列出库内可用的英雄名（去掉 ``unknown_*`` 与扩展名）。"""

    directory = Path(library_dir)
    if not directory.is_dir():
        return []
    names = []
    for path in sorted(directory.glob("*.png")):
        stem = path.stem
        if stem.startswith("unknown"):
            continue
        if re.search(r"_\d+$", stem):
            continue
        names.append(stem)
    return sorted(names)


def default_library_dir() -> Path:
    """图鉴库随包位置（与本模块同级）。

    图鉴是**游戏内的百科页**渲染，与 PC / 模拟器无关，所以只有这一份，
    不走 ``templates/pc/`` 那套平台覆盖。打包时由 spec 的 datas 一并收进去。
    """
    return Path(__file__).resolve().parent / "templates" / "arena" / "heroes_pokedex"


# 一行判定的三个去向。
#
# ⚠️ **优先名单是「优先打」，不是「只打」**（2026-11-15 用户纠正）。
# 名单里没命中 ≠ 出局 —— 那只是「这名对手没有特别想打」，回到常规挑法（按积分）。
# 早期实现按「优先名单 = 只打含名单英雄的队伍」写，会导致开了优先名单却一个都没撞上时
# 整页无人可打、只能反复刷新，与用户意图相反。
TIER_WHITE = "white"
TIER_NORMAL = "normal"
TIER_OUT = "out"


@dataclass(frozen=True)
class RowVerdict:
    """一行对手的筛选结论：进优先名单组 / 进普通组 / 出局，以及理由。

    ``white_hits`` 是优先名单命中数，优先名单组内**先比它、再比积分**
    （用户 2026-11-15 拍板：命中两名优先名单英雄的队比命中一名的更想打）。
    """

    tier: str
    reason: str
    white_hits: int = 0

    @property
    def keep(self) -> bool:
        return self.tier != TIER_OUT


def judge_row(
    team: "OpponentTeam",
    *,
    blacklist: set[str],
    whitelist: set[str],
    conflict: str,
) -> RowVerdict:
    """单行结论。纯函数：只吃识别结果与两份名单，不看画面。

    口径（2026-11-15 用户拍板）：

    1. **避战名单命中就出局**，除非优先名单命中更多（下一行）。
    2. **优先名单命中数量 > 避战名单命中数量 ⇒ 进「优先名单组」**。
       用户原话（当时叫黑 / 白名单）：「一个黑名单、两个白名单，那就按白名单走」。
    3. **数量相等且都 ≥1 ⇒ 按 ``conflict``**：``blacklist``（默认）出局、
       ``whitelist`` 进优先名单组。用户原话：「相等的时候才优先走黑名单」。
    4. **只命中优先名单 ⇒ 优先名单组**；**两边都没命中 ⇒ 普通组**（不是出局）。
    5. 认不出的头像不计入任何一边；四个全认不出本身就是「两边都没命中」，
       进普通组 —— 优先名单只是偏好，没有理由因为认不出就把它排除。

    数量按**不同英雄名**计（``set`` 交集大小）：同一名英雄重复出现只算一次，
    上限 4（一行只有四个槽位）。
    """

    heroes = set(team.heroes)
    black = len(heroes & blacklist)
    white = len(heroes & whitelist)
    if black and white:
        if white > black:
            return RowVerdict(
                TIER_WHITE, f"优先命中更多（优先{white}／避战{black}）", white
            )
        if white < black:
            return RowVerdict(
                TIER_OUT, f"避战命中更多（避战{black}／优先{white}）", white
            )
        if conflict == "whitelist":
            return RowVerdict(
                TIER_WHITE, f"命中数相等（{white}／{black}），按设置照打", white
            )
        return RowVerdict(TIER_OUT, f"命中数相等（{black}／{white}），按设置跳过", white)
    if black:
        return RowVerdict(
            TIER_OUT, "命中避战名单：" + "、".join(sorted(heroes & blacklist)), white
        )
    if white:
        return RowVerdict(
            TIER_WHITE, "命中优先名单：" + "、".join(sorted(heroes & whitelist)), white
        )
    return RowVerdict(TIER_NORMAL, "两边都没命中")

