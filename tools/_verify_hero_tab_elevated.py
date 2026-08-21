from pathlib import Path
import sys
from time import sleep

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pc_window import Epic7PcWindow


window = Epic7PcWindow()
window.click((65, 150))
sleep(3)
frame = window.capture()
output = ROOT / "runtime_diagnostics" / "hero_capture" / "33_hero_detail_tab_after_switch.png"
assert cv2.imwrite(str(output), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
