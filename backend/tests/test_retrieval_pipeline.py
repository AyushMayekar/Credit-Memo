import unittest

from app.ai.retrieval.json_utils import LlmJsonError, parse_json_object


class RetrievalPipelineTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(parse_json_object('{"answer":"ok"}')["answer"], "ok")

    def test_markdown_json(self):
        value = parse_json_object('```json\n{"answer":"ok"}\n```')
        self.assertEqual(value["answer"], "ok")

    def test_prefixed_json(self):
        value = parse_json_object('Here is the result:\n{"answer":"ok"}\nThank you')
        self.assertEqual(value["answer"], "ok")

    def test_braces_inside_string(self):
        value = parse_json_object('prefix {"answer":"value with { braces }"} suffix')
        self.assertIn("braces", value["answer"])

    def test_empty_rejected(self):
        with self.assertRaises(LlmJsonError):
            parse_json_object("  ")

    def test_incomplete_rejected(self):
        with self.assertRaises(LlmJsonError):
            parse_json_object('{"answer":')


if __name__ == "__main__":
    unittest.main()
