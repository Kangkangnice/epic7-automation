"""Read-only capture of the page the user has parked the emulator on.

保存完整 fixture 到 tests/fixtures/<group>/<name>.png，可选连续多帧并报告
帧间平均差，供 AI 程序化确认页面是否静止（AI 不读图，只看数值）。
"""

from argparse import ArgumentParser
from pathlib import Path
import sys
from time import sleep

import cv2

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from auto_game_unified.core.window import Epic7Window


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _parser() -> ArgumentParser:
    parser = ArgumentParser(description="只读截取当前游戏窗口并保存 fixture")
    parser.add_argument("name", help="保存的文件名（不含扩展名）")
    parser.add_argument(
        "--group",
        default="epic7_shop_refresh",
        help="tests/fixtures 下的子目录名",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="连续截取帧数，用于判断页面是否静止",
    )
    parser.add_argument("--interval", type=float, default=0.6, help="多帧间隔秒数")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    window = Epic7Window()
    frames = []
    for index in range(max(1, args.repeat)):
        frames.append(window.capture())
        if index + 1 < args.repeat:
            sleep(args.interval)

    directory = FIXTURE_ROOT / args.group
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{args.name}.png"
    if not cv2.imwrite(str(path), cv2.cvtColor(frames[-1], cv2.COLOR_RGB2BGR)):
        raise OSError(f"无法写入 fixture: {path}")

    print(f"已保存 {path} 画布={frames[-1].shape[1]}x{frames[-1].shape[0]}")
    for index in range(1, len(frames)):
        difference = cv2.absdiff(frames[index - 1], frames[index])
        print(
            f"帧差 f{index}->f{index + 1} 平均={float(difference.mean()):.3f} "
            f"最大={int(difference.max())}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
