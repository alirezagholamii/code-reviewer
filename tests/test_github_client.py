import json
import unittest

import httpx

from app.github_client import DiffTooLargeError, GitHubClient


class GitHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_and_comment(self):
        seen = []

        def handler(request):
            seen.append(request)
            if request.method == "GET":
                self.assertEqual(request.headers["Accept"], "application/vnd.github.v3.diff")
                return httpx.Response(200, text="diff --git a/a b/a\n+hello")
            self.assertEqual(json.loads(request.content), {"body": "review"})
            return httpx.Response(201, json={"id": 1})

        async with httpx.AsyncClient(
            base_url="https://api.github.com", transport=httpx.MockTransport(handler)
        ) as http:
            github = GitHubClient(http, 1000)
            self.assertIn("+hello", await github.fetch_diff("owner/repo", 1))
            await github.post_comment("owner/repo", 1, "review")
        self.assertEqual(
            [r.url.path for r in seen],
            ["/repos/owner/repo/pulls/1", "/repos/owner/repo/issues/1/comments"],
        )

    async def test_diff_limit(self):
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 11)),
        ) as http:
            with self.assertRaises(DiffTooLargeError):
                await GitHubClient(http, 10).fetch_diff("owner/repo", 1)

    async def test_http_errors(self):
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(lambda _: httpx.Response(403)),
        ) as http:
            github = GitHubClient(http, 100)
            with self.assertRaises(httpx.HTTPStatusError):
                await github.fetch_diff("owner/repo", 1)
            with self.assertRaises(httpx.HTTPStatusError):
                await github.post_comment("owner/repo", 1, "review")
