"""首次启动：风险确认 + 环境清单。

## 为什么需要这一层

装上就能双击打开，不等于新用户知道「先开雷电、游戏停在大厅、跑的时候不能最小化」。
2026-10-19 的产品化差距评估里，陌生人拿到安装包卡住的第一处**不是功能，是环境** ——
他双击之后看到的是一屏勾选框，不知道自己在同意什么、也不知道该先做什么。

所以第一屏只干三件事：把风险讲清楚、把前置条件列成清单、给一个「检测」按钮。
攒够一次真实检测，新用户就不用再回去翻文档。

## 四条规矩（改之前先读）

1. **不同意就不许跑**：`DesktopApp` 的「开始任务」在确认状态为假时保持禁用。
   这不是「弹个窗提示一下」—— 是启动按钮根本点不下去。

2. **认不出就当没同意过**（fail-closed）：文件不存在、JSON 坏了、字段缺失、
   版本号对不上，一律重新确认。宁可多问一遍，也不替用户默认他已经同意。

3. **落盘失败不许把人关在门外**：目录只读、权限不足导致写不进去时，**本次照常放行**
   （用户刚刚确实点了同意），只记一条日志让下次再问。那是 `core/data_paths.py`
   该暴露的问题，不该变成一道进不去的门。

4. **点「开始使用」就是同意，不做二次确认**（2026-10-20 用户明确要求）：
   这一屏**没有**「我已阅读并理解…」勾选框，按钮也不会因为你没勾而置灰 ——
   别再把这个勾选框加回来，也别在按钮后面再接一个「确定吗」。
   「不同意」的出口是「暂不使用」和直接关窗，两者都让 `accepted` 保持 `False`。

## 文案来源

`RISK_POINTS` 与 `SETUP_POINTS` 每一句都必须能在文档里找到出处：
风险 → `NOTICE.md` / `SECURITY.md`；环境 → `README.md` §环境要求 与 §已知限制。
**不要在这里写文档里没有的承诺**（比如「不会封号」），也不要写已经不成立的限制
（比如「不提供 PVP」—— 竞技场路线是存在的）。
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Callable

from auto_game_unified.desktop.theme import (
    SPACE_LG,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    TYPE_TITLE,
    Palette,
    Theme,
)

#: 确认记录的格式版本。**改动条款就把这个号加一** —— 老用户会被重新问一次。
#: 这是唯一能让「已经同意过旧条款」的人重新看到新条款的机制，别省。
#:
#: 变更记录（加号时在下面写一行「为什么」，否则过半年没人知道这个号为什么不是 1）：
#:   v1 —— 首版。
#:   v2 —— 2026-10-20：风险那四条合成一条重写，并**新增「非商业用途」**这个约束
#:         （此前只在 README / NOTICE 里写，弹窗里没有）。新增约束就该重新征得同意。
#:
#: ⚠️ 2026-10-21 又改了一次（**删掉「非商业用途」**：用户拍板「别人随便怎么用都行，
#:    许可也不用换，把措辞删掉就行」），但**没有加号**：删约束是**放宽**，
#:    已经同意过 v2 的人本来就受更紧的约束，不需要再问一遍。
#:    **下次新增义务（要用户多做/少做什么）时才加号。**
CONSENT_VERSION = 2

CONSENT_FILENAME = "consent.json"

#: 对话框正文的换行宽度（逻辑像素）。窄一点更好读；窗口本身不跟着变宽。
#:
#: ⚠️ 2026-10-20 用户反馈「使用须知太宽了」，随后又要求「一列写完」：
#: 这**一版是单栏**，所以 DIALOG_WRAP 基本就等于整窗内文宽度
#: （整窗 ≈ DIALOG_WRAP + 左右内边距 24×2）。原来两栏各 560 时整窗约 1200 逻辑像素，
#: 1600 的屏要占 3/4；现在 520 → 整窗约 568，同一块屏只占 35%。
#: **加大之前先按 1366 的屏量一遍**；量法：`d.winfo_reqwidth()`。
DIALOG_WRAP = 520

RISK_POINTS = (
    # 2026-10-20 用户要求：原来那四点（非官方 / 只做识别与点击 / 可能被封号 / 竞技场
    # 不保胜负）**合成一点**，并按「非官方第三方工具 → 不读取数据 → 只做视觉识别」
    # 这个顺序讲。合成后与 README「许可证与免责声明」那一段逐句对得上，
    # 所以**改这里就要顺手看那一节**，别让两处说两套话。
    #
    # ⚠️ 2026-10-21 删掉了「非商业用途」：用户原话「别人随便怎么用都行，怕什么，
    # 许可也不用换，你把措辞删掉就行了」。代码本来就是 MIT（允许商用），
    # 界面再写一句「非商业」只是自相矛盾 —— **别再把它加回来**。
    #
    # ⚠️ 「账号与游戏资源风险由使用者自行承担」这半句**不能省** —— 它是整页的落点，
    # 也是 `test_risk_points_state_the_real_boundaries` 守着的东西（可以不说「会封号」，
    # 但不能反过来说「不会封号」，更不能只讲我们干净、不讲风险归谁）。
    #
    # 同日第二版：用户嫌「太宽」，长句拆成短句、去掉重复的「本项目的」，
    # 语义一个都没少（`test_risk_points_state_the_real_boundaries` 逐条钉着）。
    #
    # ⚠️ 长度与**字符构成**都是排版参数：单栏 520 下这段正好 4 行。
    # 这里刻意**不写 Smilegate / Super Creative / STOVE** 三个英文名 ——
    # Tk 的 wraplength 优先在空格处断行，英文名连着写时中间会挤出一行只剩
    # 「Creative、STOVE」，截图里看着像被截断（2026-10-20 见过）。公司名在
    # README §许可证 与 NOTICE.md 里都写全了，这一屏只讲身份与边界。
    "非官方的免费第三方工具，与游戏开发商及发行商均无关联，"
    "未获授权或认可。只做截图视觉识别与普通鼠标点击，"
    "不读取或修改内存、网络数据与客户端文件，不含反检测或绕过安全机制的功能。"
    "账号与资源风险由使用者自行承担。",
)

SETUP_POINTS = (
    "64 位 Windows 10/11 + 雷电模拟器；窗口标题须为「第七史诗」。",
    # 「识别画布 1982×1132」这个数字**刻意不写**：用户只需要知道「渲染区 1920×1080、
    # 别乱改」，1982×1132 是助手的内部换算（客户区 + 标题栏），写进来只会占一整行
    # 还把括号拆到两行去（2026-10-20 截图里见过「（识别画布 / 1982×1132）」）。
    # 需要这个数的人看 README §环境要求。
    "模拟器渲染区设 1920×1080；改过分辨率、显示缩放或游戏 UI 之后要重新检测。",
    "先把游戏停在大厅，再点「开始任务」；跑完会自动回大厅。",
    # 2026-10-20 用户实测纠正：这条原来写的是「自动化期间游戏必须保持前台，
    # 不能最小化或被别的窗口挡住；不支持后台运行」—— 对**模拟器**来说是错的。
    # 模拟器这条链路：取图走 `PrintWindow`（`core/window.py::_print_window_render`
    # 的注释就写着「模拟器被遮挡/失焦时仍能取到正确画面」），点击走
    # `ldconsole adb shell input tap`，在安卓内部注入，根本不经过 Windows 鼠标栈
    # ⇒ 被别的窗口压住、不处于前台都照跑，真实鼠标也不被占用。
    #
    # ⚠️ **别把 PC 后端那套结论抄过来**：`core/pc_window.py` 的点击是 `SendInput`
    # 真实鼠标事件，每次点击都要先把游戏窗口抢到前台再还回去，窗口也不能最小化
    # （见 `docs/PC_TEMPLATE_MIGRATION.md`）。PC 后端还没上界面，这里按模拟器写。
    #
    # 「建议不要最小化」这半句是保守留的：最小化之后 `PrintWindow` 还灵不灵取决于
    # 显卡驱动与 DWM，没有实测证据前不写成承诺。真跑通了再删。
    "不必一直放前台：读的是窗口画面、点击走模拟器自己的输入通道，"
    "被别的窗口挡住也能跑，鼠标可以照常用；建议不要最小化。",
    # ⚠️ 2026-10-20 用户要求**删掉原文第 5 条**「游戏语言用简体中文：模板是在中文
    # 界面上采集的」。删掉的是这句话在**首启弹窗**里的位置，不是这个约束本身 ——
    # 模板全是在中文界面上采的，游戏换成英文/日文之后判定会大面积失效。
    # 所以这句话搬到了 README §环境要求 与 USER_GUIDE §前置条件；
    # 哪天又想在弹窗里提醒，从那里抄回来，别自己另编一个说法。
)

#: 这些文字直接塞进 tk 的 Label，**不解释任何标记语法**。
#: 写 `**重点**` 会原样显示成星号（2026-10-19 渲染截图时踩到），
#: 所以强调只能靠分句和措辞 —— `test_onboarding.py` 里有一条测试守着这件事。


def consent_path(data_root: Path) -> Path:
    """确认记录的落盘位置。跟着 `core/data_paths.py` 走，不在别处再写一份。"""
    return data_root / CONSENT_FILENAME


def has_consent(data_root: Path) -> bool:
    """这份确认记录算不算「已经同意过」。

    只要有任何一处对不上就返回 ``False`` —— 见模块 docstring 第 2 条规矩。
    注意 ``json.JSONDecodeError`` 是 ``ValueError`` 的子类，这里一并接住；
    文件不存在则是 ``OSError``。两种都当作「没同意过」。
    """
    try:
        payload = json.loads(consent_path(data_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("version") != CONSENT_VERSION:
        return False
    return payload.get("accepted") is True


def record_consent(
    data_root: Path,
    *,
    now: Callable[[], datetime] = datetime.now,
) -> bool:
    """把「已同意」写下来。**写失败不算错**，返回 ``False`` 交给调用方记日志。

    先写同目录临时文件再 ``os.replace``：中途断电不会留下一个半截 JSON，
    而半截 JSON 正好会被 `has_consent` 判成「没同意过」——那会把用户绕回对话框。
    """
    path = consent_path(data_root)
    payload = {
        "version": CONSENT_VERSION,
        "accepted": True,
        "accepted_at": now().isoformat(timespec="seconds"),
    }
    temp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temp, path)
    except OSError:
        # 临时文件可能已经落地但替换失败，留着会让下次「看起来有记录」。
        temp.unlink(missing_ok=True)
        return False
    return True


def clear_consent(data_root: Path) -> bool:
    """删掉确认记录（「重新查看使用须知」用）。文件本来就不在也算成功。"""
    try:
        consent_path(data_root).unlink(missing_ok=True)
    except OSError:
        return False
    return True


class ConsentDialog(tk.Toplevel):
    """使用须知对话框。关窗 = 不同意，此时 ``accepted`` 保持 ``False``。

    ⚠️ 这里**不做任何判定**（不读盘、不写盘）—— 判定全在上面的纯函数里，
    对话框只负责「用户看到什么、勾了什么」。这样测试能绕开 Tk 覆盖到判定逻辑。
    """

    def __init__(self, parent: tk.Misc, theme: Theme) -> None:
        super().__init__(parent)
        self.accepted = False
        self._theme = theme
        palette: Palette = theme.palette
        px = theme.px

        self.title("使用须知")
        self.configure(background=palette.surface)
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        body = ttk.Frame(self, style="Card.TFrame", padding=(px(SPACE_XL), px(SPACE_XL)))
        body.pack(fill=tk.BOTH, expand=True)

        self._heading(body, "第七史诗自动助手", TYPE_TITLE)
        self._caption(
            body,
            # 2026-10-20 用户：「一列写完不就好了吗？」—— 单栏之后这句话也不再说
            # 「左边/右边」，按阅读顺序讲：先说风险，再说开始前的准备。
            "第一次使用前请读完：先说风险，再说开始前的准备。读完点「开始使用」。",
        )

        # ⚠️ 2026-10-20 用户要求**改成单栏**（原来左右两栏并排）：
        # 两栏的整窗宽度 ≈ 2 × 换行宽度 + 内边距，1600 的屏要占 3/4，还容易出现
        # 左栏一墙字、右栏几条的难看对比。单栏一段接一段读下来就够了 ——
        # 这是个说明框，不是对比表，不需要并排。**别再把 columnconfigure 加回来。**
        self._section(body, "你需要知道的风险", RISK_POINTS)
        self._section(body, "开始之前先准备好", SETUP_POINTS)

        # 2026-10-20 用户要求：**去掉「我已阅读并理解…」勾选框，也不做二次确认** ——
        # 读完直接点「开始使用」就走。原来那个勾选 + 按钮置灰只多一道门、不多一分信息
        # （见模块 docstring 第 4 条规矩）。
        # 「不同意」的出口是「暂不使用」和直接关窗，两者都让 `accepted` 留在 False。
        footer = ttk.Frame(body, style="Card.TFrame")
        footer.pack(fill=tk.X, pady=(px(SPACE_LG), 0))
        self._accept_button = ttk.Button(
            footer, text="开始使用", style="Accent.TButton", command=self._on_accept
        )
        self._accept_button.pack(side=tk.RIGHT)
        ttk.Button(footer, text="暂不使用", command=self._on_close).pack(
            side=tk.RIGHT, padx=(0, px(SPACE_SM))
        )

        self._center_on(parent)
        self.grab_set()
        self.focus_set()

    def _center_on(self, parent: tk.Misc) -> None:
        """摆到父窗口中间偏上。

        ⚠️ 不摆的话 Tk 会把新窗口丢在**屏幕左上角**（2026-10-19 打包装上后截图才看到），
        用户第一眼看到的提示框贴着屏幕边缘，像没装好。

        父窗口还没映射（宽高为 1）时按屏幕居中 —— 那不正常的调用方也需要一个像样的位置。
        """
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        if parent_width > 1 and parent_height > 1:
            left = parent.winfo_rootx() + (parent_width - width) // 2
            # 垂直方向偏上三分之一：对话框下方通常还有用户想看的按钮，不要压住
            top = parent.winfo_rooty() + (parent_height - height) // 3
        else:
            left = (self.winfo_screenwidth() - width) // 2
            top = (self.winfo_screenheight() - height) // 3
        # 别把窗口中心摆到屏幕外（父窗口贴着边缘时会出现负坐标）
        left = max(0, left)
        top = max(0, top)
        self.geometry(f"+{left}+{top}")

    # ── 排布小工具 ────────────────────────────────────────────────────────
    def _heading(self, parent: ttk.Frame, text: str, size: int) -> None:
        ttk.Label(
            parent, text=text, style="Title.TLabel", font=self._theme.font(size, bold=True)
        ).pack(anchor="w")

    def _caption(self, parent: ttk.Frame, text: str) -> None:
        ttk.Label(
            parent,
            text=text,
            style="Caption.TLabel",
            # ⚠️ 这里是 ``DIALOG_WRAP`` 本身，不是 ``× 2``：``× 2`` 是两栏时代为了让
            # 引言横跨两栏写的，改成单栏之后它会把整窗**撑宽到两倍**（标题不会，
            # 只有这段会，所以特别容易看不出来）。
            wraplength=self._theme.px(DIALOG_WRAP),
            justify="left",
        ).pack(anchor="w", pady=(self._theme.px(SPACE_XS), 0))

    def _section(self, parent: ttk.Frame, title: str, points: tuple[str, ...]) -> None:
        """一段带标题的正文，竖向接在前一段下面（单栏，没有 column 参数）。

        段与段之间留 ``SPACE_LG``，段内第一条与标题之间留 ``SPACE_SM``。
        """
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.pack(fill=tk.X, pady=(self._theme.px(SPACE_LG), 0))
        ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w")
        for index, point in enumerate(points):
            # ⚠️ 编号用**全角**「．」而不是 ``. ``：Tk 的 wraplength 只在**空格**处
            # 换行，一段连续中文会被当成一个「词」。用半角「2. 」的话，那个超长
            # 单词放不进行尾剩余宽度，就整体挪到下一行 —— 屏幕上表现为「2.」孤零零
            # 占一行（2026-10-19 渲染截图时发现）。去掉空格让编号跟着正文一起排。
            ttk.Label(
                frame,
                text=f"{index + 1}．{point}",
                style="Body.TLabel",
                wraplength=self._theme.px(DIALOG_WRAP),
                justify="left",
            ).pack(
                anchor="w",
                pady=(self._theme.px(SPACE_SM if index == 0 else SPACE_XS), 0),
            )

    # ── 状态 ──────────────────────────────────────────────────────────────
    def _on_accept(self) -> None:
        # 勾选框已经去掉（2026-10-20），点这个按钮本身就是同意 —— 没有别的门。
        # 仍然留成一个方法而不是直接把赋值写进按钮回调，是为了让测试能直接调它。
        self.accepted = True
        self.destroy()

    def _on_close(self) -> None:
        self.accepted = False
        self.destroy()


def prompt_consent(parent: tk.Misc, theme: Theme) -> bool:
    """弹一次对话框并等它关掉，返回用户有没有同意。

    做成模块级函数而不是让 `DesktopApp` 直接 new 一个 `ConsentDialog`，
    是为了让界面层能注入替身（测试里不必真的起一个 grab 住的窗口）。
    """
    dialog = ConsentDialog(parent, theme)
    parent.wait_window(dialog)
    return dialog.accepted


__all__ = [
    "CONSENT_VERSION",
    "ConsentDialog",
    "RISK_POINTS",
    "SETUP_POINTS",
    "clear_consent",
    "consent_path",
    "has_consent",
    "prompt_consent",
    "record_consent",
]
