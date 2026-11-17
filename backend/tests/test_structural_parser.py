import unittest
from app.ai.parsing.section_detector import SectionDetector
from app.ai.parsing.table_parser import ParsedTableBuilder


class Tests(unittest.TestCase):
    def setUp(self):
        self.d = SectionDetector()

    def test_note_promoted(self):
        h = self.d.detect_page_headings(
            "12. Property, plant and equipment\nCost", page_no=1, in_notes=True
        )
        self.assertEqual(h[0].level, 1)

    def test_action_rejected(self):
        self.assertFalse(
            self.d.detect_page_headings(
                "5. To approve the Directors' Remuneration Report", page_no=1
            )
        )

    def test_date_rejected(self):
        self.assertFalse(self.d.detect_page_headings("30TH APRIL, 2024", page_no=1))

    def test_year_columns_rejected(self):
        self.assertFalse(
            self.d.detect_page_headings(
                "8. Finance costs (net) 2024 2023", page_no=1, in_notes=True
            )
        )

    def test_address_rejected(self):
        self.assertFalse(
            self.d.detect_page_headings(
                "1. Ivy House Foundry, Hanley, Stoke-on-Trent ST1 3NR",
                page_no=1,
                in_notes=True,
            )
        )

    def test_short_valid(self):
        self.assertTrue(self.d.detect_page_headings("BORROWINGS", page_no=1))

    def test_negative(self):
        self.assertEqual(ParsedTableBuilder._number_value("(1,234)")["value"], "-1234")


if __name__ == "__main__":
    unittest.main()
