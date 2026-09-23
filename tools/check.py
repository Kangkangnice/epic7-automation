"""项目提交前检查：把「验证门槛」从文档约定变成机器执行。

门槛（与 docs/RESUME_COVERAGE.md 及项目约定一致，按改动范围决定跑多少）：
- **只改文档**：只做编译检查，不跑测试。
- **只改某条路线内部**（`games/epic7/<route>.py`、`evidence/<route>.py`）：
  编译检查 + 该路线的测试（按文件名关键词匹配）。
- **改了测试或夹具/模板**：跑改动到的测试文件，夹具/模板另外带上
  `test_project_layout.py`（它断言各路线夹具的精确文件集）。
- **改了共享模块**（`core/**`、`desktop/**`、`runner_base`、`navigation`、`modes`、
  `battle_controls`、`pre_battle`、`unknown_screen`、`global_popups`、`stamina`、
  `hero_transition`、`evidence/common`、`main.py`、`launcher.py`）或**认不出归属**：跑全量。
- **只改 `tools/`、`.github/`**：只做编译检查（这些没有测试覆盖）。

用法（在仓库根 `auto_game_unified` 下执行）：
    python tools/check.py                # 按 git 暂存区（pre-commit 钩子用这个）
    python tools/check.py --vs HEAD      # 按工作区相对 HEAD 的改动
    python tools/check.py --since origin/main
    python tools/check.py --files a.py b.py
    python tools/check.py --full         # 强制全量
    python tools/check.py --install-hook # 装上 pre-commit 钩子（每 clone 一次）

装上钩子后，每次 `git commit` 都会自动跑本检查；`git commit --no-verify` 可跳过。

fail-closed：认不出改了哪条路线、或该路线一个测试文件都匹配不到，一律退化成全量，
绝不用「没测到」冒充「没问题」。

本机会自动找一个真的装了 pytest 的解释器来跑测试（PATH 上的 `python` 可能没有依赖，
那样钩子会安静退化成只做编译检查 —— 看着跑了其实没验）。可用环境变量
`AUTO_GAME_PYTHON` 覆盖。确实找不到时只做编译检查并**大声警告**（不阻塞提交），
退出码仍为 0；真正的测试失败才会返回非 0。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PASSED_RE = re.compile(r"\d+ passed")
FAILED_RE = re.compile(r"\d+ (failed|error)")

PACKAGE_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = PACKAGE_DIR.parent
PACKAGE = PACKAGE_DIR.name

# 改动这些就等于动了所有路线 -> 必须跑全量
SHARED_PATHS = {
    "main.py",
    "launcher.py",
    "games/epic7/runner_base.py",
    "games/epic7/modes.py",
    "games/epic7/navigation.py",
    "games/epic7/battle_controls.py",
    "games/epic7/pre_battle.py",
    "games/epic7/unknown_screen.py",
    "games/epic7/global_popups.py",
    "games/epic7/stamina.py",
    "games/epic7/hero_transition.py",
    "games/epic7/evidence/common.py",
}
SHARED_PREFIXES = ("core/", "desktop/")

# 这些目录的改动不参与路线判定：既不是路线代码，也没有测试覆盖它们。
# 只要本次改动全在这里 + 文档，就只做编译检查。
NO_TEST_PREFIXES = ("tools/", ".github/", "docs/", "tests/")

# 路线模块 -> 在 tests 文件名里找的关键词
ROUTE_KEYWORDS = {
    "story": "story",
    "arena": "arena",
    "expedition": "expedition",
    "fodder": "fodder",
    "hero": "hero",
    "hero_synthesis": "hero",
    "shop_refresh": "shop_refresh",
    "survivor": "survivor",
}

DOC_SUFFIXES = (".md", ".txt", ".json", ".yaml", ".yml")
ASSET_PREFIXES = ("tests/fixtures/", "games/epic7/templates/", "docs/manual_review/")
LAYOUT_TEST = "test_project_layout.py"


def git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=PACKAGE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def normalise(path: str) -> str:
    """把路径统一成「相对仓库根」。

    git 输出与钩子给的都是相对根（`core/window.py`），但手工敲 `--files` 时
    常带上包名（`auto_game_unified/core/window.py`）或反斜杠，两种都认。
    """
    cleaned = path.strip().replace("\\", "/").lstrip("./")
    if cleaned.startswith(PACKAGE + "/"):
        cleaned = cleaned[len(PACKAGE) + 1 :]
    return cleaned


def changed_files(args: argparse.Namespace) -> list[str]:
    if args.files:
        return [normalise(path) for path in args.files]
    if args.since:
        return git("diff", "--name-only", f"{args.since}...HEAD")
    if args.vs:
        return git("diff", "--name-only", args.vs)
    staged = git("diff", "--cached", "--name-only")
    if staged:
        return staged
    return git("diff", "--name-only", "HEAD")


def route_of(path: str) -> str | None:
    """把改动文件映射回它属于哪条路线。认不出返回 None（-> 全量）。"""
    if not path.startswith("games/epic7/") or not path.endswith(".py"):
        return None
    return ROUTE_KEYWORDS.get(Path(path).stem)


def route_tests(routes: set[str], all_tests: list[str]) -> list[str] | None:
    """按路线关键词挑测试文件；一条路线都没匹配到返回 None（-> 全量）。"""
    selected = sorted(
        name for name in all_tests if any(route in name for route in routes)
    )
    return selected or None


def run(label: str, command: list[str]) -> int:
    print(f"[check] {label}: {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=WORKSPACE, check=False).returncode


def _has_pytest(executable: list[str]) -> bool:
    probe = subprocess.run(
        [*executable, "-c", "import pytest"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


def find_python_with_pytest() -> list[str] | None:
    """找一个真的装了 pytest 的解释器。

    本机踩过的坑：PATH 上的 `python` 是托管的 3.13（没装依赖），
    于是一个「装好了的」pre-commit 钩子会安静地退化成只做编译检查 ——
    看着跑了，其实没验。所以这里主动去找带 pytest 的那个。
    """
    candidates: list[list[str]] = []
    override = os.environ.get("AUTO_GAME_PYTHON")
    if override:
        candidates.append([override])
    candidates.append([sys.executable])
    candidates.append(["python"])
    candidates.append(["py", "-3"])
    # 常见安装位置兜底（同一台机器上装了多个解释器很常见）
    if os.name == "nt":
        candidates.append([r"D:\anaconda\python.exe"])
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append([os.path.join(local, "Programs", "Python", "Python311", "python.exe")])
    seen: set[str] = set()
    for candidate in candidates:
        key = " ".join(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            if _has_pytest(candidate):
                return candidate
        except OSError:
            continue
    return None


def run_tests(targets: list[str], interpreter: list[str]) -> int:
    """跑 pytest，并按「结果行」而不是单看退出码判定成败。

    本机有个已知干扰：pytest 结束时清理临时目录会撞上 safe-delete 守卫，
    以致 `SystemExit: 1` —— 退出码非 0 但测试其实是全绿的。
    钩子里误拦提交比漏测更烦人，所以这里以结果行为准，并把判断依据打印出来。

    另外**必须显式指定 `--basetemp`**：不给时 pytest 用自己的默认临时目录，清空动作
    同样会撞守卫。给一个**仓库内、名字固定、每次都复用**的目录即可 ——
    pytest 正常退出时会把 basetemp **清空**（实测跑完 0 残留），所以下次进来它本来就是空的，
    不会触发「清空已有目录」这一步，也就不会在**用例收集阶段**炸掉
    （2026-09-22 踩过：basetemp 给了相对路径、落到工作区根、攒了几十项，
    pytest 一清空就触发守卫，表现成 37 个 `ERROR at setup`，看起来像大面积回归）。

    ⚠️ 两个别用的替代方案：
    - **先删再建**：safe-delete 垫片 fail-closed，`shutil.rmtree` 大量文件会抛 `OSError`，
      旧目录还在 ⇒ pytest 又去清它 ⇒ 白绕一圈。
    - **每次生成唯一目录名**（带 pid/时间戳）：会不断堆积垃圾（实测每次全量留 56 个文件）。
    """
    basetemp = PACKAGE_DIR / "runtime_logs" / "_basetemp"
    basetemp.mkdir(parents=True, exist_ok=True)
    command = [
        *interpreter,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp={basetemp}",
        *targets,
    ]
    print(f"[check] 测试: {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=WORKSPACE, capture_output=True, text=True)
    print(result.stdout, end="")
    if result.stderr.strip():
        print(result.stderr, end="")
    if result.returncode == 0:
        return 0
    if PASSED_RE.search(result.stdout) and not FAILED_RE.search(result.stdout):
        print(
            f"[check] pytest 退出码 {result.returncode}，但结果行没有 failed/error —— "
            "按已知的临时目录清理守卫误报处理，判为通过"
        )
        return 0
    return result.returncode


def install_hook() -> int:
    """把仓库的 core.hooksPath 指向 tools/githooks。

    只改本地配置，不写系统目录；每个 clone 各执行一次。
    """
    result = subprocess.run(
        ["git", "config", "core.hooksPath", "tools/githooks"],
        cwd=PACKAGE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"[check] 安装失败：{result.stderr.strip() or result.stdout.strip()}")
        return result.returncode
    print("[check] 已把 core.hooksPath 设为 tools/githooks，之后提交会自动跑本检查")
    print("[check] 跳过检查：git commit --no-verify")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="提交前验证门槛")
    parser.add_argument("--full", action="store_true", help="强制跑全量")
    parser.add_argument("--files", nargs="*", default=None, help="直接指定改动文件")
    parser.add_argument("--vs", default=None, help="相对某个 revision 取改动（如 HEAD）")
    parser.add_argument("--since", default=None, help="相对某个分支取改动（三点比较）")
    parser.add_argument(
        "--skip-tests", action="store_true", help="只做编译检查（手工排查用）"
    )
    parser.add_argument(
        "--install-hook",
        action="store_true",
        help="把 core.hooksPath 指向 tools/githooks 后退出（每 clone 执行一次）",
    )
    args = parser.parse_args()

    if args.install_hook:
        return install_hook()

    files = changed_files(args)
    code_files = [
        path
        for path in files
        if path.endswith(".py") and (PACKAGE_DIR / path).exists()
    ]

    print(f"[check] 改动 {len(files)} 个文件，其中待编译的 py {len(code_files)} 个")
    for path in files[:40]:
        print(f"        {path}")
    if len(files) > 40:
        print(f"        …另有 {len(files) - 40} 个")

    compile_targets = [f"{PACKAGE}/{path}" for path in code_files] or [PACKAGE]
    status = run("编译检查", [sys.executable, "-m", "compileall", "-q", *compile_targets])
    if status != 0:
        print("[check] 编译失败，先修语法再提交")
        return status

    if args.skip_tests:
        print("[check] 按要求只做编译检查")
        return 0

    all_tests = sorted(p.name for p in (PACKAGE_DIR / "tests").glob("test_*.py"))
    all_targets = [f"{PACKAGE}/tests/{name}" for name in all_tests]

    if args.full:
        targets, reason = list(all_targets), "按要求强制全量"
    else:
        changed_tests = [
            path for path in files if path.startswith("tests/") and path.endswith(".py")
        ]
        assets = [path for path in files if path.startswith(ASSET_PREFIXES)]
        routes: set[str] = set()
        full_reason: str | None = None

        for path in files:
            if path in SHARED_PATHS or path.startswith(SHARED_PREFIXES):
                full_reason = f"改了共享模块 {path}"
                break
            if path.startswith(("tests/", "docs/")) or path.startswith(
                NO_TEST_PREFIXES
            ):
                continue
            if not path.endswith(".py") or path.endswith(DOC_SUFFIXES):
                continue
            route = route_of(path)
            if route:
                routes.add(route)
            else:
                full_reason = f"认不出 {path} 属于哪条路线"
                break

        if full_reason:
            targets, reason = list(all_targets), f"{full_reason} -> 全量"
        elif not (changed_tests or assets or routes):
            print("[check] 本次改动没有测试覆盖（文档/配置/工具脚本），跳过测试")
            return 0
        else:
            picked: set[str] = {Path(path).name for path in changed_tests}
            if assets:
                picked.add(LAYOUT_TEST)
            if routes:
                matched = route_tests(routes, all_tests)
                if matched is None:
                    targets, reason = (
                        list(all_targets),
                        "改了 " + "、".join(sorted(routes)) + " 但没匹配到测试 -> 全量",
                    )
                    picked = set()
                else:
                    picked.update(matched)
            if picked:
                targets = [f"{PACKAGE}/tests/{name}" for name in sorted(picked)]
                reason = "改动范围：" + "、".join(
                    sorted([*changed_tests, *assets, *sorted(routes)])
                )
            else:
                targets, reason = list(all_targets), "无可依据的定向选择 -> 全量"

    if not targets:
        print("[check] 没有需要跑的内容")
        return 0

    interpreter = find_python_with_pytest()
    if interpreter is None:
        print(
            f"[check] 警告：本机找不到装了 pytest 的解释器，**只做了编译检查、没跑测试**"
            f"（依据：{reason}）"
        )
        print("[check] 跳过测试不等于没问题。可用 AUTO_GAME_PYTHON 指定解释器，")
        print("[check] 例如：AUTO_GAME_PYTHON=D:\\anaconda\\python.exe python tools/check.py")
        return 0

    print(f"[check] 依据：{reason}")
    print(f"[check] 测试解释器：{' '.join(interpreter)}")
    if targets != all_targets:
        print(f"[check] 选中 {len(targets)} 个测试文件（共 {len(all_tests)} 个）")
    return run_tests(targets, interpreter)


if __name__ == "__main__":
    raise SystemExit(main())
