"""欧多马顿塔（月塔）路线的视觉证据画像。

## 页面判据的选型（2026-10-08 实机采齐，全库分离度终检见下）

| 判据 | 判哪一页 | 本页最高 | 他页最高 | 间距 |
|---|---|---|---|---|
| `season_tower_title` | 赛季页（月塔卡片标题） | 1.0000 | 0.4092 | +0.59 |
| `home_enter` | 月塔主页（入场按钮） | 1.0000 | 0.4302 | +0.57 |
| `floor_select_team` | 楼层列表（选择队伍按钮） | 1.0000 | 0.5648 | +0.44 |
| `team_battle_start` | 准备战斗（战斗开始按钮） | 1.0000 | 0.5319 | +0.47 |
| `card_decide` | 三选一（决定装置按钮） | 1.0000 | 0.5104 | +0.49 |
| `result_clear` | 结算页（CLEAR 字样） | 1.0000 | 0.4614 | +0.54 |
| `conquer_title` | 征服弹窗（标题「征服欧多马顿塔」） | 1.0000 | 0.2810 | +0.72 |

阈值统一 0.88；16 张真机夹具上**逐帧零误报**（每帧恰好命中自己那页的判据）。

## ⚠️ 为什么不复用「右下角按钮槽」判页

月塔的**入场 / 选择队伍 / 战斗开始 / 下一层 共用右下角同一个按钮槽**
（实测各页该区域「绿底占比」都在 0.60~0.79），只靠位置和颜色分不开；
而按钮**文字**（入场 / 选择队伍 / 战斗开始）互相排他 ⇒ 判据一律走「按钮文字」。

## ⚠️ 为什么结算页不认「下一层」按钮

三选一页也有「下一层」（暗态，亮占比 0.000），结算页是亮态（0.032）。
但那一块区域在**六个页面上都有绿按钮**，亮度/绿占比都分不开
（实测 `floor_list` 0.767 / `home` 0.793 / `team` 0.783 / `result` 0.734）。
⇒ 结算页改用 `result_clear`（大 CLEAR 字样），那是结算页独有的。

## ⚠️ CLEAR 只裁左侧两个字母

中央有一颗**动画星芒**从上方穿过 V/A 之间，整行裁会带进会动的光效。
只裁 x=[803,922]（字母 C 和 L），这两个字母实测无光效污染。

## ⚠️ 两张模板刻意不存在

- **`home_title`（「欧多马顿塔」标题）**：楼层列表页左侧残留月塔主页，
  该标题在两页上都命中（1.000 / 0.987）⇒ **零区分度**，不能作判据。
- **`prepare_tower_label`（「欧多马顿塔N队」）**：队号会变（用户有多支队伍），
  且跨帧渲染大小不同（实测 0.335）⇒ 不稳定，不能作判据。
- **`conquer_button`（右下角「征服」按钮）**：2026-10-09 实测**不可用**。
  打满第 25 层时右下角按钮从「下一层」变成「征服」，想用它区分「该收工了」，
  但那一屏**从弹窗底下露出来**：

  ======================  ==========
  帧                       分数
  ======================  ==========
  `result_conquered_floor`  1.0000 ← 正样本
  `conquered`（弹窗屏）      0.9997 ← **也命中**
  ======================  ==========

  间距只有 **+0.0003** ⇒ 同一枚模板同时命中两屏，判据等于没有。
  根因是布局本身：`conquer` 与 `next-floor` 是**同一个按钮槽**（绿底 bbox
  逐像素一致：`1483,997 → 1879,1092`，只有文字不同），而弹窗是半透明的，
  不遮住它。**⇒ 结论：按钮文字不做判据，「打满」只认标题（见下）。**

三条都不进 `_TEMPLATE_NAMES`：它们**不是「可选」而是「不该存在」**。

## 「打满」为什么只认标题、不认按钮（2026-10-09 实机，用户拍板）

打满 25 层的链路是：**结算页（`result_clear`）→ 点右下角那个按钮 → 弹出
「征服欧多马顿塔」叙述屏 → 这一屏就是整条路线的终点，停**。

按钮文字**不需要**参与判据，理由有二：

1. 上面那条 —— 两屏都命中的模板没有区分度；
2. 更根本：`conquer` 与 `next-floor` 是**同一个按钮槽的两种文字**，而
   `tower.RESULT` 的动作本来就是「点那个槽位」。第 25 层点下去弹出的就是征服
   弹窗，**点哪个文字都是点同一个坐标**（`(1787, 1041)`）。

⇒ 动作照旧、判据只加一条 `conquer_title`。用户原话（2026-10-09）：
「一碰到这个界面就代表要结束了，就是整个环节的最终的一个终点」。
"""

