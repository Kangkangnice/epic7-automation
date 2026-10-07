"""社区 H5（竖屏）的**页面判据**：把一帧竖屏画面判成「在哪一页」。

这条路线走的是 ``core/portrait.py`` 那条独立竖屏链路（1080x1920），
与横屏的 ``navigation.py`` 完全隔离，所以判据也单独一份，不要合并。

## ⚠️ 先读这段：社区 H5 是「叠层」的

实测（2026-10-06，真机帧池）兑换流程是这样叠上去的：

```
商品详情（栈根）
  └─ 订单确认页：几乎盖住整屏，只露底部一条**被压暗**的上一页
       └─ 兑换成功弹窗：x 260..820, y 731..997
```

**下层元素在上层依然可见（只是压暗），而 ``TM_CCOEFF_NORMED`` 对整体压暗几乎免疫**
（项目里早有记录：「×0.45 只掉到 0.9987」）。真机实测：

| 判据 | 来源页 | 在下层暴露处 |
| --- | --- | --- |
| 底部「立即兑换」按钮 | 1.0000 | **0.9587**（订单确认页 / 成功弹窗页） |
| 弹窗内「确认兑换」按钮 | 1.0000 | **1.0000**（成功弹窗页，它就在下面） |

⇒ **「立即兑换 / 确认兑换」这类只差两个字的同形按钮，怎么调阈值都落在死区，
不能当判据。** 正确做法是**只取「上层会盖住」的那块区域**：

- ``order_confirm`` —— 取成功弹窗未来会出现的位置（那里是**固定免责提示文字**）；
- ``redeem_done`` —— 取弹窗本体。

两者**同一块坐标、内容完全不同**，所以天然互斥（实测来源帧 1.0000、对手 0.23~0.41）。

## ⚠️ 两个「栈根页」没有专有正向特征 ⇒ 只能做兜底态

- ``feed_home``（首页列表）：底栏四格导航、左上角放大镜**都是共享控件**
  （放大镜实测 6 页里 5 页逐像素完全相同）；底栏「首页」的青绿激活态判的是
  **「在首页这个 Tab 的导航栈里」**，帖子详情页底下那个页签也还在。
- ``item_detail``（商品详情）：被订单确认页盖得只剩底部那条被压暗的按钮。

⇒ 这两页**不设正向锚点**，由 ``resolve_stack_root()`` 用「栈根判据 + 未检出任何盖层」
兜底。**不要**为了「有个正向判据」去调阈值硬凑 —— 那正是 2026-10-05 竞技场入口事故的形状。

## 已验证结果（全库 105 张竖屏帧 → 42 类唯一页面）

9 个锚点全部零可疑命中，明细见 ``runtime_logs/_make_community_anchors.py`` 的报告。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

import numpy as np

from auto_game_unified.core.matcher import best_match, load_template
from auto_game_unified.core.portrait import PORTRAIT_CANVAS
from auto_game_unified.games.epic7.community_numbers import PORTRAIT_SIZE

# 门槛与项目其它锚点同口径。9 个锚点实测在来源帧上都是 1.0000、对手 ≤0.41，
# 0.82 处在很宽的空档里。
THRESHOLD = 0.82

PAGES_DIRNAME = "pages"

# 日志用中文画面名。
PAGE_LABELS = {
    "feed_home": "社区首页（帖子列表）",
    "exchange_center": "兑换中心",
    "exchange_empty": "兑换中心（空列表，要重试）",
    "tasks_page": "我的任务",
    "item_detail": "商品详情",
    "order_confirm": "订单确认",
    "redeem_done": "兑换成功",
    "share_sheet": "分享面板",
    "post_detail": "帖子详情",
    "network_error": "网络连接异常（H5 已死）",
    "signin_done": "签到成功弹窗",
    "task_todo": "任务行·去完成",
    "task_done": "任务行·已完成",
    "unknown": "认不出的画面",
}


@dataclass(frozen=True)
class PageAnchor:
    """一个页面判据锚点。

    ``region`` 是**竖屏标准画布坐标** ``(x, y, w, h)``；模板只从来源帧的这一块裁，
    匹配时也**只在同一块区域搜**（区域限定，与横屏那套一致：比全屏搜快一个数量级，
    也天然挡掉「别处也有个长得像的东西」）。
    """

    name: str
    region: tuple[int, int, int, int]
    note: str


@dataclass(frozen=True)
class TaskRow:
    """「我的任务」页里的一行任务。

    ``band`` 是这一行**按钮的搜索带**（不是页面区域）：同一对按钮模板要在这条带里
    各判一次，才能得出「这一行做没做」。
    """

    key: str
    label: str
    band: tuple[int, int, int, int]


@dataclass(frozen=True)
class TaskRowState:
    """一行任务的读数。``state`` 取 ``"todo"`` / ``"done"`` / ``"unknown"``。

    ⚠️ ``"unknown"`` 是**必须存在**的第三态：两个按钮都没过阈时**不许猜**是哪一种 ——
    猜错会让路线「以为做完了」而漏掉任务，或者「以为没做」而反复点同一个按钮。
    """

    key: str
    label: str
    state: str
    confidence: float

    @property
    def is_todo(self) -> bool:
        return self.state == "todo"

    @property
    def is_done(self) -> bool:
        return self.state == "done"

    def describe(self) -> str:
        text = {"todo": "未完成", "done": "已完成", "unknown": "认不出"}[self.state]
        return f"{self.label}={text}" + (f"({self.confidence:.4f})" if self.state != "unknown" else "")


# ── 锚点表 ────────────────────────────────────────────────────────────────────
#
# ⚠️ 加锚点前先问两件事（这两条各让一个候选作废过）：
#   ① 这块内容是**该页专有**的吗？（共享控件不行：底栏四格、左上角放大镜）
#   ② 这块内容**会不会变**？（数值/名字/倒计时/轮播横幅不行）
ANCHORS: tuple[PageAnchor, ...] = (
    PageAnchor("feed_home", (125, 1738, 65, 100), "底栏「首页」页签激活态（青绿）"),
    PageAnchor("exchange_center", (410, 96, 260, 68), "居中标题「兑换中心」"),
    # 空列表态（偶发，记忆里点名的隐患）：认不出来就会对着空白页反复点商品卡。
    # 文案是浅灰细字，位置实测 x 375..666 / y 1237..1270。
    PageAnchor("exchange_empty", (360, 1220, 320, 70), "「暂时还没有商品哦」"),
    PageAnchor("tasks_page", (390, 96, 190, 68), "居中标题「我的任务」"),
    PageAnchor("item_detail", (140, 1730, 800, 110), "底部「立即兑换」（叠层，见模块头）"),
    PageAnchor("order_confirm", (270, 745, 540, 240), "订单确认页·固定免责提示"),
    PageAnchor("redeem_done", (265, 736, 550, 256), "「兑换成功」弹窗本体"),
    PageAnchor("share_sheet", (330, 1570, 420, 220), "分享面板「复制链接」"),
    # ⚠️ 2026-10-07 改裁：原区域 (560,1790,440,90) 把**评论数**也罩进去了，
    # 而评论数逐帖不同（实测 10-06 那帖「221」、10-07 那帖「165」）⇒ 在今天的帧上
    # 只拿到 **0.7706**，落在死区里判不出「帖子详情」，于是整页读成 unknown。
    # 新区域只取右侧那颗**分享箭头**（↗）—— 字形固定、逐帖一模一样。
    # 全库 54 张唯一竖屏帧扫描：13 张帖子详情帧全是 1.0000，其余最高 0.3x，零误命中。
    PageAnchor("post_detail", (790, 1790, 110, 85), "帖子底部操作栏·分享箭头（不含评论数）"),
    # 「签到成功！」弹窗的**表头**（✅ 图标 + 那行字）——弹窗本体里「获得 行动力*50 /
    # 同时经验+55」逐次不同，只有表头是固定的。实测在弹窗帧上 1.0000，
    # 全库次高分只有 0.1419，是一道很宽的空档。
    PageAnchor("signin_done", (271, 628, 539, 103), "「签到成功！」弹窗表头"),
    PageAnchor("network_error", (280, 880, 520, 260), "「网络连接异常，下拉刷新」"),
)

# 「我的任务」页三行任务的按钮**长相**模板。
#
# ⚠️ 这两个**不是页面判据**（所以不在 ``ANCHORS`` 里）：它们表达的是「这一行做没做」，
# 而且同一帧上会**同时出现两种**（实测 `tasks_one_browse_done` 上第 1、3 行是绿
# 「去完成」、第 2 行是灰「已完成」）。当页面判据用会导致「一帧命中两个锚点」。
# 正确用法是 ``observe_task_rows()``：在**每一行的搜索带**里各判一次。
TASK_BUTTON_ANCHORS: tuple[PageAnchor, ...] = (
    PageAnchor("task_todo", (927, 1178, 121, 55), "任务行绿底「去完成」"),
    PageAnchor("task_done", (944, 1191, 88, 27), "任务行灰底「已完成」"),
)

TASK_ROW_ANCHORS = tuple(anchor.name for anchor in TASK_BUTTON_ANCHORS)

# 三行任务的**按钮搜索带**。实测按钮都是 x 927..1049、高 55，三行 y = 1178 / 1322 / 1466
# （行距 144）。带子给到宽 180、高 90，两边都留了余量。
TASK_ROWS: tuple["TaskRow", ...] = (
    TaskRow("browse", "浏览帖子", (900, 1160, 180, 90)),
    TaskRow("like", "点赞帖子", (900, 1304, 180, 90)),
    TaskRow("share", "分享帖子", (900, 1448, 180, 90)),
)

# 兜底态：没有专有正向特征，只能由「栈根判据 + 未检出盖层」推出来。
STACK_ROOT_FALLBACKS = {
    "feed_home": ("feed_home",),            # 栈根判据就是它自己那个青绿页签
    "item_detail": ("exchange_center",),    # 兑换流程的栈根判据是兑换中心标题
}

# 每个栈里「会盖住栈根」的页。栈根兜底时必须这些**都没命中**。
STACK_OVERLAYS = {
    "feed_home": ("post_detail", "signin_done", "network_error"),
    "item_detail": ("order_confirm", "redeem_done", "network_error"),
}

# 页面属于哪个「栈」。
#
# 同栈内的下层锚点在栈内其它页面上命中是**正常**的（弹窗是叠上去的、下层还在，
# 见模块头），跨栈命中才是事故 —— 那说明用的是共享控件，不是页面专有判据
# （2026-10-05 竞技场入口就是这么炸的）。判据验收时按这条来分「可接受」和「可疑」。
PAGE_STACKS = {
    "feed_home": "feed",
    "post_detail": "feed",
    "share_sheet": "feed",
    "signin_done": "feed",
    "tasks_page": "tasks",
    "exchange_center": "exchange",
    "exchange_empty": "exchange",
    "item_detail": "exchange",
    "order_confirm": "exchange",
    "redeem_done": "exchange",
    # 它会把整个 H5 弄死，不属于任何一条业务栈，必须能独立认出来。
    "network_error": "global",
}

# 叠层优先级：数字越小越靠上。同一次观察里有多个命中时，取最靠上的那个当当前页。
# 依据就是模块头那张叠层图 —— 成功弹窗在订单确认页之上，订单确认页在商品详情之上。
LAYER_ORDER = {
    "network_error": 0,   # 它会把整个 H5 弄死，优先级最高，必须先认出来退出重进
    "redeem_done": 1,
    "order_confirm": 2,
    "share_sheet": 3,
    # 签到成功弹窗是**盖在信息流上**的模态层，必须比 feed_home（6）靠上，
    # 否则会把弹窗那一帧判成「就在信息流」⇒ 路线去点被弹窗挡住的地方，白等到超时
    # （2026-10-07 实测：弹窗帧判成 feed_home 0.9999，随后点的两下全被弹窗吃掉了）。
    "signin_done": 2,
    "post_detail": 4,
    # 空列表是兑换中心的**子状态**（标题还在），比「兑换中心」本身更具体 ⇒ 排在它上面，
    # 否则空列表会被判成「正常兑换中心」，路线就会去点不存在的商品卡。
    "exchange_empty": 5,
    "exchange_center": 6,
    "tasks_page": 6,
    "feed_home": 6,
    "item_detail": 7,
}


@dataclass(frozen=True)
class TemplateRoot:
    """模板根目录（``templates/community``）。"""

    path: Path

    def page_path(self, name: str) -> Path:
        return self.path / PAGES_DIRNAME / f"{name}.png"


def build_page_templates(template_root: Union[str, Path]) -> dict[str, np.ndarray]:
    """把 9 个页面判据 + 2 个任务按钮模板全部读出来（共 11 张）。

    ⚠️ **fail closed**：任何一个缺失都当场抛 ``FileNotFoundError``，不做
    ``if exists() else None``。判据型模板静默降级过一次就走了整整一个月的弯路
    （2026-10-03 血泪：PC 镜像文件被删 → 判据悄悄消失），这里不再重演。
    """
    root = TemplateRoot(Path(template_root))
    templates: dict[str, np.ndarray] = {}
    missing: list[str] = []
    for anchor in (*ANCHORS, *TASK_BUTTON_ANCHORS):
        path = root.page_path(anchor.name)
        if not path.is_file():
            missing.append(f"{anchor.name}（{path}）")
            continue
        templates[anchor.name] = load_template(str(path))
    if missing:
        raise FileNotFoundError(
            "缺社区页面判据模板：" + "、".join(missing) + "；判据型模板不许缺，缺失必须在这里报错"
        )
    return templates


def _assert_portrait(screen: np.ndarray) -> None:
    if screen.shape[0] != PORTRAIT_CANVAS[1] or screen.shape[1] != PORTRAIT_CANVAS[0]:
        raise ValueError(
            f"社区页面判据只吃竖屏 {PORTRAIT_CANVAS[0]}x{PORTRAIT_CANVAS[1]}，"
            f"拿到 {screen.shape[1]}x{screen.shape[0]}；"
            "横屏帧喂进来会判出莫名其妙的结果"
        )


@dataclass(frozen=True)
class Observation:
    name: str
    confidence: float
    region: tuple[int, int, int, int]

    def describe(self) -> str:
        label = PAGE_LABELS.get(self.name, self.name)
        return f"{label} {self.confidence:.4f}"


@dataclass(frozen=True)
class PageJudgement:
    """判页结论。

    ``fallback=True`` 表示**没有任何正向判据命中**，名字是「栈根兜底」推出来的
    （见 ``STACK_ROOT_FALLBACKS``）。业务上要用它时请明确知道这一点，
    别把它当成一个正向判据来用。
    """

    name: str
    confidence: float
    observations: tuple[Observation, ...]
    fallback: bool = False

    @property
    def label(self) -> str:
        return PAGE_LABELS.get(self.name, self.name)

    def describe(self) -> str:
        if self.fallback:
            return f"{self.label}（兜底，无正向判据命中）"
        return f"{self.label} {self.confidence:.4f}"


def observe_pages(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    threshold: float = THRESHOLD,
    names: Optional[Iterable[str]] = None,
) -> tuple[Observation, ...]:
    """在**各锚点自己的限定区域内**搜模板，返回所有过阈的观察，按分数从高到低。

    区域限定是刻意的：与横屏那套一致，既快，也天然挡掉「别处也有个长得像的东西」。
    """
    _assert_portrait(screen)
    wanted = set(names) if names is not None else None
    found: list[Observation] = []
    for anchor in ANCHORS:
        if wanted is not None and anchor.name not in wanted:
            continue
        template = templates.get(anchor.name)
        if template is None:
            raise KeyError(f"锚点 {anchor.name} 没有模板；build_page_templates() 是 fail-closed 的，不该走到这里")
        x, y, w, h = anchor.region
        patch = screen[y : y + h, x : x + w]
        if patch.shape[0] != h or patch.shape[1] != w:
            continue
        score, _ = best_match(patch.astype(np.float32), template.astype(np.float32))
        if np.isfinite(score) and score >= threshold:
            found.append(Observation(anchor.name, float(score), (x, y, w, h)))
    found.sort(key=lambda item: (-item.confidence, LAYER_ORDER.get(item.name, 99)))
    return tuple(found)


def top_page(observations: Iterable[Observation]) -> Optional[Observation]:
    """从观察里挑「当前页」：**先看叠层优先级，再看分数**。

    ⚠️ 不能只按分数挑：下层页面在上层被压暗后照样能拿高分（模块头那张表），
    只有叠层次序才说得清谁盖着谁。
    """
    candidates = [item for item in observations if item.name not in TASK_ROW_ANCHORS]
    if not candidates:
        return None
    best = min(candidates, key=lambda item: (LAYER_ORDER.get(item.name, 99), -item.confidence))
    return best


def judge_page(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    threshold: float = THRESHOLD,
) -> PageJudgement:
    """判页。认不出来就返回 ``unknown`` —— **绝不猜**（认错比认不出更糟）。"""
    observations = observe_pages(screen, templates, threshold=threshold)
    top = top_page(observations)
    if top is not None:
        return PageJudgement(top.name, top.confidence, observations)
    return PageJudgement("unknown", 0.0, observations)


def observe_task_rows(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    threshold: float = THRESHOLD,
) -> tuple[TaskRowState, ...]:
    """读「我的任务」页三行各自做没做。

    在**每一行自己的搜索带**里各判一次「去完成」与「已完成」，取分高者；
    两个都没过阈 ⇒ ``unknown``。

    ⚠️ 三态是刻意的：认不出时返回 ``unknown`` 而不是默认成某一种 ——
    「以为做完了」会漏任务，「以为没做」会对着同一个按钮反复点。
    """
    _assert_portrait(screen)
    out: list[TaskRowState] = []
    for row in TASK_ROWS:
        x, y, w, h = row.band
        patch = screen[y : y + h, x : x + w]
        if patch.shape[0] != h or patch.shape[1] != w:
            out.append(TaskRowState(row.key, row.label, "unknown", 0.0))
            continue
        scores: dict[str, float] = {}
        for name in TASK_ROW_ANCHORS:
            template = templates.get(name)
            if template is None:
                raise KeyError(f"任务按钮锚点 {name} 没有模板；build_page_templates() 是 fail-closed 的")
            score, _ = best_match(patch.astype(np.float32), template.astype(np.float32))
            scores[name] = float(score) if np.isfinite(score) else 0.0
        best = max(scores, key=lambda key: scores[key])
        if scores[best] < threshold:
            out.append(TaskRowState(row.key, row.label, "unknown", scores[best]))
            continue
        out.append(
            TaskRowState(
                row.key,
                row.label,
                "todo" if best == "task_todo" else "done",
                scores[best],
            )
        )
    return tuple(out)


def resolve_stack_root(
    observations: Iterable[Observation],
    root: str,
    *,
    threshold: float = THRESHOLD,
) -> Optional[PageJudgement]:
    """栈根兜底：``root`` 的栈根判据命中、且**该栈的盖层一个都没命中** ⇒ 就是 ``root``。

    用法（业务侧）::

        # 首页列表：底栏「首页」青绿页签还在，且没看到帖子详情
        resolve_stack_root(obs, "feed_home")

        # 商品详情：兑换流程里，没收看到订单确认页 / 成功弹窗
        resolve_stack_root(obs, "item_detail")

    ⚠️ 这是**兜底**，不是正向判据：``PageJudgement.fallback`` 为 True，
    日志里必须写清楚（``describe()`` 已经带了「兜底」字样）。
    """
    items = list(observations)
    hit = {item.name for item in items}
    stack_anchor = STACK_ROOT_FALLBACKS.get(root)
    if stack_anchor is None:
        raise KeyError(f"{root} 不是栈根兜底态；可用的有 {sorted(STACK_ROOT_FALLBACKS)}")
    if not any(name in hit for name in stack_anchor):
        return None
    if any(name in hit for name in STACK_OVERLAYS.get(root, ())):
        return None
    base = next((item for item in items if item.name in stack_anchor), None)
    return PageJudgement(root, base.confidence if base else 0.0, tuple(items), fallback=True)


def assert_anchor_regions_inside_canvas() -> None:
    """构造期自检：每个锚点区域都必须落在竖屏画布内、尺寸为正。

    与横屏 ``Epic7Navigator._assert_anchor_templates()`` 同一个用意 ——
    区域写错了（负数、越界）会让匹配悄悄退化成「什么都搜不到」，
    在这里喊出来比在真机上查便宜得多。
    """
    width, height = PORTRAIT_CANVAS
    for anchor in ANCHORS:
        x, y, w, h = anchor.region
        if w <= 0 or h <= 0:
            raise ValueError(f"锚点 {anchor.name} 区域尺寸非正：{anchor.region}")
        if x < 0 or y < 0 or x + w > width or y + h > height:
            raise ValueError(
                f"锚点 {anchor.name} 区域 {anchor.region} 越出竖屏画布 {width}x{height}"
            )


assert_anchor_regions_inside_canvas()
assert PORTRAIT_SIZE == PORTRAIT_CANVAS, "community_numbers 与 portrait 的画布口径必须一致"
