"""Arena visual evidence profile.

This module is intentionally limited to assets, regions and page evidence. Arena
business decisions remain in ``games.epic7.arena``.
"""

from pathlib import Path
from typing import Mapping

from .common import (
    AtomEvidence,
    AtomObservation,
    EvidenceProfile,
    EvidenceState,
    PageEvidence,
)
from .pre_battle import (
    QUICK_BUTTON_THRESHOLD,
    QUICK_SWITCH_THRESHOLD,
    REGION as PRE_BATTLE_REGION,
    classify_pre_battle_evidence,
    PreBattleEvidenceState,
)


REFERENCE_SIZE = (1982, 1132)
RANK_PROMOTION_ARROW_REGION = (850, 760, 280, 170)
RANK_PROMOTION_CONFIRM_REGION = (700, 930, 520, 202)
FREE_REFRESH_TITLE_REGION = (700, 300, 550, 160)
FREE_REFRESH_OFFER_REGION = (850, 700, 350, 180)
FREE_REFRESH_CONFIRM_REGION = (1050, 700, 400, 180)

# 「战斗结果」页底部那条「战斗结果 / 确认」是**竞技场和远征共用**的通用结算条
# （实测竞技场 result.png 上 confirm=1.0000，远征 result.png 上也有 0.9448 > 阈值），
# 光靠它分不出这是哪条路线的结算页。下面两个是竞技场结果页专有的内容锚点：
#
# - ``result_rating``：「积分」= 评分面板标题。**胜负都会出现**，原本当主判据用。
#   ⚠️ 2026-09-25 拿真机结算帧复测：它只在**旧基准夹具**上有效，真机 5 张全部只有
#   0.3815~0.3899（阈值 0.80）⇒ **真机上早就失效了**。没有立刻换掉它，是因为它同时
#   被接力页判据引用、换模板会牵动多条测试；实际在干活的是下面两个横幅锚点。
# - ``result_victory`` / ``result_defeat``：「VICTORY」/「DEFEAT」横幅，一局只会出现一个。
#
# 两个横幅**占的是同一块区域**（``ARENA_RESULT_BANNER_REGION``）：2026-09-25 真机帧实测，
# 它们都落在这一带；共用搜索区，两个锚点才是同一把尺子。
#
# 阈值 0.80 的依据（2026-09-25 复测，数字来自 ``runtime_logs/_arena_defeat_probe.txt``）：
# - ``result_victory``：真机赢局帧 0.8761~0.8816；全库 227 张夹具里除结果页外最高 0.2724。
# - ``result_defeat``：真机输局帧 0.9871~1.0000；**赢局帧只有 0.1090~0.1129**；
#   全库 227 张夹具里最高 **0.3828**（远征 result.png）—— 离 0.80 还差一倍。
# - ``result_victory`` 模板是 2026-09-16 从 ``tests/fixtures/epic7_arena/result.png`` 实裁的；
#   ``result_defeat`` 是 2026-09-25 从真机输局帧实裁的 —— 那天有两张帧被记成「未知」，
#   其实都是输局。源帧出自 ``docs/manual_review/arena/..._unknown_r4.png``，
#   但那个目录**只留最近 10 张、会被轮转删掉**，所以别把它当依赖；回归用的是
#   ``tests/fixtures/epic7_arena/result_defeat_live_20260925.png``（原 r1，**另一张**）。
ARENA_RESULT_RATING_REGION = (922, 657, 73, 41)
ARENA_RESULT_BANNER_REGION = (683, 378, 558, 83)
ARENA_RESULT_VICTORY_REGION = ARENA_RESULT_BANNER_REGION
ARENA_RESULT_DEFEAT_REGION = ARENA_RESULT_BANNER_REGION

