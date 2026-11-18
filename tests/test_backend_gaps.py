import sys
import tempfile
import unittest
import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import capabilities


class BackendGaps(unittest.TestCase):
    def test_sync_preserves_body_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            agents = root / '.claude' / 'agents'
            agents.mkdir(parents=True)
            file = agents / 'critic.md'
            file.write_bytes(b'---\r\nname: critic\r\nmodel: haiku\r\n---\r\nBody\r\nmodel: untouched\r\n')
            result = capabilities.sync_claude(root, {'critic': 'opus'})
            self.assertEqual(result['changed'], ['critic'])
            self.assertEqual(file.read_bytes(), b'---\r\nname: critic\r\nmodel: opus\r\n---\r\nBody\r\nmodel: untouched\r\n')
            self.assertEqual(capabilities.sync_claude(root, {'critic': 'opus'})['changed'], [])

    def test_sync_validates_all_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            agents = root / '.claude' / 'agents'
            agents.mkdir(parents=True)
            file = agents / 'critic.md'
            file.write_text('---\nmodel: haiku\n---\nBody')
            before = file.read_bytes()
            with self.assertRaises(ValueError):
                capabilities.sync_claude(root, {'critic': 'opus', 'extractor': 'bad\nmodel'})
            self.assertEqual(file.read_bytes(), before)

    def test_ux_validates_scenario_and_captures_steps(self):
        import ux_capture as ux
        with self.assertRaises(ValueError):
            ux.validate_steps([{'action': 'evaluate', 'script': 'anything'}])
        page = Mock()
        page.url = 'https://example.org/'
        page.title.return_value = 'Example'
        page.locator.return_value.inner_text.return_value = 'Visible rendered content'
        page.locator.return_value.aria_snapshot.return_value = '- heading: Example'
        page.screenshot.return_value = b'png'
        page.goto.return_value.status = 200
        with tempfile.TemporaryDirectory() as d, patch.object(ux, 'validate_url'):
            records = ux.capture_steps(page, [{'action': 'goto', 'url': page.url},
                {'action': 'click', 'selector': '#menu'}], Path(d))
            self.assertEqual(len(records), 2)
            self.assertIn('Visible rendered content', (Path(d) / 'content.md').read_text(encoding='utf-8'))
            self.assertTrue((Path(d) / '02.png').exists())
            page.locator.return_value.click.assert_called_once()

    def test_ux_registers_saved_artifact(self):
        import ux_capture as ux
        import strateg as S
        def fake_browser(steps, folder):
            (folder / 'content.md').write_text('Rendered content', encoding='utf-8')
            (folder / '01.png').write_bytes(b'png')
            return {'screens': [{'screenshot': '01.png'}], 'blocked_requests': []}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'materials').mkdir()
            scenario = root / 'scenario.json'
            scenario.write_text(json.dumps([{'action': 'goto', 'url': 'https://example.org'}]))
            with patch.object(S, 'project_dir', return_value=root), patch.object(ux, 'browser_capture', side_effect=fake_browser):
                ux.cmd_capture(SimpleNamespace(project='fixture', scenario=str(scenario), title='UX fixture'))
            sources = S.read_csv(root / 'materials' / 'sources.csv', S.SOURCE_FIELDS)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]['вид'], 'сайт')
            saved = root / sources[0]['адрес']
            self.assertEqual(saved.read_text(encoding='utf-8'), 'Rendered content')
            self.assertTrue(saved.with_name('metadata.json').is_file())

    def test_sync_rollback_preserves_concurrent_edit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder = root / '.claude' / 'agents'
            folder.mkdir(parents=True)
            for role in ('critic', 'extractor'):
                (folder / (role + '.md')).write_text('---\nmodel: haiku\n---\nBody')
            original_replace = Path.replace
            def conflict(file, target):
                if file.name == 'extractor':
                    (folder / 'critic.md').write_text('concurrent user edit')
                    raise OSError('simulated failure')
                return original_replace(file, target)
            with patch.object(Path, 'replace', conflict), self.assertRaises((OSError, ValueError)):
                capabilities.sync_claude(root, {'critic': 'opus', 'extractor': 'sonnet'})
            self.assertEqual((folder / 'critic.md').read_text(), 'concurrent user edit')


if __name__ == '__main__':
    unittest.main()