from pathlib import Path

from auto_game_unified.core.matcher import MATCH_MODE_RAW, MATCH_MODE_WHITE_MASK

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)

REGIONS = {
    # 赛季页：月塔卡片标题（白字 + 左侧徽标）
    "season_tower_title": (600, 250, 900, 200),
    # 月塔主页：右下角「入场」按钮
    "home_enter": (1400, 950, 582, 182),
    # 楼层列表：右下角「选择队伍」按钮
    "floor_select_team": (1400, 950, 582, 182),
    # 准备战斗：右下角「战斗开始」按钮
    "team_battle_start": (1400, 950, 582, 182),
    # 准备战斗：左上「准备战斗」标题（候选证据，与上一个同一页）
    "prepare_title": (60, 55, 240, 80),
    # 三选一：右下角「决定装置」按钮
    "card_decide": (800, 950, 700, 182),
    # 三选一：底部提示文案「请选择装置后按下决定装置按钮。」
    "card_hint": (600, 870, 800, 120),
    # 结算页：中央大 CLEAR 的「C L」两个字母（避开动画星芒）
    "result_clear": (650, 400, 700, 180),
    # 打满后的「征服欧多马顿塔」叙述屏：居中标题（实测文字 bbox x[801,1117]
    # y[280,324]，区域留足四周余量）
    "conquer_title": (700, 230, 600, 150),
    # 局内：右上角「自动战斗已关闭」图标（**共享模板**，见下面 auto_off 原子）
    "auto_off": (1550, 0, 300, 200),
}

# 只有这两张需要放宽：它们在大厅/其它页面上能撞到 0.4~0.5 的分数，
# 但真机上稳定在 0.95+，所以沿用全局 0.88 已经足够，本表刻意留空。
#
# ⚠️ 唯一的例外是 `auto_off`，而且**必须**是例外：它换了比对口径。
#
# 它跟远征/主线共用同一张图（右上角「自动战斗已关闭」图标）。原来的比法是
# 原样 RGB，`TM_CCOEFF_NORMED` 把模板的**背景**也算进相似度 —— 那张模板生在
# 主线的亮灰雾天场景里，叠到月塔的深色书架上只剩 **0.7492**（月塔实跑 19:34
# 事故帧，阈 0.80）⇒ 判据失效，12 秒后报 `auto_point_missing`。
#
# 现在改用 `white_mask` 口径（两侧先二值化成「白色像素掩膜」再比）。同一批帧：
#
#   ==========================  ==========  ==========
#   帧                           原样比       白掩膜
#   ==========================  ==========  ==========
#   月塔真机夹具                  0.7704      0.9214
#   月塔实跑事故帧 13:59          0.7704      0.9214
#   月塔实跑事故帧 19:34          0.7492      0.9214
#   本页最高非战斗页（home 等）    0.4499      0.4499
#   ==========================  ==========  ==========
#
# 0.85 是**在新口径上重新扫全库**定出来的，不是把旧的 0.80 搬过来：
#   * 真阳性侧：月塔三帧都是 0.9214（余量 0.071）；全库最大的「真·战斗中」帧
#     0.9208（`story/battle_manual_skill_variant`）。
#   * 真阴性侧：全库 243 张基准帧里，**凡是不显示这个图标的**最高只到 0.6215
#     （余量 0.23）；月塔自己的非战斗页最高 0.4499。
#   * 0.85 正好落在「干净命中簇（>=0.9208）」与「其余一切（<=0.8347）」之间，
#     偏向命中侧一点 —— 这里漏判的代价（整条路线卡死）远大于误判。
#
# ⚠️ 别把这个数字当通用档：白掩膜下真阳性的最低分可以低到 0.64（相位/遮挡），
# 所以换到别的路线要**按那条路线自己的帧重扫**，不能照搬。
THRESHOLDS: dict[str, float] = {"auto_off": 0.85}

# 判据 -> 比对口径。只有 `auto_off` 走背景无关口径；其余锚点仍是原样 RGB。
# ⚠️ 本表必须与 `tower.TowerStateMachine._MATCH_MODES` 一致（同一套纪律：
# 类常量镜像证据画像），否则带假模板的用例会和真机走两个口径。
MATCH_MODES: dict[str, str] = {"auto_off": MATCH_MODE_WHITE_MASK}

