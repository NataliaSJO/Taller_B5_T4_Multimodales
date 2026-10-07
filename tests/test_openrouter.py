"""Verify OpenRouter request construction without making a network call."""

import importlib.util
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.preferences import parse_with_optional_llm


@unittest.skipUnless(importlib.util.find_spec("openai") and importlib.util.find_spec("pydantic"),
                     "El complemento de IA es opcional")
class OpenRouterTests(unittest.TestCase):
    def test_structured_extraction_uses_router_and_validates_result(self):
        payload = ('{"horizon_years":5,"risk":"medio","currency":"EUR","amount":null,'
                   '"region":"global","sector":null,"excluded_sectors":[],"asset_class":null}')
        answer = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only", "OPENROUTER_MODEL": "openai/gpt-6-luna"}), \
             patch("openai.OpenAI") as client_type:
            client_type.return_value.chat.completions.create.return_value = answer
            profile, method = parse_with_optional_llm("Quiero fondos globales en euros a 5 años, riesgo medio", True)

        self.assertEqual(profile.region, "global")
        self.assertEqual(profile.risk, "medio")
        self.assertIn("OpenRouter", method)
        self.assertEqual(client_type.call_args.kwargs["base_url"], "https://openrouter.ai/api/v1")
        request = client_type.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "openai/gpt-6-luna")
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertTrue(request["extra_body"]["provider"]["require_parameters"])
        self.assertEqual(request["extra_body"]["reasoning"]["effort"], "none")


if __name__ == "__main__":
    unittest.main()
