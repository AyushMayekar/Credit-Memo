import json
import tempfile
import unittest
from pathlib import Path

from app.ai.chunking.pipeline import HybridTextChunkingPipeline


class StructuralChunkerTests(unittest.TestCase):
    def run_data(self, records, tables=None, sections=None):
        payload = {
            "document": {"filename": "report.pdf"},
            "sections": sections or [{"section_id":"S1","title":"Revenue","heading_level":1,"heading_path":["Revenue"],"page_start":1,"page_end":5}],
            "records": records,
            "tables": tables or [],
        }
        path = Path(tempfile.mktemp(suffix=".json"))
        path.write_text(json.dumps(payload), encoding="utf-8")
        return HybridTextChunkingPipeline().run(path, borrower_name="Goodwin PLC", reporting_year="2024")

    def record(self, text, page=1, record_id="R1"):
        return {"record_id":record_id,"record_type":"SECTION_TEXT","section_id":"S1","section_title":"Revenue","heading_path":["Revenue"],"page_start":page,"page_end":page,"content_text":text,"source_item_ids":[record_id+"-I"],"quality_classification":"ACCEPTED","warnings":[]}

    def test_children_and_parents_respect_hard_limits(self):
        result = self.run_data([self.record("Financial performance improved during the year. " * 900)])
        self.assertTrue(result.children)
        self.assertLessEqual(max(x.token_count for x in result.children), 600)
        self.assertLessEqual(max(x.token_count for x in result.parents), 2700)

    def test_all_child_parent_links_resolve(self):
        result = self.run_data([self.record("Narrative sentence. " * 500)])
        parent_ids = {x.chunk_id for x in result.parents}
        self.assertTrue(all(x.parent_chunk_id in parent_ids for x in result.children))
        self.assertFalse(result.audit["broken_parent_links"])

    def test_split_parent_relationships_exist(self):
        records = [self.record("Page narrative sentence. " * 450, page=i, record_id=f"R{i}") for i in range(1, 6)]
        result = self.run_data(records)
        self.assertGreater(len(result.parents), 1)
        groups = {x.parent_group_id for x in result.parents}
        self.assertEqual(len(groups), 1)
        self.assertTrue(all(x.parent_part_count == len(result.parents) for x in result.parents))
        self.assertTrue(all(len(x.related_parent_ids) == len(result.parents)-1 for x in result.parents))

    def test_table_is_searchable_child_with_parent(self):
        table = {"table_id":"T1","page_number":1,"section_id":"S1","section_title":"Revenue","heading_path":["Revenue"],"quality_classification":"ACCEPTED","detected_periods":["2024","2023"],"detected_units":["GBP thousands"],"normalized_rows":[["Metric","2024","2023"],["Revenue","191258","175901"],["Profit","24094","18940"]],"source_item_ids":["I1"]}
        result = self.run_data([self.record("The group reported its annual results.")], [table])
        self.assertEqual(len(result.tables), 1)
        chunk = result.tables[0]
        self.assertIn("191258", chunk.embedding_text)
        self.assertIn("Revenue", chunk.embedding_text)
        self.assertIn(chunk.parent_chunk_id, {x.chunk_id for x in result.parents})

    def test_large_table_splits_by_rows_and_repeats_header(self):
        rows = [["Metric","2024","2023"]] + [[f"Metric {i}", str(i*100), str(i*90)] for i in range(500)]
        table = {"table_id":"T1","page_number":1,"section_id":"S1","section_title":"Revenue","heading_path":["Revenue"],"quality_classification":"ACCEPTED","normalized_rows":rows}
        result = self.run_data([], [table])
        self.assertGreater(len(result.tables), 1)
        self.assertTrue(all("Metric | 2024 | 2023" in x.content_text for x in result.tables))
        self.assertTrue(all(x.token_count <= 1800 for x in result.tables))

    def test_no_source_records_or_tables_are_lost(self):
        table = {"table_id":"T1","page_number":1,"section_id":"S1","section_title":"Revenue","normalized_rows":[["Metric","2024"],["Revenue","100"]]}
        result = self.run_data([self.record("Narrative text.", record_id="R1")], [table])
        self.assertEqual(result.audit["missing_record_ids"], [])
        self.assertEqual(result.audit["missing_table_ids"], [])

    def test_parser_parent_section_id_controls_parent_grouping(self):
        sections = [
            {"section_id":"P1","title":"Financial Review","heading_level":1,"heading_path":["Financial Review"],"parent_section_id":None,"page_start":1,"page_end":3},
            {"section_id":"C1","title":"Revenue","heading_level":2,"heading_path":["Financial Review","Revenue"],"parent_section_id":"P1","page_start":1,"page_end":1},
            {"section_id":"C2","title":"Profit","heading_level":2,"heading_path":["Financial Review","Profit"],"parent_section_id":"P1","page_start":2,"page_end":2},
        ]
        records = [
            {**self.record("Revenue was 100.", page=1, record_id="R1"), "section_id":"C1", "section_title":"Revenue", "heading_path":["Financial Review","Revenue"]},
            {**self.record("Profit was 20.", page=2, record_id="R2"), "section_id":"C2", "section_title":"Profit", "heading_path":["Financial Review","Profit"]},
        ]
        result = self.run_data(records, sections=sections)
        self.assertEqual(len(result.parents), 1)
        self.assertEqual(result.parents[0].section_id, "P1")
        self.assertEqual({x.section_id for x in result.children}, {"C1", "C2"})
        self.assertTrue(all(x.parent_chunk_id == result.parents[0].chunk_id for x in result.children))
        self.assertIn("Revenue", result.parents[0].content_text)
        self.assertIn("Profit", result.parents[0].content_text)
        self.assertEqual(result.children[0].metadata["parser_parent_section_id"], "P1")

    def test_llm_metadata_is_present_on_every_chunk_type(self):
        table = {"table_id":"T1","page_number":1,"section_id":"S1","section_title":"Revenue","normalized_rows":[["Metric","2024"],["Revenue","100"]]}
        result = self.run_data([self.record("Narrative text.")], [table])
        for chunk in [*result.parents, *result.children, *result.tables]:
            self.assertIn("llm_metadata", chunk.metadata)
            self.assertEqual(chunk.metadata["llm_metadata"]["content_type"], "PARENT_SECTION" if chunk in result.parents else "TABLE_DATA" if chunk in result.tables else "CHILD_CHUNK")


if __name__ == "__main__":
    unittest.main()
