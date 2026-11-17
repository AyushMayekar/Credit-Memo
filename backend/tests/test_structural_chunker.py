import unittest, tempfile, json
from pathlib import Path
from app.ai.chunking.pipeline import HybridTextChunkingPipeline


class Tests(unittest.TestCase):
    def run_data(self, records, tables=None):
        d = {
            "document": {"filename": "x.pdf"},
            "sections": [{"section_id": "S1", "title": "Revenue"}],
            "records": records,
            "tables": tables or [],
        }
        p = Path(tempfile.mktemp(suffix=".json"))
        p.write_text(json.dumps(d))
        return HybridTextChunkingPipeline().run(p, borrower_name="B")

    def test_max_and_unique_ids(self):
        r = self.run_data(
            [
                {
                    "record_id": "P1",
                    "record_type": "PAGE_TEXT",
                    "page_start": 1,
                    "page_end": 1,
                    "section_id": "S1",
                    "section_title": "Revenue",
                    "content_text": ("Financial sentence, value 1,234. " * 900),
                    "quality_classification": "ACCEPTED",
                    "warnings": [],
                }
            ]
        )
        self.assertLessEqual(max(x.token_count for x in r.children), 520)
        self.assertEqual(len({x.chunk_id for x in r.children}), len(r.children))

    def test_non_contiguous_split(self):
        rec = [
            {
                "record_id": f"P{x}",
                "record_type": "PAGE_TEXT",
                "page_start": x,
                "page_end": x,
                "section_id": "S1",
                "section_title": "Revenue",
                "content_text": "Narrative text. " * 100,
                "quality_classification": "ACCEPTED",
                "warnings": [],
            }
            for x in (1, 5)
        ]
        r = self.run_data(rec)
        self.assertEqual(len(r.parents), 2)

    def test_table_suppresses_dense_text_children(self):
        rec = [
            {
                "record_id": "P1",
                "record_type": "PAGE_TEXT",
                "page_start": 1,
                "page_end": 1,
                "section_id": "S1",
                "section_title": "Revenue",
                "content_text": "Revenue 2024 100 2023 90 " * 100,
                "quality_classification": "ACCEPTED",
                "warnings": [],
            }
        ]
        tab = [
            {
                "table_id": "T1",
                "page_number": 1,
                "section_title": "Revenue",
                "quality_classification": "ACCEPTED",
                "normalized_rows": [
                    ["Revenue", "2024", "2023"],
                    ["Total", "100", "90"],
                ],
                "raw_rows": [],
                "markdown": "| Revenue | 2024 | 2023 |",
            }
        ]
        r = self.run_data(rec, tab)
        self.assertEqual(len(r.children), 0)
        self.assertEqual(len(r.tables), 1)


if __name__ == "__main__":
    unittest.main()
