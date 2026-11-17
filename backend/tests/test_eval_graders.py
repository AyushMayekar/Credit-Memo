import unittest

from app.evals.graders import answer, num, nums


class EvalGraderTests(unittest.TestCase):
    def test_parentheses_are_negative(self):
        self.assertIn(-1234.0, nums("(1,234)"))

    def test_gbp_million_normalizes_to_thousands(self):
        self.assertIn(17100.0, nums("£17.1 million"))
        self.assertTrue(num("profit", 17107, "£17.1 million", tolerance=50).passed)

    def test_exact_gbp_thousands(self):
        self.assertTrue(num("revenue", 191258, "Revenue £191,258k").passed)

    def test_generation_result_sources_after_adapter_shape(self):
        case = {"facts": [], "expect_no_answer": False}
        payload = {"answer": "Answer", "sources": [{"source_id": "SRC-1"}]}
        checks = {item.name: item.passed for item in answer(case, payload)}
        self.assertTrue(checks["sources_present"])

    def test_no_answer_does_not_contain_phrase(self):
        case = {"facts": [], "expect_no_answer": True}
        payload = {
            "answer": "The provided evidence does not contain DSCR information.",
            "sources": [],
        }
        checks = {item.name: item.passed for item in answer(case, payload)}
        self.assertTrue(checks["no_answer_honesty"])


if __name__ == "__main__":
    unittest.main()
