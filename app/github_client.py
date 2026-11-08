"""Async GitHub REST access. Never follow URLs supplied in a webhook payload."""

import httpx


class DiffTooLargeError(ValueError):
    """The diff cannot safely fit into the configured review budget."""


class GitHubClient:
    def __init__(self, client: httpx.AsyncClient, max_diff_bytes: int):
        self.client = client
        self.max_diff_bytes = max_diff_bytes

    async def fetch_diff(self, repo_full_name: str, number: int) -> str:
        async with self.client.stream(
            "GET",
            f"/repos/{repo_full_name}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        ) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self.max_diff_bytes:
                    raise DiffTooLargeError("Diff exceeds MAX_DIFF_BYTES")
            return content.decode("utf-8", errors="replace")

    async def post_comment(self, repo_full_name: str, number: int, body: str) -> None:
        response = await self.client.post(
            f"/repos/{repo_full_name}/issues/{number}/comments", json={"body": body}
        )
        response.raise_for_status()
