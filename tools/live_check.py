"""实机验证前置自检：权限对不对、窗口抓不抓得到、下一步该跑什么。

用法（在**工作区根**执行）：:

    python -m auto_game_unified.tools.live_check              # 两个后端都查
    python -m auto_game_unified.tools.live_check --backend pc # 只查 PC 客户端

为什么需要它
------------
「上一次教过你怎么控制鼠标，这次又忘了」这类重复提问，根子不是记性差，是**知识没有可执行的入口**。
提权这件事尤其典型：没提权时截图和识别全都正常，日志里每个动作都说「已点击」，游戏却一动不动 ——
看起来像模板过期、像坐标算错，实际是 Windows 的 UIPI 把输入静默拦掉了。

与其写一段说明让人记住，不如给一条命令；这条命令跑完就知道结论和下一步。

它只做**只读**检查：不点击、不改窗口、不启动任何自动化。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from auto_game_unified.core import elevation
from auto_game_unified.desktop import preflight


@dataclass
class CheckResult:
    backend: str
    status: str
    message: str


def _describe_elevation() -> tuple[bool, str]:
    """当前进程是否提权，以及一句人话。"""
    elevated = elevation.current_process_elevated()
    if elevated is True:
        return True, "当前进程**已提权**（管理员）。PC 客户端需要这一档。"
    if elevated is False:
        return False, (
            "当前进程**未提权**。模拟器后端可以跑；"
            "PC 客户端要求管理员，没提权会表现成「点不动但截图正常」。"
        )
    return False, "查不到当前进程的提权状态（不是 Windows，或令牌读取被拒）。"


def run_check(backend: str) -> CheckResult:
    try:
        report = preflight.run_preflight(window_backend=backend)
    except Exception as error:  # 窗口没开、游戏没启动，都会走到这里
        return CheckResult(backend, "ERROR", f"{type(error).__name__}: {error}")
    return CheckResult(backend, str(report.status), report.message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="实机验证前置自检（只读，不点击）")
    parser.add_argument(
        "--backend",
        choices=("pc", "emulator", "both"),
        default="both",
        help="查哪个后端（默认两个都查）",
    )
    args = parser.parse_args(argv)

    elevated, note = _describe_elevation()
    print(f"【权限】{note}")
    print()

    backends = ("pc", "emulator") if args.backend == "both" else (args.backend,)
    results = [run_check(name) for name in backends]

    for result in results:
        mark = "OK  " if result.status.upper().startswith("OK") else "FAIL"
        print(f"【{result.backend}】{mark} {result.status}: {result.message}")

    print()
    usable = [r for r in results if r.status.upper().startswith("OK")]
    if not usable:
        print("结论：两个后端都还没就绪。先把游戏/模拟器开到目标页面，再跑一次。")
        return 1

    names = "、".join(r.backend for r in usable)
    if "pc" in [r.backend for r in usable] and not elevated:
        print(
            "结论：PC 后端窗口能抓到，但你**没提权**。\n"
            "      只采模板/只读验证可以接着做；要让它真的点击，先用管理员终端重开。\n"
            "      提权方式：右键 Windows Terminal / PowerShell → 「以管理员身份运行」，再执行同一条命令。"
        )
        return 0

    print(f"结论：{names} 就绪，可以跑实机了。具体命令见 docs/maintenance/live_verification.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
