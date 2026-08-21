from contextlib import redirect_stdout
from pathlib import Path
import os
import sys
import traceback


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))
os.chdir(ROOT)

status = ROOT / "runtime_logs" / "elevated_hero_run.txt"
log = ROOT / "runtime_logs" / "elevated_hero_run_output.txt"

try:
    status.write_text("started\n", encoding="utf-8")
    sys.argv = [
        "main.py",
        "--mode",
        "hero_synthesis",
        "--live",
        "--confirm",
        "RUN",
        "--max-cycles",
        "1",
        "--window-backend",
        "pc",
    ]
    from main import main

    with log.open("w", encoding="utf-8") as stream, redirect_stdout(stream):
        result = main()
    status.write_text(f"completed exit={result}\n", encoding="utf-8")
except Exception:
    status.write_text(traceback.format_exc(), encoding="utf-8")
    raise
