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


def test_report_keeps_at_most_five_frames(tmp_path):
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
    assert len(frames) == 5


def test_first_failure_window_survives_retries_recovery_and_later_route(tmp_path, monkeypatch):
    from auto_game_unified.core.runtime import Runtime

    root, home = _root(tmp_path)
    incident = tmp_path / "first_failure.zip"
    monkeypatch.setenv("EPIC7_FAILURE_WINDOW", str(incident))
    pixels = np.zeros((8, 8, 3), dtype=np.uint8)
    log_path = root / "runtime_logs" / "epic7_story.log"
    runtime = Runtime(lambda: pixels, lambda _: None, log_path=log_path,
                      diagnostic_dir=root / "runtime_diagnostics" / "epic7_story")
    for value in range(8):
        pixels.fill(value)
        runtime.capture()
    runtime.failure_history.freeze("点击后未转场")
    for value in range(20, 30):
        pixels.fill(value)
        runtime.capture()
    monkeypatch.setenv(ACCOUNT_ENV, "康康626")  # worker learned the account after launch
    runtime.record_failure(RuntimeError("首次超时"))
    monkeypatch.delenv(ACCOUNT_ENV)
    log_path.write_text("后续运行已覆盖日志", encoding="utf-8")
    other = Runtime(lambda: pixels, lambda _: None,
                    diagnostic_dir=root / "runtime_diagnostics" / "epic7_arena")
    other.capture()
    other.record_failure(RuntimeError("另一条路线"))
    output = export_failure_report(
        root=root, modes=("story", "arena"), backend="pc", pc_input_mode="background",
        exit_code=1, last_output="已回大厅", user_home=home, incident_path=incident,
        max_bytes=1,
    )
    report = json.loads(_read(output, "report.json"))
    assert report["failed_route"] == "story"
    assert report["first_error"] == "RuntimeError: 首次超时"
    assert report["window_reason"] == "点击后未转场"
    assert report["failure"] == {}  # unrelated evidence from an older run
    assert "logs/epic7_story.log" in report["logs"]
    assert "诊断=" in _read(output, "logs/epic7_story.log").decode()
    assert "康康626" not in _read(output, "logs/epic7_story.log").decode()
    values = [cv2.imdecode(np.frombuffer(_read(output, name), np.uint8), 1)[0, 0, 0]
              for name in report["frames"]]
    assert values == [3, 4, 5, 6, 7]


def test_missing_current_incident_does_not_import_previous_run(tmp_path):
    root, home = _root(tmp_path)
    output = export_failure_report(
        root=root, modes=("story",), backend="pc", pc_input_mode="background",
        exit_code=1, last_output="启动失败", user_home=home,
        incident_path=tmp_path / "missing.zip",
    )
    report = json.loads(_read(output, "report.json"))
    assert report["frames"] == []
    assert report["failure"] == {}


def test_new_fault_after_successful_retry_uses_last_five_captures(tmp_path):
    from auto_game_unified.core.failure_history import freeze_before_retry, retry_recovered
    from auto_game_unified.core.runtime import Runtime

    frames = iter(np.full((3, 3, 3), n, np.uint8) for n in range(12))
    runtime = Runtime(lambda: next(frames), lambda _: None, diagnostic_dir=tmp_path)
    for _ in range(5):
        runtime.capture()
    freeze_before_retry(runtime, "导航重试")
    for _ in range(7):
        runtime.capture()
    retry_recovered(runtime, "导航重试")
    try:
        runtime.capture()
    except StopIteration as error:
        runtime.record_failure(error)
    with ZipFile(tmp_path / "last_failure.zip") as window:
        values = [cv2.imdecode(np.frombuffer(window.read(name), np.uint8), 1)[0, 0, 0]
                  for name in sorted(window.namelist()) if name.startswith("frames/")]
    assert values == [7, 8, 9, 10, 11]


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