REGIONS = {
    "list_ready": (700, 900, 520, 250),
    "challenge": (700, 930, 520, 202),
    "battle_start": (900, 930, 550, 202),
    "auto_off": (1550, 0, 300, 220),
    "confirm": (1500, 930, 420, 202),
    "no_ticket": (700, 150, 700, 300),
    "friendship_ticket_offer": (540, 470, 440, 230),
    "ticket_purchase_button": (900, 760, 500, 260),
    # 「购买旗帜」弹窗的**双锚点**：票耗尽时路线要先把这颗弹窗关掉再回家
    # （终点必须在非浮层页上，口径见 docs/maintenance/route_finish_points.md）。
    #
    # ⚠️ 为什么非要两个锚点：单靠「取消」两个字**会串门** —— 实测
    # 迷宫「购买确认」0.9757 / 迷宫「放弃确认」0.9758 都会命中（「取消」是通用文字）。
    # 加上标题后，那两张分别掉到 0.8044 / 0.4981，**只有票耗尽这张双过线**。
    "purchase_title": (830, 255, 350, 90),
    "purchase_cancel": (695, 845, 215, 100),
    "rank_promotion_arrow": RANK_PROMOTION_ARROW_REGION,
    "rank_confirm": RANK_PROMOTION_CONFIRM_REGION,
    "refresh_title": FREE_REFRESH_TITLE_REGION,
    "refresh_free": FREE_REFRESH_OFFER_REGION,
    "refresh_confirm": FREE_REFRESH_CONFIRM_REGION,
    "quick_battle_button": PRE_BATTLE_REGION,
    "quick_battle_switch": PRE_BATTLE_REGION,
    "result_rating": ARENA_RESULT_RATING_REGION,
    "result_victory": ARENA_RESULT_VICTORY_REGION,
    "result_defeat": ARENA_RESULT_DEFEAT_REGION,
}

THRESHOLDS = {
    "list_ready": 0.88,
    "challenge": 0.90,
    "battle_start": 0.90,
    "auto_off": 0.85,
    "confirm": 0.90,
    "no_ticket": 0.90,
    "friendship_ticket_offer": 0.92,
    "ticket_purchase_button": 0.92,
    # 双锚点都取 0.90：本尊两处实测都是 1.0000，空间充足；
    # 而最近的干扰项（迷宫购买确认的标题）只有 0.8044，留了 0.096 的余量。
    "purchase_title": 0.90,
    "purchase_cancel": 0.90,
    "quick_battle_button": QUICK_BUTTON_THRESHOLD,
    "quick_battle_switch": QUICK_SWITCH_THRESHOLD,
    # 文字贴在半透明结算面板上，跟 story/竞技场其它动态页一个量级看待。
    "result_rating": 0.80,
    "result_victory": 0.80,
    "result_defeat": 0.80,
}

# 这里只列「在 PC 客户端上实测过」的锚点。``result_rating`` / ``result_victory``
# 没有 PC 实测数据，就不编一个覆盖值 —— 它们会用 THRESHOLDS 里的 0.80。
PC_THRESHOLD_OVERRIDES = {
    # 两次 PC 实跑队伍页均为 0.711；现有 160 张非目标画面最高为 0.561。
    "list_ready": 0.75,
    "challenge": 0.85,
    "battle_start": 0.70,
    "auto_off": 0.80,
    "confirm": 0.85,
    "no_ticket": 0.85,
    "friendship_ticket_offer": 0.87,
    "ticket_purchase_button": 0.87,
}

DEFAULT_THRESHOLD = 0.90
PC_DEFAULT_THRESHOLD = 0.85

_TEMPLATE_PATHS = {
    "rank_promotion_arrow": "global/arena_rank_promotion_arrow.png",
    "list_ready": "list_ready.png",
    "challenge": "challenge.png",
    "battle_start": "battle_start.png",
    "auto_off": "auto_off.png",
    "confirm": "confirm.png",
    "rank_confirm": "rank_confirm.png",
    "no_ticket": "no_ticket.png",
    "friendship_ticket_offer": "friendship_ticket_offer.png",
    "ticket_purchase_button": "ticket_purchase_button.png",
    "purchase_title": "arena_purchase_title.png",
    "purchase_cancel": "arena_purchase_cancel.png",
    "refresh_title": "arena_refresh_title.png",
    "refresh_free": "arena_refresh_free.png",
    "refresh_confirm": "arena_refresh_confirm.png",
    "quick_battle_button": "global/quick_battle_button.png",
    "quick_battle_switch": "global/quick_battle_switch.png",
    "result_rating": "arena_result_rating.png",
    "result_victory": "arena_result_victory.png",
    "result_defeat": "arena_result_defeat.png",
}


