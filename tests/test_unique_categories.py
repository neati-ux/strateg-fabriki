import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from table_profile import profile


class UniqueCategoriesTest(unittest.TestCase):
    def test_overlapping_exports_and_conflicting_labels(self):
        rows = ("id,reason,export\na,x,1\na,x,2\nb,x,2\nc,y,1\nc,z,2\n"
                "d,,1\ne,,1\ne,y,2\n,x,2\n")
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / 'records.csv'
            table.write_text(rows, encoding='utf-8-sig')
            result = profile(table, key='id', group_by='reason')
        self.assertEqual(result['unique_records'], 5)
        self.assertEqual(result['unique_counts'], {'x': 2, 'y': 1})
        self.assertEqual(result['conflicting_records'], 1)
        self.assertEqual(result['uncategorized_records'], 1)
