"""一条命令出免安装版：清理 -> PyInstaller -> 冒烟自检 -> 打 ZIP -> 记 SHA256。

用法（在仓库目录执行）::

    python packaging/build.py               # 全流程（只出免安装版）
    python packaging/build.py --installer   # 额外再编一个 Inno Setup 安装包
    python packaging/build.py --skip-smoke  # 只打包，不跑自检（调试打包问题时用）
    python packaging/build.py --no-build    # 复用已有 dist，只重打 ZIP（改文件名/清单时用）

产物都在 ``packaging/dist/``：

    Epic7AutoAssistant/                       目录版（双击里面的 exe 即用）
    第七史诗自动助手-免安装版-<版本>.zip      整个目录打成压缩包
    SHA256SUMS.txt                            上面那个 zip 的校验值

## 为什么只发免安装版

2026-10-20 用户拍板：**只保留免安装版**。安装包（Inno Setup）体积更小（62.5 MB），
但它只是「把同一个目录解到 %LOCALAPPDATA%\\Programs 并建快捷方式」，
用户多走一道向导、我们还多维护一份 ``installer.iss`` 和简体中文语言包。
给普通玩家一个「解压 → 双击 exe」就够了，所以 ``--installer`` 变成显式开关。

## 为什么冒烟要跑 ``--self-check`` 而不是「启动 GUI 看它有没有崩」

窗口起不起来没法自动判定，而自检覆盖了真正会坏的三件事 ——
运行产物目录能不能写、模板在不在、十五条路线的模板能不能全部加载。
另有一条 ``check_pruned_binaries`` 守着「spec 里剔掉的 videoio ffmpeg 真的没进产物」
（那两个 DLL 原始 51.9 MB，是免安装版从 88 MB 降到 63 MB 的全部来源）。
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
INSTALLER = PACKAGING / "installer.iss"
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


#: spec 里被剔掉的那一类二进制（见 ``epic7_auto_assistant.spec`` 的同名前缀说明）。
#: 打包完必须**一个都不在**产物里 —— 它们在就等于白丢 24.7 MB 的压缩体积。
PRUNED_BINARY_PREFIX = "opencv_videoio_ffmpeg"


def check_pruned_binaries() -> None:
    """确认 spec 剔掉的 videoio ffmpeg DLL 真的没进产物。

    ⚠️ 这条不是形式主义：那两个 DLL 是 PyInstaller 按「整个 cv2 目录」收集时
    顺带拖进来的，**升级 opencv 或改 spec 顺序都可能让它们悄悄回来**，
    而现象只是「免安装版忽然胖了 25 MB」，没有任何报错。
    """
    leaked = [
        item
        for item in (DIST / APP_NAME).rglob(f"*{PRUNED_BINARY_PREFIX}*")
        if item.is_file()
    ]
    if leaked:
        names = ", ".join(item.name for item in leaked)
        raise SystemExit(
            f"产物里混进了本应剔除的 videoio ffmpeg 后端：{names}\n"
            "检查 packaging/epic7_auto_assistant.spec 里对 a.binaries 的过滤。"
        )
    print(f"[build] 已确认剔除 {PRUNED_BINARY_PREFIX}*", flush=True)


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def make_zip(version: str) -> Path:
    """打免安装版 ZIP。

    ⚠️ 用 **DEFLATE** 不是为了省事：换 ``ZIP_LZMA`` 能再小 18 MB（63 → 45），
    但 **Windows 资源管理器自带的「全部解压缩」不认 LZMA 的 zip**，
    用户得先装 7-Zip —— 那就不是「解压即用」了。2026-10-20 实测过两种压缩率。
    """
    archive = DIST / f"第七史诗自动助手-免安装版-{version}.zip"
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


def find_iscc() -> Path | None:
    """找 Inno Setup 的命令行编译器。用户级安装优先（不需要管理员）。"""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_installer(version: str) -> Path | None:
    """出安装包。**只有显式传 ``--installer`` 才编**（2026-10-20 起默认不要）。

    没装 Inno Setup 6 就跳过 —— 免安装版本来就不依赖它。
    """
    iscc = find_iscc()
    if iscc is None:
        print("[build] 没装 Inno Setup 6，跳过安装包（免安装版不受影响）", flush=True)
        return None
    print(f"[build] 安装包：{iscc}", flush=True)
    subprocess.run(
        [str(iscc), f"/DMyAppVersion={version}", str(INSTALLER)],
        cwd=REPO,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    archive = DIST / f"第七史诗自动助手-安装版-{version}.exe"
    if not archive.is_file():
        raise SystemExit(f"ISCC 返回成功但找不到安装包：{archive}")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="构建第七史诗自动助手免安装版")
    parser.add_argument("--no-build", action="store_true", help="复用已有 dist，只重打包")
    parser.add_argument("--skip-smoke", action="store_true", help="跳过 exe 自检")
    parser.add_argument(
        "--installer",
        action="store_true",
        help="额外编 Inno Setup 安装包（默认不编，只出免安装版）",
    )
    args = parser.parse_args()

    version = product_version()
    print(f"[build] 版本 {version}", flush=True)

    exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    if not args.no_build:
        exe = run_pyinstaller()
        # 先确认剔掉的东西真没进产物，再花时间跑自检 —— 顺序反了会白跑一遍。
        check_pruned_binaries()
        if not args.skip_smoke:
            smoke_test(exe)

    if not exe.is_file():
        raise SystemExit(f"没有可打包的产物：{exe}")

    archive = make_zip(version)
    installer = build_installer(version) if args.installer else None

    artifacts = [archive] + ([installer] if installer is not None else [])
    (DIST / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in artifacts),
        encoding="utf-8",
    )

    print("")
    print(f"[build] 目录版：{DIST / APP_NAME}  ({directory_size(DIST / APP_NAME) / 2**20:.1f} MB)")
    print(f"[build] 免安装版：{archive.name}  ({archive.stat().st_size / 2**20:.1f} MB)")
    if installer is not None:
        print(f"[build] 安装版：{installer.name}  ({installer.stat().st_size / 2**20:.1f} MB)")
    for path in artifacts:
        print(f"[build] SHA256 {path.name}：{sha256(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
