"""Signed webhook intake and asynchronous review processing."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import Settings, settings
from app.github_client import DiffTooLargeError, GitHubClient
from app.reviewer import Reviewer
from app.security import verify_signature

logger = logging.getLogger(__name__)


class Repository(BaseModel):
    full_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$")

    @field_validator("full_name")
    @classmethod
    def safe_repository_path(cls, value: str) -> str:
        if value.split("/")[1] in {".", ".."}:
            raise ValueError("Invalid repository name")
        return value


class PullRequest(BaseModel):
    number: int = Field(gt=0, strict=True)


class PullRequestEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    repository: Repository
    number: int = Field(gt=0, strict=True)
    pull_request: PullRequest


class CommentAuthor(BaseModel):
    type: str


class Comment(BaseModel):
    body: str
    user: CommentAuthor


class CommentIssue(BaseModel):
    number: int = Field(gt=0, strict=True)
    state: Literal["open", "closed"]
    pull_request: dict | None = None


class IssueCommentEvent(BaseModel):
    repository: Repository
    issue: CommentIssue
    comment: Comment


async def process_review(app: FastAPI, repo: str, number: int) -> None:
    async with app.state.review_slots:
        operation = "fetching GitHub diff"
        try:
            diff = await app.state.github.fetch_diff(repo, number)
            if not diff.strip():
                logger.info("Skipping empty diff for %s#%d", repo, number)
                return
            operation = "generating LLM review"
            review = await app.state.reviewer.review(diff)
            operation = "posting GitHub comment"
            await app.state.github.post_comment(
                repo, number, "<!-- ai-pr-reviewer -->\n## AI Code Review\n\n" + review
            )
            logger.info("Review posted for %s#%d", repo, number)
        except DiffTooLargeError:
            logger.warning("Review skipped for %s#%d: diff exceeds MAX_DIFF_BYTES", repo, number)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Review failed for %s#%d while %s (HTTPStatusError, HTTP %d)",
                repo,
                number,
                operation,
                exc.response.status_code,
            )
        except Exception as exc:
            # Provider exception text can contain request content or credentials.
            logger.error(
                "Review failed for %s#%d while %s (%s)", repo, number, operation, type(exc).__name__
            )


def create_app(config: Settings = settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {config.GITHUB_TOKEN.get_secret_value()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "github-pr-reviewer",
            },
            timeout=config.HTTP_TIMEOUT,
            follow_redirects=False,
        ) as client:
            app.state.github = GitHubClient(client, config.MAX_DIFF_BYTES)
            app.state.reviewer = Reviewer(config)
            app.state.review_slots = asyncio.Semaphore(config.MAX_CONCURRENT_REVIEWS)
            yield

    app = FastAPI(title="GitHub PR Reviewer", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/webhook", status_code=202)
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > config.MAX_WEBHOOK_BYTES:
                raise HTTPException(413, "Webhook payload too large")
        if not verify_signature(
            bytes(body),
            request.headers.get("X-Hub-Signature-256"),
            config.WEBHOOK_SECRET.get_secret_value(),
        ):
            raise HTTPException(401, "Invalid webhook signature")
        event = request.headers.get("X-GitHub-Event")
        if not event:
            raise HTTPException(400, "Missing X-GitHub-Event header")
        if event not in {"pull_request", "issue_comment"}:
            return {"status": "ignored"}
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Invalid JSON") from None
        if not isinstance(payload, dict):
            raise HTTPException(400, "Expected a JSON object")
        if event == "issue_comment":
            if payload.get("action") != "created":
                return {"status": "ignored"}
            try:
                comment_event = IssueCommentEvent.model_validate(payload)
            except ValidationError:
                raise HTTPException(422, "Invalid issue comment payload") from None
            if (
                comment_event.issue.pull_request is None
                or comment_event.issue.state != "open"
                or comment_event.comment.user.type != "User"
                or comment_event.comment.body.strip() != "/review"
            ):
                return {"status": "ignored"}
            repo = comment_event.repository.full_name
            number = comment_event.issue.number
        else:
            if not config.AUTO_REVIEW or payload.get("action") not in ("opened", "synchronize"):
                return {"status": "ignored"}
            try:
                data = PullRequestEvent.model_validate(payload)
            except ValidationError:
                raise HTTPException(422, "Invalid pull request payload") from None
            if data.number != data.pull_request.number:
                raise HTTPException(422, "Pull request numbers do not match")
            repo = data.repository.full_name
            number = data.number
        background_tasks.add_task(process_review, app, repo, number)
        return {"status": "processing"}

    return app


app = create_app()


def run():
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT)


if __name__ == "__main__":
    run()
