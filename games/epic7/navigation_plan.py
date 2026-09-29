"""导航链的**声明式计划**：把「大厅 → 路线入口」这段路写成数据。

## 为什么要有它（2026-09-30）

``Epic7Navigator.navigate()`` 以前是一张 ``if mode == "story" / elif mode == "arena" / ...``
的分派链（约 250 行）：每加一条路线都要回去改那个共享方法，而 ``main.py`` 那条
「不要在共享模块里写具名路线分支」的规矩，早就用 ``ModeSpec`` 的两个钩子清干净了
—— 只剩它还留着。

现在每条路线在自己模块里声明一份 ``NavigationPlan``（挂在 ``ModeSpec.navigation_plan``），
``navigate()`` 退化成执行器：**新增路线不用再碰 ``navigation.py``**。

## 这个模块只能是纯数据

它 import 任何本项目模块都会把 ``navigation`` / ``modes`` 卷进来成环
（``navigation`` 已经 import 了 ``modes`` 与 7 个路线模块，而路线模块 import 本模块）。
所以这里只放 dataclass，**不要** import 路线、``modes`` 或 ``navigation``。

## 字段怎么理解

一个 ``NavigationStep`` 就是原来的一次 ``_transition(source, targets, anchor, label)`` 调用。
执行器从第一步开始往下走，每一步：

- 若这一步的某个 ``targets`` 正好等于 ``already_at``（人停在半路）⇒ **跳过它以及它前面的所有步**，
  从下一步接着走，而且当前的画面帧直接沿用调用方给的那一帧；
- 若这一步声明了 ``skip_if_observed``，且当前画面已被 ``observe()`` 认成其中某个页名 ⇒ 跳过本步
  （目前只有远征的「已在赛季菜单」需要这条）；
- 否则执行 ``_transition``，并把返回的新画面当作下一步的来源帧。

⚠️ **顺序即优先级**：``already_at`` 命中哪一步就是「人停在哪一级」，所以多目标步骤的
``targets`` 要按「由浅到深」写。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavigationStep:
    """导航链上的一步：一次「点某个锚点，从 source 页去 targets 页」。"""

    source: str
    # 这一步可能到达的页面名。**单目标也要写成元组**（执行器按长度决定
    # 传给 ``_transition`` 的是 str 还是 tuple —— 那里有 ``target == "hero_list"``
    # 这类身份比较，形状不能变）。
    targets: tuple[str, ...]
    # 导航锚点名：必须在 ``Epic7Navigator._REGIONS`` 与 ``NavigationTemplates`` 上都有。
    anchor: str
    # 日志里的中文动作名（``模式=导航 页面=… 目标=… 动作=…``）。
    label: str
    # 落到这一步时，若当前画面已被 ``observe()`` 认成这些页名，就跳过这一步。
    skip_if_observed: tuple[str, ...] = ()


@dataclass(frozen=True)
class NavigationPlan:
    """一条路线的整条导航链 + 接力日志文案。"""

    mode: str
    steps: tuple[NavigationStep, ...]
    # 允许 ``navigate(already_at=...)`` 的页面白名单。**保持显式、不从 steps 派生**：
    # 「链条上有这个页面」不等于「允许从它接力」（迷宫的落点全在业务链上，
    # 它的白名单就该是空的）。``__post_init__`` 只保证它是链条页面的**子集**。
    resume_entries: frozenset[str] = frozenset()
    # 「导航完成」日志的 ``前提=`` 半句；空串表示不打（走通用的一行）。
    ready_note: str = ""
    # 接力日志的 ``模式=``。默认「导航」；竞技场 / 骑士团捐赠 / 圣域收菜用各自的中文名
    # （沿用 2026-09 之前逐字写死的那几行，日志口径不变）。
    resume_log_mode: str = "导航"
    resume_action: str = ""
    # 停在链条中间（不是末端）时的 ``动作=``；留空表示与 resume_action 相同。
    resume_action_middle: str = ""
    resume_state_done: str = ""
    resume_state_middle: str = "从当前这一级继续"

    def __post_init__(self) -> None:
        if not self.mode:
            raise ValueError("NavigationPlan.mode 不能为空")
        if not self.steps:
            raise ValueError(
                f"路线 {self.mode} 的 NavigationPlan 一步都没有；"
                "不需要导航的路线（needs_navigation=False）不该挂计划"
            )
        chain_pages = {page for step in self.steps for page in step.targets}
        for step in self.steps:
            if not step.targets:
                raise ValueError(f"路线 {self.mode} 的第 [{step.source}] 步没有目标页")
            if not step.anchor or not step.label:
                raise ValueError(
                    f"路线 {self.mode} 的第 [{step.source}] 步缺少 anchor 或 label"
                )
        unknown = sorted(self.resume_entries - chain_pages)
        if unknown:
            # 「白名单里有、链条上没有」= 声明可以从那一页接力，而导航压根到不了那里
            # —— ``_RESUME_ENTRY_PAGES`` 的注释从 2026-09 就写着这条规矩，现在由它兜住。
            raise ValueError(
                f"路线 {self.mode} 的接力白名单里有链条之外的页面 {unknown}；"
                f"导航链只到得了 {sorted(chain_pages)}"
            )
        if self.resume_entries and not self.resume_action:
            raise ValueError(
                f"路线 {self.mode} 声明了接力白名单，却没有接力日志文案 resume_action"
            )
        if self.resume_entries and not self.resume_state_done:
            raise ValueError(
                f"路线 {self.mode} 声明了接力白名单，却没有接力落点文案 resume_state_done"
            )

    def transition_target(self, step: NavigationStep) -> str | tuple[str, ...]:
        """按原 ``_transition`` 的调用形状还原目标：单目标给 str，多目标给 tuple。

        ⚠️ 不能图省事一律给 tuple：``_transition`` 里有 ``target == "hero_list"``
        这类**身份比较**（英雄列表容器那两段分支），形状一变就整段失效。
        """
        return step.targets[0] if len(step.targets) == 1 else step.targets

    def resume_log(self, *, page: str, terminal: bool) -> str:
        """接力命中时的日志行（``page`` 由调用方用 ``navigation.page_label`` 译好）。"""
        action = self.resume_action
        if not terminal and self.resume_action_middle:
            action = self.resume_action_middle
        state = self.resume_state_done if terminal else self.resume_state_middle
        return (
            f"模式={self.resume_log_mode} 开局=接力 页面={page} "
            f"动作={action} 状态={state}"
        )

    def ready_log(self, mode_label: str) -> str:
        """导航收尾的日志行（``mode_label`` 取 ``modes.MODE_LABELS``）。"""
        base = f"模式={mode_label} 状态=导航完成"
        return f"{base} 前提={self.ready_note}" if self.ready_note else base
