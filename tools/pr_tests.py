"""在 CI 的 PR 合并检出上选择业务回归。未确认消费者的变更走完整 pytest 收集。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import PurePosixPath

from auto_game_unified.tools import check


# 这些回放目录只由对应的路线测试读取。新增范围需先核查消费者。
REPLAY_FOLDERS = {"epic7_pet_adoption", "epic7_penguin_purchase", "epic7_craft_equipment"}
REPLAY_TESTS = {
    "tests/test_pet_adoption.py", "tests/test_penguin_purchase.py",
    "tests/test_epic7_penguin_purchase.py", "tests/test_epic7_craft_equipment.py",
}


def plan_pr(files: list[str]) -> tuple[list[str] | None, str]:
    """返回测试文件名和选择理由。None 要求全量。"""
    if not files:
        return None, "合并差异为空"
    for name in files:
        path = PurePosixPath(name)
        if check.bounded_behavior_tests(name) and (check.PACKAGE_DIR / name).is_file():
            continue
        if check.is_project_doc(name):
            continue
        if (path.parent.as_posix() + "/" == check.HERO_ROSTER_PREFIX
                and (path.suffix == ".png" or path.name == "meta.json")):
            continue
        if (len(path.parts) == 4 and path.parts[:2] == ("tests", "fixtures")
                and path.parts[2] in REPLAY_FOLDERS and path.suffix == ".png"):
            continue
        if name in REPLAY_TESTS and (check.PACKAGE_DIR / name).is_file():
            continue
        return None, f"{name} 超出定向验收范围"
    suite = sorted(path.name for path in (check.PACKAGE_DIR / "tests").glob("test_*.py"))
    picked, reason, warnings = check.plan_tests(files, suite)
    if warnings or not picked:
        return None, "；".join(warnings) or "没有选中测试"
    return picked, reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="PR 合并检出的目标分支父提交")
    parser.add_argument("--plan", action="store_true", help="仅预览范围")
    args = parser.parse_args()
    try:
        files = check.git(args.base, "HEAD")
        picked, reason = plan_pr(files)
    except (RuntimeError, OSError) as error:
        picked, reason = None, f"无法确定差异。{error}"
    suite = f"{check.PACKAGE}/tests"
    targets = [f"{suite}/{name}" for name in picked] if picked else [suite]
    print(f"[PR] {'定向' if picked else '全量'}：{reason}", flush=True)
    print("[PR] pytest " + " ".join(targets), flush=True)
    if args.plan:
        return 0
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--durations=10", *targets], cwd=check.WORKSPACE
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
