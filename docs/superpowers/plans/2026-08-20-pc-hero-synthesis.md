# PC Hero Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the verified non-SSS, three-star imprint-synthesis path run correctly on the Epic Seven PC client.

**Architecture:** Keep the existing hero synthesis state machine and runner. Add only a PC flag and the few PC-specific action coordinates required by live evidence; replace active PC templates with local crops from the captured live route. SSS and transmission behavior remain loaded but are deliberately not enabled or tested for PC until the account exposes a real SSS case.

**Tech Stack:** Python 3, OpenCV, unittest, existing `Runtime` / `Epic7PcWindow` backends.

---

## Captured evidence

The live, normalized 1982×1132 PC sequence is stored under `runtime_diagnostics/hero_capture/`:

| Screen | Expected decision / result |
| --- | --- |
| `03_filter_open.png` | select ★3 at `(1148, 613)` |
| `04_filter_star3_selected.png` | close filter at `(1612, 141)` |
| `05_star3_list.png` | no red dot; advance to `(1710, 570)` |
| `06_next_card_01.png` | red dot; open imprint at `(1115, 991)` |
| `07_imprint_materials.png` | add one Up material |
| `09_imprint_all_materials.png` | start synthesis at `(1200, 1041)` |
| `10_synthesis_confirm.png` | confirm button is in `(1005..1311, 676..771)` |
| `13_imprint_result_closed.png` | return arrow at `(66, 51)` |
| `14_back_to_star3_list.png` | returned to the filtered hero list |

### Task 1: Preserve the PC evidence and write failing behavior tests

**Files:**
- Create: `tests/fixtures/epic7_pc_hero/*.png`
- Create: `tests/test_pc_hero_synthesis_evidence.py`

- [ ] **Step 1: Copy the nine named live captures into `tests/fixtures/epic7_pc_hero/` without resampling them.**

Run:

```powershell
New-Item -ItemType Directory -Force tests/fixtures/epic7_pc_hero
Copy-Item runtime_diagnostics/hero_capture/03_filter_open.png tests/fixtures/epic7_pc_hero/
Copy-Item runtime_diagnostics/hero_capture/04_filter_star3_selected.png tests/fixtures/epic7_pc_hero/
Copy-Item runtime_diagnostics/hero_capture/05_star3_list.png tests/fixtures/epic7_pc_hero/
Copy-Item runtime_diagnostics/hero_capture/06_next_card_01.png tests/fixtures/epic7_pc_hero/
Copy-Item runtime_diagnostics/hero_capture/07_imprint_materials.png tests/fixtures/epic7_pc_hero/
Copy-Item runtime_diagnostics/hero_capture/09_imprint_all_materials.png tests/fixtures/epic7_pc_hero/
Copy-Item runtime_diagnostics/hero_capture/10_synthesis_confirm.png tests/fixtures/epic7_pc_hero/
Copy-Item runtime_diagnostics/hero_capture/13_imprint_result_closed.png tests/fixtures/epic7_pc_hero/
Copy-Item runtime_diagnostics/hero_capture/14_back_to_star3_list.png tests/fixtures/epic7_pc_hero/
```

- [ ] **Step 2: Write the red test file with the following assertions.**

```python
from pathlib import Path

import cv2

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.hero_synthesis import (
    HeroSynthState,
    HeroSynthStateMachine,
    build_hero_templates,
)
from auto_game_unified.games.epic7.navigation import Epic7Navigator, build_navigation_templates


ROOT = Path(__file__).resolve().parents[1]
PC_TEMPLATES = ROOT / "games" / "epic7" / "templates_pc"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_pc_hero"


def fixture(name: str):
    return cv2.cvtColor(
        cv2.imread(str(FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB
    )


def machine(*, filter_verified=False, state=HeroSynthState.HERO_LIST):
    value = HeroSynthStateMachine(build_hero_templates(PC_TEMPLATES), state)
    value.filter_verified = filter_verified
    return value


def settled_next(value, screen):
    return value.next_action(screen) or value.next_action(screen)


def test_pc_filter_open_selects_star3():
    action = machine().next_action(fixture("03_filter_open"))
    assert (action.name, action.point) == ("select_star3", (1148, 613))


def test_pc_filter_with_star3_selected_closes():
    action = machine().next_action(fixture("04_filter_star3_selected"))
    assert (action.name, action.point) == ("close_filter", (1612, 141))


def test_pc_list_without_red_dot_advances():
    action = settled_next(machine(filter_verified=True), fixture("05_star3_list"))
    assert action.name.startswith("next_card_")
    assert action.point == (1710, 570)


def test_pc_list_red_dot_opens_imprint():
    action = machine(filter_verified=True).next_action(fixture("06_next_card_01"))
    assert (action.name, action.point) == ("open_imprint", (1115, 991))


def test_pc_imprint_without_up_starts_synthesis_at_button_center():
    value = machine(filter_verified=True, state=HeroSynthState.IMPRINT_ADD)
    action = value.next_action(fixture("09_imprint_all_materials"))
    assert (action.name, action.point) == ("start_synthesis", (1200, 1041))


def test_pc_confirmation_click_is_inside_live_confirm_button():
    action = machine().next_action(fixture("10_synthesis_confirm"))
    assert action.name == "confirm_synthesis"
    assert 1005 <= action.point[0] <= 1311
    assert 676 <= action.point[1] <= 771


def test_pc_completed_imprint_uses_live_back_arrow_center():
    value = machine(filter_verified=True, state=HeroSynthState.IMPRINT_CONFIRM)
    action = value.next_action(fixture("13_imprint_result_closed"))
    assert (action.name, action.point) == ("back_to_list", (66, 51))


def test_pc_navigation_recognizes_live_hero_list():
    navigator = Epic7Navigator(
        build_navigation_templates(PC_TEMPLATES), Runtime(lambda: None, lambda _: None),
        sleep=lambda _: None,
    )
    observation = navigator.observe(fixture("05_star3_list"))
    assert observation.name == "hero_list"
    assert observation.confidence >= 0.80
```

