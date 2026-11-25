import json
import os
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np

from auto_game_unified.core.account import ACCOUNT_ENV
from auto_game_unified.desktop.report import export_failure_report


def _write_png(path: Path, *, size: int = 64, noisy: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if noisy:
        image = np.random.randint(0, 255, (size, size, 3), dtype=np.uint8)
    else:
        image = np.zeros((size, size, 3), dtype=np.uint8)
        image[:] = (10, 20, 30)
    assert cv2.imwrite(str(path), image)


def _evidence(path: Path, *, template_root: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "story",
        "action": "enter_battle",
        "source": "story_battle_menu",
        "targets": ["battle"],
        "attempt": 3,
        "conclusion": "timeout",
        "evidence": {
            "profile": {"template_root": template_root},
            "atoms": {
                "story_battle_title": {
                    "score": 0.62,
                    "threshold": 0.9,
                    "observed": False,
                    "region": [1, 2, 3, 4],
                },
                "story_home": {
                    "score": 0.97,
                    "threshold": 0.9,
                    "observed": True,
                    "region": [5, 6, 7, 8],
                },
                "未命中的锚点": {"score": None, "threshold": 0.9},
            },
            "pages": {"story_battle_menu": {"state": "miss"}},
        },
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    home = tmp_path / "User Name"
    logs = root / "runtime_logs"
    logs.mkdir(parents=True)
    (logs / "epic7_story.log").write_text(
        f"诊断={home / 'secret.png'} 账号=康康626\n", encoding="utf-8"
    )
    (logs / "desktop_worker.log").write_text(
        f"事件=结束 退出码=1 最后输出=超时 目录={home}\n", encoding="utf-8"
    )
    (logs / "epic7_arena.log").write_text("另一条路线\n", encoding="utf-8")

    frame = root / "runtime_diagnostics" / "epic7_story" / (
        "20261123_120000_123456_failure.png"
    )
    _write_png(frame)
    _evidence(
        frame.with_suffix("") / "evidence.json",
        template_root=str(home / "repo" / "templates" / "pc"),
    )
    _write_png(frame.with_suffix("") / "source.png")
    return root, home


def _read(path: Path, name: str) -> bytes:
    with ZipFile(path) as archive:
        prefix = archive.namelist()[0].split("/")[0]
        return archive.read(f"{prefix}/{name}")


def _names(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        return archive.namelist()


def test_report_contains_the_five_sections_and_redacts(tmp_path, monkeypatch):
    root, home = _root(tmp_path)
    monkeypatch.setenv(ACCOUNT_ENV, "康康626")

    output = export_failure_report(
        root=root,
        modes=("story", "arena"),
        cycles={"story": 1, "arena": 1},
        backend="pc",
        pc_input_mode="background",
        exit_code=1,
        last_output=f"超时 {home}",
        recent_output=("第一行", "账号=康康626"),
        user_home=home,
    )

    names = _names(output)
    suffix = "/".join(names[0].split("/")[:-1])
    for expected in (
        "README.txt",
        "report.json",
        "investigate.md",
        "logs/epic7_story.log",
        "logs/desktop_worker.log",
        "config/run.json",
        "config/environment.txt",
    ):
        assert f"{suffix}/{expected}" in names
    assert not any("epic7_arena.log" in name for name in names)
    assert any(name.endswith("failure.png") for name in names)
    assert any(name.endswith("evidence.json") for name in names)

    report = json.loads(_read(output, "report.json"))
    assert report["failed_route"] == "story"
    assert report["exit_code"] == 1
    assert report["failure"]["conclusion"] == "timeout"
    assert report["failure"]["evidence_dir"].endswith("_failure")
    assert report["top_scores"][0]["atom"] == "story_home"
    assert report["top_scores"][0]["score"] == 0.97
    assert len(report["top_scores"]) == 2

    log_text = _read(output, "logs/epic7_story.log").decode("utf-8")
    assert "%USERPROFILE%" in log_text
    assert "康康626" not in log_text
    assert "账号A" in log_text
    assert str(home) not in log_text

    readme = _read(output, "README.txt").decode("utf-8")
    assert "账号A" in readme
    assert "%USERPROFILE%" in readme


def test_report_falls_back_to_the_route_evidence_beside_the_worker_snapshot(
    tmp_path,
):
    """外层进程只复制了帧，没复制证据目录；证据要从路线目录里找回。"""

    root, home = _root(tmp_path)
    worker_dir = root / "runtime_diagnostics" / "desktop_worker"
    worker_dir.mkdir(parents=True)
    snapshot = worker_dir / "20261123_120001_story_exit_1.png"
    _write_png(snapshot)

    output = export_failure_report(
        root=root,
        modes=("story",),
        backend="emulator",
        pc_input_mode="background",
        exit_code=1,
        last_output="超时",
        user_home=home,
    )

    report = json.loads(_read(output, "report.json"))
    assert report["failed_route"] == "story"
    assert report["failure"]["conclusion"] == "timeout"
    assert any(name.endswith("evidence.json") for name in _names(output))


def test_report_keeps_at_most_three_frames(tmp_path):
    root, home = _root(tmp_path)
    directory = root / "runtime_diagnostics" / "epic7_story"
    for index in range(6):
        _write_png(directory / f"20261123_12000{index}_000000_step_{index}.png")

    output = export_failure_report(
        root=root,
        modes=("story",),
        backend="emulator",
        pc_input_mode="background",
        exit_code=1,
        last_output="超时",
        user_home=home,
    )

    frames = [
        name
        for name in _names(output)
        if name.endswith(".png") and name.split("/")[-2] == "frames"
    ]
    assert 1 <= len(frames) <= 3


def test_report_compresses_frames_when_over_the_limit(tmp_path):
    root, home = _root(tmp_path)
    frame = root / "runtime_diagnostics" / "epic7_story" / (
        "20261123_120000_123456_failure.png"
    )
    _write_png(frame, size=420, noisy=True)

    output = export_failure_report(
        root=root,
        modes=("story",),
        backend="emulator",
        pc_input_mode="background",
        exit_code=1,
        last_output="超时",
        max_bytes=200_000,
        user_home=home,
    )

    report = json.loads(_read(output, "report.json"))
    assert report["frames_compressed"] is True
    assert all(name.endswith(".jpg") for name in report["frames"])


def test_report_prunes_older_archives(tmp_path):
    root, home = _root(tmp_path)
    reports = root / "reports"
    reports.mkdir()
    for index in range(3):
        old = reports / f"E7-2026010{index}-0000-AAAA.zip"
        old.write_bytes(b"old")
        os.utime(old, (1_700_000_000 + index, 1_700_000_000 + index))

    output = export_failure_report(
        root=root,
        modes=("story",),
        backend="emulator",
        pc_input_mode="background",
        exit_code=1,
        last_output="超时",
        keep=2,
        user_home=home,
    )

    remaining = sorted(path.name for path in reports.glob("E7-*.zip"))
    assert len(remaining) == 2
    assert output.name in remaining
