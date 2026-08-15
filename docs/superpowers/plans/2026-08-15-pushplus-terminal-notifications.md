# PushPlus Terminal Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send one PushPlus message after a live Epic Seven run completes, stops for allowed resource exhaustion, or fails, without notifying for dry runs or manual `P` stops.

**Architecture:** Add one dependency-free PushPlus HTTP client under `core/`, then call it only from the terminal branches in `main.py`. Mode runners remain unchanged, the Token comes only from `EPIC7_PUSHPLUS_TOKEN`, and all transport failures are isolated from the automation exit code.

**Tech Stack:** Python 3 standard library (`urllib.request`, `json`, `os`, `time`), unittest/pytest, existing unified CLI entry point.

---

### Task 1: PushPlus HTTP client

**Files:**
- Create: `core/pushplus.py`
- Create: `tests/test_pushplus.py`

- [ ] **Step 1: Write failing transport tests**

Create `tests/test_pushplus.py` with a small context-manager response fake. Cover the exact JSON request, five-second timeout, absent Token, non-200 PushPlus result, malformed response, and network exception. The test must verify that warning output never contains the secret Token.

```python
import json
import unittest

from auto_game_unified.core.pushplus import TOKEN_ENV, send_pushplus


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body


class PushPlusTests(unittest.TestCase):
    def test_send_posts_wechat_text_without_exposing_token(self):
        captured = {}

        def open_request(request, *, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(b'{"code": 200, "msg": "ok"}')

        messages = []
        sent = send_pushplus(
            "第七史诗：主线已完成",
            "完成轮数：2/2",
            environ={TOKEN_ENV: "secret-token"},
            opener=open_request,
            output=messages.append,
        )

        request = captured["request"]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertTrue(sent)
        self.assertEqual("https://www.pushplus.plus/send", request.full_url)
        self.assertEqual("POST", request.method)
        self.assertEqual(5.0, captured["timeout"])
        self.assertEqual(
            {
                "token": "secret-token",
                "title": "第七史诗：主线已完成",
                "content": "完成轮数：2/2",
                "template": "txt",
                "channel": "wechat",
            },
            payload,
        )
        self.assertEqual([], messages)

    def test_missing_token_skips_request(self):
        called = False

        def open_request(request, *, timeout):
            nonlocal called
            called = True
            return FakeResponse(b'{}')

        messages = []
        sent = send_pushplus(
            "title", "content", environ={}, opener=open_request, output=messages.append
        )

        self.assertFalse(sent)
        self.assertFalse(called)
        self.assertEqual(["PushPlus 通知未启用：未配置 EPIC7_PUSHPLUS_TOKEN"], messages)

    def test_remote_and_network_failures_are_sanitized(self):
        cases = (
            lambda request, timeout: FakeResponse(b'{"code": 903, "msg": "bad"}'),
            lambda request, timeout: FakeResponse(b'not-json'),
            lambda request, timeout: (_ for _ in ()).throw(TimeoutError("secret-token")),
        )
        for opener in cases:
            with self.subTest(opener=opener):
                messages = []
                sent = send_pushplus(
                    "title",
                    "content",
                    environ={TOKEN_ENV: "secret-token"},
                    opener=opener,
                    output=messages.append,
                )
                self.assertFalse(sent)
                self.assertNotIn("secret-token", "\n".join(messages))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify RED**

From `D:\AI\codex\auto_game`, run:

```powershell
python -m pytest auto_game_unified\tests\test_pushplus.py -q
```

Expected: collection fails because `auto_game_unified.core.pushplus` does not exist.

- [ ] **Step 3: Implement the minimal client**

Create `core/pushplus.py`. Use HTTPS even though some official examples display HTTP. Treat PushPlus `code == 200` as “request accepted”; the PushPlus API is asynchronous and this does not independently prove delivery to微信.

```python
import json
import os
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen


PUSHPLUS_URL = "https://www.pushplus.plus/send"
TOKEN_ENV = "EPIC7_PUSHPLUS_TOKEN"
REQUEST_TIMEOUT_SECONDS = 5.0


