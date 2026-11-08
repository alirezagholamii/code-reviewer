import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.config import Settings
from app.reviewer import Reviewer


class ReviewerTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_and_output(self):
        captured = {}

        def fake_model(**kwargs):
            captured.update(kwargs)

            def respond(prompt):
                messages = prompt.to_messages()
                self.assertIn("Principal Software Engineer", messages[0].content)
                self.assertIn("untrusted data", messages[0].content)
                self.assertIn("+{literal braces}", messages[1].content)
                return AIMessage(content="  ## Critical Issues\nNone.  ")

            return RunnableLambda(respond)

        with patch("app.reviewer.ChatOpenAI", fake_model):
            reviewer = Reviewer(Settings(_env_file=None))
            result = await reviewer.review("+{literal braces}")
        self.assertEqual(result, "## Critical Issues\nNone.")
        self.assertEqual(captured["base_url"], "https://api.openai.com/v1")
        self.assertEqual(captured["api_key"], "test-llm-key")

    async def test_empty_output(self):
        with patch(
            "app.reviewer.ChatOpenAI",
            lambda **kwargs: RunnableLambda(lambda _: AIMessage(content=" ")),
        ):
            with self.assertRaisesRegex(ValueError, "empty review"):
                await Reviewer(Settings(_env_file=None)).review("diff")

    async def test_output_limit(self):
        with patch(
            "app.reviewer.ChatOpenAI",
            lambda **kwargs: RunnableLambda(lambda _: AIMessage(content="x" * 15000)),
        ):
            self.assertEqual(len(await Reviewer(Settings(_env_file=None)).review("diff")), 12000)
