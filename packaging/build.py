"""一条命令出免安装版：校验第三方清单 -> PyInstaller -> 冒烟自检 -> 打 ZIP -> 记 SHA256。

用法（在仓库目录执行）::

    python packaging/build.py               # 全流程（只出免安装版）
    python packaging/build.py --installer   # 额外再编一个 Inno Setup 安装包
    python packaging/build.py --skip-smoke  # 只打包，不跑自检（调试打包问题时用）
    python packaging/build.py --no-build    # 复用已有 dist，只重打 ZIP（改文件名/清单时用）

``--without-e7auto`` 出**公开候选**：不收集次元探查的第三方代码，
产物里 ``vendor/e7auto`` 成员数为 0，改收 ``vendor/NO_E7AUTO.txt`` 作为发行版
标记（界面与自检据此如实显示「不含次元探查」）。E7auto 的再分发尚未取得其
维护者同意，对外公开构建一律走这一档，见 ``NOTICE.md``。

第三方代码（次元探查的 chaos 流程）不在 Git 里：先跑一次
``python tools/fetch_vendor.py``，本脚本按 ``packaging/vendor_lock.json`` 逐文件
核对，缺文件/摘要不符/清单外文件都会在 PyInstaller 之前停下。
``--without-e7auto`` 不校第三方清单（本就不收），改为在打包后断言它一个都没进。

产物都在 ``packaging/dist/``：

    ArkyAssistant/                                  目录版（双击里面的 exe 即用）
    亚卡助手-免安装版-<版本>.zip                    整个目录打成压缩包
    亚卡助手-免安装版-<版本>-无次元探查.zip         公开候选（--without-e7auto）
    SHA256SUMS.txt                                  上面这些 zip 的校验值

每次构建成功后只保留最新一份 ZIP（和安装包）；上一次的版本会被清掉。
这样 dist 里始终只有一个 ZIP，``verify_release.py`` 按缺省规则就能找到它。

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
APP_NAME = "ArkyAssistant"
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


#: 「次元探查」的第三方代码。仓库里只有清单（commit + 逐文件 SHA-256），
#: 源码由 ``tools/fetch_vendor.py`` 在构建前取到工作区，不随 Git 分发。
VENDOR = REPO.parent / "vendor" / "e7auto"

#: 产物里第三方代码与发行版标记所在的目录（PyInstaller onedir 的内部目录）。
PAYLOAD_VENDOR = Path("_internal") / "vendor"

#: ZIP 里 ``vendor/e7auto`` 的成员前缀 —— 「公开候选成员数为 0」按它数。
ZIP_VENDOR_PREFIX = "_internal/vendor/e7auto/"

#: 不含 E7auto 的产物文件名后缀。两份 ZIP 必须能区分开：同名会让
#: ``prune_old_artifacts`` 把另一档的产物当旧版删掉，发布时也会认错包。
WITHOUT_E7AUTO_SUFFIX = "-无次元探查"


def _repo_on_path() -> None:
    if str(REPO.parent) not in sys.path:
        sys.path.insert(0, str(REPO.parent))


def _vendor_module():
    _repo_on_path()
    from auto_game_unified.tools import fetch_vendor

    return fetch_vendor


def _absent_marker_name() -> str:
    """发行版标记文件名 —— 唯一来源是 ``desktop/chaos_bridge.py``，这里只引用。"""
    _repo_on_path()
    from auto_game_unified.desktop import chaos_bridge

    return chaos_bridge.ABSENT_MARKER_NAME


def verify_vendor() -> dict:
    """构建前先验第三方代码：缺文件、摘要不符、清单外文件都当场停下。"""
    module = _vendor_module()
    lock = module.load_lock()
    problems = module.verify(VENDOR, lock)
    if problems:
        raise SystemExit(
            f"第三方代码不可用：{VENDOR}\n"
            + "\n".join(problems[:20])
            + "\n先运行：python tools/fetch_vendor.py（或 --check 排查）"
        )
    # 缓存文件不算清单外文件，但不能跟着进产物：PyInstaller 会整目录照收。
    for cache in VENDOR.rglob("__pycache__"):
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
    print(f"[build] 第三方代码校验通过（{len(lock['files'])} 个文件）", flush=True)
    return lock


def check_vendor_payload(lock: dict | None, *, without_e7auto: bool = False) -> None:
    """打完包再确认产物里的第三方文件**正好**是清单那一份。

    ⚠️ 这条不是形式主义：``.git``、``__pycache__``、测试与文档都可能被整目录
    收进来（审查看到的正是这种写法），而现象只是「包变大」，没有任何报错。

    ``--without-e7auto`` 时判据反过来，但同样是「正好」：``vendor/e7auto`` 下
    一个文件都不许有，``NO_E7AUTO.txt`` 必须到。两条合起来才算「声明不含」的
    证据 —— 只看目录不在，打包漏拷会被当成「不含」而静默通过。
    """
    vendor_dir = DIST / APP_NAME / PAYLOAD_VENDOR
    root = vendor_dir / "e7auto"
    if without_e7auto:
        leaked = (
            sorted(
                item.relative_to(root).as_posix()
                for item in root.rglob("*")
                if item.is_file()
            )
            if root.is_dir()
            else []
        )
        if leaked:
            raise SystemExit(
                f"本应不含次元探查，产物里却有 {len(leaked)} 个第三方文件：\n"
                + "\n".join(f"  {name}" for name in leaked[:10])
                + "\n检查 packaging/epic7_auto_assistant.spec 的 _VENDOR_DATAS。"
            )
        marker = vendor_dir / _absent_marker_name()
        if not marker.is_file():
            raise SystemExit(
                f"产物里没有发行版标记：{marker}\n"
                "不含次元探查的构建必须带上它，否则界面与自检分不出"
                "「声明不含」和「该有却漏了」。"
            )
        print(
            "[build] 已确认产物不含次元探查（vendor/e7auto 0 个文件，发行版标记在位）",
            flush=True,
        )
        return

    if not root.is_dir():
        raise SystemExit(f"产物里找不到第三方代码：{root}")
    module = _vendor_module()
    shipped = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file()
    }
    expected = set(lock["files"])
    extra = sorted(shipped - expected)
    missing = sorted(expected - shipped)
    changed = sorted(
        name
        for name in shipped & expected
        if module.sha256_file(root / name) != lock["files"][name]
    )
    if extra or missing or changed:
        raise SystemExit(
            "产物中的第三方文件与清单不一致：\n"
            + "\n".join(f"  多出：{name}" for name in extra[:10])
            + "\n".join(f"  缺少：{name}" for name in missing[:10])
            + "\n".join(f"  摘要不符：{name}" for name in changed[:10])
        )
    print(f"[build] 产物第三方文件与清单一致（{len(expected)} 个）", flush=True)


def run_pyinstaller(without_e7auto: bool = False) -> Path:
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
    # ⚠️ 开关走环境变量而不是 spec 的命令行：spec 里只能读 ``os.environ``。
    # 完整版要**主动清掉**它 —— 父 shell 若残留这个变量，一次「完整构建」
    # 会悄悄产出不含次元探查的包，而名字与校验都还是完整版那一套。
    env = dict(os.environ)
    if without_e7auto:
        env["ARKY_WITHOUT_E7AUTO"] = "1"
    else:
        env.pop("ARKY_WITHOUT_E7AUTO", None)
    print("[build] " + " ".join(command), flush=True)
    subprocess.run(command, cwd=REPO, check=True, env=env)

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
            encoding="utf-8",
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


def _zip_vendor_members(archive: Path) -> int:
    """ZIP 里 ``vendor/e7auto`` 的成员数 —— 公开候选必须为 0。"""
    with zipfile.ZipFile(archive) as bundle:
        return sum(1 for name in bundle.namelist() if ZIP_VENDOR_PREFIX in name)


def make_zip(version: str, lock: dict | None, *, without_e7auto: bool = False) -> Path:
    """打免安装版 ZIP。

    ⚠️ 用 **DEFLATE** 不是为了省事：换 ``ZIP_LZMA`` 能再小 18 MB（63 → 45），
    但 **Windows 资源管理器自带的「全部解压缩」不认 LZMA 的 zip**，
    用户得先装 7-Zip —— 那就不是「解压即用」了。2026-10-20 实测过两种压缩率。
    """
    # ⚠️ 先验内容再开压缩包：``--no-build`` 复用旧 dist 时也必须过这一关，
    # 否则往目录里塞一个清单外文件再重打包，它会照样进 ZIP。
    check_vendor_payload(lock, without_e7auto=without_e7auto)
    suffix = WITHOUT_E7AUTO_SUFFIX if without_e7auto else ""
    archive = DIST / f"亚卡助手-免安装版-{version}{suffix}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for item in sorted((DIST / APP_NAME).rglob("*")):
            if item.is_file():
                bundle.write(item, Path(APP_NAME) / item.relative_to(DIST / APP_NAME))
    # 目录过了还要数一遍压缩包本身：发布出去的是 ZIP，不是目录。
    members = _zip_vendor_members(archive)
    if without_e7auto and members:
        archive.unlink()
        raise SystemExit(
            f"公开候选的 ZIP 里仍有 {members} 个 vendor/e7auto 成员，已删除该包"
        )
    if not without_e7auto and not members:
        archive.unlink()
        raise SystemExit("完整版 ZIP 里没有 vendor/e7auto 成员，已删除该包")
    print(f"[build] ZIP 内 vendor/e7auto 成员 {members} 个", flush=True)
    return archive


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: 每次打包只保留最新一份：这两类产物按版本命名，不清就会在 dist 里逐版累积。
#: ⚠️ 只按精确前缀匹配，不碰 ArkyAssistant/（每次重建）、SHA256SUMS.txt（覆盖写）、
#: release-evidence/（发布验证证据，CI 要上传）。
OLD_ARTIFACT_PATTERNS = ("亚卡助手-免安装版-*.zip", "亚卡助手-安装版-*.exe")


def prune_old_artifacts(keep: set[Path]) -> None:
    """删掉上一次打包的产物，只留下本次刚生成的 ``keep``。

    调用点必须在成功造出新 ZIP/安装包**之后**：门禁拦下时保留旧产物，不毁现场。
    """
    for pattern in OLD_ARTIFACT_PATTERNS:
        for path in sorted(DIST.glob(pattern)):
            if path.is_file() and path not in keep:
                path.unlink()
                print(f"[build] 清理旧产物：{path.name}", flush=True)


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


def build_installer(version: str, *, without_e7auto: bool = False) -> Path | None:
    """出安装包。**只有显式传 ``--installer`` 才编**（2026-10-20 起默认不要）。

    没装 Inno Setup 6 就跳过 —— 免安装版本来就不依赖它。
    """
    iscc = find_iscc()
    if iscc is None:
        print("[build] 没装 Inno Setup 6，跳过安装包（免安装版不受影响）", flush=True)
        return None
    variant = WITHOUT_E7AUTO_SUFFIX if without_e7auto else ""
    print(f"[build] 安装包：{iscc}", flush=True)
    subprocess.run(
        [
            str(iscc),
            f"/DMyAppVersion={version}",
            f"/DMyAppVariant={variant}",
            str(INSTALLER),
        ],
        cwd=REPO,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    archive = DIST / f"亚卡助手-安装版-{version}{variant}.exe"
    if not archive.is_file():
        raise SystemExit(f"ISCC 返回成功但找不到安装包：{archive}")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="构建亚卡助手免安装版")
    parser.add_argument("--no-build", action="store_true", help="复用已有 dist，只重打包")
    parser.add_argument("--skip-smoke", action="store_true", help="跳过 exe 自检")
    parser.add_argument(
        "--installer",
        action="store_true",
        help="额外编 Inno Setup 安装包（默认不编，只出免安装版）",
    )
    parser.add_argument(
        "--without-e7auto",
        action="store_true",
        help="出不含次元探查（E7auto）的公开候选：不收第三方代码，改收发行版标记",
    )
    args = parser.parse_args()

    version = product_version()
    without_e7auto = args.without_e7auto
    print(f"[build] 版本 {version}", flush=True)
    if without_e7auto:
        print(
            "[build] 公开候选：本发行版不含次元探查（E7auto 的再分发未取得维护者同意）",
            flush=True,
        )

    exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    # --no-build 复用旧 dist 时没有源码目录可验，清单仍要从仓库读出来，
    # 交给 make_zip 在压缩前核对产物。不含次元探查的那一档不需要清单。
    vendor_lock: dict | None = None if without_e7auto else _vendor_module().load_lock()
    if not args.no_build:
        if not without_e7auto:
            vendor_lock = verify_vendor()
        exe = run_pyinstaller(without_e7auto)
        check_vendor_payload(vendor_lock, without_e7auto=without_e7auto)
        # 先确认剔掉的东西真没进产物，再花时间跑自检 —— 顺序反了会白跑一遍。
        check_pruned_binaries()
        if not args.skip_smoke:
            smoke_test(exe)

    if not exe.is_file():
        raise SystemExit(f"没有可打包的产物：{exe}")

    archive = make_zip(version, vendor_lock, without_e7auto=without_e7auto)
    installer = (
        build_installer(version, without_e7auto=without_e7auto)
        if args.installer
        else None
    )

    # 新包都造出来了再清旧的：门禁失败时旧产物仍在，可回溯。
    prune_old_artifacts({archive, installer} if installer is not None else {archive})

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
