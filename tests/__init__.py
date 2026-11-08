"""Offline tests with test-only credentials."""

import os

os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["GITHUB_TOKEN"] = "test-github-token"
os.environ["LLM_API_KEY"] = "test-llm-key"
