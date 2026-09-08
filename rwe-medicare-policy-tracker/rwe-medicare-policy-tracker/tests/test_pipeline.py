import copy, json, shutil, sys, tempfile, unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pipeline as p
import search_updates as search

def row(**kwargs):
    return p.validate([dict(title='测试事件（非真实政策）', source_url='https://www.nhsa.gov.cn/test-only-001.html',
                            summary='测试项目启动', province='测试省份', stage='启动', confidence='medium', **kwargs)])[0]

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'project'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('__pycache__', '.work'))
        p.write_csv(self.root / 'data/master.csv', [])
        p.write_csv(self.root / 'data/latest.csv', [])
        (self.root / 'data/run_state.json').write_text('{}')
        self.now = datetime(2026, 9, 8, 9, tzinfo=p.CN)
    def tearDown(self):
        self.tmp.cleanup()
    def batch(self, records, **kwargs):
        return dict(complete=True, records=records, **kwargs)
    def snapshot(self):
        return {str(x.relative_to(self.root)): x.read_bytes() for x in self.root.rglob('*') if x.is_file() and '__pycache__' not in str(x)}
    def test_add_report_and_province(self):
        result = p.apply_batch(self.root, self.batch([row()]), self.now)
        self.assertEqual(result['new'], 1)
        self.assertEqual(len(p.read_csv(self.root / 'data/master.csv')), 1)
        report = (self.root / 'reports/2026-09-08.md').read_text(encoding='utf-8')
        self.assertIn('测试事件', report)
        self.assertNotIn('由 Codex 补充', report)
        self.assertTrue((self.root / 'provinces/测试省份.md').exists())
    def test_replay_keeps_report_and_files(self):
        batch = self.batch([row()])
        p.apply_batch(self.root, batch, self.now)
        before = self.snapshot()
        self.assertTrue(p.apply_batch(self.root, batch, self.now)['replayed'])
        self.assertEqual(before, self.snapshot())
    def test_update_preserves_identity(self):
        old, _ = p.merge([], [row()], '2026-09-08')
        updated = row()
        updated.update(stage='完成', summary='测试项目完成')
        master, latest = p.merge(old, [updated], '2026-09-10')
        self.assertEqual(len(master), 1)
        self.assertEqual(latest[0]['status'], '更新')
        self.assertEqual(master[0]['first_seen'], '2026-09-08')
        self.assertEqual(master[0]['record_id'], old[0]['record_id'])
    def test_unchanged_and_empty_do_not_republish_old_events(self):
        p.apply_batch(self.root, self.batch([row()]), self.now)
        p.apply_batch(self.root, self.batch([row()], collected_at='new-run'), self.now)
        self.assertEqual(p.read_csv(self.root / 'data/latest.csv'), [])
        self.assertEqual(len(p.read_csv(self.root / 'data/master.csv')), 1)
    def test_duplicate_batch_rows(self):
        master, latest = p.merge([], [row(), row()], '2026-09-08')
        self.assertEqual((len(master), len(latest)), (1, 1))
    def test_partial_collection_no_write(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            p.apply_batch(self.root, {'complete': False, 'records': []}, self.now)
        self.assertEqual(before, self.snapshot())
    def test_invalid_enum_no_write(self):
        before = self.snapshot()
        r = row()
        r['status'] = 'updated'
        with self.assertRaises(ValueError):
            p.apply_batch(self.root, self.batch([r]), self.now)
        self.assertEqual(before, self.snapshot())
    def test_report_failure_no_write(self):
        before = self.snapshot()
        with patch.object(p.subprocess, 'run', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                p.apply_batch(self.root, self.batch([row()]), self.now)
        self.assertEqual(before, self.snapshot())
    def test_missing_fields_and_extra_csv_column(self):
        with self.assertRaises(ValueError):
            p.validate([{'title': 'x'}])
        with self.assertRaises(ValueError):
            p.validate([dict(row(), unknown='x')])
    def test_search_requires_actual_tool_call(self):
        with self.assertRaises(ValueError):
            search.parse_response({'output': []})
    def test_missing_key_no_network(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            with self.assertRaises(RuntimeError):
                search.collect(self.root, {})
    def test_search_valid_json(self):
        data = {'output': [
            {'type': 'web_search_call', 'status': 'completed'},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': '{"complete": true, "records": []}'}]}
        ]}
        self.assertEqual(search.parse_response(data)['records'], [])
    def test_mocked_collector_all_groups(self):
        data = {'id': 'mock', 'output': [
            {'type': 'web_search_call', 'status': 'completed', 'action': {'sources': []}},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': '{"complete": true, "records": [], "gaps": []}'}]}
        ]}
        def fake_fetch(url):
            return {'url': url, 'ok': True, 'text': 'mock page'}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-only'}), patch.object(search, 'fetch', side_effect=fake_fetch), patch.object(search, 'response', return_value=data) as api:
            batch = search.collect(self.root, {})
        self.assertEqual(api.call_count, 5)
        self.assertEqual(len(batch['coverage']['fixed_sites']), 32)
        self.assertTrue(batch['complete'])
        self.assertEqual(batch['records'], [])
    def test_low_confidence_pending(self):
        r = row()
        r['confidence'] = 'low'
        _, latest = p.merge([], [r], '2026-09-08')
        self.assertEqual(latest[0]['status'], '待核实')
    def test_new_url_existing_id(self):
        old, _ = p.merge([], [row()], '2026-09-08')
        r = old[0].copy()
        r['source_url'] = 'https://www.nhsa.gov.cn/test-only-002.html'
        master, latest = p.merge(old, [r], '2026-09-10')
        self.assertEqual(len(master), 1)
        self.assertEqual(latest[0]['status'], '更新')

if __name__ == '__main__':
    unittest.main()
