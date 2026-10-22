import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import numpy as np

from auto_game_unified.games.epic7.arena import (
    ARENA_ENTRY_PAGE,
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
    detect_resume_point,
)
from auto_game_unified.games.epic7.story import (
    STORY_ENTRY_PAGE,
    StoryRunner,
    StoryState,
    StoryStateMachine,
    build_story_templates,
    detect_resume_point as detect_story_resume_point,
)
from auto_game_unified.games.epic7.expedition import (
    EXPEDITION_BATTLE_MENU_PAGE,
    EXPEDITION_ENTRY_PAGE,
    EXPEDITION_RESUME_PAGES,
    EXPEDITION_SEASON_PAGE,
    ExpeditionRunner,
    ExpeditionState,
    ExpeditionStateMachine,
    detect_resume_point as detect_expedition_resume_point,
)
from auto_game_unified.games.epic7.fodder import (
    FodderRunner,
    FodderState,
    FodderStateMachine,
    build_fodder_templates,
)
from auto_game_unified.games.epic7.side_story import (
    SideStoryRunner,
    SideStoryStateMachine,
    build_side_story_machine,
)
# 以「模块对象」形式再导一次：``_preflight_community`` 要在调用时读
# ``LIVE_RUN_READY``（理由见该函数，与刷书签那条同源）。
from auto_game_unified.games.epic7 import community as _community
from auto_game_unified.games.epic7.community import (
    CommunityRunner,
    CommunityState,
    build_community_machine,
)
from auto_game_unified.games.epic7.hero_synthesis import (
    HeroSynthRunner,
    HeroSynthState,
    HeroSynthStateMachine,
    build_hero_templates,
)
# 以「模块对象」形式再导一次：``_preflight_shop_refresh`` 要在调用时读
# ``LIVE_TRANSACTIONS_VERIFIED``（理由见该函数），不能只在 import 期绑一份名字。
from auto_game_unified.games.epic7.evidence import shop_refresh as _shop_refresh_evidence
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    build_shop_refresh_observer,
)
from auto_game_unified.games.epic7.evidence.survivor import build_survivor_observer
from auto_game_unified.games.epic7.shop_refresh import (
    ShopPhase,
    ShopRefreshRunner,
    ShopRefreshStateMachine,
    detect_resume_point as detect_shop_resume_point,
)
from auto_game_unified.games.epic7.survivor import (
    SurvivorRunner,
    SurvivorState,
    SurvivorStateMachine,
)
from auto_game_unified.games.epic7.tower import (
    TOWER_BATTLE_MENU_PAGE,
    TOWER_ENTRY_PAGE,
    TOWER_RESUME_PAGES,
    TOWER_SEASON_PAGE,
    TowerRunner,
    TowerState,
    TowerStateMachine,
    detect_resume_point as detect_tower_resume_point,
)
from auto_game_unified.games.epic7.navigation_plan import (
    QUICK_MENU_PAGE,
    NavigationPlan,
    NavigationStep,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.knights_donation import (
    KNIGHTS_GUILD_HOME_PAGE,
    KnightsDonationRunner,
    KnightsDonationState,
    KnightsDonationStateMachine,
    detect_resume_point as detect_knights_donation_resume_point,
)
from auto_game_unified.games.epic7.labyrinth_stone import (
    LabyrinthStoneRunner,
    LabyrinthStoneState,
    LabyrinthStoneStateMachine,
    detect_resume_point as detect_labyrinth_stone_resume_point,
)
from auto_game_unified.games.epic7.sanctuary import (
    SANCTUARY_HOME_PAGE,
    SanctuaryRunner,
    SanctuaryState,
    SanctuaryStateMachine,
    detect_resume_point as detect_sanctuary_resume_point,
)
from auto_game_unified.games.epic7.moonlight_theater import (
    MoonlightRunner,
    MoonlightState,
    MoonlightStateMachine,
)
from auto_game_unified.games.epic7.world_boss import (
    WORLD_BOSS_ENTRY_PAGE,
    WorldBossRunner,
    WorldBossState,
    WorldBossStateMachine,
    detect_resume_point as detect_world_boss_resume_point,
)


MachineFactory = Callable[[Path, str], Any]


@dataclass(frozen=True)
class ResumePoint:
    """开局接力的落点：认出停在哪儿之后，调用方据此决定「怎么接着往下跑」。"""

    page: str                       # 中文页面名，给日志和诊断看
    state: Optional[str] = None     # 要拨过去的状态机状态值；None = 不动状态机
    entry: Optional[str] = None     # 已经在导航链的这个页面上，从这里接着导航
                                    # （None = 已在业务入口，不需要导航）


# 「接力探针」：给 (状态机, 一帧画面, 导航器)，认出用户停在本路线的哪一步就返回落点，
# 认不出来返回 None。命中即接管，调用方跳过「回大厅 → 按路线导航」。
# 传导航器是因为有些页面（比如竞技场模式选择页）只有导航器认得出来。
ResumeProbe = Callable[[Any, np.ndarray, Any], Optional[ResumePoint]]

# 「运行前校验」：给 (本路线名, 是否干跑)，返回拒绝文案就拒绝运行（None = 放行）。
# 有些路线在「证据还没在**当前客户端**上实证过」之前不该实跑（比如刷书签会真花钱）。
# 这条闸门以前写成 ``main.run_mode`` 里的 ``if spec.name == "shop_refresh"``，
# 结果是每加一条这样的路线就要往 ``main.py`` 里再插一个 ``if`` —— 直接违背
# ``docs/EXTENDING.md`` 的「不要在 main.py 添加新的条件分支」。
Preflight = Callable[[str, bool], Optional[str]]

# 「路线级额外构造参数」：给 (仓库根, 是否干跑, 界面传下来的该路线参数)，
# 返回要转发给 Runner 构造函数的关键字参数。像落盘位置这种「只有实跑才需要」的参数
# 走这里，``main`` 不再认具名路线。
#
# ⚠️ 第三个入参是**通道**，不是义务：现在没有任何路线读它（竞技场也不用）。
# 留着是为了将来第一条要参数的路线（深渊从第几层开始、竞技场打不打 NPC）只改自己
# 那一处，不用回头动 ``RunRequest`` / 命令行 / ``main``。
# 竞品对应：``功能参数初始化`` 先把 ``ui`` 表整理好，再交给各路线读 —— 时序照搬，
# 参数名与取值规则由各路线自己定。
RunnerOptions = Callable[[Path, bool, Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ModeSpec:
    """一条路线的全部「事实」。同名信息（中文名、默认次数）**只在这里定义一次**。

    ⚠️ 中文名 ``label`` 与次数（``default_cycles`` / ``cycles_editable`` /
    ``min_cycles``）以前各自抄在 CLI / 交互菜单 / 桌面助手 / 每日任务好几处，
    改一处漏一处不会报错
    （实测出现过 ``survivor`` 在界面叫「活动」、在通知里叫「幸存者」；
    ``shop_refresh`` 在每日任务里叫「商店刷新」、别处叫「刷书签」）。
    2026-09-27 收敛到这里，其余入口一律从这里派生 —— 别再往别处抄一份。
    """

    name: str
    label: str
    default_state: str
    states: frozenset[str]
    build_machine: MachineFactory
    runner_type: type
    # 默认跑几次。``cycles_editable=False`` 表示这条路线的次数**由游戏规则决定、
    # 不给用户选**（每天上限固定，或跑一遍就结束）⇒ 各入口直接采用本值、不问用户。
    default_cycles: int = 1
    cycles_editable: bool = True
    # 允许填的最小次数。默认 1（次数必须是正整数）；只有「0 次本身就是一种有意义的
    # 业务模式」的路线才设成 0 —— 目前**只有** ``shop_refresh``：0 次 = 照常进商店、
    # 从上到下扫一遍、把想要的买掉，但**一次都不付费刷新**（秘密商店自己会随时间自动刷新）。
    # 各入口的「次数必须为正」校验一律以本字段为准
    # （``desktop/app.py`` / ``desktop/worker.py`` / ``main.py`` / ``shop_refresh.py``）。
    min_cycles: int = 1
    needs_navigation: bool = True
    resume_probe: Optional[ResumeProbe] = None
    # 这条路线「从大厅走到自己入口」的那段路（声明式数据，见 ``navigation_plan`` 模块）。
    # ⚠️ ``needs_navigation=False`` 的路线**必须**留空；有导航却漏声明会在加载期报错
    # （``_assert_navigation_declared``）。``navigation.Epic7Navigator.navigate()``
    # 只认这一份数据，**不再认识任何具名路线**。
    navigation_plan: Optional[NavigationPlan] = None
    # 路线级的运行前闸门与额外构造参数，见上面两个类型别名的说明。
    # ⚠️ 这两个钩子就是「新路线需要专属校验 / 专属参数」时的唯一入口 ——
    # 不要再回去 ``main.py`` 里加 ``if spec.name == ...``。
    preflight: Optional[Preflight] = None
    runner_options: Optional[RunnerOptions] = None

    def resolve_state(self, requested: str | None) -> str:
        state = requested or self.default_state
        if state not in self.states:
            choices = ", ".join(sorted(self.states))
            raise ValueError(f"起始状态 {state!r} 不适用于模式 {self.name}；可选：{choices}")
        return state

def _build_arena(template_root: Path, state: str) -> ArenaStateMachine:
    return ArenaStateMachine(
        build_templates(template_root),
        initial_state=ArenaState(state),
    )


def _build_story(template_root: Path, state: str) -> StoryStateMachine:
    return StoryStateMachine(
        build_story_templates(template_root / "story"),
        initial_state=StoryState(state),
    )


def _build_expedition(template_root: Path, state: str) -> ExpeditionStateMachine:
    return ExpeditionStateMachine(
        template_root / "expedition",
        initial_state=ExpeditionState(state),
    )


def _build_tower(template_root: Path, state: str) -> TowerStateMachine:
    return TowerStateMachine(
        template_root / "tower",
        initial_state=TowerState(state),
    )


def _build_fodder(template_root: Path, state: str) -> FodderStateMachine:
    return FodderStateMachine(
        build_fodder_templates(template_root / "fodder"),
        initial_state=FodderState(state),
    )


def _build_side_story(template_root: Path, state: str) -> SideStoryStateMachine:
    # 模板子目录是 templates/side_story，里面只放本路线独有的五张图；
    # 主线那一整套（队伍/战斗/剧情/结算）由 build_side_story_machine 从兄弟目录
    # templates/story 复用，不重新加载一遍。
    return build_side_story_machine(template_root / "side_story", state)


def _build_hero_synthesis(template_root: Path, state: str) -> HeroSynthStateMachine:
    return HeroSynthStateMachine(
        build_hero_templates(template_root),
        initial_state=HeroSynthState(state),
    )


def _build_shop_refresh(template_root: Path, state: str) -> ShopRefreshStateMachine:
    if state != ShopPhase.SCAN_TOP.value:
        raise ValueError(f"刷书签起始阶段无效：{state}")
    return ShopRefreshStateMachine(
        1,
        observer=build_shop_refresh_observer(template_root),
    )


def _resume_probe(
    detect: Callable[..., Any],
    *,
    use_navigator: bool = False,
    on_hit: Optional[Callable[[Any], None]] = None,
) -> ResumeProbe:
    """接力探针工厂：把「认出落点 → 拨状态机 → 交回落点」这套固定流程写死一次。

    ⚠️ 它存在的理由是**一个真发生过的错**：手抄这段流程时最容易漏掉
    ``machine.resume_from(found.state)`` —— 漏了之后接力**看起来**是命中的
    （日志照打「开局=接力」），但状态机没拨过去，Runner 会原地干等到超时，而不是自愈。
    这个错当年**没有任何测试能发现**（见 ``docs/maintenance/route_extensibility_review.md``
    第四节）。⇒ 把那句话做成**代码**，新路线就不可能再漏。

    参数：

    - ``detect``：这条路线自己的 ``detect_resume_point``。
    - ``use_navigator``：判据要用导航器认出的页面名。**只有三条路线的判据接受
      ``observed_page=`` 参数**（arena / story / expedition —— 它们的接力点里有
      「导航链中间站」），所以这个开关同时决定「要不要问导航器」和「怎么调用判据」。
    - ``on_hit``：命中后的路线专属动作（目前只有刷书签用：打一个
      ``mark_resumed_at_shop()`` 记号，让 Runner 先把列表拨回顶部再开扫）。

    落点状态一律**归一成字符串**再放进 ``ResumePoint.state``（判据那边给的可能是 Enum）；
    ``state is None`` 表示「这个落点不需要拨状态」（如刷书签/骑士团捐赠/迷宫的落点）。
    """
    def probe(
        machine: Any,
        screen: np.ndarray,
        navigator: Any,
    ) -> Optional[ResumePoint]:
        if use_navigator:
            observed = (
                navigator.observe(screen).name if navigator is not None else None
            )
            found = detect(machine, screen, observed_page=observed)
        else:
            found = detect(machine, screen)
        if found is None:
            return None
        state = found.state
        if state is not None:
            # 命中即接管：必须把状态一起拨好，否则 Runner 会原地干等到超时。
            machine.resume_from(state)
        if on_hit is not None:
            on_hit(machine)
        return ResumePoint(
            page=found.page,
            # Enum ⇒ ``.value``；判据直接给字符串（或恒为 None）时原样带出。
            state=getattr(state, "value", state),
            entry=found.entry,
        )

    # 记下「这个探针是用哪条判据造的」（标准内省约定 ``__wrapped__``）。
    # 各路线自己的 ``tests/test_<路线>_resume.py`` 靠它断言「注册的探针确实是这条路线
    # 的判据造的」，而不是隔壁那条路线的 —— 抄注册行最容易犯的错就是漏改这个参数。
    probe.__wrapped__ = detect
    return probe


def _build_survivor(template_root: Path, state: str) -> SurvivorStateMachine:
    # 整轮循环都在活动小游戏内部，起点固定是用户人工停好的「选第一张卡」页，
    # 所以只允许这一个起始状态。
    if state != SurvivorState.CARD.value:
        raise ValueError(f"幸存者起始状态无效：{state}")
    return SurvivorStateMachine(
        observer=build_survivor_observer(template_root),
    )


def _build_world_boss(template_root: Path, state: str) -> WorldBossStateMachine:
    return WorldBossStateMachine(
        template_root / "world_boss",
        initial_state=WorldBossState(state),
    )


def _build_labyrinth_stone(template_root: Path, state: str) -> LabyrinthStoneStateMachine:
    # 模板子目录是 templates/labyrinth_stone；工厂必须把它当根，不能当 templates 根。
    return LabyrinthStoneStateMachine(
        template_root / "labyrinth_stone",
        initial_state=LabyrinthStoneState(state),
    )


def _build_knights_donation(template_root: Path, state: str) -> KnightsDonationStateMachine:
    # 模板子目录是 templates/knights_donation；工厂必须把它当根，不能当 templates 根。
    return KnightsDonationStateMachine(
        template_root / "knights_donation",
        initial_state=KnightsDonationState(state),
    )


def _build_sanctuary(template_root: Path, state: str) -> SanctuaryStateMachine:
    # 模板子目录是 templates/sanctuary；工厂必须把它当根，不能当 templates 根。
    return SanctuaryStateMachine(
        template_root / "sanctuary",
        initial_state=SanctuaryState(state),
    )


def _build_moonlight_theater(
    template_root: Path, state: str
) -> MoonlightStateMachine:
    # 模板子目录是 templates/moonlight_theater；两张复用图由证据档案用相对路径
    # （../side_story、../sanctuary）指过去，本目录里没有副本。
    return MoonlightStateMachine(
        template_root / "moonlight_theater",
        initial_state=MoonlightState(state),
    )


# ── 路线级钩子的实现（``ModeSpec.preflight`` / ``ModeSpec.runner_options``）─────────
# ⚠️ 这两个函数原先就活在 ``main.run_mode`` 里，只是当时写成了 ``if spec.name == ...``。
# 现在只是把它们搬回各自的路线旁边，**行为逐字不变**（包括报错文案与「在创建 runtime
# 之前就拦下」这个顺序 —— 有测试钉着 ``_build_runtime`` 不许被调用）。


def _preflight_shop_refresh(mode: str, dry_run: bool) -> Optional[str]:
    """刷书签的实跑闸门：目标商品与购买价格没在当前客户端实证过就不许实跑。"""
    # ⚠️ 标志位必须**在调用时**从 ``evidence.shop_refresh`` 的模块属性上读，不能
    # ``from ... import LIVE_TRANSACTIONS_VERIFIED`` 在 import 期绑一份到本模块 ——
    # 绑了之后测试改成 ``patch.object(evidence.shop_refresh, ...)`` 就拦不住它，
    # 这条闸门会悄悄退化成空转。
    if dry_run or _shop_refresh_evidence.LIVE_TRANSACTIONS_VERIFIED:
        return None
    return "刷书签目标商品和购买价格尚未通过当前客户端实证，当前只允许空跑采样"


def _preflight_community(mode: str, dry_run: bool) -> Optional[str]:
    """社区签到的实跑闸门：竖屏段要用的真机数据没采齐就不许实跑。

    这道闸门是 2026-10-06 立的，当时的理由是「三条每日任务的执行段**根本写不出来**」
    —— 信息流里「点开第几条帖子 / 点赞按钮在哪 / 滚多远」一个坐标都没量过，
    「签到未完成」那一态也没有样本；如实跑只会得到一次**必然失败**的运行，
    而失败原因看起来像程序坏了（与 PC 后端被收起来同一个理由）。

    **2026-10-07 真机采齐**（签到两态、签到入口与弹窗、三条任务的执行脚本、
    「去完成」落点、帖子详情与分享面板），``LIVE_RUN_READY`` 翻成 ``True``，
    闸门放行 —— 闸门本身留着，客户端改版或者哪天要重新验证时把它翻回 ``False`` 即可。

    ⚠️ 标志位必须**在调用时**从 ``community`` 的模块属性上读，不能
    ``from ... import LIVE_RUN_READY`` 在 import 期绑一份到本模块 —— 绑了之后测试改成
    ``patch.object(community, "LIVE_RUN_READY", True)`` 就拦不住它，闸门会悄悄退化成空转。
    """
    if dry_run or _community.LIVE_RUN_READY:
        return None
    return (
        "社区签到还没通过当前客户端的实测：竖屏段还缺 "
        f"{_community.MISSING_LIVE_DATA}；当前只允许空跑采样"
    )


def _arena_runner_options(
    root: Path, dry_run: bool, params: Mapping[str, Any]
) -> dict[str, Any]:
    """竞技场实跑才需要的两个落盘位置（干跑一个盘都不写）。

    ``params`` 现在没有消费者 —— 竞技场还没有任何可调参数。签名先接上，
    等它真要加（打不打 NPC / 输几场换人）时只改这个函数，不用动上层。
    """
    del params  # 显式声明「暂时不用」，免得下一个人以为漏读了
    if dry_run:
        return {}
    return {
        # 买票「今天买过没有」的记账文件。
        "purchase_stamp_path": root / "runtime_logs" / "arena_ticket_purchase.txt",
        # 每局结算画面留一张盘，给「胜负判得对不对」留可回看的证据（见 ArenaRunner）。
        "outcome_frame_dir": root / "docs" / "manual_review" / "arena",
    }


# 「接力」豁免名单：**必须写明理由**，才允许一条有导航的路线不挂 ``resume_probe``。
#
# 与转场契约的 ``_REQUIRE_TRANSITION_CONTRACT`` 是两件事：那个管「跑起来之后每个动作
# 有没有出口验收」，这个管「开局时人停在半路能不能接上」。一个是逐动作、一个是
# 开局一次性，所以卡法不同 —— 见 ``docs/TRANSITION_CONTRACTS.md``「接力契约」。
#
# 名单在模块加载时自查（见文件末尾 ``_assert_resume_declared``）：新路线漏了接力，
# **import 阶段就报错**，不会等到有人停在半路才发现自己白走一趟大厅。
#
# ``needs_navigation=False`` 的路线自动豁免，不用进这张表 —— 它的起点本来就是人工把
# 游戏推进到活动内部再启动，连「回大厅」这条路径都没有，谈不上接力。
RESUME_EXEMPT = {
    "fodder": (
        "锚点其实齐全，但有一个**做接力之前必须先解决**的坑：`fodder/replay.png`"
        "（「重新进行」那一页）会被 `battle_scene_visible` 误判成局内。照搬别人"
        "「先判局内」的顺序，停在结算页启动会被当成已承诺战斗去监督，而不是点"
        "「重新进行」—— 白打一局。先解决它再谈接力。"
    ),
    "hero_synthesis": (
        "缺的不是「顺序跑得动」的锚点，而是**排他**锚点：`auto_select_label` 在"
        "「传送选择 / 传送确认 / 传送奖励」三页上同时可见（实测都是 1.000）。"
        "运行期靠状态上下文分得开，**接力只有一帧、没有这个上下文** —— 把它误认成"
        "「传送选择」会重复点一次不可逆的传送确认。PC 端的英雄列表连锚点都没有。"
    ),
    "community": (
        "接力的**判据**其实够用（活动页三态与网页活动列表都有专有锚点），缺的是"
        "**更前一步**：这条路线有一半时间在竖屏，而人停在社区里时，开局那一步"
        "`home_return()` 是拿**横屏**通道去取图的（`Epic7Window.capture`），"
        "竖屏下它会直接抛「LDPlayer render size changed」—— 起步就失败，"
        "连探针都轮不到跑。"
        "⇒ 要争取力，得先把「起步时若模拟器是竖屏，就先退出社区」这一步放到 "
        "`_enter_mode` **之前**；那是 `main.py` 的活，属于另一件事。"
        "在那之前挂探针等于给用户一个「看起来能接力、实际一起步就炸」的假承诺。"
    ),
    "side_story": (
        "2026-10-15 把那条前置事实测了（`runtime_logs/_probe_side_story_consumers.py`）："
        "**关卡地图页 `battle_scene_visible=False`，但打完一关的场景页是 `True`**"
        "（`scene.png` / `scene_without_arrow.png` 都是），与狗粮 `replay.png` 同因 ——"
        "那两个页面「左侧竖列 + 右上角按钮」的白色结构撞上了战斗画面的判据。"
        "这条路线继承 `StoryRunner`，它那支「接力落在局内」会**跳过状态机、直接把"
        "这一局交给战斗监督**：停在场景页启动会被当成「已承诺战斗」去监督，"
        "而监督在那一页上认作「还在战斗中」（`battle_visible=True`）⇒ 一路磨到绝对"
        "超时，不是自愈。"
        "⇒ 结论由「缺一条实测」升级为「**实测确认不能接力**」；要接必须先修 "
        "`battle_controls.battle_scene_visible` 对场景页的误判 —— 那会影响全部 14 条"
        "路线，不在本路线的改动范围里（狗粮也是用「先不接力」处理同一个坑）。"
    ),
    "moonlight_theater": (
        "用户 2026-10-17 明确「不做」。这条路线**一轮自己就能跑完**（从入口扫到最右端），"
        "半路接力的收益远小于风险：它的分集页在「刚入场」和「领完奖励」两种状态下长得"
        "一模一样，只靠一帧认不出该点「进行观览」还是「返回」，而点错「进行观览」"
        "会弹出 500,000 金币的购买门票确认（用户明确不许花金币）。"
        "⇒ 宁可不接，也不要给一个会误点花钱的接力点。"
    ),
}


# 「动作验收方式」的豁免名单：**必须写清「用自己的什么机制验收」**，才允许一条路线
# 不打开基类的转场强制开关（``ModeRunnerBase._REQUIRE_TRANSITION_CONTRACT``）。
#
# 与上面的 ``RESUME_EXEMPT`` 是**路线准入的两半**，形状刻意做成一样的（一份表 + 一句理由 +
# 加载期自查），因为它们回答的是同一类问题：「这条路线有没有对某件事表过态」。
#   - ``RESUME_EXEMPT`` 管「开局停在半路，做不做接力」；
#   - ``TRANSITION_EXEMPT`` 管「跑起来之后，动作的出口验收靠什么」。
#
# 判定规则见 ``_assert_transition_stance_declared``：**打开开关、或进本名单，二选一**。
# 漏了在 **import 阶段**就报错，不会等到实跑才发现某个动作点了不回头。
#
# ⚠️ 名单里标着「**已知欠债**」的两条是真缺判据，不是「用了别的机制」——
# 把缺口写在明处，比假装它不存在强。它们各自的补法写在理由里。
TRANSITION_EXEMPT = {
    "arena": (
        "继承**事务型主循环基类** `TransactionalRunnerBase`，但**保留自己的 `run()`**"
        "（循环策略与远征不同，见 `arena.ArenaRunner` 的类 docstring）⇒ 这个开关的"
        "读取点在 `ModeRunnerBase.run()` 里，对它无效。转场那一段走基类的 "
        "`_execute_transition`：`Action.source_state` / `target_states` 缺任一"
        "**直接 raise**，且目标页要连续两帧才算转场成功 —— 比开关更严。"
    ),
    "expedition": (
        "继承**事务型主循环基类** `TransactionalRunnerBase`（2026-09-26 从裸定义搬过去的），"
        "**不是** `ModeRunnerBase` ⇒ 这个开关的读取点在基类 `run()` 里，对它一样无效。"
        "它走 `ExpeditionAction.source_page` / `target_pages` ＋ 基类 `_execute_transition`："
        "来源/目标合同缺任一**直接 raise**，且目标页要连续两帧才算转场成功。"
    ),
    "tower": (
        "与 `expedition` 同族：继承**事务型主循环基类** `TransactionalRunnerBase`，"
        "**不是** `ModeRunnerBase` ⇒ 这个开关的读取点在基类 `run()` 里，对它无效。"
        "它走 `TowerAction.source_page` / `target_pages` ＋ 基类 `_execute_transition`："
        "来源/目标合同缺任一**直接 raise**，且目标页要连续两帧才算转场成功。"
    ),
    "shop_refresh": (
        "自带独立主循环，验收靠自己的 `_wait_stable` / `_open_with_retry`："
        "每次购买或刷新都「点完等到目标页稳定」才放行，不经过基类的转场账本。"
    ),
    "survivor": (
        "自带独立主循环，用 `_observe_stable(page, timeout)` 验收。"
        "⚠️ **已知欠债**：出口验收确实缺 —— 点完不回头看，没生效只能靠"
        "`_BATTLE_TIMEOUT_SECONDS=1800` 兜（那是安全网，不是判据）。"
    ),
    "fodder": (
        "⚠️ **已知欠债**：走基类主循环，但 `FodderAction` 只有 `name` / `point` 两个字段，"
        "**完全没有判据** —— 漏写不会有任何报错。补法见 docs/TRANSITION_CONTRACTS.md。"
    ),
    "story": (
        "走基类主循环、未开开关，但**不需要**：`StoryAction` 全项目只有 1 个构造点"
        "（在 `_action()` 内），而它的 `source_page` / `target_pages` 是**无默认值的必填参数**"
        "⇒ 漏填直接 `TypeError`，比开关更硬。开它属于冗余。"
    ),
}


MODE_SPECS = {
    "arena": ModeSpec(
        name="arena",
        label="竞技场",
        default_state=ArenaState.LIST.value,
        states=frozenset(state.value for state in ArenaState),
        # ⚠️ 默认 **10 次**（用户 2026-10-18 拍板）：竞技场每天能免费打的场次
        # 就在 10 场上下，原来默认 1 次等于「点开只打一场就走」。
        # 次数仍然可改（下面 `cycles_editable` 默认 True）—— 只想打几场清个体力也合理。
        default_cycles=10,
        build_machine=_build_arena,
        runner_type=ArenaRunner,
        # 开局不无脑回大厅：先看一眼停在哪一步，停在对战详情/准备战斗/对手列表
        # 就直接从那一步接着跑；停在别的支线页面才退回原来的「一直返回」流程。
        # 判据要问导航器认出的页名 —— 接力点里有「竞技场模式选择页」这个导航链中间站。
        resume_probe=_resume_probe(detect_resume_point, use_navigator=True),
        # 实跑要落两个盘（买票记账 + 每局结算画面），路径只有主线装配层知道仓库根。
        runner_options=_arena_runner_options,
        navigation_plan=NavigationPlan(
            mode="arena",
            steps=(
                NavigationStep("lobby", ("arena_mode",), "lobby_arena", "进入竞技场"),
                NavigationStep(
                    # 锚点名沿用历史 `novice_arena`（改名的波及面比收益大），
                    # 它指的是这一页底部那个入口按钮 —— 2026-10-05 起该锚点同时
                    # 认「新手竞技场」和「竞技场」两种长相，见 `NavigationTemplates`。
                    "arena_mode", ("arena_ready",), "novice_arena", "进入竞技场"
                ),
            ),
            resume_entries=frozenset({ARENA_ENTRY_PAGE}),
            resume_log_mode="竞技场",
            resume_action="跳过回大厅与进入竞技场",
            resume_state_done="直接进竞技场",
        ),
    ),
    "story": ModeSpec(
        name="story",
        label="主线",
        default_state=StoryState.STAGE.value,
        states=frozenset(state.value for state in StoryState),
        build_machine=_build_story,
        runner_type=StoryRunner,
        # 开局不无脑回大厅：先看停在主线哪一步。关卡入口直接接管，队伍准备/战斗中
        # 就接着打，结算/通关提示/额外奖励就接着收奖励（这几页回大厅会白丢奖励）。
        # ⚠️ 落点必须把状态拨对：``next_action`` 有两支依赖进来时的状态才肯点
        # （``prepare_battle`` 在 WAIT_COMPLETE/WAIT_NEXT_STAGE 下只记轮次不点；
        # 战斗控件分支只在 WAIT_SKIP_CONFIRM/WAIT_BATTLE/ACTIVE 下跑），
        # 拨错会让 Runner 原地干等到超时，而不是自愈。
        resume_probe=_resume_probe(detect_story_resume_point, use_navigator=True),
        navigation_plan=NavigationPlan(
            mode="story",
            steps=(
                NavigationStep("lobby", ("story_ready",), "lobby_story", "进入主线"),
            ),
            resume_entries=frozenset({STORY_ENTRY_PAGE}),
            resume_action="跳过回大厅与进入主线",
            resume_state_done="已在关卡入口",
        ),
    ),
    "expedition": ModeSpec(
        name="expedition",
        label="远征",
        default_state=ExpeditionState.HOME.value,
        states=frozenset(state.value for state in ExpeditionState),
        build_machine=_build_expedition,
        runner_type=ExpeditionRunner,
        # 开局不无脑回大厅：导航链四级（战斗菜单/赛季菜单/远征主页）都开放接力，
        # 业务页从通缉传单一路到公开招募也都接得住。
        # ⚠️ 落点必须拨状态：``next_action`` 是纯状态驱动的，拨错**不会自愈**
        # （会走到 ``_required`` 失败或点错按钮）。
        resume_probe=_resume_probe(detect_expedition_resume_point, use_navigator=True),
        navigation_plan=NavigationPlan(
            mode="expedition",
            steps=(
                NavigationStep(
                    # ⚠️ ``battle_other_menu`` 必须在这份落点名单里（2026-10-12 补）：
                    # 判页改成「按哪个标签被选中分三页」之后，落在**第三个标签页**上
                    # 返回的就是这个名字；不写进来，这一跳会「目标页未出现」而重试到失败。
                    # 后面「切换到赛季」那一步不受影响（''skip_if_observed'' 只跳赛季页，
                    # 第三页会照常点「赛季」标签 —— 那枚锚点在第三页上是过阈的）。
                    "lobby",
                    (EXPEDITION_BATTLE_MENU_PAGE, EXPEDITION_SEASON_PAGE, "battle_other_menu"),
                    "lobby_battle",
                    "进入战斗菜单",
                ),
                NavigationStep(
                    EXPEDITION_BATTLE_MENU_PAGE,
                    (EXPEDITION_SEASON_PAGE,),
                    "expedition_season_tab",
                    "切换到赛季",
                    skip_if_observed=(EXPEDITION_SEASON_PAGE,),
                ),
                NavigationStep(
                    EXPEDITION_SEASON_PAGE,
                    (EXPEDITION_ENTRY_PAGE,),
                    "expedition_entry",
                    "进入远征队",
                ),
            ),
            resume_entries=EXPEDITION_RESUME_PAGES,
            resume_action="跳过回大厅与进入远征队",
            resume_action_middle="跳过回大厅与进入战斗菜单",
            resume_state_done="已在远征主页",
        ),
    ),
    "tower": ModeSpec(
        name="tower",
        label="月塔",
        default_state=TowerState.HOME.value,
        states=frozenset(state.value for state in TowerState),
        build_machine=_build_tower,
        runner_type=TowerRunner,
        # ⚠️ 默认 **25 层**（用户 2026-10-08 拍板）：月塔一个赛季总共约 25 层，
        # 「默认打满」就是连打 25 层。每层耗 **15 点体力**（实测逐层 -15），
        # 所以 25 层不是「次数」而是「打满整座塔」—— 体力不够时走
        # `StaminaExhausted`（退出码 2），**不补充体力、不买叶子**。
        default_cycles=25,
        # 次数可改：用户想只打几层清个体力也合理。
        cycles_editable=True,
        # 开局不无脑回大厅：导航链四级（战斗菜单/赛季菜单/月塔主页）都开放接力，
        # 业务页从楼层列表一路到结算页也都接得住。
        # ⚠️ 落点必须拨状态：``next_action`` 是纯状态驱动的，拨错**不会自愈**。
        resume_probe=_resume_probe(detect_tower_resume_point, use_navigator=True),
        navigation_plan=NavigationPlan(
            mode="tower",
            steps=(
                NavigationStep(
                    # ⚠️ ``battle_other_menu`` 必须在这份落点名单里（2026-10-12 补）：
                    # 判页改成「按哪个标签被选中分三页」之后，从大厅点进「战斗」落在
                    # **第三个标签页**上时返回的就是这个名字。不写进来，这一跳会一直
                    # 「目标页未出现」直到报「导航开始前应处于[大厅]」。
                    #
                    # 与远征链同形同理由；为什么第三页不必单独处理，见
                    # ``navigation.NavigationTemplates.battle_general_active``
                    # 与远征链那一段注释。下面「切换到赛季」这一步**不用改**：
                    # 它用的 ``expedition_season_tab`` 在第三页实测 1.0000、
                    # 一般页 0.8975，两页都过阈，点下去都进赛季页。
                    "lobby",
                    (TOWER_BATTLE_MENU_PAGE, TOWER_SEASON_PAGE, "battle_other_menu"),
                    "lobby_battle",
                    "进入战斗菜单",
                ),
                NavigationStep(
                    TOWER_BATTLE_MENU_PAGE,
                    (TOWER_SEASON_PAGE,),
                    "expedition_season_tab",
                    "切换到赛季",
                    skip_if_observed=(TOWER_SEASON_PAGE,),
                ),
                # ⚠️ 最后一步用**固定坐标**：月塔卡片没有自己那一格的专有锚点
                # （`season_tower_title` 是卡片标题，实测在卡片被点开前后都在，
                # 拿它定位会点到标题而不是卡片中心）；而卡片在赛季页上的位置
                # 实测稳定（标题 x=[992,1197] y=[331,373]，点 (1000, 420)）。
                # 为什么敢用固定坐标：**来源页身份仍由本步的 ``targets`` 验收**
                # （点空了 `tower_home` 不出现 ⇒ 按额度重试 ⇒ 失败留诊断），
                # 页面身份这一道「眼睛」没有少（与社区「前往活动页」同一个道理）。
                NavigationStep(
                    TOWER_SEASON_PAGE,
                    (TOWER_ENTRY_PAGE,),
                    "lobby_battle",
                    "进入月塔",
                    fixed_point=(1000, 420),
                ),
            ),
            resume_entries=TOWER_RESUME_PAGES,
            resume_action="跳过回大厅与进入月塔",
            resume_action_middle="跳过回大厅与进入战斗菜单",
            resume_state_done="已在月塔主页",
        ),
    ),
    "fodder": ModeSpec(
        name="fodder",

        label="狗粮",
        default_state=FodderState.STAGE.value,
        states=frozenset(state.value for state in FodderState),
        build_machine=_build_fodder,
        runner_type=FodderRunner,
        navigation_plan=NavigationPlan(
            mode="fodder",
            steps=(
                NavigationStep(
                    "lobby", ("fodder_side_story",), "lobby_side_story", "进入支线故事"
                ),
                NavigationStep(
                    "fodder_side_story",
                    ("fodder_special_book",),
                    "side_story_special_book",
                    "进入特别的时间之书",
                ),
                NavigationStep(
                    "fodder_special_book",
                    ("fodder_episode_detail",),
                    "special_book_episode",
                    "进入Episode",
                ),
                NavigationStep(
                    "fodder_episode_detail",
                    ("fodder_stage",),
                    "episode_adventure",
                    "进入冒险地图",
                ),
            ),
        ),
    ),
    "side_story": ModeSpec(
        name="side_story",
        label="支线故事",
        default_state=StoryState.STAGE.value,
        # 复用主线的状态集：本路线的状态机就是 `StoryStateMachine` 的子类，
        # 独有页面（关卡地图 / 场景页）不占新状态 —— 它们每帧靠画面现判
        # （用户 2026-10-15 的要求：地图布局每期都变，位置绝不能写死）。
        states=frozenset(state.value for state in StoryState),
        build_machine=_build_side_story,
        runner_type=SideStoryRunner,
        # 次数**不给用户选**（用户 2026-10-15 明确）：这条路线是「一次把本期所有关卡
        # 打光」，没有「打几遍」的概念。所以只给一个兜底上限；真实终点是场景页上
        # 看不到蓝色三箭头，那一步抛 `SideStoryCleared` 提前收工（退出码 2 = 干完了
        # 但没得干了，基类会顺手把游戏带回首页）。
        default_cycles=99,
        cycles_editable=False,
        navigation_plan=NavigationPlan(
            mode="side_story",
            steps=(
                # 与狗粮第一步**逐字相同**：同一个大厅入口、同一个落点页
                # （导航器对这个页面的名字就叫 `fodder_side_story`，它认的是
                # 右下那颗「特别的时间之书」，两支线共用同一页）。
                # ⚠️ 导航只做这一跳，往后的「快速入场 / 冒险 / 关卡地图 / 场景页」
                # 一律交给 `SideStoryStateMachine` 自己认 —— 那几页不在导航器的
                # 页面表里，为了导航再补一遍锚点等于同一件事写两份判据，
                # 而两份判据迟早会分叉。
                NavigationStep(
                    "lobby", ("fodder_side_story",), "lobby_side_story", "进入支线故事"
                ),
            ),
            ready_note="支线故事页已就绪",
        ),
    ),
    "moonlight_theater": ModeSpec(
        name="moonlight_theater",
        label="月光剧场",
        default_state=MoonlightState.ENTRY.value,
        states=frozenset(state.value for state in MoonlightState),
        build_machine=_build_moonlight_theater,
        runner_type=MoonlightRunner,
        # 「一次把本周免费的观览都打完」⇒ 没有「打几遍」的概念，次数不给用户选。
        # 真实终点是「右边没有海报了且当前剧场没有 Free」，那一步抛
        # ``MoonlightCleared`` 提前收工（退出码 2 = 干完了但没得干了）。
        #
        # ⚠️ 给的是**兜底上限**，不是「跑一幕」：``completed_cycles`` 记的是**幕**
        # （一个剧场一幕），写 1 就变成「打完第一个剧场就收工」，剩下的剧场白放着。
        # 与 ``side_story`` 同一个口径（它也是「一次打光」⇒ 99）。
        default_cycles=99,
        cycles_editable=False,
        # 接力：用户 2026-10-17 明确不做，理由写在 ``RESUME_EXEMPT``。
        navigation_plan=NavigationPlan(
            mode="moonlight_theater",
            steps=(
                # 与支线故事 / 狗粮第一步**逐字相同**：同一个大厅入口、同一个落点页。
                # 导航只做这一跳；往后的「月光剧场入口 → 剧场选择页 → 分集页 → 剧情页」
                # 一律交给 MoonlightStateMachine 自己认 —— 那几页不在导航器页面表里，
                # 为了导航再补一遍锚点等于同一件事写两份判据，而两份判据迟早会分叉。
                NavigationStep(
                    "lobby", ("fodder_side_story",), "lobby_side_story", "进入支线故事"
                ),
            ),
            ready_note="支线故事页已就绪",
        ),
    ),
    "hero_synthesis": ModeSpec(
        name="hero_synthesis",
        label="英雄合成",
        default_state=HeroSynthState.HERO_LIST.value,
        states=frozenset(state.value for state in HeroSynthState),
        build_machine=_build_hero_synthesis,
        runner_type=HeroSynthRunner,
        # 英雄合成跑完一遍列表就结束，没有「跑几遍」这件事 ⇒ 不给用户选。
        cycles_editable=False,
        navigation_plan=NavigationPlan(
            mode="hero_synthesis",
            steps=(
                # 2026-10-04：不再点大厅右下角那条**横排快捷栏**（「英雄」在那儿）——
                # 那条是**账号自己排的**，不同账号位置不同（用户明确要求改）。
                # 改走**右上蓝四格 → 快捷菜单 → 菜单里的「英雄」**（菜单固定布局）。
                NavigationStep(
                    "lobby", (QUICK_MENU_PAGE,), "lobby_quick_menu_button", "打开快捷菜单"
                ),
                NavigationStep(
                    QUICK_MENU_PAGE, ("hero_list",), "quick_menu_hero", "进入英雄列表"
                ),
            ),
            ready_note="英雄信息页已就绪",
        ),
    ),
    "shop_refresh": ModeSpec(
        name="shop_refresh",
        label="刷书签",
        default_state=ShopPhase.SCAN_TOP.value,
        states=frozenset({ShopPhase.SCAN_TOP.value}),
        build_machine=_build_shop_refresh,
        runner_type=ShopRefreshRunner,
        # 默认**不付费刷新**（0 次）：秘密商店自己会随时间自动刷新，每天进去扫一遍、
        # 把自动刷出来的目标商品买掉即可 —— 0 次不花天空石，所以是安全默认值。
        # ⚠️ 这也是唯一 ``min_cycles=0`` 的路线，见 ``ModeSpec.min_cycles``。
        default_cycles=0,
        min_cycles=0,
        # 开局不无脑回大厅：先看一眼是不是已经站在秘密商店页上 —— 是的话就地接管
        # （回大厅会白走一趟「大厅 → 秘密商店」导航，中间还可能被别的弹窗截住）。
        # 判据是三个锚点（商店标题 + 立即更新 + 购买按钮）同时过阈，不是「像商店」。
        # 落点**不拨状态**（phase 是内部阶段、起始恒为 SCAN_TOP），只打一个
        # ``mark_resumed_at_shop`` 记号：Runner 据此先把列表拨回顶部再开扫，
        # 免得人停在列表半截时被当成「顶部批次」。判据自带走观察器，用不到导航器。
        resume_probe=_resume_probe(
            detect_shop_resume_point,
            on_hit=lambda machine: machine.mark_resumed_at_shop(),
        ),
        # 这条路线会真花钱 ⇒ 目标商品与购买价格没在当前客户端实证过就不许实跑
        # （干跑不受影响）。闸门本体见 ``_preflight_shop_refresh``。
        preflight=_preflight_shop_refresh,
        navigation_plan=NavigationPlan(
            mode="shop_refresh",
            steps=(
                NavigationStep(
                    "lobby", ("shop_refresh",), "lobby_shop_entry", "进入秘密商店"
                ),
            ),
            ready_note="秘密商店顶部已就绪",
        ),
    ),
    "survivor": ModeSpec(
        name="survivor",
        label="活动",
        default_state=SurvivorState.CARD.value,
        states=frozenset({SurvivorState.CARD.value}),
        build_machine=_build_survivor,
        runner_type=SurvivorRunner,
        # 界面默认填 3 轮，但用户可以改（这条路线没有每日上限）。
        default_cycles=3,
        # 起点是用户人工推进到的活动小游戏内部页面，不需要从大厅导航过来，
        # 出问题时也不做任何「回大厅」动作（Back 会退回活动主页那个未知状态）。
        needs_navigation=False,
    ),
    "world_boss": ModeSpec(
        name="world_boss",
        label="世界首领战",
        default_state=WorldBossState.HOME.value,
        states=frozenset(state.value for state in WorldBossState),
        build_machine=_build_world_boss,
        runner_type=WorldBossRunner,
        # 每天固定 2 次（主页「剩余/上限」就是 2），用户明确要求「不要让我选择次数」。
        default_cycles=2,
        cycles_editable=False,
        # 开局不无脑回大厅：主页 / 选择辅助队伍 / 配置队伍 / 战斗结算 / 战斗级别奖励
        # 就地从那一步接着跑，停在局内则把这一局打完再说。骑士团主页这个导航链
        # 中间站也接（省掉「回大厅 → 进骑士团」两级）。
        # ⚠️ 落点必须拨状态 —— 不是为了让页面判得准（``next_action`` 每页都现判），
        # 而是为了让 ``WorldBossRunner`` 拿到 ``resumed_from``：停在局内时要靠它跳过
        # 状态机、把这一局直接交给战斗监督，不能按 Back 回大厅。
        resume_probe=_resume_probe(detect_world_boss_resume_point),
        navigation_plan=NavigationPlan(
            mode="world_boss",
            steps=(
                # 2026-10-04：不再点大厅右下角那条**横排快捷栏**（「骑士团」在那儿）
                # —— 那条是账号自己排的。改走**右上蓝四格 → 快捷菜单 → 菜单里的
                # 「骑士团」**（菜单固定布局，与底部那颗到的是同一个骑士团主页）。
                NavigationStep(
                    "lobby", (QUICK_MENU_PAGE,), "lobby_quick_menu_button", "打开快捷菜单"
                ),
                NavigationStep(
                    QUICK_MENU_PAGE,
                    (KNIGHTS_GUILD_HOME_PAGE,),
                    "quick_menu_knights",
                    "进入骑士团",
                ),
                NavigationStep(
                    KNIGHTS_GUILD_HOME_PAGE,
                    (WORLD_BOSS_ENTRY_PAGE,),
                    "worldboss_entry",
                    "进入世界首领战",
                ),
            ),
            resume_entries=frozenset({KNIGHTS_GUILD_HOME_PAGE, WORLD_BOSS_ENTRY_PAGE}),
            resume_action="跳过回大厅与进入骑士团",
            resume_state_done="已在世界首领战主页",
            ready_note="世界首领战主页已就绪",
        ),
    ),
    "knights_donation": ModeSpec(
        name="knights_donation",
        label="骑士团捐赠",
        # 路线从骑士团主页开始（导航把画面停在那儿），第一步就是点「骑士团活动」图标。
        default_state=KnightsDonationState.GUILD_HOME.value,
        # 终态 ``FINISHED`` 不给当起始状态：它不是一页画面，是「本轮已收工」的记号。
        states=frozenset(
            state.value
            for state in KnightsDonationState
            if state is not KnightsDonationState.FINISHED
        ),
        build_machine=_build_knights_donation,
        runner_type=KnightsDonationRunner,
        # 每天跑一遍就够：请求支援一天只能发一次、红点领完就没了 ⇒ 不给用户选。
        cycles_editable=False,
        # 开局不无脑回大厅：停在骑士团主页 / 资源支援列表 / 每周任务上就地接管。
        # 三个弹窗与活动界面兜底页不接（不可逆 / 判据不排他 / 无正例），
        # 见 knights_donation._RESUMABLE_STATES 上方的理由。
        # 落点状态恒为 None（本路线每帧重判页面，不需要拨状态）；停在大厅认不出
        # （``activity_entry`` 在骑士团主页上，大厅上不成立），照旧走「回大厅 → 进骑士团」。
        resume_probe=_resume_probe(detect_knights_donation_resume_point),
        navigation_plan=NavigationPlan(
            mode="knights_donation",
            steps=(
                # 2026-10-04：与 world_boss 同步改走「右上蓝四格 → 快捷菜单 →
                # 菜单里的骑士团」（底部那条横排是账号自定义的，不可靠）。
                NavigationStep(
                    "lobby", (QUICK_MENU_PAGE,), "lobby_quick_menu_button", "打开快捷菜单"
                ),
                NavigationStep(
                    QUICK_MENU_PAGE,
                    (KNIGHTS_GUILD_HOME_PAGE,),
                    "quick_menu_knights",
                    "进入骑士团",
                ),
            ),
            resume_entries=frozenset({KNIGHTS_GUILD_HOME_PAGE}),
            resume_log_mode="骑士团捐赠",
            resume_action="跳过回大厅与进入骑士团",
            resume_state_done="已在骑士团主页",
            ready_note="骑士团主页已就绪",
        ),
    ),
    "labyrinth_stone": ModeSpec(
        name="labyrinth_stone",
        label="迷宫强化石",
        # 导航把画面停在战斗菜单（「一般」页），第一步就是点迷宫卡片。
        default_state=LabyrinthStoneState.BATTLE_MENU.value,
        states=frozenset(
            state.value
            for state in LabyrinthStoneState
            if state is not LabyrinthStoneState.FINISHED
        ),
        build_machine=_build_labyrinth_stone,
        runner_type=LabyrinthStoneRunner,
        # 迷宫采购一天一次，跑一遍就结束 ⇒ 不给用户选。
        cycles_editable=False,
        # 开局不无脑回大厅：停在战斗菜单 / 迷宫列表 / 详情页 / 准备战斗页时接着往里走，
        # 停在迷宫里 / 暂停菜单 / 放弃确认框 / 快捷菜单时接着往外走。
        # 判据与运行期同源（状态机自己的 ``observe_page``）；停在「已经进过迷宫」的那几页
        # 时 ``detect_resume_point`` 会顺手把 ``entered`` 拨对，落点状态本身恒为 None。
        resume_probe=_resume_probe(detect_labyrinth_stone_resume_point),
        navigation_plan=NavigationPlan(
            mode="labyrinth_stone",
            steps=(
                NavigationStep(
                    # **三个落点都接**：游戏**记住**上次停在哪个标签页。
                    #   2026-10-04 落在「赛季」页（前一趟跑过远征，它要点「赛季」）；
                    #   2026-10-12 落在**第三个标签页**（那天它的文字是「事件」）。
                    # 只认 battle_menu 的那一版：落到赛季页后「没有下一步可走」，
                    # 干等 92 秒报「导航开始前应处于[大厅]」（远征那条链早就写全了）。
                    # 只补了 season_menu 的那一版：落到第三页时会被**误判成一般页**
                    # —— 旧判据问的是「『赛季』有没有被选中」，第三页同样满足
                    # => 下面的「切回一般页」被 skip_if_observed 跳过 => 迷宫路线
                    # 接手后只认一般页那四张卡片 => 判「认不出」=> 干等 60 秒超时。
                    # 三页怎么分、为什么不能拿第三个标签的文字当判据，见
                    # ``navigation.NavigationTemplates.battle_general_active``。
                    # 10-12 那张现场帧已升为夹具
                    # ``tests/fixtures/epic7_navigation/battle_menu_third_tab_20261012.png``
                    # （原图 runtime_diagnostics/epic7_labyrinth_stone/
                    # 20261012_230202_433099_timeout_battle_menu.png）。
                    "lobby",
                    ("battle_menu", "season_menu", "battle_other_menu"),
                    "lobby_battle",
                    "进入战斗菜单",
                ),
                # 迷宫入口只在「一般」页；从**赛季页或第三页**切回就这一步。
                #
                # ``source`` 写 ``season_menu`` 只是沿用，它**不参与等页**（``navigate``
                # 把上一跳返回的帧直接喂进来）—— 落到第三页时日志里的「页面=赛季菜单」
                # 指的是「这一步本来是为赛季页准备的」，别据此判断实际在哪一页。
                NavigationStep(
                    "season_menu",
                    ("battle_menu",),
                    "battle_general_tab",
                    "切回一般页",
                    skip_if_observed=("battle_menu",),
                    # 位置由 ``battle_general_tab`` 定位（**不用固定坐标**，2026-10-13）：
                    # 这一步可能在赛季页或第三页上被调起来，「一般」标签在这两页上的
                    # 底纹不同，所以那枚锚点配了**两张候选图**，各管一个来源页
                    # （第三页上原来那张只有 0.8185，差 0.0015 过不了 0.82 的阈 ——
                    # 改进经过见 ``navigation.NavigationTemplates.battle_general_tab``）。
                    # 两张候选命中的中心恒在 (225±5, 222±3)，都落在「一般」标签那一格里。
                ),
            ),
            ready_note="战斗菜单「一般」页已就绪",
        ),
    ),
    "sanctuary": ModeSpec(
        name="sanctuary",
        label="圣域收菜",
        # 导航把画面停在圣域主页（大厅左侧最上面那个入口进去），第一步就是点「精灵之森」。
        default_state=SanctuaryState.HOME.value,
        # 终态 ``FINISHED`` 不给当起始状态：它不是一页画面，是「本轮已收工」的记号。
        states=frozenset(
            state.value
            for state in SanctuaryState
            if state is not SanctuaryState.FINISHED
        ),
        build_machine=_build_sanctuary,
        runner_type=SanctuaryRunner,
        # 每天跑一遍就够：圣域材料按天刷新，收完就没有可领的了 ⇒ 不给用户选。
        cycles_editable=False,
        # 开局不无脑回大厅：停在圣域主页时就地接管（并且把落点 ``entry`` 交给导航，
        # 省掉「回大厅 → 再进圣域」那一趟）；停在精灵之森页也接得住。
        # 领取完成弹窗刻意不接（它的动作只有一个「点关闭」，而回大厅路上的 ESC
        # 本来就会把它关掉）；停在大厅认不出（``forest_row`` 在大厅上不成立），
        # 照旧走「回大厅 → 进圣域」。
        # 落点状态恒为 None（本路线每帧重判页面，不需要拨状态）。
        resume_probe=_resume_probe(detect_sanctuary_resume_point),
        navigation_plan=NavigationPlan(
            mode="sanctuary",
            steps=(
                NavigationStep(
                    "lobby", (SANCTUARY_HOME_PAGE,), "lobby_sanctuary", "进入圣域"
                ),
            ),
            resume_entries=frozenset({SANCTUARY_HOME_PAGE}),
            resume_log_mode="圣域收菜",
            resume_action="跳过回大厅与进入圣域",
            resume_state_done="已在圣域主页",
            ready_note="圣域主页已就绪",
        ),
    ),
    "community": ModeSpec(
        name="community",
        label="社区签到",
        # 导航把画面停在**横屏的**网页活动列表；第一步就是点「游戏社区」——
        # 点完模拟器整块转成竖屏，之后由 `core/portrait.py` 那条 adb 链路接管。
        # 所以「起始状态」有一半是横屏的（WEB_ENTRY 就是那一半）。
        default_state=CommunityState.WEB_ENTRY.value,
        # 终态 `DONE` 不给当起始状态：它不是一页画面，是「本轮已收工」的记号。
        states=frozenset(
            state.value
            for state in CommunityState
            if state is not CommunityState.DONE
        ),
        build_machine=build_community_machine,
        runner_type=CommunityRunner,
        # 每天跑一遍就够：三条任务与兑换清单都是按天刷新的 ⇒ 不给用户选次数。
        cycles_editable=False,
        # ⚠️ 竖屏段要用的真机数据还没采齐 ⇒ **拦住实跑**（干跑照常）。
        # 理由与「PC 后端被收起来」同源：缺数据时状态机一定会抛「缺数据」，
        # 让用户一键选中一次**必然失败**的运行，失败原因还像程序坏了。
        preflight=_preflight_community,
            navigation_plan=NavigationPlan(
                mode="community",
                steps=(
                    # ⚠️⚠️ 第一步的目标是**两个态**，不是只有未选中态（2026-10-07 修）。
                    #
                    # 游戏**记得**上次在活动页上选没选「更多精彩活动」⇒ 点进来的
                    # 画面**可能就是选中态**（那一行已经变橙）。旧写法只写
                    # ``("activity_menu",)`` ⇒ 进页面若已是选中态，``_wait_for_page``
                    # 会一直等一个**永远不会出现**的 `activity_menu` 直到超时
                    # （用户原话：「如果我一点到活动就在那个更多精彩里面，它就识别不到了」）。
                    #
                    # 为什么这一步**不写** ``skip_if_observed``：那玩意只在**手上已有
                    # 一帧**时检查（见 ``navigate`` 的循环），而这一步点之前手上是
                    # **大厅**帧 —— 「进活动页之后会看到什么」正是这一步的**出口**。
                    # 所以正确做法是**把两个态都声明成出口**，让 `_transition` 自己
                    # 认出哪一个就是走通；后面两步再各带自己的 ``skip_if_observed``。
                    NavigationStep(
                        "lobby",
                        ("activity_menu", "activity_web_promo"),
                        "lobby_activity",
                        "进入活动",
                    ),
                    # 后面两步都带 `skip_if_observed`：进页面时可能已经是选中态
                    # （`activity_web_promo`）甚至已经在网页活动列表上，
                    # 那时这一步的锚点不在画面上了。
                    NavigationStep(
                        "activity_menu",
                        ("activity_web_promo",),
                        "activity_more",
                        "选中「更多精彩活动」",
                        skip_if_observed=("activity_web_promo", "web_activity_list"),
                        # ⚠️ 兜底：**游戏记得上次点了哪个活动** ⇒ 再进来还停在那一个。
                        # 上次点的活动排在「更多精彩活动」下面时，那一行就被挤出视野
                        # ⇒ 找不到锚点 ⇒ 第一步都走不过去（用户 2026-10-08）。
                        # 锚点找不着时先滚一屏再找，最多 3 次。
                        scroll_before_retry="activity_column",
                    ),
                    NavigationStep(
                        "activity_web_promo",
                        ("web_activity_list",),
                        "web_activity_gate",
                        "打开网页活动列表",
                        skip_if_observed=("web_activity_list",),
                        # ⚠️ 2026-10-18：**这一行原来的 ``scroll_before_retry`` 删掉了**。
                        # 它当年是为了「选中态那一行被挤出视野 ⇒ 点了也白点」而加的，
                        # 但现在这一步**不找那一行了**（用固定坐标点右侧的按钮），
                        # 而且上一步的扫描已经保证了「那一行看得见、选中态已成立」——
                        # 一个用不到、又会让「上下扫」在右侧白跑一趟的声明，不如没有。
                        # ⚠️⚠️ **固定坐标点击**，不再用模板定位这颗按钮。
                        #
                        # 为什么：按钮上有一颗**来回滑动的光球**。2026-10-06 光球
                        # 罩住「活动」二字时模板 1.0000，2026-10-07 滑到右边罩住
                        # 「动页」⇒ 同一位置掉到 0.7282，过不了 0.82 ⇒ 抛
                        # 「缺少导航锚点」⇒ **连点都没点**，整条路线进不去
                        # （13:37 / 14:55 两次实跑就是这么失败的）。
                        # 「模板里不放会动的元素」只保住了**判页**（选中态已改用
                        # ``activity_more_selected`` 白字，跨两天 0.89~1.00），
                        # 但**点击目标**同样不能押在会动的按钮上。
                        #
                        # 为什么敢用固定坐标 (1722, 985)：按钮位置固定（两次实跑
                        # 模板命中的中心都是它）；而**页面身份这道眼睛没有少** ——
                        # 本步的 source 仍由 ``activity_more_selected`` 验收，
                        # 点空了 ``web_activity_list`` 不出现 ⇒ 按额度重试 ⇒
                        # 失败留诊断，而不是无声跳过。
                        fixed_point=(1722, 985),
                    ),
                ),
                ready_note=(
                    "网页活动列表已就绪（点「游戏社区」进竖屏，之后横屏通道认不出这页）"
                ),
            ),
    ),
}

# 中文名的**唯一来源**。``main`` / ``navigation`` 直接用它；桌面助手的
# 菜单与面板也从这里取（见 ``desktop/catalog.py``）。⚠️ 别在别处再抄一份名字表 —— 抄了就会漂移，
# 因为没有任何机制会告诉你「另一处的名字没跟着改」。
MODE_LABELS = {name: spec.label for name, spec in MODE_SPECS.items()}


def get_mode(name: str) -> ModeSpec:
    return MODE_SPECS[name]


def _assert_resume_declared() -> None:
    """加载期自查：每条有导航的路线都必须对「接力」表态。

    两种合法表态，二选一，**不能两边都写、也不能两边都不写**：

    - 挂 ``resume_probe``（能接力）；
    - 进 ``RESUME_EXEMPT`` 并写明理由（不做接力）。

    只查结构，不跑判据 —— 判据准不准要靠拿真夹具跑一遍（
    ``tests/test_resume_contracts.py``），代码里看不出来。
    """
    for name, spec in MODE_SPECS.items():
        if not spec.needs_navigation:
            continue
        has_probe = spec.resume_probe is not None
        exempt = name in RESUME_EXEMPT
        if has_probe and exempt:
            raise RuntimeError(
                f"路线 {name} 既挂了接力探针、又躺在 RESUME_EXEMPT 里；"
                "两边只能写一边（挂了探针就把豁免那条划掉）。"
            )
        if not has_probe and not exempt:
            raise RuntimeError(
                f"路线 {name} 既没有 resume_probe，也不在 RESUME_EXEMPT 里。"
                "要么挂接力探针，要么在 RESUME_EXEMPT 里写明为什么不做接力；"
                "规矩见 docs/TRANSITION_CONTRACTS.md「接力契约」。"
            )


# 「结论门槛」的登记表：**必须写明这条路线靠什么保证「不一帧下结论」**。
#
# ⚠️ 背景（2026-09-25 实跑）：动作要连续两帧一致才敢点，这条规矩早就有了；但
# **收工 / 认不出画面这类终止性结论**是从 ``preview()`` 里直接抛到主循环的，
# 压根没过那道门槛 ⇒ 一帧就能宣布「今天打完了」、一帧没认出画面就去点屏幕中间。
# 动作要两帧、结论只要一帧，等于门只掩了一半。
#
# 判定规则（``_assert_conclusion_gate_declared``）：继承 ``ModeRunnerBase``、且没重写
# ``_stable_next_action`` 的路线自动达标（基类里已经接了 ``ConclusionGate``）；
# 其余（自带独立主循环的，以及 2026-09-26 起的 ``TransactionalRunnerBase`` 那一族）
# 必须在这张表里写明自己靠什么达标。
CONCLUSION_GATE_DECLARATION = {
    "arena": (
        "继承**事务型主循环基类** ``TransactionalRunnerBase``，但**保留自己的 "
        "``run()``**（循环策略与远征不同，见 ``arena.ArenaRunner`` 的类 docstring）。"
        "``ConclusionGate`` 接在它自己的 ``run()`` 里：``preview`` 抛出的终止性结论"
        "先过门槛、两帧一致才允许按结论处理。覆盖见 "
        "``tests/test_conclusion_gate.py::ArenaLoopConclusionTests``。"
    ),
    "expedition": (
        "继承**事务型主循环基类** ``TransactionalRunnerBase``（不是 ``ModeRunnerBase``）。"
        "``ConclusionGate`` 接在基类 ``run()`` 里：``preview`` 抛出的终止性结论先过门槛、"
        "两帧一致才允许按结论处理。覆盖见 "
        "``tests/test_conclusion_gate.py::ExpeditionLoopConclusionTests``。"
    ),
    "tower": (
        "与 ``expedition`` 同族：继承**事务型主循环基类** ``TransactionalRunnerBase``"
        "（不是 ``ModeRunnerBase``）。``ConclusionGate`` 接在基类 ``run()`` 里："
        "``preview`` 抛出的终止性结论先过门槛、两帧一致才允许按结论处理。"
        "⚠️ 月塔的终止性结论目前只有一条 —— 打满 25 层（``FloorsConquered``）；"
        "「体力不足」是**资源耗尽**通道（``StaminaExhausted``，退出码 2），"
        "不经过这道门槛。"
    ),
    "shop_refresh": (
        "不是「每帧下一结论」的形态：全程靠 ``_wait_stable`` / ``_observe_stable`` "
        "先等画面稳定再判定，认不出也只有**超时之后**才失败，不存在单帧收工。"
    ),
    "survivor": (
        "同上：靠 ``_observe_stable(page, timeout)`` 验收，``_failure`` 全部发生在"
        "「页面已稳定确认」或「超时」之后，不存在单帧收工。"
    ),
}


def _base_conclusion_gate_protected(runner_type: type) -> bool:
    """这条路线的 Runner 是否真的走得到基类那道结论门槛。

    重写 ``_stable_next_action`` **不等于绕过门槛** —— ``HeroSynthRunner`` 就重写了它
    （为了导航后先等画面稳一稳），但内部调了 ``super()``，门槛照样生效。所以判据是：
    没重写 = 达标；重写了 = 必须把基类的实现调回去（``super()._stable_next_action``）。
    """

    if not issubclass(runner_type, ModeRunnerBase):
        return False
    overridden = "_stable_next_action" in runner_type.__dict__
    if not overridden:
        return True
    return "super()._stable_next_action" in inspect.getsource(
        runner_type._stable_next_action
    )


def _assert_conclusion_gate_declared() -> None:
    """加载期自查：每条路线都必须对「不一帧下结论」表态。

    两种合法表态，二选一，**不能两边都写、也不能两边都不写**：

    - 走 ``ModeRunnerBase`` 主循环、且门槛没被自己绕过去（见
      ``_base_conclusion_gate_protected``）；
    - 进 ``CONCLUSION_GATE_DECLARATION`` 并写明「自己靠什么保证」。

    与 ``_assert_transition_stance_declared`` 是同一类护栏的两半：那个管「点了
    之后有没有回头看」，这个管「下结论之前有没有看够两帧」。
    """
    for name, spec in MODE_SPECS.items():
        runner_type = spec.runner_type
        guarded = _base_conclusion_gate_protected(runner_type)
        declared = name in CONCLUSION_GATE_DECLARATION
        if guarded and declared:
            raise RuntimeError(
                f"路线 {name} 走基类主循环、门槛已经生效，却又躺在 "
                "CONCLUSION_GATE_DECLARATION 里；两边只能写一边（走基类就把登记划掉）。"
            )
        if not guarded and not declared:
            raise RuntimeError(
                f"路线 {name} 既不在基类门槛的保护下、也没登记自己的结论门槛。"
                "要么别重写 _stable_next_action（让基类的 ConclusionGate 生效），"
                "要么在 CONCLUSION_GATE_DECLARATION 里写清「自己靠什么保证不一帧下结论」；"
                "规矩见 docs/TRANSITION_CONTRACTS.md「结论门槛（全局强制）」。"
            )


def _assert_transition_stance_declared() -> None:
    """加载期自查：每条路线都必须对「动作的出口验收」表态。

    两种合法表态，二选一，**不能两边都写、也不能两边都不写**：

    - 打开 ``_REQUIRE_TRANSITION_CONTRACT``（此后每个动作必须带 ``source_page`` +
      ``target_pages`` / ``in_page_evidence``）；
    - 进 ``TRANSITION_EXEMPT`` 并写清「用自己的什么机制验收」。

    ⚠️ **只认继承 ``ModeRunnerBase`` 的路线**（读开关的代码在那儿）。
    ``shop_refresh`` / ``survivor`` 是自带独立主循环的裸定义，连这个属性都没有；
    ``arena`` / ``expedition`` 继承的是 ``TransactionalRunnerBase``（另一族基类，
    2026-09-26 起）—— 四者的共同点是「属性设了也没人读」⇒ 必然落在豁免名单里，
    理由写「用自己的哪套机制」。别把「它的动作没有 ``target_pages``」直接推成
    「打开开关会抛错」—— 还要问一句「它的 runner 走得到那段代码吗」。

    只查结构，不跑判据 —— 判据准不准要靠拿真夹具跑一遍
    （``tests/test_transition_contracts.py`` 与各路线自己的 ``test_*_runner``）。
    """
    for name, spec in MODE_SPECS.items():
        enforced = (
            getattr(spec.runner_type, "_REQUIRE_TRANSITION_CONTRACT", False) is True
        )
        exempt = name in TRANSITION_EXEMPT
        if enforced and exempt:
            raise RuntimeError(
                f"路线 {name} 既打开了转场强制开关、又躺在 TRANSITION_EXEMPT 里；"
                "两边只能写一边（打开了就把豁免那条划掉）。"
            )
        if not enforced and not exempt:
            raise RuntimeError(
                f"路线 {name} 既没有打开 _REQUIRE_TRANSITION_CONTRACT，"
                "也不在 TRANSITION_EXEMPT 里。要么打开开关（此后每个动作必须带 "
                "source_page + target_pages / in_page_evidence），要么在 "
                "TRANSITION_EXEMPT 里写清「用自己的什么机制验收」；"
                "规矩见 docs/TRANSITION_CONTRACTS.md。"
            )

def _assert_navigation_declared() -> None:
    """加载期自查：每条「有导航」的路线都必须声明导航链。

    两种合法表态，二选一：

    - 声明 ``navigation_plan``（有链）；
    - ``needs_navigation=False``（起点是人工推进到活动内部，压根不走导航）。

    ⚠️ 2026-09-30 之前这段路是一张 ``if mode == "story" / elif ...`` 的分派链、
    写在 ``navigation.py`` 里 —— 漏写一条路线**不会报错**，只会走到那个 ``else``
    抛「导航不支持的模式」，而且要等到实跑开局才现形。现在它是数据，漏了在
    **模块加载**就报错。
    """
    for name, spec in MODE_SPECS.items():
        plan = spec.navigation_plan
        if not spec.needs_navigation:
            if plan is not None:
                raise RuntimeError(
                    f"路线 {name} 声明了 navigation_plan，却 needs_navigation=False；"
                    "不需要导航的路线不该挂计划（它连回大厅那条路都没有）。"
                )
            continue
        if plan is None:
            raise RuntimeError(
                f"路线 {name} 需要导航，却没有 navigation_plan。"
                "在 modes.MODE_SPECS 的注册项里补一份 NavigationPlan（字段语义见 "
                "navigation_plan 模块 docstring），或把 needs_navigation 显式设成 False "
                "并写明理由。"
            )
        if plan.mode != name:
            raise RuntimeError(
                f"路线 {name} 的 navigation_plan.mode 是 {plan.mode!r}，对不上；"
                "抄注册行最容易漏改的就是它。"
            )


def _run_load_time_checks() -> None:
    """把所有「路线准入表态」的自查接在**模块加载**上。

    ⚠️ 2026-09-30 之前 ``_assert_resume_declared`` / ``_assert_transition_stance_declared``
    / ``_assert_conclusion_gate_declared`` **只有测试在调**，生产代码一处都没有 ——
    文档承诺的「漏了在 import 阶段就报错」是一句空话（项目自己早在
    ``docs/maintenance/action_verification_plan.md`` 里记成「发现但未处理」）。
    三者在全量测试里都是绿的，挂到加载上没有额外风险，顺手把这笔欠债还掉。
    """
    _assert_navigation_declared()
    _assert_resume_declared()
    _assert_transition_stance_declared()
    _assert_conclusion_gate_declared()


_run_load_time_checks()

