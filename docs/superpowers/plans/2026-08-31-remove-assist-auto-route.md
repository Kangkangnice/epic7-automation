# Delete Assist Auto Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completely remove the `assist_auto` product route while preserving shared battle automation used by the remaining routes.

**Architecture:** Remove the route at its public registration boundaries first, then delete its isolated implementation, templates, and dedicated tests. Shared supervisors and helpers stay in place; current documentation is updated while historical specifications remain unchanged.

**Tech Stack:** Python 3, pytest, OpenCV fixtures/templates, Markdown documentation, Git.

---

### Task 1: Define the six-route product surface

**Files:**
- Modify: `tests/test_modes.py`
- Modify: `tests/test_desktop_catalog.py`
- Modify: `tests/test_launcher.py`

- [x] **Step 1: Write the failing registry and UI tests**

Change the expected mode set to:

```python
{
    "arena",
    "story",
    "expedition",
    "fodder",
    "hero_synthesis",
    "shop_refresh",
}
```

Change the desktop route order to:

```python
[
    "hero_synthesis",
    "story",
    "arena",
    "expedition",
    "fodder",
    "shop_refresh",
]
```

Rename the desktop catalog test to expect four formal and two experimental routes. Change launcher choices so `5` is `hero_synthesis`, `6` is `shop_refresh`, and assert that no menu line contains `助手自动`.

- [x] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_modes.py tests/test_desktop_catalog.py tests/test_launcher.py -q`

Expected: FAIL because `assist_auto` still exists and the launcher still uses the old numbering.

- [x] **Step 3: Confirm the failures are caused by the old route surface**

Each failure must point to the old route registration or numbering, not a typo or fixture error.

### Task 2: Remove route registration, UI entries, and isolated implementation

**Files:**
- Modify: `main.py`
- Modify: `launcher.py`
- Modify: `desktop/catalog.py`
- Modify: `games/epic7/modes.py`
- Modify: `games/epic7/navigation.py`
- Modify: `games/epic7/pre_battle.py`
- Delete: `games/epic7/assist_auto.py`
- Delete: `games/epic7/templates/assist_auto/*.png`
- Delete: `tests/test_assist_auto.py`
- Modify: `tests/test_quick_battle_route_integration.py`

- [x] **Step 1: Remove public route registration**

Delete the `assist_auto` label from `main.MODE_LABELS`, its import/factory/`ModeSpec` from `games/epic7/modes.py`, its navigation label, and its `RouteInfo` from the desktop catalog.

- [x] **Step 2: Renumber the launcher continuously**

Use this exact mapping:

```python
MENU_OPTIONS = {
    "1": ("主线", "story"),
    "2": ("竞技场", "arena"),
    "3": ("远征", "expedition"),
    "4": ("狗粮", "fodder"),
    "5": ("英雄合成", "hero_synthesis"),
    "6": ("刷书签", "shop_refresh"),
}
```

Update the validation message to `请输入 1 到 6 之间的功能编号。`.

- [x] **Step 3: Delete only route-owned files**

Delete `games/epic7/assist_auto.py`, all five templates under `games/epic7/templates/assist_auto/`, and `tests/test_assist_auto.py`. In `tests/test_quick_battle_route_integration.py`, remove only the assistant-auto imports and assistant-auto test; retain every shared-route test.

- [x] **Step 4: Remove route-name-only fallback branches**

Remove `assist_auto` from the template-directory set in `games/epic7/pre_battle.py`. Do not alter the fast-battle switch implementation used by remaining routes.

- [x] **Step 5: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_modes.py tests/test_desktop_catalog.py tests/test_launcher.py tests/test_quick_battle_route_integration.py -q`

Expected: all tests pass and importing `games.epic7.modes` no longer imports `assist_auto`.

- [x] **Step 6: Commit the code removal**

Run: `git add -A` then `git commit -m "refactor: remove assist auto route"`.

### Task 3: Update current documentation and shared-code wording

**Files:**
- Modify: `README.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/TODO.md`
- Modify: `docs/EXTENDING.md`
- Modify: `docs/TRANSITION_CONTRACTS.md`
- Modify: `docs/PC_TEMPLATE_MIGRATION.md`
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/stamina.py`
- Modify: `games/epic7/runner_base.py`

- [x] **Step 1: Remove current product documentation references**

Change route counts and lists from seven to six, remove assistant-auto commands and behavior sections, and describe only the remaining experimental routes (`fodder` and `shop_refresh`). Remove its row from the current TODO and PC support tables.

- [x] **Step 2: Correct shared-code comments without changing behavior**

Replace wording such as `story/fodder/assist_auto` with `story/fodder` and remove assistant-auto examples from comments. Do not restructure or change executable shared runner logic.

- [x] **Step 3: Verify current references are gone**

Run:

```powershell
rg -n "assist_auto|助手自动|辅助自动" main.py launcher.py desktop games README.md docs/USER_GUIDE.md docs/ARCHITECTURE.md docs/TODO.md docs/EXTENDING.md docs/TRANSITION_CONTRACTS.md docs/PC_TEMPLATE_MIGRATION.md tests -g "*.py" -g "*.md"
```

Expected: no matches. Historical files under `docs/superpowers/specs` and `docs/superpowers/plans` are intentionally outside this check.

- [x] **Step 4: Commit documentation cleanup**

Run: `git add README.md docs games/epic7/story.py games/epic7/stamina.py games/epic7/runner_base.py` then `git commit -m "docs: remove assist auto references"`.

### Task 4: Full regression and repository verification

**Files:**
- Verify: entire repository

- [x] **Step 1: Compile the package**

Run: `python -m compileall -q .`

Expected: exit code 0.

- [x] **Step 2: Run the complete test suite**

Run: `python -m pytest tests -q`

Expected: all remaining tests pass.

- [x] **Step 3: Check patch hygiene and worktree state**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors and no uncommitted files.
