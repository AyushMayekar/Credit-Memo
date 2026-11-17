import unittest

from app.ai.embedding_model import EmbeddingClient


class Tests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(EmbeddingClient)

    def test_item_limit(self):
        batches = self.client.build_batches(
            ["hello"] * 10, batch_size=4, batch_token_limit=1000
        )
        self.assertEqual([len(batch.texts) for batch in batches], [4, 4, 2])

    def test_token_limit(self):
        texts = ["a" * 120, "b" * 120, "c" * 120]
        batches = self.client.build_batches(texts, batch_size=10, batch_token_limit=80)
        self.assertEqual([len(batch.texts) for batch in batches], [2, 1])
        self.assertTrue(all(batch.estimated_tokens <= 80 for batch in batches))

    def test_oversized_item_rejected_before_api(self):
        with self.assertRaises(ValueError):
            self.client.build_batches(["x" * 400], batch_size=10, batch_token_limit=100)

    def test_order_ranges(self):
        batches = self.client.build_batches(
            [str(i) for i in range(5)], batch_size=2, batch_token_limit=100
        )
        self.assertEqual(
            [(b.item_start, b.item_end) for b in batches], [(0, 1), (2, 3), (4, 4)]
        )


if __name__ == "__main__":
    unittest.main()
