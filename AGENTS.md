# AGENTS.md — AI Code Reviewer Bot (LangChain + FastAPI + Docker)

This document provides complete instructions, architecture guidelines, and technical specifications for autonomous coding agents building and open-sourcing the **GitHub PR Reviewer Bot**.

---

## 1. Project Overview
A containerized Python webhook service that listens to GitHub Pull Request events, retrieves the PR diff, analyzes the code changes using LangChain with a customizable LLM backend (OpenAI, OpenAI-compatible providers, or self-hosted Ollama), and automatically posts constructive code reviews as comments back to the GitHub PR.

---

## 2. Tech Stack & Dependencies
* **Language:** Python 3.11+
* **Framework:** FastAPI + Uvicorn (ASGI server)
* **AI/Orchestration:** LangChain (`langchain-core`, `langchain-openai`)
* **HTTP Client:** `httpx` or `requests` (for GitHub API interactions)
* **Containerization:** Docker & Docker Compose
* **Configuration:** Pydantic-Settings (`pydantic-settings`) reading from `.env`

---

## 3. Directory Structure
```text
.
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .env
├── requirements.txt
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entrypoint & webhook router
│   ├── config.py            # Pydantic settings parsing environment variables
│   ├── github_client.py     # GitHub API interactions (fetch diff, post comment)
│   ├── security.py          # HMAC SHA-256 webhook signature verification
│   └── reviewer.py          # LangChain setup and prompt chain execution
└── tests/
    ├── __init__.py
    ├── test_webhook.py
    └── test_reviewer.py
```

---

## 4. Configuration & Environment Variables (`.env`)

The application must be completely configurable via environment variables in a `.env` file. LangChain's `ChatOpenAI` client will be configured dynamically using `base_url` to support OpenAI, OpenAI-compatible APIs, and local Ollama instances.

### Required `.env.example` Schema:
```env
# Server Configuration
PORT=8000
HOST=0.0.0.0
WEBHOOK_SECRET=your_github_webhook_secret_here

# GitHub Integration
GITHUB_TOKEN=ghp_your_github_personal_access_token_or_app_token

# LLM Configuration (Supports OpenAI, OpenRouter, DeepSeek, Local Ollama, etc.)
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1          # Use http://host.docker.internal:11434/v1 for local Ollama
LLM_API_KEY=sk-your-api-key-here                # Use "ollama" if running local Ollama without auth
LLM_MODEL_NAME=gpt-4o                           # Use "llama3" or "deepseek-coder" for Ollama
LLM_TEMPERATURE=0.2
```

---

## 5. Core Architectural Modules

### A. Configuration (`app/config.py`)
Use `pydantic-settings` to load and validate all environment variables on startup.
* Expose a singleton `settings` object.
* Ensure `LLM_BASE_URL` defaults correctly depending on whether the user targets OpenAI or Ollama.

### B. Webhook Security (`app/security.py`)
* Implement GitHub Webhook HMAC SHA-256 signature validation.
* Compare the `X-Hub-Signature-256` header against the computed hash of the raw request body using `WEBHOOK_SECRET`. Reject requests with invalid signatures (`401 Unauthorized`).

### C. GitHub Client (`app/github_client.py`)
* **Fetch Diff:** Given `repo_full_name` and `pull_request_number`, call GitHub REST API (`GET /repos/{owner}/{repo}/pulls/{number}`) with `Accept: application/vnd.github.v3.diff` to retrieve the raw git diff.
* **Post Comment:** Call GitHub REST API (`POST /repos/{owner}/{repo}/issues/{number}/comments`) to post the AI-generated review summary back to the pull request.

### D. LangChain Reviewer Engine (`app/reviewer.py`)
* Initialize LangChain's `ChatOpenAI`:
  ```python
  from langchain_openai import ChatOpenAI
  from app.config import settings

  llm = ChatOpenAI(
      base_url=settings.LLM_BASE_URL,
      api_key=settings.LLM_API_KEY,
      model=settings.LLM_MODEL_NAME,
      temperature=settings.LLM_TEMPERATURE
  )
  ```
* **Prompt Engineering:** Create a structured prompt instructing the LLM to act as a Principal Software Engineer. Focus the review on:
  1. Bugs, edge cases, and concurrency issues.
  2. Security vulnerabilities (injection, auth flaws, secret leaks).
  3. Performance bottlenecks and memory leaks.
  4. Clean code architecture and readability.
* **Output Format:** Markdown-formatted review comment with clear categorization (Critical Issues, Suggestions, Positive Notes).

### E. Webhook Router (`app/main.py`)
* FastAPI endpoint: `POST /webhook`
* Verify headers. Filter incoming action events: process only when `action` in `["opened", "synchronize"]` for `pull_request` payloads.
* Extract `repo_full_name`, `pr_number`, and clone/diff URL.
* Trigger background task or direct async processing to fetch diff, run LLM review, and post comment to GitHub, returning `{"status": "processing"}` immediately to avoid webhook timeouts.

---

## 6. Docker & Deployment Specification

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose (`docker-compose.yml`)
```yaml
version: '3.8'

services:
  pr-reviewer:
    build: .
    container_name: github-pr-reviewer
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

---

## 7. Open Source Readiness & Documentation Files

To publish this project successfully as open source on GitHub, the agent coder must also generate the following standard repository files:

### A. `README.md`
Must include:
* Project title & badges (License, Python version, Docker).
* Clear value proposition (Self-hosted AI PR reviewer compatible with OpenAI and Ollama).
* Step-by-step setup guide (Clone, configure `.env`, run `docker-compose up -d`).
* How to configure GitHub Webhooks.

### B. `LICENSE`
* Standard **MIT License** to allow broad open-source community usage.

### C. `CONTRIBUTING.md`
* Guidelines on how community members can submit issues, run tests locally, and open pull requests.

---

## 8. Implementation & Testing Guidelines for Agent Coder
1. **Step 1:** Create `requirements.txt` containing FastAPI, Uvicorn, langchain-core, langchain-openai, pydantic-settings, and httpx.
2. **Step 2:** Implement `app/config.py` with robust Pydantic validation.
3. **Step 3:** Implement `app/security.py` for GitHub HMAC signature verification.
4. **Step 4:** Implement `app/github_client.py` using `httpx` async client for fetching diffs and posting PR comments.
5. **Step 5:** Implement `app/reviewer.py` using LangChain's `ChatOpenAI` and system prompts tailored for code reviews.
6. **Step 6:** Implement `app/main.py` tying everything together into an asynchronous FastAPI endpoint.
7. **Step 7:** Create open-source collateral (`README.md`, `LICENSE`, `CONTRIBUTING.md`, `.env.example`).
8. **Step 8:** Write unit tests under `tests/` mocking GitHub API responses and LLM outputs.
9. **Step 9:** Verify Docker build and local execution readiness.