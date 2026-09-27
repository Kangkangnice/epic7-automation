"""Chinese interactive launcher for the existing Epic Seven modes."""

from collections.abc import Callable

from auto_game_unified import main as main_module
from auto_game_unified.games.epic7.daily_tasks import DAILY_TASKS
from auto_game_unified.games.epic7.modes import MODE_SPECS, get_mode


# 「每日任务」在菜单里的标识。它没有对应的 MODE_SPECS 条目，所以用一个
# 不可能跟模式名撞车的值；`run_interactive` 见到它就切到 --daily 分支。
DAILY_MENU_ID = "__daily__"

DAILY_LABEL = "每日任务"

# 每日任务那条菜单项里列的路线次序 —— 从 ``DAILY_TASKS`` 派生，与执行次序同源。
_DAILY_ORDER = " → ".join(get_mode(task.mode).label for task in DAILY_TASKS)


def _menu_label(mode: str) -> str:
    """菜单上显示的名字。每日任务不是路线，单独给一个常量。"""
    return DAILY_LABEL if mode == DAILY_MENU_ID else MODE_SPECS[mode].label


# 菜单：**编号、次序、以及每项后面的括号说明**是本模块自己的交互设计
# （用户已经习惯了这套编号，别按别处的顺序重排）；**中文名不写在这儿**，
# 从 ``modes.MODE_SPECS`` 取（那边是唯一来源）。
#
# 每日任务那行列的路线清单也是派生的 —— 它曾经手抄成
# 「世界首领战 → 骑士团捐赠 → 竞技场」，漏了后来加进去的两条。
_MENU_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("1", "story", ""),
    ("2", "arena", ""),
    ("3", "expedition", ""),
    ("4", "fodder", "（特别的时间之书 3-7）"),
    ("5", "hero_synthesis", "（三星刻印合成，跑完一遍列表自动结束）"),
    ("6", "shop_refresh", "（实验功能，只支持模拟器）"),
    ("7", "world_boss", "（骑士团每日任务，每场 20 体力，不够自动用树叶买）"),
    (
        "8",
        "knights_donation",
        "（骑士团每日捐赠，请求支援 + 支援团员 + 每周任务，跑一遍结束）",
    ),
    (
        "9",
        "labyrinth_stone",
        "（迷宫每日采购：传送到流浪商人，商店只买强化石，跑一遍结束）",
    ),
    ("10", DAILY_MENU_ID, f"（{_DAILY_ORDER}，依次跑完；每步自动回首页）"),
)

MENU_OPTIONS = {key: (_menu_label(mode), mode) for key, mode, _ in _MENU_ITEMS}

MENU_LINES = (
    "请选择功能：",
    *(f"{key}. {_menu_label(mode)}{note}" for key, mode, note in _MENU_ITEMS),
)


# 运行平台选择：模拟器（LDPlayer）与 PC 客户端共用同一套业务代码与模板资产，
# 仅窗口捕获/输入后端不同。模拟器为默认，PC 为新接入后端。
BACKEND_OPTIONS = {
    "1": ("模拟器（LDPlayer）", "emulator"),
    "2": ("PC 客户端", "pc"),
}


def run_interactive(
    *,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    run_main: Callable[[list[str]], int] | None = None,
) -> int:
    output("请选择运行平台：")
    for key, (label, _) in BACKEND_OPTIONS.items():
        output(f"{key}. {label}")
    while True:
        backend_choice = input_fn("请输入平台编号：").strip()
        if backend_choice in BACKEND_OPTIONS:
            break
        output("请输入 1 或 2 选择运行平台。")
    _, window_backend = BACKEND_OPTIONS[backend_choice]

    for line in MENU_LINES:
        output(line)

    while True:
        selected = input_fn("请输入功能编号：").strip()
        if selected in MENU_OPTIONS:
            break
        output("请输入 1 到 10 之间的功能编号。")

    label, mode = MENU_OPTIONS[selected]
    if mode == DAILY_MENU_ID:
        # 每日任务是一个编排入口：次数由各条路线自己的每日默认值决定（见
        # games/epic7/daily_tasks.py），菜单上不问用户；勾选在桌面助手里做，
        # 命令行这里一律按「全跑」。
        output(f"即将运行：{label}（平台={BACKEND_OPTIONS[backend_choice][0]}）")
        output("按 P 可随时停止。")
        entry = run_main or main_module.main
        return entry(
            [
                "--daily",
                "--window-backend",
                window_backend,
                "--live",
                "--confirm",
                "RUN",
            ]
        )
    # 次数由游戏规则决定的路线（``cycles_editable=False``）直接采用默认值、
    # 不问用户；其余路线让用户填。次数只在 ``modes.MODE_SPECS`` 里定义一次。
    # （以前这里是三条写死的 ``if mode == ...`` 分支，与 main.py / catalog.py
    # 三处手工对齐，改漏了没人知道。）
    spec = get_mode(mode)
    if not spec.cycles_editable:
        cycles = spec.default_cycles
    else:
        while True:
            raw_cycles = input_fn("请输入运行次数：").strip()
            try:
                cycles = int(raw_cycles)
            except ValueError:
                cycles = 0
            if cycles > 0:
                break
            output("运行次数必须是正整数。")

    output(f"即将运行：{label}（平台={BACKEND_OPTIONS[backend_choice][0]}），共 {cycles} 次")
    output("按 P 可随时停止。")
    entry = run_main or main_module.main
    return entry(
        [
            "--mode",
            mode,
            "--window-backend",
            window_backend,
            "--max-cycles",
            str(cycles),
            "--live",
            "--confirm",
            "RUN",
        ]
    )


def main() -> int:
    return run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
