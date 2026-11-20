import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from ingest import record_incident
from opencode_usage import session_usage


class HostEvidence(unittest.TestCase):
    def test_nested_sessions_overlap_and_separate_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / 'projects' / 'school'
            project.mkdir(parents=True)
            database = root / 'host.db'
            with closing(sqlite3.connect(database)) as db, db:
                db.execute('create table session_v2(id,parent_id,directory,cost,tokens_input,tokens_output)')
                db.execute('create table session_message(session_id,type,data)')
                for key, parent, name, start, end in [
                    ('main', None, 'school', 1000, 5000), ('child', 'main', 'school', 2000, 3000),
                    ('other', None, 'shop', 7000, 8000)]:
                    db.execute('insert into session_v2 values(?,?,?,?,?,?)', (key,parent,str(root),0.1,12,4))
                    message = dict(time=dict(created=start,completed=end),content=[
                        dict(type='tool',name='write',state=dict(status='completed',input=dict(path=f'projects/{name}/state.md')))])
                    db.execute('insert into session_message values(?,?,?)',(key,'assistant',json.dumps(message)))
            result = session_usage(project,database=database)
            self.assertEqual(result, dict(sessions=2,input=24,output=8,cost=0.2,seconds=4))
            self.assertEqual(result, session_usage(project,'child',database))
            with self.assertRaises(ValueError):
                session_usage(project,'missing',database)

    def test_incident_repeated_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            state = project / 'state.md'
            state.write_text('## Сбои и обходы\n\nНет.\n\n## Дальше\n',encoding='utf-8')
            for _ in range(2):
                record_incident(project,'weekly.txt')
            content = state.read_text(encoding='utf-8')
            self.assertEqual(content.count('weekly.txt'),1)
            self.assertNotIn('Нет.',content)
            self.assertIn('## Дальше',content)
