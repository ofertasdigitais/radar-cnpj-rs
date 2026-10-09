import unittest

from tools.db_qa import database_ready
from tools.qa_live_readonly import EXPECTED_ROUTES, route_failures


class QAGateTests(unittest.TestCase):
    def test_all_expected_routes_and_redirect_pass(self):
        self.assertEqual(route_failures(dict(EXPECTED_ROUTES)), [])

    def test_missing_or_failed_route_is_not_a_pass(self):
        routes = dict(EXPECTED_ROUTES)
        routes['/api/admin/state'] = 500
        del routes['/api/help']
        self.assertEqual(set(route_failures(routes)), {'/api/admin/state', '/api/help'})

    def test_anonymous_help_must_not_be_public(self):
        routes = dict(EXPECTED_ROUTES)
        routes['anonymous_help'] = 200
        self.assertEqual(route_failures(routes), ['anonymous_help'])

    def test_owner_and_integrity_checks_cannot_be_omitted(self):
        result = dict(integrity_check=['ok'], foreign_key_violations=0,
                      duplicate_company_keys=0, orphan_sales_leads=0,
                      profiles_without_owner=0)
        self.assertTrue(database_ready(result))
        for key in result:
            with self.subTest(key=key):
                incomplete = dict(result)
                del incomplete[key]
                self.assertFalse(database_ready(incomplete))
        result['profiles_without_owner'] = 1
        self.assertFalse(database_ready(result))


if __name__ == '__main__':
    unittest.main()
