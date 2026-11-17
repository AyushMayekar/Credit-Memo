import unittest
from app.ai.parsing.lightweight_parser_v8 import LightweightParsingPipelineV8

class Tests(unittest.TestCase):
    def setUp(self): self.p=LightweightParsingPipelineV8.__new__(LightweightParsingPipelineV8)
    def test_fake_heading_rejected(self):
        self.assertIsNone(self.p._heading_events({"item_type":"heading"},"GOODWIN PLC"))
        self.assertIsNone(self.p._heading_events({"item_type":"heading"},"Directors:"))
        self.assertIsNone(self.p._heading_events({"item_type":"heading"},"J. E. Kelly"))
    def test_merged_continuation_split(self):
        result=self.p._heading_events({"item_type":"heading"},"OBJECTIVES, STRATEGY AND BUSINESS MODEL (continued) DIVIDEND AND CAPITAL EXPENDITURE POLICY")
        self.assertEqual([x["classification"] for x in result],["CONTINUATION","SECTION"])
    def test_garbage(self):
        self.assertEqual(self.p._text_quality("@@@@ #### <<<<")[0],"REJECTED")
