# -*- coding: utf-8 -*-
"""宠物领养的视觉证据（2026-11-15 模拟器实机帧采集）。

## 判据为什么这么设计

用户口述里最要紧的一条：**领养弹窗里只点带「免费」字样的那颗按钮**。
没有免费标记的领养会消耗宠物领养券，属于不可逆花费。所以这一页不能用
「左边第一颗按钮」这种位置判据，也不能靠「没找到免费」反推「已经领完」。

因此领养弹窗的两态各有**独立的正向证据**：

* 今日免费额度已用完 —— 左按钮上出现紫色券图标（``paid_ticket_icon``）。
  实测本页 1.0000，全库 117 张其它帧最高 0.1572，是干净的排他判据。
* 今日可免费领养 —— 免费态已于 2026-11-16 采到并接线：金色「免费」二字
  （``free_adopt_text``）+「N/N可免费领养！」提示条（``free_adopt_hint``）。
  两态都不认得时安全停止并留证，不点任何按钮，见路线模块与 TODO 登记。

两态都不认得 = 陌生页，绝不猜测。这是「判据唯一 + 陌生页可恢复」的落地。

## 页面判定顺序

领养弹窗是半透明遮罩，实测底下宠物小屋的 ``house_title`` 在弹窗帧上仍有
0.9996。所以弹窗必须排在宠物小屋之前判，否则会对着被盖住的小屋按钮点。

``shop_title`` 与 ``house_title`` 是四个形近的中文字，互相只有 0.6472，
阈值 0.80 两侧余量 0.20 / 0.15，不靠顺序也能分开。

## 模板不含会变内容

* 左上标题只裁四个字，避开模拟器绿色 FPS 数字与返回箭头。
* 快捷菜单入口只裁小房子图标本体，避开会出现的红点角标。
* 冷却文字只取两种文案共有的「后可购买」四字（2026-11-19 定稿）：游戏日刷新
  显示「N小时后可购买」、周额度用尽显示「N天后可购买」，前缀会变且长度不同，
  所以模板只裁不变的尾部，避开会变的小时数 / 天数，用宽区域滑窗吸收文字平移。
  一张模板同时覆盖两态：实测新帧「3天后」三行 1.0000/0.9474/0.9962、
  老帧「1小时后」三行 0.9622/0.9190/0.9625，亮态帧 0 命中（排他）。
* 券图标只裁图标，不裁按钮里的数量与右上角会变的券余额。

## 商店三行

滑到底后三行宠物用品依次为：一般饲料（一周 3 次）、宠物玩具（一周 1 次）、
宠物玩具（一周 1 次）。三行「小时后可购买」用 ``find_all_templates`` 逐行检出，
实测分数 1.000 / 0.995 / 0.956。三行全灰 = 本周买不了，正常收工。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from auto_game_unified.core.matcher import Match, find_all_templates
from auto_game_unified.games.epic7.evidence.common import (
    AtomEvidence,
    EvidenceProfile,
    PageEvidence,
)
REFERENCE_SIZE = (1982, 1132)
DEFAULT_THRESHOLD = 0.80

REGIONS: dict[str, tuple[int, int, int, int]] = {
    # 宠物小屋左上「宠物小屋」四字。
    "house_title": (60, 45, 240, 100),
    # 宠物小屋底部绿色「领养」按钮（页面判据 + 点击目标）。
    "house_adopt_button": (1150, 990, 380, 120),
    # 宠物小屋左下蓝色「宠物商店」按钮（页面判据 + 点击目标）。
    "house_shop_button": (20, 985, 370, 120),
    # 领养弹窗「领养宠物」四字。
    "adopt_modal_title": (290, 130, 240, 100),
    # 领养弹窗左按钮上的紫色券图标 = 今日免费已用完的正向证据（只判不点）。
    "paid_ticket_icon": (545, 910, 110, 110),
    # 领养弹窗底部「点击关闭」。
    "adopt_modal_close": (850, 1040, 300, 80),
    # 免费态（2026-11-16 采到，额度刷新当天）：左按钮上的**金色「免费」二字**，
    # 以及按钮上方「N/N可免费领养！」的提示条 —— 模板只裁「可免费领养！」，
    # 不含会变的数字。⚠️ 券图标两态都有（付费态是券 + 数字，免费态是券 + 免费），
    # **不能拿它判"今日已领完"**：2026-11-15 版就是这么误判的，白丢一天免费领养。
    "free_adopt_text": (580, 920, 320, 100),
    "free_adopt_hint": (650, 850, 260, 80),
    # 领养结果弹窗顶部紫色横幅「领养结果」。
    "adopt_result_title": (820, 160, 280, 90),
    # 商店左上「宠物商店」四字。
    "shop_title": (60, 45, 240, 100),
    # 滑到底的证据：第一行「宠物用品 / 一般饲料」固定文字。
    # ⚠️ 区域必须**罩住整个商品列表**，不能只罩第一次采集时的那一行位置：
    # 第二轮连跑时列表已停在上次的位置、再进商店滚动位置略有不同，
    # 实测窄区域把 1.0000 掉到 0.2797，状态机误判「还没滑到底」又滑 3 次，
    # 越滑越偏直到状态超时（2026-11-15 实跑复现）。宽区域实测：
    # 正常底部 1.0000 / 滚动位置偏移帧 0.9878 / 未滑帧 0.4242 ⇒ 0.80 门槛
    # 两侧余量 0.19 与 0.38，仍然能证伪。
    "shop_supplies_section": (950, 200, 400, 900),
    # 灰态冷却文字；三行共用一个宽区域逐行检出。模板只裁两态共有的「后可购买」
    # （日刷新「N小时后」/ 周用尽「N天后」前缀不同，见模块 docstring）。
    # 同理放宽到整列，避免滚动位置变化后漏检某几行。
    "shop_cooldown": (720, 200, 320, 920),
    # 三件用品的**商品名**（2026-11-16 采到的亮态帧）：「一般饲料」1 行、
    # 「宠物玩具」2 行。为什么用名字定位而不是「购买」两个字：领养券那两行也有
    # 「购买」，只有商品名能把"用品行"与"券行"分开，避免误点 500 天空石的礼包。
    # 区域罩整列（高 620）而不是只罩某一行：滚动落点差几十像素是常态。
    "supply_food_name": (1020, 500, 210, 620),
    "supply_toy_name": (1020, 500, 210, 620),
    # 购买确认框（2026-11-17 实跑诊断帧采集）。
    # ⚠️ 2026-11-16 曾**借用企鹅批量购买**的「数量」弹窗模板，实跑时标题只有
    # 0.2736、购买按钮 0.0000 ⇒ 认不出弹窗、卡到超时（退出码 1）。两个弹窗
    # 长得像但不是同一个：宠物商店是「购买商品 / 确定要购买该商品吗？」。
    # 已从真机诊断帧重裁，本页 1.0000 / 商店底部 ≤0.25。
    # 2026-11-23 弹窗改版：标题上移到 y=242、问句到 y=337（旧版 y=287/392），
    # 绿色「购买」从 y=801 下移到 y=921。三条搜索带都要同时罩住新旧两版：
    # 旧窗口标题/问句区域从 y=220/340 起，会把新版那一行截掉上半截；
    # 购买按钮旧窗口只到 y=840，新版按钮落在框外 ⇒ 点了却认不出，卡到超时。
    # 全库 479 帧复扫：放宽后的「购买」过阈 12 张，全是各路线**共用同一颗按钮**
    # 的购买确认弹窗 ⇒ 排他交给下面的 ``shop_title``（宠物商店底页独有）。
    "confirm_title": (780, 180, 420, 190),
    "confirm_buy": (1140, 740, 180, 230),
    # 「确定要购买该商品吗？」固定提示，与标题一起证伪「相似但不同」的弹窗。
    "confirm_question": (720, 280, 460, 180),
}

THRESHOLDS = {key: DEFAULT_THRESHOLD for key in REGIONS}
# 「点击关闭」是全局通用控件，跨页同形分数可到 0.9971。它只在
# ``adopt_modal_title`` 已确认的弹窗里使用，靠页面判据排他，不靠自己排他。
THRESHOLDS["adopt_modal_close"] = 0.80

_TEMPLATE_PATHS = {key: f"{key}.png" for key in REGIONS}
# 三行冷却共用同一张模板；逐行检出用 ``cooldown_rows``，不走页面组合。
_TEMPLATE_PATHS["shop_cooldown"] = "shop_cooldown.png"

# 同一控件的第二长相（2026-11-23）。判定语义是「任一过阈即命中」，所以旧版帧
# 仍由原模板负责、新版帧由 *_v2 接住，谁都不用调阈值：
#   新版帧 旧模板 0.7897/0.6048（阈 0.80）→ v2 双 1.0000；
#   旧版帧 原模板双 1.0000 → v2 0.7897/0.6048。
# 新模板从当日失败帧裁；全库 479 帧里过阈的只有企鹅数量弹窗 / 月塔购买页
# （共用同款弹窗皮肤），它们没有宠物商店底页标题 ⇒ 由 purchase 页的
# ``shop_title`` 排他（宠物弹窗 0.9998，那两类最高 0.7514）。
_ALT_TEMPLATES = {
    "confirm_title": ("confirm_title_v2.png",),
    "confirm_question": ("confirm_question_v2.png",),
}

_PAGES = (
    # 领养结果弹窗在最前：它盖在领养弹窗上，领养弹窗标题在这帧掉到 0.7815，
    # 顺序反了就会把结果页当成"还可以领"的弹窗。
    PageEvidence("pet_adoption.adopt_result", required=("adopt_result_title",)),
    # 购买确认框：标题 + 固定问句 + 绿色「购买」三锚点同时命中才认。
    # ⚠️ 2026-11-16 用「标题 + 购买 + 商店标题」，买错了模板（企鹅数量弹窗）
    # 且商店标题在遮罩下不稳；改成自采三锚点后正例全 1.0000、反例全 ≤0.25。
    PageEvidence(
        "pet_adoption.purchase",
        # shop_title 是排他锚点：宠物商店购买弹窗 0.9998，企鹅/月塔/迷宫/刷书签
        # 那些同款弹窗最高只有 0.7514（阈 0.80），不会串到这条路线来。
        # 它在 11-16 曾被摘掉（当时遮罩下不稳），现两版实测都满分，恢复它。
        required=("confirm_title", "confirm_question", "confirm_buy", "shop_title"),
    ),
    # 弹窗在前：半透明遮罩下小屋标题仍是 0.9996（见模块 docstring）。
    PageEvidence("pet_adoption.adopt_popup", required=("adopt_modal_title",)),
    # 商店滑到底：标题 + 三件用品区同时出现。
    PageEvidence(
        "pet_adoption.shop_bottom",
        required=("shop_title", "shop_supplies_section"),
    ),
    # 商店上半部：只有标题，用品区还没进视口。
    PageEvidence(
        "pet_adoption.shop_top",
        required=("shop_title",),
        forbidden=("shop_supplies_section",),
    ),
    # 宠物小屋：标题 + 两颗底部按钮，避免与商店页串。
    PageEvidence(
        "pet_adoption.house",
        required=("house_title", "house_adopt_button"),
    ),
)

# 三行「小时后可购买」的逐行检出参数。min_gap=120 小于行间距约 218，
# 大于模板高 40，三个真实实例不会被互相抑制。
COOLDOWN_ROW_MIN_GAP = 120
COOLDOWN_ROW_COUNT = 3


def build_pet_adoption_evidence(template_dir: Path) -> EvidenceProfile:
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=relative_path,
            region=REGIONS[key],
            threshold=THRESHOLDS[key],
            reference_size=REFERENCE_SIZE,
            alt_template_paths=_ALT_TEMPLATES.get(key, ()),
        )
        for key, relative_path in _TEMPLATE_PATHS.items()
    }
    return EvidenceProfile(
        atoms=atoms,
        pages=_PAGES,
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )


def cooldown_rows(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> list[Match]:
    """逐行检出「小时后可购买」，按 y 从小到大返回。

    三行是同一种固定文字，只靠 ``find_template`` 永远只能看到分数最高的那一个。
    宽区域 + 非极大值抑制把三行都找出来，业务才能回答「三件是不是都买不了」。
    """
    scale_y = screen.shape[0] / reference_size[1]
    gap = max(1, round(COOLDOWN_ROW_MIN_GAP * scale_y))
    hits = find_all_templates(
        screen,
        template,
        DEFAULT_THRESHOLD,
        region=REGIONS["shop_cooldown"],
        reference_size=reference_size,
        min_gap=round(gap / scale_y),
    )
    return sorted(hits, key=lambda match: match.center[1])
