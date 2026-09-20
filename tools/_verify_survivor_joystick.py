"""由用户运行：验证局内移动方式——靠连续短滑动累积位移。

用户实测结论（2026-09-16，推翻了之前「必须按住摇杆」的假设）：adb 的 `input swipe`
结束时必然松手，但**不需要一直按住**——每滑一次角色就前进一段，松手后还在继续走，
再滑又前进一段。所以靠「重复滑动」就能持续移动，「保持按下」这个难题根本不用解。

本脚本跑的就是正式 Runner 用的那份移动方案（`games/epic7/survivor.py` 的 `movement_steps`），
免得测试和正式跑两处定义漂移：上右下左各连滑 **3~8 次随机**（`MOVE_REPEATS_RANGE`，每次运行重掷一次），
距离 630px / 时长 700ms。

几何以屏幕正中央为中心摆放，两端都落在渲染区内（`Epic7Window.swipe` 会越界拒绝并抛错）。

滑动期间用相位相关测战场背景的整体平移量，客观确认角色真的在动
（标定：人工平移 30px→测出 30.02、8px→7.99、不动→0.0、无关页互比→0.21）。

用法（先停在局内战斗画面）：
    python -m auto_game_unified.tools._verify_survivor_joystick
    python -m auto_game_unified.tools._verify_survivor_joystick --dry-run
"""

from argparse import ArgumentParser
from pathlib import Path
import sys
import threading
from time import perf_counter, sleep

import cv2
import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from auto_game_unified.core.window import Epic7Window
from auto_game_unified.games.epic7.survivor import (
    CANVAS_CENTER,
    MOVE_DISTANCE,
    MOVE_DURATION_MS,
    SurvivorRunner,
    movement_steps,
)

# 两次滑动之间的空等现在挂在 Runner 上（`_MOVE_STEP_GAP_SECONDS`），这里读同一份。
MOVE_STEP_GAP_SECONDS = SurvivorRunner._MOVE_STEP_GAP_SECONDS


LEGACY_TOP = 52

# 只取画面中部的战场区域做平移估算，避开上下两侧的 HUD 文字与按钮。
_FIELD = (slice(200, 900), slice(100, 1800))


def _shift(previous: np.ndarray, current: np.ndarray) -> float:
    """估算两帧战场区域的整体平移量（像素）。"""

    before = previous[_FIELD]
    after = current[_FIELD]
    if float(np.mean(np.abs(before.astype(np.int16) - after.astype(np.int16)))) < 2.0:
        return 0.0
    (dx, dy), _ = cv2.phaseCorrelate(np.float32(before), np.float32(after))
    return float((dx * dx + dy * dy) ** 0.5)


class _MotionSampler:
    """滑动期间后台连续抓帧，用整体平移量判断镜头有没有在滚动。"""

    def __init__(self, game: Epic7Window, interval: float) -> None:
        self._game = game
        self._interval = interval
        self._frames: list[np.ndarray] = []
        self._failure = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self) -> "_MotionSampler":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._game.capture()
                self._frames.append(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY))
            except Exception as error:  # 抓帧失败不该打断实测，退化成肉眼判断
                self._failure = str(error)
                return
            self._stop.wait(self._interval)

    def report(self) -> None:
        if self._failure:
            print(f"  [抓帧失败，只能靠肉眼判断] {self._failure}")
            return
        if len(self._frames) < 2:
            print("  [抓帧不足，只能靠肉眼判断]")
            return
        shifts = [
            _shift(self._frames[index - 1], self._frames[index])
            for index in range(1, len(self._frames))
        ]
        median = sorted(shifts)[len(shifts) // 2]
        print(f"  抓帧 {len(self._frames)} 张，逐帧平移量(px)="
              f"{[round(value, 1) for value in shifts]}")
        print(f"  平移量中位数={median:.1f}px  → 明显大于 0 = 镜头在跟角色滚动")


class _NullSampler:
    def __enter__(self) -> "_NullSampler":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def report(self) -> None:
        return None


def _sampler(args: ArgumentParser, game: Epic7Window):
    if args.no_sample:
        return _NullSampler()
    return _MotionSampler(game, interval=0.4)


def _render(point: tuple[int, int]) -> tuple[int, int]:
    return point[0], point[1] - LEGACY_TOP


def _parser() -> ArgumentParser:
    parser = ArgumentParser(description="验证局内靠连续短滑动累积位移的移动方式")
    parser.add_argument("--cycles", type=int, default=2, help="跑几轮移动步骤")
    parser.add_argument("--no-sample", action="store_true", help="关闭抓帧量化")
    parser.add_argument("--dry-run", action="store_true", help="只打印坐标，不发任何输入")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    steps = movement_steps()
    total = args.cycles * len(steps)

    print(f"屏幕正中央={CANVAS_CENTER}（渲染 {_render(CANVAS_CENTER)}）")
    print(f"滑动距离={MOVE_DISTANCE}px 时长={MOVE_DURATION_MS}ms "
          f"停顿={MOVE_STEP_GAP_SECONDS}s")
    print(f"计划：{args.cycles} 轮 × {len(steps)} 步 = {total} 次滑动")
    print("一步的坐标：")
    for step in steps:
        print(f"  {step.name}：画布 {step.start}->{step.end}  "
              f"渲染 {_render(step.start)}->{_render(step.end)}")
    print()

    if args.dry_run:
        print("干跑，未发送任何输入。")
        return 0

    game = Epic7Window()
    sent = 0
    slowest = 0.0
    with _sampler(args, game) as sampler:
        for cycle in range(1, args.cycles + 1):
            print(f"—— 第 {cycle}/{args.cycles} 轮 ——")
            for step in steps:
                started = perf_counter()
                game.swipe(step.start, step.end, MOVE_DURATION_MS)
                elapsed = perf_counter() - started
                sent += 1
                slowest = max(slowest, elapsed)
                print(f"  {step.name} 耗时={elapsed:.2f}s")
                sleep(MOVE_STEP_GAP_SECONDS)
    print()
    print(f"共发 {sent} 次滑动，单次最慢={slowest:.2f}s（含 {MOVE_DURATION_MS}ms 滑动本身）")
    sampler.report()
    print()
    print("请反馈：角色有没有绕圈跑？是连续前进还是只抖一下？")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
