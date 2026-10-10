"""界面令牌层：颜色 / 字号 / 间距 / 尺寸，以及基于它的 ttk 样式。

## 为什么单独拆一个模块

本项目的界面过去把色值、间距、字号直接写在各面板里。2026-09-29 审计结果：
**间距出现 10 个不同取值**（0/2/4/6/10/12/14/16/20，只有一半落在 4px 梯度上）、
**硬编码色值 10 个**散在组件里。用户当天反馈「排布不合理、空了很多、挤在一块」。
根因在**排布**（每张卡各占一整块、内容缩在左边；说明文字压在卡片底部窄栏里折成 7 行），
但「没有单一事实源」让排布没法系统地调 —— 所以先建这一层：面板不再写具体数值，
只引用这里的语义名。

## 单位约定（本项目最容易踩的一条）

令牌里的数字**一律是逻辑像素**，落到 Tk 时必须乘 ``Theme.scale``（设备像素比）。
字体一律用**负数字号**（Tk 约定：负数＝像素，正数＝磅）。

为什么：字号用磅、间距用裸像素的话，两者会各走各的。**本机确实是这个情况**
（2026-09-29 实测）：``core/window.py`` 在**导入时**就调了
``ctypes.windll.user32.SetProcessDPIAware()``，所以助手进程是 DPI 感知的 ——
Tk 拿到真实桌面 3200×2000、192 DPI，``Theme.scale`` = 2.0。
旧界面正文用 ``10pt``（磅 ⇒ 26.7px），而间距是裸像素（不放大）⇒ 字大间隙小，
视觉上就是用户说的「挤在一块」。令牌层把两者都乘同一个 ``scale`` 修掉它。

⇒ 推论：**新写字号一律走 ``Theme.font()``，别直接写磅数**。

## 对比度（实测值，不是估计）

正文对比度门槛 4.5:1，非文本元素 3:1。本表用 WCAG 相对亮度公式算过：

| 用途 | 前景 / 背景 | 实测 |
| --- | --- | --- |
| 正文 | `#18181B` / `#FFFFFF` | **17.72:1** |
| 正文（页底） | `#18181B` / `#F6F7F9` | **16.53:1** |
| 次要文字 | `#52525B` / `#FFFFFF` | **7.73:1** |
| 弱化文字 | `#71717A` / `#FFFFFF` | **4.83:1** |
| 主色文字 | `#2563EB` / `#FFFFFF` | **5.17:1** |
| 成功态文字 | `#15803D` / `#FFFFFF` | **5.02:1** |
| 错误态文字 | `#B91C1C` / `#FFFFFF` | **6.47:1** |
| 日志正文 | `#E4E4E7` / `#18181B` | **13.96:1** |
"""

from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk


# ══════════════════════════════════════════════════════════════════════════
# 1. 原始值层 —— 具体数值只允许出现在本模块，别处一律引用语义名
# ══════════════════════════════════════════════════════════════════════════

# 间距：4px 基准。用法约定：关联元素用 XS~SM，组件内边距用 MD~XL，
# 区块之间用 LG。**只留用到的档** —— 空档位等真的需要时再加。
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

# 字号：单屏只用 4 档，避免「12 种字号彼此无梯度」那种漂移。
TYPE_TITLE = 24
TYPE_SECTION = 16
TYPE_BODY = 14
TYPE_CAPTION = 12

# 一条路线的格子**估计**占多宽（勾选框文字 + 次数框 + 「次」）。只用来算屏幕能
# 排几列（`route_columns`），**不是** grid 的 minsize —— 格子实际宽度由内容决定。
# ⚠️ 别把它当下限塞进 `grid_columnconfigure`：那会把次数框推离它自己的名字，
# 看上去像属于下一条路线（2026-09-29 踩过，见 `app._build_task_panel`）。
CELL_MIN_WIDTH = 214
LOG_MIN_HEIGHT = 160

# 说明文字的**初始**换行宽度。真实宽度由控件自己的 ``<Configure>`` 决定
# （见 ``app.DesktopApp._wrap_at_own_width``）；这里只给个够窄的初值，
# 免得窗口首次测量时被一整行不换行的长文案顶成超宽。
WRAP_MIN_WIDTH = CELL_MIN_WIDTH * 2

# 任务网格的形状约束。用户两次要求「别太长」，且明说「以后还有很多路线」⇒
# 行数封顶、多出来的用**加列**解决：加路线不用改排布代码。
ROUTE_ROWS_TARGET = 3
ROUTE_COLUMNS_MIN = 2
ROUTE_COLUMNS_MAX = 4

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"


@dataclass(frozen=True)
class Palette:
    """语义色。组件引用这一层，绝不直接写原始色值。

    暗色模式的做法是**只覆盖本层**（原始色板不动）——目前没做暗色主题，
    但把色值收在这里，将来做的时候不用回去翻每个面板。
    """

    bg: str = "#F6F7F9"
    surface: str = "#FFFFFF"
    text: str = "#18181B"
    text_secondary: str = "#52525B"
    text_muted: str = "#71717A"
    primary: str = "#2563EB"
    success: str = "#15803D"
    error: str = "#B91C1C"
    log_bg: str = "#18181B"
    log_text: str = "#E4E4E7"


