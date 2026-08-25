"""Create a user-reviewed, local diagnostic archive for one route."""

from datetime import datetime
import json
from pathlib import Path
import platform
from zipfile import ZIP_DEFLATED, ZipFile

from auto_game_unified.desktop.catalog import PRODUCT_VERSION, route_by_name


def export_diagnostics(
    mode: str,
    *,
    root: Path,
    output_dir: Path,
    user_home: Path | None = None,
) -> Path:
    route_by_name(mode)
    exported_at = datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / (
        f"epic7-{mode}-diagnostics-{exported_at:%Y%m%d-%H%M%S}.zip"
    )
    home = user_home or Path.home()
    metadata = {
        "product_version": PRODUCT_VERSION,
        "mode": mode,
        "exported_at": exported_at.isoformat(timespec="seconds"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        log_path = root / "runtime_logs" / f"epic7_{mode}.log"
        for path in (log_path, *(Path(f"{log_path}.{index}") for index in range(1, 5))):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            archive.writestr(
                f"logs/{path.name}",
                _redact_home(text, home).encode("utf-8"),
            )

        diagnostic_dir = root / "runtime_diagnostics" / f"epic7_{mode}"
        if diagnostic_dir.is_dir():
            for path in sorted(diagnostic_dir.glob("*.png")):
                archive.write(path, f"diagnostics/{path.name}")

    return archive_path


def _redact_home(text: str, user_home: Path) -> str:
    redacted = text.replace(str(user_home), "%USERPROFILE%")
    return redacted.replace(user_home.as_posix(), "%USERPROFILE%")
