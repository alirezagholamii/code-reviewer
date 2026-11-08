# GitHub PR Reviewer Bot

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Docker](https://img.shields.io/badge/Docker-ready-blue)

Self-hosted AI pull request reviews using FastAPI and LangChain. Use OpenAI, an
OpenAI-compatible Chat Completions endpoint, or a local Ollama model. Signed GitHub
`pull_request` events (`opened` and `synchronize`) and `/review` PR comments trigger
Markdown reviews covering critical issues, suggestions, and positive notes.

## Quick start

1. Clone your copy of this repository and enter its directory:
   ```sh
   git clone https://github.com/alirezagholamii/code-reviewer.git
   cd code-reviewer
   cp .env.example .env
   ```
2. Edit `.env`: set a strong `WEBHOOK_SECRET`, a GitHub token, and your LLM settings.
   Generate a secret with `python -c 'import secrets; print(secrets.token_hex(32))'`.
   Set `GITHUB_TOKEN` to a GitHub access token using the
   [token setup below](#github-token-setup). The token needs access to the target
   repositories with **Read and write** access to both **Issues** and **Pull requests**.
   A GitHub App installation
   token with equivalent permissions also works, but token refresh must be
   handled externally. Classic PATs need `repo` for private repositories.
3. Start the service:
   ```sh
   docker compose up --build -d
   curl http://localhost:8000/health
   docker compose logs -f pr-reviewer
   ```
   Legacy installations can use `docker-compose up --build -d`.
4. Expose the service through HTTPS using your reverse proxy or development tunnel.
   In GitHub, open **Repository → Settings → Webhooks → Add webhook**:
   - Payload URL: `https://your-host/webhook`
   - Content type: `application/json`
   - Secret: the exact `WEBHOOK_SECRET` from `.env`
   - Select individual events → **Issue comments** (required for `/review`) and
     **Pull requests** (for automatic reviews); keep the webhook active.
5. Post `/review` as a new comment in an open PR's **Conversation** tab, or open a
   PR or push a commit for automatic reviews. Check **Recent deliveries** and
   the service logs. A signed ping is ignored successfully. Accepted PR events
   return HTTP 202 with `{"status":"processing"}`; the comment arrives later.

## GitHub token setup

`WEBHOOK_SECRET` and `GITHUB_TOKEN` have separate purposes:

| Setting | Value and purpose |
| --- | --- |
| `WEBHOOK_SECRET` | A secret you generate and enter in GitHub's webhook **Secret** field; authenticates incoming deliveries |
| `GITHUB_TOKEN` | A GitHub personal access token or App token; authorizes fetching diffs and posting comments |

To configure a fine-grained personal access token:

1. Open your GitHub account **Settings → Developer settings → Personal access
   tokens → Fine-grained tokens** and create or edit a token.
2. Choose the resource owner for the repositories you want to review, and include
   those repositories under **Repository access**.
3. Under **Repository permissions**, set:
   - **Issues → Read and write**.
   - **Pull requests → Read and write**.
4. Save the token and put its value in `GITHUB_TOKEN` in `.env`.

Use **Read and write** for both permissions to match the working configuration.
The bot fetches the PR diff and posts a conversation comment through GitHub's
issue comments API. See the
[comment endpoint permissions](https://docs.github.com/en/rest/issues/comments#create-an-issue-comment).

After replacing a token or changing `.env`, recreate the container so it receives
the updated environment:

```sh
docker compose up -d --force-recreate
```

## Request a review with `/review`

Post a new PR conversation comment containing only:

```text
/review
```

Surrounding whitespace is accepted. The command is case-sensitive. Inline code
comments, edited comments, regular issues, closed PRs, and bot comments do not
trigger reviews. Anyone who can post a human comment on the PR can request a
review. The bot fetches the current diff and posts its review in the same PR.

For command-only reviews, set `AUTO_REVIEW=false` in `.env` and rebuild/restart:

```sh
docker compose up --build -d
```

Automatic reviews remain enabled by default. Make sure an existing webhook also
subscribes to **Issue comments**. GitHub delivers PR conversation comments through
the [`issue_comment` event](https://docs.github.com/en/webhooks/webhook-events-and-payloads#issue_comment).

## Providers and configuration

`.env.example` lists all configuration. Environment variables override `.env`.
`HOST` and `PORT` control the native and container server. Compose publishes `PORT`
(default 8000). Keep `HOST=0.0.0.0` inside Docker so the published port is reachable.
Restart the service after changing settings.

For OpenAI, keep `LLM_PROVIDER=openai`, set `LLM_API_KEY`, and choose
`LLM_MODEL_NAME`. Omit `LLM_BASE_URL` to use `https://api.openai.com/v1`.
For OpenRouter, DeepSeek, or another compatible service, set a descriptive
`LLM_PROVIDER` and explicitly set its `LLM_BASE_URL`, key, and model. The provider
label selects defaults only; all requests use LangChain's `ChatOpenAI` client.
Provider-specific features are not implemented. Choose a model that accepts a
`temperature` parameter.

For Ollama, first pull a model on the host (for example, `ollama pull llama3`), then:

```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_MODEL_NAME=llama3
LLM_TEMPERATURE=0.2
```

Native execution uses `http://localhost:11434/v1` by default for Ollama. Docker
must use the host address above. On Linux, Ollama must listen on an interface
reachable from the container; restrict access with your firewall.

| Setting | Default | Purpose |
| --- | --- | --- |
| `AUTO_REVIEW` | true | Review opened/updated PRs automatically; `/review` works in either mode |
| `HTTP_TIMEOUT` | 30 | GitHub request timeout in seconds |
| `LLM_TIMEOUT` | 120 | Per-request model timeout in seconds; up to two retries |
| `MAX_WEBHOOK_BYTES` | 2000000 | Incoming request size limit |
| `MAX_DIFF_BYTES` | 100000 | Diff size limit; larger PRs are skipped and logged |
| `MAX_CONCURRENT_REVIEWS` | 4 | Simultaneous review pipelines per process |

The byte limit is not a token limit. Tune it to your model's context window.
Diffs are never silently truncated. Reviews are capped at 12000 characters.
GitHub errors, oversized diffs, and model failures are logged without provider
exception text. Failed reviews do not post comments and require a new event or
manual redelivery after fixing the cause.

## Troubleshooting reviews

`GET /health` confirms the service responds; it does not check GitHub credentials,
LLM connectivity, or permission to post comments. `GET /` returns 404 because the
service has no homepage.

Watch the logs while posting a new `/review` comment:

```sh
docker compose logs --tail=100 -f pr-reviewer
```

In GitHub, check **Repository → Settings → Webhooks → your webhook → Recent
deliveries** for the matching `issue_comment` event.

| Result | What to check |
| --- | --- |
| No delivery | Enable **Issue comments** and make sure the webhook is active |
| Connection failure or webhook 404 | Use a public HTTPS payload URL ending in `/webhook` |
| Webhook 401 | Match the webhook Secret to `WEBHOOK_SECRET` exactly |
| Webhook 422 | Check the event payload for missing or invalid fields |
| 202 with `ignored` | Post exactly `/review` as a new human conversation comment on an open PR |
| 202 with `processing` | The job was accepted; inspect service logs for its later outcome |
| Failure while fetching GitHub diff | Check token validity, repository access, and **Pull requests: Read and write** |
| Failure while generating LLM review | Check the LLM URL, key, model, context size, and provider connectivity |
| Failure while posting GitHub comment, HTTP 403 | Check **Read and write** access to both **Issues** and **Pull requests** on the token used by the container |

For example, this log means diff retrieval and review generation completed, but
GitHub rejected comment creation:

```text
Review failed for owner/repo#1 while posting GitHub comment (HTTPStatusError, HTTP 403)
```

Confirm the token includes the affected repository and has comment write
permission. If you changed `.env`, recreate the container using the command above,
then post a new `/review`. GitHub can also return 403 for rate limits or other
restrictions; if permissions are correct, consult its
[REST API troubleshooting guide](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api).
Background failures do not automatically retry the entire review.

## Local development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # if you have not configured it already
# Edit .env before starting the server.
python -m app.main
```

Run offline unit tests and lint checks:

```sh
python -m unittest discover -v
ruff check .
ruff format --check .
```

Tests use fake credentials, mocked GitHub HTTP responses, and a fake LangChain
model. They never post to GitHub or call a paid model.

## Operational scope

- Signature verification uses HMAC SHA-256 over raw request bytes and a constant
  time comparison. Payload URLs are not followed; GitHub requests target a fixed
  API host. Keep `.env` private; it is excluded from Git and Docker images.
- Diffs, including private repository code, are sent to your configured LLM.
  Review that provider's data policy or use Ollama. Prompts treat diff content as
  untrusted input, but generated reviews still need human judgment.
- Background tasks run in the web process. Restarts lose pending work. There is
  no persistent queue, automatic job retry, delivery deduplication, or stale-head
  check. Redeliveries can post duplicate comments, and rapid pushes can produce
  out-of-order reviews. Use a durable queue and head-SHA coordination before
  relying on this service for high-volume workloads. The semaphore limits active
  reviews, but waiting tasks remain in memory.
- Use trusted webhook configuration and secret holders: there is no repository
  allowlist. The bot only comments; it does not approve, merge, or execute code.

See the [documentation index](docs/README.md) and [architecture guide](docs/architecture.md)
for components, webhook flows, deployment, and operational limits.
See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

API references: [GitHub signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
and [LangChain ChatOpenAI](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI).
