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
