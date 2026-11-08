import hashlib
import hmac
import json
import unittest
from unittest.mock import AsyncMock

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.github_client import DiffTooLargeError
from app.main import create_app
from app.security import verify_signature


def payload(action="opened"):
    return {
        "action": action,
        "number": 12,
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"number": 12, "diff_url": "https://untrusted.invalid/diff"},
    }


def comment_payload(body="/review", action="created"):
    return {
        "action": action,
        "repository": {"full_name": "owner/repo"},
        "issue": {"number": 12, "state": "open", "pull_request": {}},
        "comment": {"body": body, "user": {"type": "User"}},
    }


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Settings(_env_file=None))
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.app.state.github = AsyncMock()
        self.app.state.github.fetch_diff.return_value = "diff --git a/a.py b/a.py\n+print('hello')"
        self.app.state.reviewer = AsyncMock()
        self.app.state.reviewer.review.return_value = "## Critical Issues\nNone."

    def send(self, value, event="pull_request", signature=None):
        body = json.dumps(value).encode()
        digest = hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/webhook",
            content=body,
            headers={
                "X-GitHub-Event": event,
                "X-Hub-Signature-256": signature or "sha256=" + digest,
                "Content-Type": "application/json",
            },
        )

    def test_review_pipeline(self):
        for action in ["opened", "synchronize"]:
            with self.subTest(action=action):
                self.app.state.github.reset_mock()
                response = self.send(payload(action))
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json(), {"status": "processing"})
                self.app.state.github.fetch_diff.assert_awaited_once_with("owner/repo", 12)
                args = self.app.state.github.post_comment.await_args.args
                self.assertEqual(args[:2], ("owner/repo", 12))
                self.assertIn("## Critical Issues", args[2])

    def test_ignored_events(self):
        for event, action in [("ping", "opened"), ("issues", "opened"), ("pull_request", "closed")]:
            self.assertEqual(self.send(payload(action), event).json(), {"status": "ignored"})
        self.app.state.github.fetch_diff.assert_not_awaited()

    def test_review_command(self):
        for body in ["/review", "  /review\n"]:
            with self.subTest(body=body):
                self.app.state.github.reset_mock()
                response = self.send(comment_payload(body), event="issue_comment")
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json(), {"status": "processing"})
                self.app.state.github.fetch_diff.assert_awaited_once_with("owner/repo", 12)
                self.app.state.github.post_comment.assert_awaited_once()

    def test_ignored_comments(self):
        values = [
            comment_payload(body)
            for body in [
                "looks good",
                "/review please",
                "`/review`",
                "text\n/review",
                "/reviewer",
                "/REVIEW",
            ]
        ]
        values.extend(comment_payload(action=action) for action in ["edited", "deleted"])
        issue = comment_payload()
        issue["issue"].pop("pull_request")
        values.append(issue)
        closed = comment_payload()
        closed["issue"]["state"] = "closed"
        values.append(closed)
        bot = comment_payload()
        bot["comment"]["user"]["type"] = "Bot"
        values.append(bot)
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(
                    self.send(value, event="issue_comment").json(), {"status": "ignored"}
                )
        self.app.state.github.fetch_diff.assert_not_awaited()

    def test_invalid_comment_payload(self):
        for key in ["repository", "issue", "comment"]:
            value = comment_payload()
            value.pop(key)
            self.assertEqual(self.send(value, event="issue_comment").status_code, 422)
        self.app.state.github.fetch_diff.assert_not_awaited()

    def test_unsigned_command_rejected(self):
        self.assertEqual(
            self.send(comment_payload(), event="issue_comment", signature="sha256=bad").status_code,
            401,
        )
        self.app.state.github.fetch_diff.assert_not_awaited()

    def test_command_only_mode(self):
        self.app = create_app(Settings(_env_file=None, AUTO_REVIEW=False))
        with TestClient(self.app) as session:
            self.client = session
            self.app.state.github = AsyncMock()
            self.app.state.github.fetch_diff.return_value = "+change"
            self.app.state.reviewer = AsyncMock()
            self.app.state.reviewer.review.return_value = "Review"
            for action in ["opened", "synchronize"]:
                self.assertEqual(self.send(payload(action)).json(), {"status": "ignored"})
            self.app.state.github.fetch_diff.assert_not_awaited()
            self.assertEqual(
                self.send(comment_payload(), event="issue_comment").json(), {"status": "processing"}
            )
            self.app.state.github.post_comment.assert_awaited_once()

    def test_invalid_signature(self):
        for signature in ["sha256=bad", "sha1=bad"]:
            self.assertEqual(self.send(payload(), signature=signature).status_code, 401)
        self.assertFalse(verify_signature(b"{}", "sha256=é", "test-webhook-secret"))
        self.assertEqual(self.client.post("/webhook", json=payload()).status_code, 401)
        self.app.state.github.fetch_diff.assert_not_awaited()

    def test_invalid_payload(self):
        for value in [
            [],
            {"action": "opened"},
            {**payload(), "number": 13},
            {**payload(), "repository": {"full_name": "../repo"}},
            {**payload(), "repository": {"full_name": "owner/.."}},
        ]:
            self.assertIn(self.send(value).status_code, (400, 422))
        self.app.state.github.fetch_diff.assert_not_awaited()

    def test_invalid_json_and_missing_event(self):
        body = b"not json"
        signature = "sha256=" + hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()
        headers = {"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature}
        self.assertEqual(
            self.client.post("/webhook", content=body, headers=headers).status_code, 400
        )
        headers.pop("X-GitHub-Event")
        self.assertEqual(
            self.client.post("/webhook", content=body, headers=headers).status_code, 400
        )

    def test_payload_limit(self):
        with TestClient(create_app(Settings(_env_file=None, MAX_WEBHOOK_BYTES=10))) as session:
            self.assertEqual(session.post("/webhook", content=b"x" * 11).status_code, 413)

    def test_background_failures(self):
        for failure in [RuntimeError("private provider details"), DiffTooLargeError()]:
            self.app.state.github.fetch_diff.side_effect = failure
            with self.assertLogs("app.main") as logs:
                self.assertEqual(self.send(payload()).status_code, 202)
            self.assertIn("owner/repo#12", " ".join(logs.output))
            self.assertNotIn("private provider details", " ".join(logs.output))
        self.app.state.github.post_comment.assert_not_awaited()

    def test_empty_diff_skipped(self):
        self.app.state.github.fetch_diff.return_value = ""
        self.assertEqual(self.send(payload()).status_code, 202)
        self.app.state.reviewer.review.assert_not_awaited()
        self.app.state.github.post_comment.assert_not_awaited()

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_github_failures_identify_operation_and_status(self):
        for method, operation, status in [
            ("fetch_diff", "fetching GitHub diff", 404),
            ("post_comment", "posting GitHub comment", 403),
        ]:
            with self.subTest(method=method):
                self.app.state.github.fetch_diff.side_effect = None
                self.app.state.github.post_comment.side_effect = None
                request = httpx.Request("GET", "https://api.github.com/private?token=secret")
                response = httpx.Response(status, request=request, text="private response")
                getattr(self.app.state.github, method).side_effect = httpx.HTTPStatusError(
                    "private error message",
                    request=request,
                    response=response,
                )
                with self.assertLogs("app.main") as captured:
                    self.assertEqual(
                        self.send(comment_payload(), event="issue_comment").status_code, 202
                    )
                output = " ".join(captured.output)
                self.assertIn(operation, output)
                self.assertIn(f"HTTP {status}", output)
                self.assertNotIn("private", output)
                self.assertNotIn("secret", output)
