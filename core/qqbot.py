import json
import os
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen


# 官方 QQ 机器人平台地址（固定，不随部署变化）。
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
DEFAULT_API_BASE = "https://api.sgroup.qq.com"
APP_ID_ENV = "EPIC7_QQBOT_APP_ID"
CLIENT_SECRET_ENV = "EPIC7_QQBOT_CLIENT_SECRET"
USER_OPENID_ENV = "EPIC7_QQBOT_USER_OPENID"
BASE_URL_ENV = "EPIC7_QQBOT_BASE_URL"
REQUEST_TIMEOUT_SECONDS = 5.0
SEND_C2C_PATH = "/v2/users/{user_openid}/messages"


def get_access_token(
    app_id: str,
    client_secret: str,
    *,
    opener: Callable[..., Any] = urlopen,
    output: Callable[[str], None] = print,
) -> str | None:
    """用 AppID/AppSecret 换 access_token。拿不到就返回 None（旁路边走边报错）。"""
    body = json.dumps(
        {"appId": app_id, "clientSecret": client_secret}, ensure_ascii=False
    ).encode("utf-8")
    request = Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        output(f"QQ 通知失败：获取 token 时 {type(error).__name__}")
        return None

    if not isinstance(result, dict):
        output("QQ 通知失败：获取 token 返回格式异常")
        return None
    # 官方接口即便失败也返回 HTTP 200，错误码放在响应体的 code 字段里。
    token = result.get("access_token")
    if not token:
        code = result.get("code")
        message = result.get("message")
        output(f"QQ 通知失败：获取 token 失败 code={code!r} message={message!r}")
        return None
    return token


def send_qqbot_c2c(
    title: str,
    content: str,
    *,
    environ: Mapping[str, str] | None = None,
    opener: Callable[..., Any] = urlopen,
    output: Callable[[str], None] = print,
) -> bool:
    """把一条通知私聊发给配置好的 QQ 用户（官方 API 的 C2C 主动消息）。

    没配 AppID/Secret/对方 openid 就当成「这条路没启用」：只打一行提示、不发请求。
    通知是旁路，配没配都不该让主流程出动静、也不改退出码。
    """
    environment = os.environ if environ is None else environ
    app_id = environment.get(APP_ID_ENV, "").strip()
    client_secret = environment.get(CLIENT_SECRET_ENV, "").strip()
    user_openid = environment.get(USER_OPENID_ENV, "").strip()
    if not (app_id and client_secret and user_openid):
        output(
            "QQ 通知未启用：未配置 "
            f"{APP_ID_ENV} / {CLIENT_SECRET_ENV} / {USER_OPENID_ENV}"
        )
        return False

    token = get_access_token(app_id, client_secret, opener=opener, output=output)
    if token is None:
        return False

    base = environment.get(BASE_URL_ENV, "").strip() or DEFAULT_API_BASE
    url = f"{base.rstrip('/')}{SEND_C2C_PATH.format(user_openid=user_openid)}"
    # 标题没有独立字段，并进正文首行；官方接口用 QQBot 前缀（不是 Bearer）。
    body = json.dumps(
        {"msg_type": 0, "content": f"{title}\n{content}"},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"QQBot {token}",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        output(f"QQ 通知失败：发送时 {type(error).__name__}")
        return False

    if not isinstance(result, dict):
        output("QQ 通知失败：发送返回格式异常")
        return False
    # 同 token 接口：失败也是 HTTP 200 + code 字段。有 id 才算真的发出去了。
    code = result.get("code")
    if code is not None and code != 0:
        message = result.get("message")
        output(f"QQ 通知失败：code={code!r} message={message!r}")
        return False
    return True
