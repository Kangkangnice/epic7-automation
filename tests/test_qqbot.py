import json
import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from auto_game_unified.core import qqbot


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


class _FakeOpener:
    """按 URL 子串回放固定响应；token 与发消息是两个不同地址。"""

    def __init__(self, by_marker: dict[str, object]) -> None:
        self._by_marker = by_marker
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> _FakeResponse:
        self.requests.append(request)
        url = request.full_url
        for marker, payload in self._by_marker.items():
            if marker in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResponse(payload.encode("utf-8"))
        raise AssertionError(f"unexpected url {url}")


def _env(**overrides: str) -> dict[str, str]:
    base = {
        qqbot.APP_ID_ENV: "APPID",
        qqbot.CLIENT_SECRET_ENV: "SECRET",
        qqbot.USER_OPENID_ENV: "OPENID",
    }
    base.update(overrides)
    return base


class QqbotTests(unittest.TestCase):
    def test_missing_config_disables_notification_without_request(self):
        opener = _FakeOpener({})
        sent = qqbot.send_qqbot_c2c(
            "标题", "内容", environ=_env(**{qqbot.APP_ID_ENV: ""}), opener=opener
        )
        self.assertFalse(sent)
        self.assertEqual([], opener.requests)

    def test_token_failure_disables_notification(self):
        opener = _FakeOpener({"getAppAccessToken": '{"code": 100016, "message": "bad"}'})
        sent = qqbot.send_qqbot_c2c("标题", "内容", environ=_env(), opener=opener)
        self.assertFalse(sent)
        # token 没拿到，就不该再去发消息。
        self.assertEqual(1, len(opener.requests))

    def test_send_success_uses_qqbot_header_and_c2c_path(self):
        opener = _FakeOpener(
            {
                "getAppAccessToken": '{"access_token": "TOK", "expires_in": "7200"}',
                "/v2/users/": '{"id": "MSGID"}',
            }
        )
        sent = qqbot.send_qqbot_c2c(
            "第七史诗：主线已完成", "完成轮数：2/2", environ=_env(), opener=opener
        )
        self.assertTrue(sent)
        self.assertEqual(2, len(opener.requests))

        token_request, send_request = opener.requests
        self.assertIn("getAppAccessToken", token_request.full_url)
        self.assertIn("/v2/users/OPENID/messages", send_request.full_url)
        self.assertEqual("QQBot TOK", send_request.headers.get("Authorization"))
        sent_body = json.loads(send_request.data.decode("utf-8"))
        self.assertEqual(0, sent_body["msg_type"])
        self.assertIn("第七史诗：主线已完成", sent_body["content"])
        self.assertIn("完成轮数：2/2", sent_body["content"])

    def test_send_failure_code_returns_false(self):
        opener = _FakeOpener(
            {
                "getAppAccessToken": '{"access_token": "TOK", "expires_in": "7200"}',
                "/v2/users/": '{"code": 304031, "message": "no permission"}',
            }
        )
        sent = qqbot.send_qqbot_c2c("标题", "内容", environ=_env(), opener=opener)
        self.assertFalse(sent)

    def test_token_network_error_returns_false(self):
        opener = _FakeOpener({"getAppAccessToken": OSError("connection refused")})
        sent = qqbot.send_qqbot_c2c("标题", "内容", environ=_env(), opener=opener)
        self.assertFalse(sent)

    def test_malformed_token_response_returns_false(self):
        opener = _FakeOpener({"getAppAccessToken": "not json"})
        sent = qqbot.send_qqbot_c2c("标题", "内容", environ=_env(), opener=opener)
        self.assertFalse(sent)

    def test_sandbox_base_url_is_used_when_configured(self):
        opener = _FakeOpener(
            {
                "getAppAccessToken": '{"access_token": "TOK", "expires_in": "7200"}',
                "/v2/users/": '{"id": "MSGID"}',
            }
        )
        environ = _env(**{qqbot.BASE_URL_ENV: "https://sandbox.api.sgroup.qq.com/"})
        sent = qqbot.send_qqbot_c2c("标题", "内容", environ=environ, opener=opener)
        self.assertTrue(sent)
        self.assertIn(
            "https://sandbox.api.sgroup.qq.com/v2/users/OPENID/messages",
            opener.requests[1].full_url,
        )


if __name__ == "__main__":
    unittest.main()