def send_pushplus(
    title: str,
    content: str,
    *,
    environ: Mapping[str, str] | None = None,
    opener: Callable[..., Any] = urlopen,
    output: Callable[[str], None] = print,
) -> bool:
    environment = os.environ if environ is None else environ
    token = environment.get(TOKEN_ENV, "").strip()
    if not token:
        output(f"PushPlus 通知未启用：未配置 {TOKEN_ENV}")
        return False

    body = json.dumps(
        {
            "token": token,
            "title": title,
            "content": content,
            "template": "txt",
            "channel": "wechat",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        PUSHPLUS_URL,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        output(f"PushPlus 通知失败：{type(error).__name__}")
        return False

    code = result.get("code") if isinstance(result, dict) else None
    if code != 200:
        output(f"PushPlus 通知失败：返回码 {code!r}")
        return False
    return True
```

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
python -m pytest auto_game_unified\tests\test_pushplus.py -q
```

Expected: all PushPlus client tests pass without network access.

- [ ] **Step 5: Commit the client**

```powershell
git add core/pushplus.py tests/test_pushplus.py
git commit -m "feat: add PushPlus notification client"
```

### Task 2: Unified live-run terminal notifications

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main_story.py`

- [ ] **Step 1: Write failing main-entry tests**

Import `TOKEN_ENV`, clear it in `MainStoryTests.setUp()` so existing live tests can never perform a real request, then add tests that patch `main_module.send_pushplus`:

```python
import os

from auto_game_unified.core.pushplus import TOKEN_ENV


def setUp(self):
    self.token_patch = patch.dict(os.environ, {TOKEN_ENV: ""}, clear=False)
    self.token_patch.start()
    self.addCleanup(self.token_patch.stop)


def test_live_success_sends_one_completion_notification(self):
    with (
        patch.object(main_module, "run_mode", return_value=RunResult(2)),
        patch.object(main_module, "send_pushplus") as send,
        patch.object(main_module.time, "monotonic", side_effect=[100.0, 165.0]),
    ):
        exit_code = main_module.main(
            ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "2"]
        )

    self.assertEqual(0, exit_code)
    title, content = send.call_args.args
    self.assertIn("主线已完成", title)
    self.assertIn("完成轮数：2/2", content)
    self.assertIn("耗时：65 秒", content)


def test_live_resource_stop_sends_one_resource_notification(self):
    with (
        patch.object(
            main_module,
            "run_mode",
            return_value=RunResult(3, resource_exhausted=True),
        ),
        patch.object(main_module, "send_pushplus") as send,
    ):
        exit_code = main_module.main(
            ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "5"]
        )

    self.assertEqual(2, exit_code)
    title, content = send.call_args.args
    self.assertIn("资源不足", title)
    self.assertIn("完成轮数：3/5", content)


def test_live_runtime_failure_sends_one_failure_notification(self):
    with (
        patch.object(main_module, "run_mode", side_effect=RuntimeError("unknown page")),
        patch.object(main_module, "send_pushplus") as send,
    ):
        exit_code = main_module.main(
            ["--mode", "arena", "--live", "--confirm", "RUN", "--max-cycles", "1"]
        )

    self.assertEqual(1, exit_code)
    title, content = send.call_args.args
    self.assertIn("竞技场运行失败", title)
    self.assertIn("unknown page", content)
    self.assertIn("runtime_diagnostics", content)


def test_unexpected_live_exception_notifies_then_preserves_exception(self):
    with (
        patch.object(main_module, "run_mode", side_effect=ValueError("bad state")),
        patch.object(main_module, "send_pushplus") as send,
        self.assertRaisesRegex(ValueError, "bad state"),
    ):
        main_module.main(
            ["--mode", "fodder", "--live", "--confirm", "RUN", "--max-cycles", "1"]
        )

    send.assert_called_once()


def test_manual_and_dry_runs_do_not_notify(self):
    cases = (
        (["--mode", "story", "--max-cycles", "1"], RunResult(1), None),
        (
            ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "1"],
            None,
            ManualStop("P"),
        ),
    )
    for arguments, result, error in cases:
        with self.subTest(arguments=arguments):
            effect = error if error is not None else None
            with (
                patch.object(main_module, "run_mode", return_value=result, side_effect=effect),
                patch.object(main_module, "send_pushplus") as send,
            ):
                main_module.main(arguments)
            send.assert_not_called()


def test_notification_bug_does_not_change_success_exit_code(self):
    with (
        patch.object(main_module, "run_mode", return_value=RunResult(1)),
        patch.object(main_module, "send_pushplus", side_effect=RuntimeError("notify bug")),
    ):
        exit_code = main_module.main(
            ["--mode", "expedition", "--live", "--confirm", "RUN", "--max-cycles", "1"]
        )

    self.assertEqual(0, exit_code)
```

- [ ] **Step 2: Run main tests and verify RED**

```powershell
python -m pytest auto_game_unified\tests\test_main_story.py -q
```

Expected: notification assertions fail because `main.py` has no terminal notification integration.

- [ ] **Step 3: Implement terminal formatting and dispatch**

In `main.py`, import `time` and `send_pushplus`, add a local Chinese mode label map, and add these helpers:

```python
import time

from auto_game_unified.core.pushplus import send_pushplus


MODE_LABELS = {
    "story": "主线",
    "arena": "竞技场",
    "expedition": "远征",
    "fodder": "狗粮",
}


def _elapsed_seconds(started_at: float) -> int:
    return max(0, round(time.monotonic() - started_at))


