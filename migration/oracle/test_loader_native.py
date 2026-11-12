"""Regression checks for text preservation, exact readback and PDB ownership."""
from decimal import Decimal
import unittest
from unittest.mock import MagicMock
import loader_native as loader

class LoaderTests(unittest.TestCase):
    def test_original_identifiers_and_text_are_preserved(self):
        self.assertEqual(loader.quote_identifier('County Name'), '"County Name"')
        self.assertEqual(loader.quote_identifier('a"b'), '"a""b"')
        for value in (' Alameda ', '', '1998-10-14', 'x\x00y'):
            self.assertEqual(loader.storage_value(value, {'logical_type':'VARCHAR'}), value)
        self.assertEqual(loader.username_for('california_schools'), 'CALIFORNIA_SCHOOLS')

    def test_int64_has_no_float_roundtrip(self):
        value=9007199254740993
        self.assertEqual(loader.storage_value(value, {'logical_type':'BIGINT'}), value)
        columns=[{'logical_type':'BIGINT'}]
        a,b=loader.Fingerprint(),loader.Fingerprint()
        a.add([value],columns);b.add([Decimal(value)],columns)
        self.assertEqual(a.evidence(),b.evidence())
        with self.assertRaises(ValueError):b.add([Decimal('1.5')],columns)

    def test_fingerprint_preserves_empty_null_and_duplicates(self):
        c=[{'logical_type':'VARCHAR'}]
        a,b=loader.Fingerprint(),loader.Fingerprint();a.add([''],c);b.add([None],c)
        self.assertNotEqual(a.evidence(),b.evidence())
        a.add([''],c);self.assertEqual(a.evidence()['rows'],2)

    def test_root_service_rejected_before_create(self):
        connection=MagicMock();cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value=('CDB$ROOT',)
        with self.assertRaises(ValueError):loader.setup_oracle_user(connection,'bench')
        self.assertEqual(cursor.execute.call_count,1)

    def test_maintained_user_is_never_dropped(self):
        connection=MagicMock();cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect=[('FREEPDB1',),('Y',)]
        with self.assertRaises(ValueError):loader.setup_oracle_user(connection,'bench',recreate=True)
        self.assertFalse(any('DROP USER' in args[0] for args,kwargs in cursor.execute.call_args_list))

    def test_ordinary_user_creation_has_minimal_grants(self):
        connection=MagicMock();cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect=[('FREEPDB1',),None,('N',)]
        loader.setup_oracle_user(connection,'bench')
        statements=[args[0]for args,kwargs in cursor.execute.call_args_list]
        self.assertTrue(any('CREATE SESSION, CREATE TABLE' in s for s in statements))
        self.assertFalse(any('_ORACLE_SCRIPT' in s or 'DBA TO' in s for s in statements))

if __name__=='__main__':unittest.main()