- [ ] **Step 3: Run the focused test and confirm it fails because the legacy PC assets and points are wrong.**

Run: `pytest tests/test_pc_hero_synthesis_evidence.py -q`
Expected: failures including `open_filter` instead of `select_star3`, an off-screen `open_imprint` point, and the old green/back points.

### Task 2: Replace active PC templates with stable local crops

**Files:**
- Modify: `games/epic7/templates_pc/hero/filter_button.png`
- Modify: `games/epic7/templates_pc/hero/filter_level_label.png`
- Modify: `games/epic7/templates_pc/hero/filter_star3_selected.png`
- Modify: `games/epic7/templates_pc/hero/imprint_button_normal.png`

- [ ] **Step 1: Generate the four assets from the named source frames at these exact crop rectangles (`image[y:y+h, x:x+w]`).**

```python
crops = {
    "filter_button.png": ("02_after_lobby_hero.png", 1595, 122, 35, 38),
    "filter_level_label.png": ("04_filter_star3_selected.png", 676, 522, 72, 42),
    "filter_star3_selected.png": ("04_filter_star3_selected.png", 1099, 578, 97, 71),
    "imprint_button_normal.png": ("05_star3_list.png", 1045, 920, 140, 140),
}
```

The source `02_after_lobby_hero.png` is copied from the diagnostic directory only for this crop; it is not a test fixture. Do not crop names, combat power, material counts, hero portraits, or any whole screen.

- [ ] **Step 2: Inspect every output image.**

Expected: the filter icon, “级别” label, white selected ★3 button, and circular imprint button respectively; no output is larger than 140×140.

### Task 3: Add the smallest PC-only behavior selection

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Test: `tests/test_pc_hero_synthesis_evidence.py`

- [ ] **Step 1: Add two explicit template flags in `HeroTemplates` and set them in `build_hero_templates`.**

```python
    pc_client: bool = False
    assume_non_max_rating: bool = False
```

```python
    is_pc = template_root.name == "templates_pc"
    return HeroTemplates(
        # existing template assignments unchanged
        pc_client=is_pc,
        assume_non_max_rating=is_pc,
    )
```

- [ ] **Step 2: Make `_is_max_rating` honor the confirmed PC scope.**

```python
    def _is_max_rating(self, screen: np.ndarray) -> bool:
        if self.templates.assume_non_max_rating:
            return False
        return (
            self._locate(
                screen, "rating_sss", self._RATING_SSS_MIN,
                region_override=self._RATING_REGION,
            ) is not None
        )
```

- [ ] **Step 3: Add a small `_point` helper and use it only for the four PC-proven points.**

```python
    _PC_FUNNEL_POINT = (1612, 141)
    _PC_STAR3_POINT = (1148, 613)
    _PC_IMPRINT_BUTTON_POINT = (1115, 991)
    _PC_GREEN_BTN_POINT = (1200, 1041)
    _PC_BACK_OFFSET = (11, -4)

    def _point(self, emulator_point, pc_point):
        return pc_point if self.templates.pc_client else emulator_point
```

Replace only the existing uses of `_FUNNEL_POINT`, `_STAR3_POINT`,
`_IMPRINT_BUTTON_POINT`, `_GREEN_BTN_POINT`, and `_BACK_OFFSET` with this helper.

- [ ] **Step 4: Give the PC imprint template its captured geometry before matching and red-dot masking.**

```python
    _PC_BUTTON_TL = (1045, 920)
    _PC_DOT_MASK = (1065, 935, 32, 32)
```

In `__init__`, select `_button_tl` and `_dot_mask` from the PC constants when
`templates.pc_client` is true; otherwise keep `_BUTTON_TL` and `_DOT_MASK`.
Use the instance values in `_mask_dot` and `_locate_button`. Leave emulator
constants and all non-PC behavior unchanged.

- [ ] **Step 5: Run the focused test until green.**

Run: `pytest tests/test_pc_hero_synthesis_evidence.py -q`
Expected: `8 passed`.

### Task 4: Regression verification and one controlled live repeat

**Files:**
- Test: `tests/test_hero_synthesis.py`
- Test: `tests/test_navigation.py`
- Modify: `docs/PC_TEMPLATE_MIGRATION.md`

- [ ] **Step 1: Run existing hero and navigation tests.**

Run: `pytest tests/test_hero_synthesis.py tests/test_navigation.py tests/test_pc_hero_synthesis_evidence.py -q`
Expected: all tests pass; simulator behavior remains unchanged.

- [ ] **Step 2: Run `python main.py --mode hero_synthesis --live --confirm RUN --max-cycles 1 --window-backend pc` in an elevated process.**

Expected: navigation enters heroes; the program filters three-star heroes; it skips no-red cards; it opens only red-dot cards; each synthesis follows confirmed material, confirmation, result, and return states. It stops on an unknown page instead of making a blind click.

- [ ] **Step 3: Update `docs/PC_TEMPLATE_MIGRATION.md` to mark only the non-SSS hero-imprint path as live-verified.**

Record the verified boundaries: PC filter point, red-dot logic, material selection, confirmation, result-close, return; explicitly list SSS and transmission as unverified future work.

- [ ] **Step 4: Inspect the working-tree diff and run `git diff --check`.**

Do not commit: the working tree already contains user and prior-agent changes outside this route.
