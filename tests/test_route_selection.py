import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import capabilities as cap
from route_preview import preview


class Routing(unittest.TestCase):
    def test_catalog_is_listed_not_verified(self):
        out = io.StringIO()
        with patch.dict(cap.os.environ, {'OPENCODE': '1'}, clear=True), patch.object(cap.shutil, 'which', return_value='opencode'), patch.object(cap.subprocess, 'run', return_value=SimpleNamespace(stdout='p/a\np/b\nlog message\np/a\n')), redirect_stdout(out):
            cap.discover(SimpleNamespace(host=None))
        result = json.loads(out.getvalue())
        self.assertEqual((result['host'], result['listed']), ('opencode', ['p/a', 'p/b']))
        self.assertFalse(result['verified_for_billing'])
        self.assertEqual(cap.detect_host({'OPENCODE':'1','CODEX_THREAD_ID':'abc'})['host'], 'unknown')

    def test_custom_assignment_respects_inventory_and_budget(self):
        inv = cap.template()
        base = dict(provider='test', evidence='fixture', available=True, roles=['critic'],
                    context_tokens=8000, rates_usd_per_million={'input':1,'output':2})
        inv['models'] = [dict(base, id='a'),dict(base, id='b'),dict(base, id='off', available=False),
                         dict(base, id='small', context_tokens=10)]
        task = dict(id='review', role='critic', input_tokens=1000, max_output_tokens=500)
        request = dict(operations=[task], custom={'review':['test','b']})
        result = preview(inv, request)
        self.assertEqual(result['custom_choices_by_operation']['review'], [['test','a'],['test','b']])
        self.assertEqual(result['plans']['custom']['operations'][0]['model'], 'b')
        self.assertEqual(result['plans']['custom']['estimated_usd'], '0.002')
        self.assertEqual(preview(inv, request, 0)['plans']['custom']['status'], 'over_budget')
        request['custom']['review'] = ['test','off']
        self.assertEqual(preview(inv, request)['plans']['custom']['status'], 'incomplete')
        del inv['models'][1]['rates_usd_per_million']
        request['custom']['review'] = ['test', 'b']
        result = preview(inv, request)
        self.assertIn(['test', 'b'], result['custom_choices_by_operation']['review'])
        self.assertIsNone(result['plans']['custom']['estimated_usd'])
        self.assertEqual(result['plans']['custom']['status'], 'incomplete')
