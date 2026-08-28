"""Inspect one complete game screenshot against a route evidence profile."""

from argparse import ArgumentParser
from pathlib import Path
import sys

import cv2

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from auto_game_unified.core.evidence_diagnostics import inspect_profile
from auto_game_unified.games.epic7.evidence.arena import (
    REFERENCE_SIZE,
    build_arena_evidence,
)
from auto_game_unified.games.epic7.evidence.common import validate_profile


def _parser() -> ArgumentParser:
    parser = ArgumentParser(description="检查第七史诗路线视觉证据")
    parser.add_argument("--mode", required=True)
    parser.add_argument("--screen", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.mode != "arena":
        print(f"不支持的模式: {args.mode}")
        return 2

    root = Path(__file__).resolve().parents[1]
    template_root = root / "games" / "epic7" / "templates"
    profile = build_arena_evidence(template_root)
    errors = validate_profile(profile, template_root)
    if errors:
        for error in errors:
            print(f"配置错误: {error}")
        return 2

    screen_bgr = cv2.imread(str(args.screen), cv2.IMREAD_COLOR)
    if screen_bgr is None:
        print(f"截图不存在或无法读取: {args.screen}")
        return 2
    screen = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2RGB)
    reference_width, reference_height = REFERENCE_SIZE
    scale_x = screen.shape[1] / reference_width
    scale_y = screen.shape[0] / reference_height
    if (
        abs(scale_x - scale_y) > 0.02
        and screen.shape[1] >= reference_width
        and screen.shape[0] >= reference_height
    ):
        screen = screen[:reference_height, :reference_width]
    report = inspect_profile(screen, profile, template_root)
    for observation in report.atoms.values():
        print(
            "证据 "
            f"key={observation.key} "
            f"observed={int(observation.observed)} "
            f"score={observation.score if observation.score is not None else '-'} "
            f"threshold={observation.threshold} "
            f"center={observation.center if observation.center is not None else '-'} "
            f"template={observation.template}"
        )
    for page, state in report.pages.items():
        print(f"页面 key={page} 状态={state.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