@dataclass(frozen=True)
class Theme:
    """把逻辑像素换算成设备像素的唯一入口。"""

    palette: Palette
    scale: float

    def px(self, value: float) -> int:
        """逻辑像素 → 设备像素（取整，至少 1）。"""
        return max(1, int(round(value * self.scale)))

    def font(self, size: int, *, bold: bool = False, mono: bool = False) -> tuple:
        """字号令牌 → Tk 字体元组。

        ⚠️ 用**负数字号**（Tk 约定：负数＝像素高度，正数＝磅）—— 见模块
        docstring 的单位约定。
        """
        family = MONO_FAMILY if mono else FONT_FAMILY
        pixels = -self.px(size)
        return (family, pixels, "bold") if bold else (family, pixels)


def detect_scale(root: tk.Misc) -> float:
    """设备像素比。

    本机实测返回 **2.0**（192 DPI / 200% 缩放）—— 见模块 docstring：
    助手进程导入了 ``core.window``，那里设了 DPI 感知，所以 Tk 拿到真实分辨率。
    写成「探测」而不是写死 2.0，是为了换台机器/换缩放比例时结果自动跟上。
    """
    return max(1.0, root.winfo_fpixels("1i") / 96.0)


def route_columns(*, route_count: int, screen_logical_width: float) -> int:
    """任务网格排几列。

    两条约束取小：① 不超过 `ROUTE_ROWS_TARGET` 行；② 屏幕宽度装得下（每格至少
    `CELL_MIN_WIDTH`）。新增路线时先涨行、到 3 行就自动加列 ⇒ **加路线不用改排布**。
    """
    rows_needed = -(-route_count // ROUTE_ROWS_TARGET)
    by_width = int(screen_logical_width // CELL_MIN_WIDTH)
    return max(ROUTE_COLUMNS_MIN, min(rows_needed, by_width, ROUTE_COLUMNS_MAX))


def build(root: tk.Misc) -> Theme:
    """探测缩放 → 组装令牌 → 灌好样式。界面层只需要这一行。"""
    theme = Theme(palette=Palette(), scale=detect_scale(root))
    apply_styles(root, theme)
    return theme


def apply_styles(root: tk.Misc, theme: Theme) -> None:
    """把令牌灌进 ttk 样式表。所有面板引用的样式名在这里集中定义。

    ⚠️ 用 `vista`（Windows 原生外观），只覆写**字体与内边距**；不去改控件的
    绘制方式 —— 原生控件手感对用户更友好，本项目的问题从来不是控件长相，
    而是间距比例与排布。**推论：vista 主题下控件的背景色由系统绘制，
    ``Accent.TButton`` 的「强调」只能靠字重与内边距，给不出彩色按钮。**
    """
    palette = theme.palette
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")

    # 容器
    style.configure("App.TFrame", background=palette.bg)
    style.configure("Card.TFrame", background=palette.surface)

    # 文字：4 档字号，各配一个固定语义的样式名
    style.configure(
        "Title.TLabel",
        background=palette.surface,
        foreground=palette.text,
        font=theme.font(TYPE_TITLE, bold=True),
    )
    style.configure(
        "Section.TLabel",
        background=palette.surface,
        foreground=palette.text,
        font=theme.font(TYPE_SECTION, bold=True),
    )
    style.configure(
        "Body.TLabel",
        background=palette.surface,
        foreground=palette.text_secondary,
        font=theme.font(TYPE_BODY),
    )
    style.configure(
        "Caption.TLabel",
        background=palette.surface,
        foreground=palette.text_muted,
        font=theme.font(TYPE_CAPTION),
    )
    # 分组标题（「日常 / 赛季 / 活动」）：比正文小一档、比说明文字重一点，
    # 靠**字重 + 位置**区分层级，不额外给底色 —— 卡片本来就是白的，再铺一层
    # 只会让「三个分组」看起来像三个卡片，反而比路线本身还抢眼。
    style.configure(
        "Group.TLabel",
        background=palette.surface,
        foreground=palette.text,
        font=theme.font(TYPE_BODY, bold=True),
    )

    # 按钮：主行动（Accent，靠字号加粗与更大内边距强调）/ 次行动（默认）/ 工具条
    style.configure(
        "TButton",
        padding=(theme.px(SPACE_LG), theme.px(SPACE_SM)),
        font=theme.font(TYPE_BODY),
    )
    style.configure(
        "Accent.TButton",
        padding=(theme.px(SPACE_XL), theme.px(SPACE_SM)),
        font=theme.font(TYPE_BODY, bold=True),
    )
    style.configure(
        "Tool.TButton",
        padding=(theme.px(SPACE_MD), theme.px(SPACE_XS)),
        font=theme.font(TYPE_CAPTION),
    )

    # 勾选框 / 单选框 / 次数框：都坐在卡片（白底）上
    for name in ("Route.TCheckbutton", "Route.TRadiobutton"):
        style.configure(name, background=palette.surface, font=theme.font(TYPE_BODY))
    style.configure(
        "Route.TSpinbox",
        padding=(theme.px(SPACE_XS), theme.px(SPACE_XS)),
        font=theme.font(TYPE_BODY),
    )
