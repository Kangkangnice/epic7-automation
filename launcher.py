"""Chinese interactive launcher for the existing Epic Seven modes."""

from collections.abc import Callable

from auto_game_unified import main as main_module


# 「每日任务」在菜单里的标识。它没有对应的 MODE_SPECS 条目，所以用一个
# 不可能跟模式名撞车的值；`run_interactive` 见到它就切到 --daily 分支。
DAILY_MENU_ID = "__daily__"

MENU_OPTIONS = {
    "1": ("主线", "story"),
    "2": ("竞技场", "arena"),
    "3": ("远征", "expedition"),
    "4": ("狗粮", "fodder"),
    "5": ("英雄合成", "hero_synthesis"),
    "6": ("刷书签", "shop_refresh"),
    "7": ("世界首领战", "world_boss"),
    "8": ("骑士团捐赠", "knights_donation"),
    # 每日任务不是单条路线，是一个编排入口（见 games/epic7/daily_tasks.py）。
    "10": ("每日任务", DAILY_MENU_ID),
}

MENU_LINES = (
    "请选择功能：",
    "1. 主线",
    "2. 竞技场",
    "3. 远征",
    "4. 狗粮（特别的时间之书 3-7）",
    "5. 英雄合成（三星刻印合成，跑完一遍列表自动结束）",
    "6. 刷书签（实验功能，只支持模拟器）",
    "7. 世界首领战（骑士团每日任务，每场 20 体力，不够自动用树叶买）",
    "8. 骑士团捐赠（骑士团每日捐赠，请求支援 + 支援团员 + 每周任务，跑一遍结束）",
    "10. 每日任务（世界首领战 → 骑士团捐赠 → 竞技场，依次跑完；每步自动回首页）",
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
    if mode == "hero_synthesis":
        cycles = 1
    elif mode == "world_boss":
        # 每天固定 2 次（游戏主页「剩余/上限」就是 2），不给用户选。
        # 与 desktop/catalog.py 的 default_cycles / main.py 的兜底保持一致。
        cycles = 2
    elif mode == "knights_donation":
        # 每天跑一遍就够（请求支援一天只能发一次），不给用户选。
        # 同上，与 desktop/catalog.py / main.py 三处保持一致。
        cycles = 1
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