_TEMPLATE_NAMES = (
    "season_tower_title",
    "home_enter",
    "floor_select_team",
    "team_battle_start",
    "prepare_title",
    "card_decide",
    "card_hint",
    "result_clear",
    "conquer_title",
)

# ⚠️ 月塔**一张模板都不许缺席**：`_TEMPLATE_NAMES` 里的每张都是某页面的
# 主判据或该判据的组合项，少一张就是配置错误，加载期 `FileNotFoundError` 直接拦。
#
# 为什么是空集而不是「先可选、以后再补」：远征的 `empty_posters` 就是这样丢的
# （模板文件不存在 → 收工判据整个失效 → 空等超时 6 次才被发现，详见
# `evidence/expedition.py` 的常量注释）。月塔起步就照远征 2026-10-04 之后的口径来。
#
# ⚠️ 本集合必须与 `tower.TowerStateMachine._OPTIONAL_TEMPLATES` **逐字一致**
# （`test_whitelist_matches_the_evidence_profile` 钉住）。
_OPTIONAL_TEMPLATES: frozenset[str] = frozenset()


def build_tower_evidence(template_dir: Path) -> EvidenceProfile:
    """月塔证据画像。阈值只有模拟器基线一套；平台差异收敛到图片。

    ⚠️ 月塔**只面向模拟器后端**（PC 端这条路线不可用，理由见
    `docs/PC_TEMPLATE_MIGRATION.md` 的月塔条目），所以不需要 PC 阈值覆盖。
    """
    thresholds = THRESHOLDS
    atoms = {
        name: AtomEvidence(
            key=name,
            template_path=f"{name}.png",
            region=REGIONS[name],
            threshold=thresholds.get(name, 0.88),
            required=name not in _OPTIONAL_TEMPLATES,
            reference_size=REFERENCE_SIZE,
            # 口径逐锚点声明；表里没写的走原样比（与 `thresholds.get(...)` 同一套写法）。
            match_mode=MATCH_MODES.get(name, MATCH_MODE_RAW),
        )
        for name in _TEMPLATE_NAMES
    }
    # `auto_off` 跟主线/远征**共用同一张图**（右上角「自动战斗已关闭」图标）：
    # 三处画的是同一个控件，尺寸一致 ⇒ 直接复用 `story/auto_off.png`，
    # 不按目标平台重裁（同内容跨平台不能复用那条规矩针对的是**同一控件在不同
    # 平台渲染尺寸不同**；这里三处是同一个模拟器口径）。
    #
    # ⚠️ 而且它走 `white_mask` 口径 ⇒ 这张图连「换场景」都不怕了：判据只认
    # 图标本身的白色形状，底图是书架、是雪原、是宫殿都一样。以后新增一条有战斗
    # 的路线，**直接引用这张图 + 这一档阈值**即可，不必再截一次。
    atoms["auto_off"] = AtomEvidence(
        key="auto_off",
        template_path="../story/auto_off.png",
        region=REGIONS["auto_off"],
        threshold=thresholds["auto_off"],
        reference_size=REFERENCE_SIZE,
        match_mode=MATCH_MODES["auto_off"],
    )
    return EvidenceProfile(
        atoms=atoms,
        pages=(
            PageEvidence("tower.season", required=("season_tower_title",)),
            PageEvidence("tower.home", required=("home_enter",)),
            PageEvidence("tower.floor_list", required=("floor_select_team",)),
            # 准备战斗页：主判据「战斗开始」；`prepare_title` 是同页的第二重证据。
            # ⚠️ 用 `required` 而不是 `any_of`：两枚锚点在同一页上实测同时命中
            # （1.000 / 1.000），都要求反而能把「页面渲染到一半」的帧挡在外面。
            PageEvidence(
                "tower.team",
                required=("team_battle_start", "prepare_title"),
            ),
            # 三选一页：按钮 + 提示文案同页共存（实测两枚都 1.000）。
            PageEvidence("tower.card", required=("card_decide", "card_hint")),
            PageEvidence("tower.result", required=("result_clear",)),
            # 打满 25 层的终点屏（「征服欧多马顿塔」叙述弹窗）。
            # ⚠️ 它是**整条路线的终点**，不是「一页过场」—— 认出即收工，不点任何
            # 东西（用户 2026-10-09 拍板）。与其余七页实测全部互斥（该屏上
            # `home_enter` 0.5780 / `result_clear` 0.3141，都不过阈）。
            PageEvidence("tower.conquered", required=("conquer_title",)),
        ),
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
