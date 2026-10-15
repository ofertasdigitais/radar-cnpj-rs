import sqlite3
import unittest
from app import filters
import company_access


class SegmentationTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE companies(cnpj TEXT,uf TEXT,cnae TEXT,cnae_descricao TEXT,
                razao_social TEXT,nome_fantasia TEXT,porte TEXT,data_source TEXT,telefone TEXT,email TEXT);
            INSERT INTO companies VALUES('1','RS','5611201','Restaurantes','Pizza da Serra','','ME','Receita Federal','51','');
            INSERT INTO companies VALUES('2','RS','5611203','Lanchonetes','Burger Sul','','EPP','Receita Federal','','a@example.com');
            INSERT INTO companies VALUES('3','RS','5510801','Hotéis','Hotel Serra','','ME','Importação CSV','51','');
            CREATE TABLE sales_profiles(id TEXT,owner_id TEXT);
            CREATE TABLE sales_profile_leads(profile_id TEXT,cnpj TEXT,lead_status TEXT);
            INSERT INTO sales_profiles VALUES('a','conta-a'),('b','conta-b');
            INSERT INTO sales_profile_leads VALUES('a','1','qualificado'),('b','2','contatado');
            ALTER TABLE companies ADD COLUMN situacao TEXT DEFAULT 'ATIVA';
        """)
        company_access.ensure_schema(self.db)

    def results(self, params, owner='conta-a'):
        where,values=filters({key:[value] for key,value in params.items()},owner_id=owner)
        return [row[0] for row in self.db.execute('SELECT cnpj FROM companies WHERE '+where,values)]

    def test_categories_union_exclusion_and_name_refinement(self):
        self.assertEqual(self.results({'cnae_include':'5611201,5611203'}),['1','2'])
        self.assertEqual(self.results({'cnae_include':'56','cnae_exclude':'5611203'}),['1'])
        self.assertEqual(self.results({'cnae_include':'56','name_terms':'Pizza,Burger','name_exclude':'Burger'}),['1'])

    def test_icp_source_and_contact(self):
        self.assertEqual(self.results({'porte':'ME','data_source':'Receita Federal','phone_available':'sim'}),['1'])
        self.assertEqual(self.results({'email_available':'sim'}),['2'])

    def test_workflow_cannot_reveal_other_accounts_selection(self):
        self.assertEqual(self.results({'work_stage':'selected'}),['1'])
        self.assertEqual(self.results({'work_stage':'not_selected'}),['2','3'])
        self.assertEqual(self.results({'work_stage':'contatado'}),[])
        self.assertEqual(self.results({'work_stage':'selected'},owner=None),[])

    def test_text_cnae_and_parameterized_terms(self):
        self.assertEqual(self.results({'cnae':'Restaurantes'}),['1'])
        self.assertEqual(self.results({'name_terms':"' OR 1=1 --"}),[])


if __name__=='__main__':
    unittest.main()
