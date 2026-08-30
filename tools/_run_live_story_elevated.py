from pathlib import Path
import os
import sys
import traceback


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))
os.chdir(ROOT)

status = ROOT / "runtime_logs" / "elevated_story_run.txt"
try:
    sys.argv = [
        "main.py",
        "--mode",
        "story",
        "--live",
        "--confirm",
        "RUN",
        "--max-cycles",
        "1",
        "--window-backend",
        "pc",
    ]
    from main import main

    status.write_text("started\n", encoding="utf-8")
    main()
    status.write_text("completed\n", encoding="utf-8")
except Exception:
    status.write_text(traceback.format_exc(), encoding="utf-8")
    raise
