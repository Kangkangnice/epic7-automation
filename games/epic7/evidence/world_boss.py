"""骑士团「世界首领战」视觉证据档案。

本模块只放资源、区域、阈值和页面判据；业务决策在 ``games/epic7/world_boss.py``。

## 页面互斥的实测依据（2026-09-21，全库 185 张 1982×1132 夹具扫描）

六个锚点的「本路线最高 / 跨路线最高 / 倍数」：

| 锚点 | 本路线最高 | 跨路线最高 | 倍数 | 跨路线最高出处 |
|---|---|---|---|---|
| ``knights_title`` | 1.0000 | 0.6337 | 1.58x | arena/free_refresh_confirm_live_20260814 |
| ``worldboss_title`` | 1.0000 | 0.6223 | 1.61x | arena/free_refresh_confirm_live_20260814 |
| ``select_team_button`` | 1.0000 | 0.5861 | 1.71x | story/battle_guide_warning_live_20260815 |
| ``team_select_title`` | 1.0000 | 0.3693 | 2.71x | hero/transmit_selected |
| ``level_reward_title`` | 1.0000 | 0.4432 | 2.26x | story/friendship_points_popup |
| ``result_title`` | 1.0000 | 0.3612 | 2.77x | story/battle_guide_warning_live_20260815 |

跨路线最高 0.6337 离阈值 0.80 还有 0.17 的余量，故六个锚点统一取 **0.80**。

## ⚠️ 两个「锚点会串页」的坑（实施时必须看，别按直觉写判据）

### 1. ``worldboss_title`` 在本路线的四个页面上**常驻**，不能判「是主页」

「世界首领战」标题栏在世界首领战主页 / 选择辅助队伍 / 配置队伍 / 行动力不足弹窗
**四页上都是同一块、同一位置**（命中中心都是 (192,101)，得分 0.9988~1.0000）——
因为后三页本来就是世界首领战这一屏的子页面。所以：

- ✅ ``worldboss_title`` 可以判「我还在世界首领战里」（用于导航链校验、未知页面兜底）
- ❌ ``worldboss_title`` **不能**判 ``world_boss.home``，否则队伍页 / 体力弹窗都会被判成主页，
  状态机就会在队伍页上点「选择队伍」，白等到超时。

主页的排他锚点是 **``select_team_button``**（右下角「选择队伍」）：本路线只在该页命中
（主页 1.0000 / 次数耗尽页 0.9161），其余 7 张本路线夹具最高 0.4192。

### 2. ``result_title`` 在「战斗级别奖励」弹窗上仍可见（背景被压暗）

奖励弹窗是把结算页**压暗**后盖上去的，不是换页。``TM_CCOEFF_NORMED`` 对亮度缩放不敏感，
所以「战斗结果」四个字在奖励弹窗上还能拿 **0.7103**（项目记忆里「转场重试 来源=X仍在」同源问题）。

⇒ ``world_boss.result`` 必须写 ``forbidden=("level_reward_title",)``，靠奖励弹窗自己的标题排他。
实测该组合：battle_result 判 result、level_reward 判 level_reward，两页互不串。

## 体力弹窗：零改动复用 ``games/epic7/stamina.py``

行动力不足弹窗的三个模板（弹窗标题 / 生命之叶卡片 / 确认购买按钮）在世界首领战这一屏上
实测 0.9999 / 0.9895 / 1.0000，与 story 用的是同一套控件。本模块**不新建体力锚点**，
决策一律走 ``next_stamina_decision``。
"""

from pathlib import Path

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)

DEFAULT_THRESHOLD = 0.80

REGIONS = {
    # 骑士团主页 / 世界首领战主页的标题栏同处左上角。
    "knights_title": (0, 30, 500, 180),
    "worldboss_title": (0, 30, 500, 180),
    # 右下角「选择队伍」按钮。窗口要容得下 303x37 的模板滑动，
    # 又不能让搜索范围爬回队伍页的「组成战斗队伍」（中心 1631）那一带。
    "select_team_button": (1450, 990, 532, 130),
    # 「选择辅助队伍」页面标题，在标题栏下面一条。
    "team_select_title": (0, 140, 520, 140),
    # 配置队伍页左下角「自动配置」按钮。**注意**：体力弹窗是盖在这一页上的对话框，
    # 弹窗出现时本锚点仍有 0.9995（模板匹配对压暗不敏感），所以这一页必须
    # ``forbidden=("stamina_popup",)`` 才能与弹窗分开（见 _PAGES）。
    "team_config_auto": (100, 1000, 300, 110),
    # 「战斗级别奖励」弹窗标题（弹窗本体在画面中上部）。
    "level_reward_title": (600, 120, 800, 160),
    # 结算页右上角「战斗结果」，避开右下角的确认按钮（跨路线共用，不可独占）。
    "result_title": (1400, 50, 400, 110),
    # 行动力不足弹窗（与 story 共用同一套模板，复用它的搜索区域）。
    "stamina_popup": (400, 200, 1200, 700),
}

THRESHOLDS = {key: DEFAULT_THRESHOLD for key in REGIONS}

_TEMPLATE_PATHS = {
    key: f"{key}.png" for key in REGIONS
}
# 体力弹窗的模板复用 story 那一份（实测 0.9989 命中，同一个控件），
# 与 expedition 复用 story 的 ``auto_off`` 是同一种做法。
_TEMPLATE_PATHS["stamina_popup"] = "../story/stamina_popup.png"

_PAGES = (
    # 骑士团主页：标题栏 + 世界首领战入口图标都在。
    # 只用 ``knights_title`` 即可 —— 世界首领战主页用的是同一个标题栏位置，
    # 但那一页的 ``knights_title`` 实测只有 0.4888，进不了门槛。
    PageEvidence("world_boss.knights_home", required=("knights_title",)),
    PageEvidence("world_boss.home", required=("select_team_button",)),
    PageEvidence("world_boss.team_select", required=("team_select_title",)),
    PageEvidence(
        "world_boss.team_config",
        required=("team_config_auto",),
        # 体力弹窗盖在本页上时 ``team_config_auto`` 仍有 0.9995，必须靠弹窗锚点排除，
        # 否则配置队伍页会在弹窗期间被判成「已回到配置页」，状态机就会在弹窗上点
        # 「战斗开始」——那正好是弹窗后面的按钮，等于越过购买白点一次。
        forbidden=("stamina_popup",),
    ),
    PageEvidence(
        "world_boss.result",
        required=("result_title",),
        # 奖励弹窗是压暗的结算页，``result_title`` 在那上面还有 0.7103；
        # 靠奖励弹窗自己的标题排他（见模块 docstring 第 2 条）。
        forbidden=("level_reward_title",),
    ),
    PageEvidence("world_boss.level_reward", required=("level_reward_title",)),
)


def build_world_boss_evidence(template_dir: Path) -> EvidenceProfile:
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=relative_path,
            region=REGIONS[key],
            threshold=THRESHOLDS[key],
            reference_size=REFERENCE_SIZE,
        )
        for key, relative_path in _TEMPLATE_PATHS.items()
    }
    return EvidenceProfile(
        atoms=atoms,
        pages=_PAGES,
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
