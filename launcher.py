"""Chinese interactive launcher for the existing Epic Seven modes."""

from collections.abc import Callable

from auto_game_unified import main as main_module


MENU_OPTIONS = {
    "1": ("主线", "story"),
    "2": ("竞技场", "arena"),
    "3": ("远征", "expedition"),
    "4": ("狗粮", "fodder"),
}

MENU_LINES = (
    "请选择功能：",
    "1. 主线",
    "2. 竞技场",
    "3. 远征",
    "4. 狗粮（特别的时间之书 3-7）",
)


def run_interactive(
    *,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    run_main: Callable[[list[str]], int] | None = None,
) -> int:
    for line in MENU_LINES:
        output(line)

    while True:
        selected = input_fn("请输入功能编号：").strip()
        if selected in MENU_OPTIONS:
            break
        output("请输入 1 到 4 之间的功能编号。")

    while True:
        raw_cycles = input_fn("请输入运行次数：").strip()
        try:
            cycles = int(raw_cycles)
        except ValueError:
            cycles = 0
        if cycles > 0:
            break
        output("运行次数必须是正整数。")

    label, mode = MENU_OPTIONS[selected]
    output(f"即将运行：{label}，共 {cycles} 次")
    output("按 P 可随时停止。")
    entry = run_main or main_module.main
    return entry(
        [
            "--mode",
            mode,
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