def classify_arena_selected_scores(
    challenge_score: float | None,
    list_ready_score: float | None,
) -> EvidenceState:
    if challenge_score is None:
        return EvidenceState.UNKNOWN
    if list_ready_score is None or challenge_score >= list_ready_score:
        return EvidenceState.SAFE
    return EvidenceState.UNKNOWN


def evaluate_arena_pages(
    observations: Mapping[str, AtomObservation],
) -> Mapping[str, EvidenceState]:
    flags = {key: item.observed for key, item in observations.items()}

    def score(key: str) -> float | None:
        item = observations.get(key)
        return item.score if item is not None and item.observed else None

    states = {
        page.key: page.evaluate(flags)
        for page in _PAGES
    }
    states["arena.selected"] = classify_arena_selected_scores(
        score("challenge"), score("list_ready")
    )
    pre_battle = classify_pre_battle_evidence(
        normal_observed=flags.get("battle_start", False),
        quick_observed=flags.get("quick_battle_button", False),
        switch_observed=flags.get("quick_battle_switch", False),
    )
    states["arena.team"] = (
        EvidenceState.UNSAFE
        if flags.get("no_ticket", False)
        else EvidenceState.SAFE
        if pre_battle is not PreBattleEvidenceState.UNKNOWN
        else EvidenceState.UNKNOWN
    )
    return states


_PAGES = (
    PageEvidence("arena.list", required=("list_ready",)),
    PageEvidence("arena.selected", required=("challenge",)),
    PageEvidence(
        "arena.team",
        any_of=(("battle_start", "quick_battle_button"),),
        forbidden=("no_ticket",),
    ),
    PageEvidence("arena.battle", required=("auto_off",)),
    # ``arena.result`` 是**运行期**用的松判据：此时进程已经确定自己在竞技场里，
    # 只要 ``confirm`` 在就说明结算页出来了。远征结算页也会命中这一条，但这不影响运行。
    PageEvidence("arena.result", required=("confirm",)),
    # ``arena.result_arena`` 是**接力期**用的紧判据：开局时屏幕上可能是任何路线，
    # 必须同时拿到竞技场专有的内容锚点才敢认，否则停在远征结算页会被误当竞技场结算。
    #
    # ⚠️ ``result_defeat`` 必须在这里：``result_rating`` 在真机帧上只有 0.38（见上方说明），
    # 少了它，接力落在**输局**结算页时会认不出来，退回去走「回大厅 → 重新导航」。
    # 而 ``result_defeat`` 在真机输局帧上是 0.9871~1.0000，在全库其它图上最高只有 0.3828。
    PageEvidence(
        "arena.result_arena",
        required=("confirm",),
        any_of=(("result_rating", "result_victory", "result_defeat"),),
    ),
    # 结果确认中（= 段位提升弹窗）复用已有的 ``arena.rank_promotion``：判据完全一样
    # （arrow + rank_confirm 双锚点），就不再另立一个页面键了。
    PageEvidence(
        "arena.rank_promotion",
        required=("rank_promotion_arrow", "rank_confirm"),
    ),
    PageEvidence(
        "arena.friendship_ticket_offer",
        required=("friendship_ticket_offer", "ticket_purchase_button"),
    ),
    PageEvidence(
        "arena.refresh_confirmation",
        required=("refresh_title", "refresh_free", "refresh_confirm"),
    ),
)


def thresholds_for(backend: str) -> dict[str, float]:
    thresholds = dict(THRESHOLDS)
    if backend == "pc":
        thresholds.update(PC_THRESHOLD_OVERRIDES)
    return thresholds


def build_arena_evidence(
    template_dir: Path,
    *,
    backend: str = "emulator",
) -> EvidenceProfile:
    thresholds = thresholds_for(backend)
    default_threshold = (
        PC_DEFAULT_THRESHOLD if backend == "pc" else DEFAULT_THRESHOLD
    )
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=relative_path,
            region=REGIONS[key],
            threshold=thresholds.get(key, default_threshold),
            reference_size=REFERENCE_SIZE,
        )
        for key, relative_path in _TEMPLATE_PATHS.items()
    }
    return EvidenceProfile(
        atoms=atoms,
        pages=_PAGES,
        page_evaluator=evaluate_arena_pages,
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