def _notify_live(
    *,
    live: bool,
    mode: str,
    status: str,
    elapsed_seconds: int,
    completed_cycles: int | None = None,
    target_cycles: int | None = None,
    error: Exception | None = None,
) -> None:
    if not live:
        return
    label = MODE_LABELS[mode]
    titles = {
        "completed": f"第七史诗：{label}已完成",
        "resource": f"第七史诗：{label}资源不足",
        "failed": f"第七史诗：{label}运行失败",
    }
    lines = [f"模式：{label}", f"耗时：{elapsed_seconds} 秒"]
    if completed_cycles is not None and target_cycles is not None:
        lines.insert(1, f"完成轮数：{completed_cycles}/{target_cycles}")
    if error is not None:
        lines.insert(1, f"原因：{error}")
        lines.append(f"诊断目录：{ROOT / 'runtime_diagnostics' / f'epic7_{mode}'}")
    try:
        send_pushplus(titles[status], "\n".join(lines))
    except Exception as notification_error:
        print(
            f"PushPlus 通知失败：{type(notification_error).__name__}",
            flush=True,
        )
```

Start `started_at = time.monotonic()` immediately before `run_mode()`. Call `_notify_live()` in the live `RuntimeError`, unexpected `Exception`, resource-exhausted, and successful branches. Keep `ManualStop` before the other exception handlers and do not call the helper there. For unexpected exceptions, notify and then use bare `raise` so the existing traceback semantics remain intact.

```python
    started_at = time.monotonic()
    try:
        result = run_mode(...)
    except ManualStop as error:
        print(f"手动停止 mode={args.mode} reason={error}", flush=True)
        return 130
    except RuntimeError as error:
        _notify_live(
            live=args.live,
            mode=args.mode,
            status="failed",
            elapsed_seconds=_elapsed_seconds(started_at),
            error=error,
        )
        print(f"运行失败 mode={args.mode} reason={error}", flush=True)
        return 1
    except Exception as error:
        _notify_live(
            live=args.live,
            mode=args.mode,
            status="failed",
            elapsed_seconds=_elapsed_seconds(started_at),
            error=error,
        )
        raise

    status = "resource" if result.resource_exhausted else "completed"
    _notify_live(
        live=args.live,
        mode=args.mode,
        status=status,
        elapsed_seconds=_elapsed_seconds(started_at),
        completed_cycles=result.completed_cycles,
        target_cycles=args.max_cycles,
    )
```

- [ ] **Step 4: Run main and transport tests and verify GREEN**

```powershell
python -m pytest auto_game_unified\tests\test_main_story.py auto_game_unified\tests\test_pushplus.py -q
```

Expected: all focused tests pass and no real HTTP request is made.

- [ ] **Step 5: Commit the unified integration**

```powershell
git add main.py tests/test_main_story.py
git commit -m "feat: notify live run terminal states"
```

### Task 3: User configuration documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the PushPlus setup section**

Add a section after “日志、截图和退出码” that tells the user to register and complete PushPlus verification, then configure the Token outside Git:

```markdown
## 安卓结束通知（PushPlus）

实跑达到目标次数、因允许的资源耗尽停止或发生运行故障时，可以通过 PushPlus 向微信发送一条通知。离线诊断和按 `P` 手动停止不会通知。

1. 登录 PushPlus，完成实名认证并取得用户 Token 或消息 Token。
2. 仅对当前 PowerShell 窗口启用：

   ```powershell
   $env:EPIC7_PUSHPLUS_TOKEN = "你的 Token"
   ```

3. 永久保存到当前 Windows 用户环境变量：

   ```powershell
   setx EPIC7_PUSHPLUS_TOKEN "你的 Token"
   ```

   `setx` 后需要关闭并重新打开终端才会生效。

Token 不要写进仓库文件、日志或聊天记录。未配置 Token 时，自动化仍会正常运行，终端会提示通知未启用。PushPlus 接口返回成功只代表平台接受了异步发送请求；手机最终投递仍取决于 PushPlus、微信和当前网络。
```

- [ ] **Step 2: Review the documentation diff**

```powershell
git diff --check
git diff -- README.md
```

Expected: no whitespace errors; commands use `EPIC7_PUSHPLUS_TOKEN` exactly.

- [ ] **Step 3: Commit documentation**

```powershell
git add README.md
git commit -m "docs: explain PushPlus notification setup"
```

### Task 4: Full offline verification

**Files:**
- Verify only; do not start the simulator and do not send a real PushPlus message.

- [ ] **Step 1: Ensure the verification shell cannot send notifications**

From `D:\AI\codex\auto_game`:

```powershell
Remove-Item Env:EPIC7_PUSHPLUS_TOKEN -ErrorAction SilentlyContinue
```

- [ ] **Step 2: Run the complete offline suite**

```powershell
python -m pytest auto_game_unified\tests -q
```

Expected: zero failed tests.

- [ ] **Step 3: Compile all Python modules**

```powershell
python -m compileall -q auto_game_unified
```

Expected: exit code `0` with no syntax errors.

- [ ] **Step 4: Inspect the final change set**

```powershell
git -C auto_game_unified diff --check origin/main...HEAD
git -C auto_game_unified status --short --branch
git -C auto_game_unified log --oneline --max-count=6
```

Expected: no whitespace errors, only approved notification code/tests/docs plus the approved design and plan, and no uncommitted files.

