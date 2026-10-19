"""一条命令出便携版：清理 -> PyInstaller -> 冒烟自检 -> 打 ZIP -> 记 SHA256。

用法（在仓库目录执行）::

    python packaging/build.py              # 全流程
    python packaging/build.py --skip-smoke # 只打包，不跑自检（调试打包问题时用）
    python packaging/build.py --no-build   # 复用已有 dist，只重打 ZIP（改文件名/清单时用）

产物都在 ``packaging/dist/``：

    Epic7AutoAssistant/                       目录版（双击里面的 exe 即用）
    第七史诗自动助手-便携版-<版本>.zip        整个目录打成压缩包
    SHA256SUMS.txt                            上面那个 zip 的校验值

为什么冒烟要跑 ``--self-check`` 而不是「启动 GUI 看它有没有崩」：
窗口起不起来没法自动判定，而自检覆盖了真正会坏的三件事 ——
运行产物目录能不能写、模板在不在、十五条路线的模板能不能全部加载。
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

PACKAGING = Path(__file__).resolve().parent
REPO = PACKAGING.parent
APP_NAME = "Epic7AutoAssistant"
SPEC = PACKAGING / "epic7_auto_assistant.spec"
DIST = PACKAGING / "dist"
BUILD = PACKAGING / "build"


def product_version() -> str:
    """从 catalog 里读版本号 —— 版本只有一个来源，不在打包脚本里再写一份。"""
    text = (REPO / "desktop" / "catalog.py").read_text(encoding="utf-8")
    match = re.search(r'^PRODUCT_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("desktop/catalog.py 里找不到 PRODUCT_VERSION")
    return match.group(1)


def run_pyinstaller() -> Path:
    for path in (DIST / APP_NAME, BUILD):
        if path.exists():
            shutil.rmtree(path)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        str(SPEC),
    ]
    print("[build] " + " ".join(command), flush=True)
    subprocess.run(command, cwd=REPO, check=True)

    exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    if not exe.is_file():
        raise SystemExit(f"打包结束但找不到 exe：{exe}")
    return exe


def smoke_test(exe: Path) -> None:
    """跑一次自检。产物目录指到临时目录，**不碰**本机真实的 %LOCALAPPDATA%。"""
    with tempfile.TemporaryDirectory(prefix="epic7-smoke-") as temp:
        env = dict(os.environ, EPIC7_DATA_DIR=temp)
        print("[build] 冒烟自检：exe --self-check", flush=True)
        result = subprocess.run(
            [str(exe), "--self-check"],
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
        )
        report = Path(temp) / "runtime_logs" / "self_check.txt"
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            raise SystemExit(f"自检失败，退出码 {result.returncode}")
        if not report.is_file():
            raise SystemExit(f"自检没有留下报告：{report}")
        text = report.read_text(encoding="utf-8")
        if "结果：通过" not in text:
            print(text)
            raise SystemExit("自检报告不是「通过」")
        print(text, flush=True)


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def make_zip(version: str) -> Path:
    archive = DIST / f"第七史诗自动助手-便携版-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for item in sorted((DIST / APP_NAME).rglob("*")):
            if item.is_file():
                bundle.write(item, Path(APP_NAME) / item.relative_to(DIST / APP_NAME))
    return archive


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="构建第七史诗自动助手便携版")
    parser.add_argument("--no-build", action="store_true", help="复用已有 dist，只重打 ZIP")
    parser.add_argument("--skip-smoke", action="store_true", help="跳过 exe 自检")
    args = parser.parse_args()

    version = product_version()
    print(f"[build] 版本 {version}", flush=True)

    exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    if not args.no_build:
        exe = run_pyinstaller()
        if not args.skip_smoke:
            smoke_test(exe)

    if not exe.is_file():
        raise SystemExit(f"没有可打包的产物：{exe}")

    archive = make_zip(version)
    digest = sha256(archive)
    (DIST / "SHA256SUMS.txt").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )

    print("")
    print(f"[build] 目录版：{DIST / APP_NAME}  ({directory_size(DIST / APP_NAME) / 2**20:.1f} MB)")
    print(f"[build] 便携版：{archive}  ({archive.stat().st_size / 2**20:.1f} MB)")
    print(f"[build] SHA256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
