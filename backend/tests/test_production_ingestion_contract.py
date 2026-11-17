import unittest
from unittest.mock import Mock

from app.ai.embedding_model import EmbeddingClient


class ProductionIngestionContractTests(unittest.TestCase):
    def test_validated_batch_shape(self):
        client = object.__new__(EmbeddingClient)
        batches = client.build_batches(
            ["x" * 600] * 235, batch_size=48, batch_token_limit=16000
        )
        self.assertTrue(all(len(batch.texts) <= 48 for batch in batches))
        self.assertTrue(all(batch.estimated_tokens <= 16000 for batch in batches))
        self.assertEqual(sum(len(batch.texts) for batch in batches), 235)


if __name__ == "__main__":
    unittest.main()
