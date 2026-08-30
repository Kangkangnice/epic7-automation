"""Chinese interactive launcher for the existing Epic Seven modes."""

from collections.abc import Callable

from auto_game_unified import main as main_module


MENU_OPTIONS = {
    "1": ("主线", "story"),
    "2": ("竞技场", "arena"),
    "3": ("远征", "expedition"),
    "4": ("狗粮", "fodder"),
    "5": ("辅助自动", "assist_auto"),
    "6": ("英雄合成", "hero_synthesis"),
    "7": ("刷书签", "shop_refresh"),
}

MENU_LINES = (
    "请选择功能：",
    "1. 主线",
    "2. 竞技场",
    "3. 远征",
    "4. 狗粮（特别的时间之书 3-7）",
    "5. 辅助自动（自动重复战斗）",
    "6. 英雄合成（三星刻印合成，跑完一遍列表自动结束）",
    "7. 刷书签（实验功能，只支持模拟器）",
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
        output("请输入 1 到 7 之间的功能编号。")

    label, mode = MENU_OPTIONS[selected]
    if mode == "hero_synthesis":
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
