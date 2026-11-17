import unittest
from app.ai.extraction.standalone_hybrid_extractor_v4 import StandaloneHybridExtractorV4

class Tests(unittest.TestCase):
    def setUp(self):self.s=StandaloneHybridExtractorV4.__new__(StandaloneHybridExtractorV4)
    def test_variable_columns(self):
        rows=[]
        for y in range(6):rows.append([{'text':str(i+y),'x0':float(x),'x1':float(x+15),'top':float(y)} for i,x in enumerate((200,270,340,410),1)])
        self.assertEqual(len(self.s._value_anchors(rows)),4)
    def test_index_layout(self):
        rows=[{'label':'Accounting policies','cells':{'C01':'55','C02':'62'}},{'label':'Revenue','cells':{'C01':'65','C02':'68'}},{'label':'Borrowings','cells':{'C01':'77','C02':'83'}}]
        columns=[{'column_id':'C01','x_anchor':240},{'column_id':'C02','x_anchor':390}]
        kind,_=self.s._classify('INDEX Accounting policies 55 Revenue 65',rows,columns,600,[],[])
        self.assertEqual(kind,'INDEX_LAYOUT')
    def test_financial_table(self):
        rows=[{'label':'Revenue','cells':{'C01':'100','C02':'90'}},{'label':'Profit','cells':{'C01':'20','C02':'18'}},{'label':'Assets','cells':{'C01':'300','C02':'280'}}]
        columns=[{'column_id':'C01','x_anchor':300},{'column_id':'C02','x_anchor':400}]
        kind,_=self.s._classify('Financial statements',rows,columns,600,['2024','2023'],['£’000'])
        self.assertEqual(kind,'FINANCIAL_TABLE')
if __name__=='__main__':unittest.main()
