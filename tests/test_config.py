import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.config import Settings


class ConfigTests(unittest.TestCase):
    def test_ollama_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = Settings(
                _env_file=None, WEBHOOK_SECRET="secret", GITHUB_TOKEN="token", LLM_PROVIDER="ollama"
            )
        self.assertEqual(config.LLM_BASE_URL, "http://localhost:11434/v1")
        self.assertEqual(config.LLM_API_KEY.get_secret_value(), "ollama")

    def test_invalid_configuration(self):
        for overrides in [
            {"WEBHOOK_SECRET": " "},
            {"PORT": 0},
            {"LLM_TEMPERATURE": 3},
            {"LLM_BASE_URL": "file:///tmp/model"},
            {"LLM_PROVIDER": "custom"},
            {"LLM_BASE_URL": "https://user:secret@example.com/v1"},
        ]:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                Settings(_env_file=None, **overrides)

    def test_missing_credentials(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValidationError):
            Settings(_env_file=None)
