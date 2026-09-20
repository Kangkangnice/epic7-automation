"""Visual evidence for the activity mini-game survivor route."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from auto_game_unified.core.matcher import Match, find_best_template, load_template

from .common import AtomEvidence, EvidenceProfile, EvidenceState, PageEvidence


REFERENCE_SIZE = (1982, 1132)
# 开局只发一把随机武器，武器名、图标、Lv 和描述文字每次都可能不同，都不能做锚点。
# 稳定的是卡片左上角的分类标签：一个 22x23 的分类图标加「攻击武器」四个字。
# 实测 2026-09-16 首卡页命中 1.0000，在 story/reward、arena/result、
# expedition/result、navigation/lobby 四张负例上最高只有 0.4530，取 0.90。
WEAPON_CARD_THRESHOLD = 0.90
# 卡片在基准画面中的范围，实测自饱和度连通块 (757,282)-(1133,896)。卡片任意位置
# 都可点击，所以点击点直接用锚点命中中心；该中心必须落在卡片内，否则会点到卡片外。
WEAPON_CARD_BOX = (757, 282, 376, 614)

# 结算页靠固定标题「游戏结果」识别：奖励数量（+3/+11）、游玩时间、武器名每次都不同，
# 都不能做锚点。实测 2026-09-16 正向 1.0000，8 张负例（含另外三条路线的结算页）
# 最高 0.3847，取 0.90。
RESULT_TITLE_THRESHOLD = 0.90
# 「重新进行」是循环的闭环动作：点一下直接进下一轮。实测正向 1.0000，负例最高 0.5077，取 0.90。
RESULT_RESTART_THRESHOLD = 0.90
# 按钮底板实测自饱和度连通块 (632,974)-(946,1067)。锚点命中中心 (789,1021) 落在这块内。
RESULT_RESTART_BOX = (632, 974, 314, 93)
# 右边并排的「确认」底板 (978,973)-(1293,1067)：尺寸与「重新进行」只差 1 像素、中心只差
# 346 像素。误点它会离开结算流程，所以「重新进行」的搜索区域必须收紧到左半边。
CONFIRM_BUTTON_BOX = (978, 973, 315, 94)

# 局内画面靠右上角固定文字「Score」识别（分值和计时每次都变，不能做锚点）。
# 实测 2026-09-16 正向 1.0000，负例最高 0.5228（首卡页），取 0.90。
BATTLE_SCORE_THRESHOLD = 0.90

# 升级三选一弹窗：两个锚点**任一命中即可**（any_of），因为它们各自都有失效的场景。
#
# 锚点一「升级」标题（`level_up_title.png` 89x45）：白色文字，但**压在半透明面板上**，
#     面板会透出背后的局内画面。2026-09-16 21:29 的报错帧上，这一块的背景整体变暗
#     （R 通道均值 169→101），同为 1.0000 的两张老帧到它上面只剩 0.8662。
# 锚点二「重新抽取」按钮上的文字（`level_up_redraw.png` 112x27）：按钮底板不透明，
#     几乎不受背景影响（报错帧 0.9874）。它唯一的风险是**抽完次数后可能变灰**，
#     那时就得靠标题兜底。
#
# **不要再用副标题「请选择武器。」当锚点**：它同样压在半透明面板上、更容易透出背景，
# 2026-09-16 实跑留下的三选一实时帧上只有 0.7101（同一张图在夹具上是 1.0000），
# 整页因此认不出来，状态机把弹窗当成首卡页、在选卡画面上继续滑摇杆，30 秒后判 UNKNOWN。
#
# **两个模板都在 2026-09-16 重裁成「只有字形」的紧凑版**（原先外围留白占 43% / 51%，
# 那些留白就是半透明面板的像素）。实测重裁后正例更高、负例更低：
#     标题   0.8662 → 0.9171（报错帧），负例最高 0.4567 → 0.3310
#     按钮   0.9134 → 0.9874（报错帧），负例最高 0.2078 → 0.1867
# 重裁工具：`tools/refit_text_anchor.py`（裁图时同时打印 ASCII 图确认字形没裁缺）。
LEVEL_UP_THRESHOLD = 0.90
# 三张卡横向并排、位置固定（无滚动），格式 (x, y, width, height)，实测自饱和度连通块。
LEVEL_UP_CARDS = (
    (326, 239, 380, 662),
    (759, 276, 374, 616),
    (1183, 282, 376, 614),
)
# 卡片顶部标签栏（分类图标 + 分类名）所在的纵向范围。卡面颜色就体现在这一条上，
# 是判断「哪张是蓝卡」的取样带。
LEVEL_UP_LABEL_STRIP_Y = (310, 380)
# 升级页底部中央的「重新抽取」按钮实测盒 (980,1037)-(1100,1072)，旁边标着剩余次数。
# 它会消耗抽取次数，**永远不许点**（同结算页的「确认」）；它的文字同时是升级页的
# 判别锚点——锚点中心必须落在这个盒子里，这条由测试守住。
LEVEL_UP_REDRAW_BOX = (980, 1037, 120, 35)
# 蓝卡（= 攻击武器，含开局那把）标签栏中位色相实测：开局卡 94、升级页左卡 94、右卡 94。
# 青绿卡（辅助武器）实测 76~77。下界取两者中点（86）留安全间隔；上界放宽到蓝紫交界，
# 避免更深的蓝卡被误判成非蓝。
BLUE_CARD_HUE = (86, 128)

REGIONS = {
    # 收紧到卡片头部一带：既覆盖锚点，又把局内动态画面和底部区域排除在搜索范围外。
    "weapon_card_label": (700, 250, 480, 170),
    # 标题一带。窗口要容得下 220x66 的模板滑动，再往外留点余量防轻微偏移。
    "result_title": (790, 120, 380, 170),
    # 左半边按钮区：右边界 900 小于「确认」底板起点 978，孪生按钮进不了搜索范围。
    "result_restart": (700, 970, 200, 110),
    # 标题一条，收紧到文字所在行，避免在别处文字上误命中。
    "level_up_title": (860, 60, 200, 130),
    # 「重新抽取」一带。模板 132x47，这个窗口够它滑动，又不会滑到别的按钮上。
    "level_up_redraw": (950, 1005, 180, 100),
    # 右上角分值一带。避开底部中央的「重新抽取」按钮（(980,1037)-(1100,1072)）与
    # 雷电键位提示浮层（约 (1668,617)），这两个都不是游戏 UI。
    "battle_score_label": (1380, 60, 260, 150),
}

THRESHOLDS = {
    "weapon_card_label": WEAPON_CARD_THRESHOLD,
    "result_title": RESULT_TITLE_THRESHOLD,
    "result_restart": RESULT_RESTART_THRESHOLD,
    "level_up_title": LEVEL_UP_THRESHOLD,
    "level_up_redraw": LEVEL_UP_THRESHOLD,
    "battle_score_label": BATTLE_SCORE_THRESHOLD,
}


def build_survivor_evidence(template_root: Path) -> EvidenceProfile:
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=f"survivor/{key}.png",
            region=REGIONS[key],
            threshold=THRESHOLDS[key],
            reference_size=REFERENCE_SIZE,
        )
        for key in REGIONS
    }
    return EvidenceProfile(
        atoms=atoms,
        # 顺序就是一轮循环的顺序：选首卡 -> 局内 -> （升级三选一）-> 结算 -> 回首卡页。
        pages=(
            PageEvidence(
                "survivor.weapon_card",
                required=("weapon_card_label",),
                # 三选一弹窗左卡的分类标签同样是「攻击武器」，和首卡页一模一样：实测
                # 弹窗上这个锚点能拿到 0.9994。少了这条排除，弹窗就会被当成首卡页
                # （2026-09-16 就是这么卡住的）。「重新抽取」只有弹窗上才有，拿它排除。
                forbidden=("level_up_redraw",),
            ),
            PageEvidence(
                "survivor.battle",
                required=("battle_score_label",),
            ),
            PageEvidence(
                "survivor.level_up",
                # 两个锚点任一命中即可：标题怕半透明面板透底，按钮怕抽完次数后变灰，
                # 谁先失效另一个都能兜住（见上面 LEVEL_UP_THRESHOLD 那段的实测数据）。
                any_of=(("level_up_title", "level_up_redraw"),),
            ),
            PageEvidence(
                "survivor.result",
                required=("result_title",),
            ),
        ),
        config_path=str(Path(__file__).resolve()),
        template_root=template_root,
    )


# 页面 -> 可点锚点。可点锚点为 None 表示这一页的点击目标不靠锚点算：
# 升级页的三张卡位置固定，由 `survivor.choose_level_up_card` 决定点哪张。
#
# 这个元组只管**判定顺序**和点哪儿；每一页的必要/排除锚点一律从 profile 里读，
# 免得 required / forbidden 在两处各写一份、改一处忘一处。
#
# **局内页排最后**：它的锚点是右上角的常驻 HUD 文字，弹窗盖上来时可能仍然可见，
# 所以必须先判弹窗页（结算 / 三选一），判不出来才认作「还在局内」。
# 四个页面的互斥性由 tests/test_survivor_evidence.py 的矩阵测试守着。
_PAGE_ORDER = (
    ("survivor.result", "result_restart"),
    ("survivor.level_up", None),
    ("survivor.weapon_card", "weapon_card_label"),
    ("survivor.battle", None),
)


@dataclass(frozen=True)
class SurvivorObservation:
    """一帧画面的识别结果。"""

    page: str | None
    anchor: tuple[int, int] | None


class SurvivorObserver:
    """运行时页面识别：按 evidence profile 做模板匹配，返回命中的页面与可点锚点中心。"""

    def __init__(self, profile: EvidenceProfile, template_root: Path) -> None:
        self.profile = profile
        self.template_root = template_root
        self.templates = {
            key: load_template(str(template_root / atom.template_path))
            for key, atom in profile.atoms.items()
        }

    def locate(self, screen: np.ndarray, key: str) -> Match | None:
        atom = self.profile.atom(key)
        match = find_best_template(
            screen,
            self.templates[key],
            region=atom.region,
            reference_size=atom.reference_size,
        )
        if match is None or match.score < atom.threshold:
            return None
        return match

    def observe(self, screen: np.ndarray) -> SurvivorObservation:
        # 先把每个锚点都定位一次，再把布尔结果交给 `PageEvidence.evaluate` 判页：
        # required / any_of / forbidden 的语义只在 `common.py` 里有一份实现，
        # 这里不再抄一遍（2026-09-16 加了 any_of 之后，抄的那份漏判会让每帧都命中升级页）。
        matches = {key: self.locate(screen, key) for key in self.profile.atoms}
        flags = {key: match is not None for key, match in matches.items()}
        for page_key, click_key in _PAGE_ORDER:
            page = self.profile.page(page_key)
            if page.evaluate(flags) is not EvidenceState.SAFE:
                continue
            if click_key is None:
                return SurvivorObservation(page_key, None)
            anchor = matches[click_key]
            return SurvivorObservation(
                page_key, None if anchor is None else anchor.center
            )
        return SurvivorObservation(None, None)


def build_survivor_observer(template_root: Path) -> SurvivorObserver:
    return SurvivorObserver(build_survivor_evidence(template_root), template_root)
