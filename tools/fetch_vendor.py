"""把「次元探查」的第三方源码取到构建位置，并按清单逐文件校验。

上游是 ``Ricardo1503449/E7auto``（v1.5.5），固定 commit 与分发文件清单都在
``packaging/vendor_lock.json``。**不把第三方源码收进本仓库**：上游仓库没有
LICENSE 文件，重分发依据未确认；构建时按固定 commit 取回，再逐文件比对 SHA-256。

落点固定为 ``<工作区>/vendor/e7auto`` —— ``desktop/chaos_bridge.py`` 与打包 spec
都认这个路径。只写 ``src`` / ``config`` / ``assets/templates`` 三个目录，不带历史。

**校验的是哪一种字节**：固定 commit 的 Git blob 原始字节。取回用
``git archive`` 直接从对象库导出，不经过 ``git checkout`` —— 后者会按调用者的
``core.autocrlf`` / ``core.eol`` 转换换行，同一 commit 在不同机器上字节就不同。
因此清单与 ``core.autocrlf=true/false`` 都无关，用户不需要改全局配置。

用法（在仓库根执行）::

    python tools/fetch_vendor.py                  # 缺就取，已在就只校验
    python tools/fetch_vendor.py --check          # 只校验，不联网
    python tools/fetch_vendor.py --source <url>   # 内网镜像 / 本地副本
    python tools/fetch_vendor.py --write-lock     # 维护者：从当前检出重建清单

退出码：0 就绪 / 1 缺失或校验不符（信息里逐条写是哪个文件）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
DEST = WORKSPACE / "vendor" / "e7auto"
LOCK_PATH = REPO / "packaging" / "vendor_lock.json"

#: 随包分发的目录（相对 vendor 根）。其余上游文件（docs / tests / scripts /
#: artifacts / .git）不进产物：它们不参与运行，只会让包变大、清单变脏。
INCLUDE = ("src", "config", "assets/templates")

#: 目录里本来就允许存在、但不算「清单外文件」的东西。
IGNORED_DIRS = frozenset({"__pycache__", ".pytest_cache"})
IGNORED_SUFFIXES = frozenset({".pyc", ".pyo"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(path: Path = LOCK_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def inventory(root: Path, include: tuple[str, ...] = INCLUDE) -> dict[str, str]:
    """``{相对路径: sha256}``，只统计会随包分发的那几个目录。"""
    files: dict[str, str] = {}
    for name in include:
        base = root / name
        if not base.is_dir():
            continue
        for item in sorted(base.rglob("*")):
            if not item.is_file():
                continue
            if any(part in IGNORED_DIRS for part in item.parts):
                continue
            if item.suffix in IGNORED_SUFFIXES:
                continue
            files[item.relative_to(root).as_posix()] = sha256_file(item)
    return files


def verify(root: Path, lock: dict) -> list[str]:
    """返回问题清单；空列表表示「文件齐、摘要对、没有清单外文件」。"""
    if not root.is_dir():
        return [f"缺少第三方目录：{root}（先运行 python tools/fetch_vendor.py）"]
    problems: list[str] = []
    expected: dict[str, str] = lock["files"]
    actual = inventory(root, tuple(lock.get("include", INCLUDE)))
    for rel, digest in expected.items():
        if rel not in actual:
            problems.append(f"缺少文件：{rel}")
        elif actual[rel] != digest:
            problems.append(
                f"摘要不符：{rel}（文件字节与 Git blob 不一致；换行符不同也会到这里，"
                "重新运行 fetch_vendor.py 取回）"
            )
    for rel in sorted(actual.keys() - expected.keys()):
        problems.append(f"清单外文件：{rel}")
    return problems


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} 失败（退出码 {result.returncode}）："
            f"{(result.stderr or result.stdout).strip()}"
        )


def _force_remove(function, path: str, _error) -> None:
    """Windows 上 git 对象是只读的，直接删会 PermissionError。"""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, onerror=_force_remove)


def _tree_entries(commit: str, repo: Path) -> list[tuple[str, str]]:
    """``[(blob sha, 相对路径)]``，只保留随包分发的那三段。"""
    result = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", commit],
        cwd=repo,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git ls-tree 失败：{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    prefixes = tuple(f"{name}/" for name in INCLUDE)
    entries: list[tuple[str, str]] = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        meta, _, raw_path = record.partition(b"\t")
        parts = meta.split()
        if len(parts) != 3 or parts[1] != b"blob":
            continue
        path = raw_path.decode("utf-8")
        if not path.startswith(prefixes):
            continue
        entries.append((parts[2].decode("ascii"), path))
    return entries


def _export_blobs(commit: str, repo: Path, dest: Path) -> None:
    """按 **Git blob 原始字节**写出文件，不经过 checkout / archive 的换行转换。"""
    entries = _tree_entries(commit, repo)
    if not entries:
        raise RuntimeError(f"{commit} 里没有可分发文件")
    # ``cat-file --batch`` 一次把 500 多个 blob 原样吐出来，避免逐文件起进程。
    payload = b"".join(sha.encode("ascii") + b"\n" for sha, _ in entries)
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        input=payload,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git cat-file 失败：{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    stream = result.stdout
    offset = 0
    for _sha, path in entries:
        newline = stream.find(b"\n", offset)
        if newline < 0:
            raise RuntimeError(f"blob 输出不完整：{path}")
        header = stream[offset:newline].split()
        if len(header) != 3 or header[1] != b"blob":
            raise RuntimeError(f"读不到 blob：{path}（{stream[offset:newline]!r}）")
        size = int(header[2])
        start = newline + 1
        data = stream[start : start + size]
        if len(data) != size:
            raise RuntimeError(f"blob 长度不符：{path}")
        target = dest / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        offset = start + size + 1  # 每条记录后面跟一个换行


def fetch(lock: dict, source: str, dest: Path = DEST) -> None:
    """把固定 commit 取到 ``dest``；目标已存在时**不覆盖**。"""
    if dest.exists():
        raise RuntimeError(
            f"目标已存在：{dest}\n"
            "确认它没有本地改动后删掉再重取；本脚本不会覆盖已有目录。"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="e7auto-fetch-", dir=dest.parent))
    work = temp / "repo"
    work.mkdir()
    try:
        _run_git(["init", "--quiet"], work)
        _run_git(["remote", "add", "origin", source], work)
        _run_git(["fetch", "--depth", "1", "origin", lock["commit"]], work)
        _export_blobs(lock["commit"], work, temp / "tree")
        problems = verify(temp / "tree", lock)
        if problems:
            raise RuntimeError(
                "取回的内容与清单不符：\n" + "\n".join(problems[:20])
            )
        (temp / "tree").rename(dest)
    except Exception:
        try:
            _remove_tree(temp)
        except OSError:
            pass
        raise
    else:
        _remove_tree(temp)


def write_lock(dest: Path = DEST, *, upstream: str, commit: str, tag: str) -> None:
    files = inventory(dest)
    if not files:
        raise SystemExit(f"{dest} 里没有可分发文件，清单不会写成空的")
    payload = {
        "upstream": upstream,
        "commit": commit,
        "tag": tag,
        "include": list(INCLUDE),
        "license": "上游仓库未见 LICENSE 文件；本仓库不重分发其源码，只在构建时按 commit 取回。",
        "files": files,
    }
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"已写入 {LOCK_PATH}（{len(files)} 个文件）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="取回并校验第三方 e7auto 源码")
    parser.add_argument("--check", action="store_true", help="只校验，不联网")
    parser.add_argument("--source", help="镜像地址或本地路径（默认用清单里的上游）")
    parser.add_argument(
        "--write-lock", action="store_true", help="维护者：从当前检出重建清单"
    )
    args = parser.parse_args(argv)

    lock = load_lock()
    if args.write_lock:
        write_lock(upstream=lock["upstream"], commit=lock["commit"], tag=lock.get("tag", ""))
        return 0

    if args.check:
        problems = verify(DEST, lock)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print(f"第三方代码就绪：{DEST}（{len(lock['files'])} 个文件，commit {lock['commit'][:7]}）")
        return 0

    if not DEST.is_dir():
        try:
            fetch(lock, args.source or lock["upstream"])
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1

    problems = verify(DEST, lock)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"第三方代码就绪：{DEST}（{len(lock['files'])} 个文件，commit {lock['commit'][:7]}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
