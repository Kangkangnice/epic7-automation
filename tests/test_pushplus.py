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
            return FakeResponse(b"{}")

        messages = []
        sent = send_pushplus(
            "title", "content", environ={}, opener=open_request, output=messages.append
        )

        self.assertFalse(sent)
        self.assertFalse(called)
        self.assertEqual(
            ["PushPlus 通知未启用：未配置 EPIC7_PUSHPLUS_TOKEN"], messages
        )

    def test_remote_and_network_failures_are_sanitized(self):
        def remote_failure(request, *, timeout):
            return FakeResponse(b'{"code": 903, "msg": "bad"}')

        def malformed_response(request, *, timeout):
            return FakeResponse(b"not-json")

        def network_failure(request, *, timeout):
            raise TimeoutError("secret-token")

        for opener in (remote_failure, malformed_response, network_failure):
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
