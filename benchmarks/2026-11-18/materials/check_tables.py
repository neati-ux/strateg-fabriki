"""Reproduce the table checks. Requires openpyxl to build the Excel fixture."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ROWS = [
    ['id', 'amount', 'unit'],
    ['A', '100', 'RUB/week'],
    ['A', '100', 'RUB/week'],
    ['B', '', 'RUB/week'],
    ['C', '600', 'RUB/month'],
]


def run():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for folder in ('tools', 'templates', 'routing'):
            shutil.copytree(ROOT / folder, root / folder, ignore=shutil.ignore_patterns('__pycache__'))

        def cli(*args):
            return subprocess.check_output([sys.executable, '-X', 'utf8', str(root / 'tools/strateg.py'),
                                            *map(str, args)], cwd=root, encoding='utf-8')

        cli('new', 'tables')
        project = root / 'projects/tables'
        table = root / 'amounts.csv'
        with table.open('w', encoding='utf-8-sig', newline='') as f:
            csv.writer(f, delimiter=';').writerows(ROWS)
        profile = json.loads(cli('profile-table', table, '--key', 'id'))
        assert profile['rows'] == 4 and profile['delimiter'] == ';'
        assert profile['duplicate_rows_after_first'] == profile['duplicate_keys_after_first'] == 1
        assert profile['missing_by_column'] == {'id': 0, 'amount': 1, 'unit': 0}
        book = Workbook()
        for row in ROWS:
            book.active.append([int(v) if v.isdigit() else v or None for v in row])
        book.create_sheet('Check')['A1'] = '=1+1'
        excel = root / 'amounts.xlsx'
        book.save(excel)
        for source in (table, excel):
            cli('collect', source)
            cli('collect', source)
        with (project / 'materials/sources.csv').open(encoding='utf-8-sig') as f:
            sources = list(csv.DictReader(f))
        assert len(sources) == 2
        for record, source in zip(sources, (table, excel)):
            path = project / record['адрес']
            original = path.with_name('original' + source.suffix)
            assert original.read_bytes() == source.read_bytes()
            body = path.read_text(encoding='utf-8')
            assert 'RUB/week' in body and 'RUB/month' in body
            if source == excel:
                assert all(s in body for s in ('B2: 100', 'B3: 100', 'A4: B', 'C4: RUB/week', 'B5: 600'))
                assert 'B4: 0' not in body and 'ФОРМУЛА 1+1' in body and 'не пересчитано' in body
        return {'status': 'PASS', 'cli': ['new', 'profile-table', 'collect'],
                'input_rows': ROWS, 'csv_profile': profile, 'unique_sources_after_four_imports': len(sources),
                'xlsx_checks': ['cell addresses and duplicate values', 'missing value not replaced by zero',
                                'formula identified as not recalculated', 'original bytes preserved'],
                'unit_check': 'Both unit labels preserved; automatic detection of incompatible periods was not tested.',
                'fixture_csv_sha256': hashlib.sha256(table.read_bytes()).hexdigest()}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
