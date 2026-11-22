"""从最终 ZIP 解压验证 Windows 产物：自检、离线 worker、停止信号。

只做发布验证，不连接游戏、不截图、不点击：

- ``--self-check``：模板与第三方代码能加载，报告写进 ``EPIC7_DATA_DIR``；
- ``--worker --offline-probe``：走真实 CLI 的停止判定，正常结束退出 0；
- 同一个探针加 ``--stop-file``：写入停止文件后退出 130。

同时生成可比较的成员清单（路径 / 未压缩大小 / 压缩后大小 / CRC32）与摘要，
供 CI 保留证据。**不上传 ZIP 本体**，只留清单、摘要和日志。

本地复跑（在仓库根）::

    python packaging/build.py
    python packaging/verify_release.py

CI 用法见 ``.github/workflows/package-smoke.yml``。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
import zipfile


PACKAGING = Path(__file__).resolve().parent
REPO = PACKAGING.parent
DIST = PACKAGING / "dist"
APP_NAME = "ArkyAssistant"
EXE_NAME = f"{APP_NAME}.exe"

#: 记录进证据的依赖。版本没钉死的项（PySide6 / Fluent）正是两次包大小不同的嫌疑，
#: 每次 CI 都把真实版本留下来，下一次才有得比。
DEPENDENCIES = (
    "PyInstaller",
    "PySide6",
    "PySide6-Fluent-Widgets",
    "PySide6-Essentials",
    "PySide6-Addons",
    "shiboken6",
    "numpy",
    "opencv-python",
    "Pillow",
    "PyAutoGUI",
    "psutil",
    "PyYAML",
    "rapidocr-onnxruntime",
    "onnxruntime",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_zip(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise SystemExit(f"找不到 ZIP：{explicit}")
        return explicit
    candidates = sorted(DIST.glob("*.zip"))
    if len(candidates) != 1:
        raise SystemExit(
            f"{DIST} 里应当恰好有一个 ZIP，实际 {len(candidates)} 个；请用 --zip 指定"
        )
    return candidates[0]


def dependency_versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in DEPENDENCIES:
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


def member_rows(archive: Path) -> list[dict[str, object]]:
    with zipfile.ZipFile(archive) as bundle:
        broken = bundle.testzip()
        if broken is not None:
            raise SystemExit(f"ZIP 成员损坏：{broken}")
        return [
            {
                "path": info.filename,
                "uncompressed": info.file_size,
                "compressed": info.compress_size,
                "crc32": f"{info.CRC:08x}",
            }
            for info in bundle.infolist()
            if not info.is_dir()
        ]


def extract(archive: Path, work: Path) -> Path:
    target = work / "extracted"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)
    exe = target / APP_NAME / EXE_NAME
    if not exe.is_file():
        raise SystemExit(f"解压后找不到 {exe}")
    return exe


def run_exe(exe: Path, args: list[str], *, env: dict[str, str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(exe), *args],
        env=env,
        capture_output=True,
        timeout=timeout,
    )


def verify_self_check(exe: Path, *, env: dict[str, str], data_dir: Path) -> str:
    result = run_exe(exe, ["--self-check"], env=env, timeout=300)
    report = data_dir / "runtime_logs" / "self_check.txt"
    if result.returncode != 0:
        raise SystemExit(f"自检退出码 {result.returncode}，期望 0")
    if not report.is_file():
        raise SystemExit(f"自检没有写报告：{report}")
    text = report.read_text(encoding="utf-8")
    if "结果：通过" not in text or "[失败]" in text:
        raise SystemExit(f"自检报告不是全部通过：\n{text}")
    return text


def verify_worker_exit_zero(exe: Path, *, env: dict[str, str]) -> None:
    result = run_exe(
        exe, ["--worker", "--offline-probe", "1"], env=env, timeout=120
    )
    if result.returncode != 0:
        raise SystemExit(f"离线 worker 退出码 {result.returncode}，期望 0")


def verify_stop_signal(exe: Path, *, env: dict[str, str], work: Path) -> None:
    stop_file = work / "stop.signal"
    process = subprocess.Popen(
        [
            str(exe),
            "--worker",
            "--offline-probe",
            "60",
            "--stop-file",
            str(stop_file),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    code: int | None = None
    try:
        time.sleep(2)
        stop_file.write_text("stop", encoding="utf-8")
        try:
            code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
            raise SystemExit("停止信号没有让 worker 退出（等待 30 秒超时）") from None
    finally:
        if process.poll() is None:
            process.kill()
    if code != 130:
        raise SystemExit(f"停止后退出码 {code}，期望 130")


def write_evidence(
    *,
    out: Path,
    archive: Path,
    members: list[dict[str, object]],
    self_check: str,
    python_version: str,
    platform_text: str,
    versions: dict[str, str | None],
    zip_size: int,
    zip_sha: str,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    members_sorted = sorted(
        members, key=lambda row: int(row["uncompressed"]), reverse=True
    )
    manifest = {
        "zip": {
            "name": archive.name,
            "sha256": zip_sha,
            "size_bytes": zip_size,
            "member_count": len(members),
            "uncompressed_bytes": sum(int(row["uncompressed"]) for row in members),
        },
        "python": python_version,
        "platform": platform_text,
        "dependencies": versions,
        "largest_members": members_sorted[:20],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = ["path,uncompressed_bytes,compressed_bytes,crc32"]
    lines.extend(
        f'{row["path"]},{row["uncompressed"]},{row["compressed"]},{row["crc32"]}'
        for row in members_sorted
    )
    (out / "members.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "self_check.txt").write_text(self_check, encoding="utf-8")
    summary = [
        f"ZIP：{archive.name}",
        f"SHA256：{zip_sha}",
        f"大小：{zip_size} 字节",
        f"成员：{len(members)} 个，未压缩合计 "
        f"{manifest['zip']['uncompressed_bytes']} 字节",
        f"Python：{python_version}",
        f"平台：{platform_text}",
        "依赖：" + "、".join(f"{k}={v or '未安装'}" for k, v in versions.items()),
        "验证：自检 0 / 离线 worker 0 / 停止 130",
    ]
    (out / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从最终 ZIP 验证 Windows 产物")
    parser.add_argument("--zip", type=Path, help="待验证 ZIP；缺省取 packaging/dist 下唯一一个")
    parser.add_argument(
        "--out",
        type=Path,
        default=DIST / "release-evidence",
        help="证据输出目录（默认 packaging/dist/release-evidence）",
    )
    parser.add_argument("--keep-work", action="store_true", help="保留解压目录以便排查")
    args = parser.parse_args(argv)

    archive = find_zip(args.zip)
    zip_sha = sha256_file(archive)
    zip_size = archive.stat().st_size
    members = member_rows(archive)

    work = Path(tempfile.mkdtemp(prefix="epic7-release-verify-"))
    try:
        exe = extract(archive, work)
        data_dir = work / "data"
        env = os.environ.copy()
        env["EPIC7_DATA_DIR"] = str(data_dir)
        self_check = verify_self_check(exe, env=env, data_dir=data_dir)
        verify_worker_exit_zero(exe, env=env)
        verify_stop_signal(exe, env=env, work=work)
        write_evidence(
            out=args.out,
            archive=archive,
            members=members,
            self_check=self_check,
            python_version=platform.python_version(),
            platform_text=platform.platform(),
            versions=dependency_versions(),
            zip_size=zip_size,
            zip_sha=zip_sha,
        )
    finally:
        if args.keep_work:
            print(f"解压目录保留在 {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
