# Contributing

Open an issue describing the problem, expected behavior, and reproduction steps.
Remove tokens, webhook secrets, private source code, and sensitive log output.
Discuss substantial changes in an issue before starting implementation.

Fork the repository, create a branch, and follow the local development setup in
README.md. Use Python 3.11 or newer and install `requirements-dev.txt`.

Before opening a pull request, run:

```sh
python -m unittest discover -v
ruff check .
ruff format --check .
docker build -t github-pr-reviewer .
```

Add meaningful tests for changed behavior. Mock GitHub and LLM calls so tests
remain offline. Keep webhook signature validation and secret handling intact.
Never commit `.env`, credentials, or captured private webhook payloads.

In your pull request, explain the problem, resulting behavior, and validation
performed. Update documentation and `.env.example` when configuration changes.
Contributions are licensed under the repository's MIT License.
