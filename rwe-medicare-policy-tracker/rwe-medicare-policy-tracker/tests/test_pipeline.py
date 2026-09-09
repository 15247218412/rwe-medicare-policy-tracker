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
    def test_conflicting_stage_for_same_source_is_kept_for_review(self):
        first = row()
        first['stage'] = '启动'
        second = row()
        second['stage'] = '实施'
        result = search.reconcile_records([first, second])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['stage'], '')
        self.assertEqual(result[0]['status'], '待核实')
        self.assertEqual(result[0]['confidence'], 'low')
        self.assertIn('阶段分类存在冲突', result[0]['notes'])

    def test_duplicate_source_with_one_known_stage_keeps_stage(self):
        first = row()
        first['stage'] = ''
        second = row()
        second['stage'] = '实施'
        result = search.reconcile_records([first, second])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['stage'], '实施')

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
    def test_format_pass_omits_web_search_tool(self):
        prose = self.search_output('检索报告：未发现新增。')
        structured = {'id': 'format-response', 'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text',
             'text': '{"complete":true,"records":[],"gaps":[]}'}]}
        ]}
        with patch.object(search, 'response', side_effect=[prose, structured]) as api:
            _, batch = search.request_batch({'model': 'deepseek-v4-flash', 'max_output_tokens': 1000}, 'test-only')
        formatter = api.call_args_list[1].args[0]
        self.assertNotIn('tools', formatter)
        self.assertNotIn('tool_choice', formatter)
        self.assertEqual(batch['records'], [])

    def test_format_pass_cannot_bypass_record_validation(self):
        prose = self.search_output('检索报告。')
        invalid = {'id': 'format-response', 'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text',
             'text': '{"complete":true,"records":[{"record":{},"evidence_quote":""}],"gaps":[]}'}]}
        ]}
        with patch.object(search, 'response', side_effect=[prose, invalid, prose, invalid]) as api:
            with self.assertRaises(search.OutputFormatError):
                search.request_batch({'model': 'deepseek-v4-flash'}, 'test-only')
        self.assertEqual(api.call_count, 4)

    def test_missing_evidence_quote_is_normalized_for_manual_review(self):
        record = row()
        payload = json.dumps({'complete': True, 'records': [{'record': record}], 'gaps': []}, ensure_ascii=False)
        batch = search.parse_response(self.search_output(payload))
        self.assertEqual(batch['records'][0]['evidence_quote'], '')

    def test_null_evidence_quote_is_normalized_for_manual_review(self):
        record = row()
        payload = json.dumps({'complete': True, 'records': [{'record': record, 'evidence_quote': None}], 'gaps': []}, ensure_ascii=False)
        batch = search.parse_response(self.search_output(payload))
        self.assertEqual(batch['records'][0]['evidence_quote'], '')

    def test_flat_record_is_wrapped_for_manual_review(self):
        record = row()
        payload = json.dumps({'complete': True, 'records': [record], 'gaps': []}, ensure_ascii=False)
        batch = search.parse_response(self.search_output(payload))
        self.assertEqual(batch['records'][0], {'record': record, 'evidence_quote': ''})

    def test_non_string_evidence_quote_is_rejected(self):
        record = row()
        for quote in (7, ['测试项目启动']):
            payload = json.dumps({'complete': True, 'records': [{'record': record, 'evidence_quote': quote}], 'gaps': []}, ensure_ascii=False)
            with self.assertRaises(search.OutputFormatError):
                search.parse_response(self.search_output(payload))

    def test_arbitrary_record_structure_is_rejected(self):
        payload = json.dumps({'complete': True, 'records': [{'unexpected': 'value'}], 'gaps': []})
        with self.assertRaises(search.OutputFormatError):
            search.parse_response(self.search_output(payload))

    def test_missing_fields_and_extra_csv_column(self):
        with self.assertRaises(ValueError):
            p.validate([{'title': 'x'}])
        with self.assertRaises(ValueError):
            p.validate([dict(row(), unknown='x')])
    def test_search_requires_actual_tool_call(self):
        with self.assertRaises(ValueError):
            search.parse_response({'output': []})
    def test_next_window_starts_on_previous_success_date(self):
        state = {'last_successful_run': '2026-09-01T18:30:00+08:00'}
        self.assertEqual(str(search.monitoring_start(state, self.now)), '2026-09-01')

    def test_first_window_uses_baseline_days(self):
        with patch.dict('os.environ', {'BASELINE_DAYS': '30'}):
            self.assertEqual(str(search.monitoring_start({}, self.now)), '2026-08-09')

    def test_missing_key_no_network(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': ''}):
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
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-only'}), patch.object(search, 'fetch', side_effect=fake_fetch), patch.object(search, 'response', return_value=data) as api:
            batch = search.collect(self.root, {})
        self.assertEqual(api.call_count, 9)
        payload = api.call_args.args[0]
        self.assertEqual(payload['model'], 'deepseek-v4-flash')
        self.assertEqual(payload['tool_choice'], {'type': 'web_search'})
        self.assertNotIn('include', payload)
        self.assertNotIn('filters', payload['tools'][0])
        self.assertEqual(len(batch['coverage']['fixed_sites']), 32)
        self.assertTrue(batch['complete'])
        self.assertEqual(batch['records'], [])
    def test_missing_quote_is_collected_only_as_low_confidence_pending(self):
        record = row()
        output = json.dumps({'complete': True, 'records': [{'record': record}], 'gaps': []}, ensure_ascii=False)
        data = {'id': 'mock', 'output': [
            {'type': 'web_search_call', 'status': 'completed', 'action': {'sources': []}},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}
        ]}
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-only'}), patch.object(search, 'fetch', return_value={'url': record['source_url'], 'ok': True, 'text': '测试项目启动'}), patch.object(search, 'response', return_value=data):
            batch = search.collect(self.root, {})
        self.assertEqual(batch['records'][0]['status'], '待核实')
        self.assertEqual(batch['records'][0]['confidence'], 'low')
        self.assertIn('未提供', batch['records'][0]['notes'])

    def test_out_of_group_sources_only_enter_supplement(self):
        record = row()
        record['source_url'] = 'https://news.example.org/test-only'
        output = json.dumps({'complete': True, 'records': [{'record': record, 'evidence_quote': '测试项目启动'}], 'gaps': []})
        data = {'id': 'mock', 'output': [
            {'type': 'web_search_call', 'status': 'completed'},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}
        ]}
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-only'}), patch.object(search, 'fetch', side_effect=lambda url: {'url': url, 'ok': False}), patch.object(search, 'response', return_value=data):
            batch = search.collect(self.root, {})
        self.assertEqual(len(batch['records']), 1)
        self.assertEqual(batch['records'][0]['status'], '待核实')
        self.assertTrue(all(b['gaps'] for b in batch['coverage']['search_batches'][:8]))
    def search_output(self, text):
        return {'id': 'test-response', 'status': 'completed', 'output': [
            {'type': 'web_search_call', 'status': 'completed'},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}
        ]}
    def test_intermediate_message_is_not_json(self):
        data = self.search_output('{"complete":true,"records":[],"gaps":[]}')
        data['output'].insert(0, {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Searching official sources'}]})
        self.assertEqual(search.parse_response(data)['records'], [])
    def test_fenced_json(self):
        text = chr(96)*3 + 'json\n{"complete":true,"records":[],"gaps":[]}\n' + chr(96)*3
        self.assertTrue(search.parse_response(self.search_output(text))['complete'])
    def test_json_embedded_after_prose(self):
        text = '检索完成，结果如下：\n{"complete":true,"records":[],"gaps":[]}\n以上为结果。'
        self.assertTrue(search.parse_response(self.search_output(text))['complete'])

    def test_only_one_complete_batch_object_is_accepted(self):
        text = '{"note":"progress"}\n{"complete":true,"records":[],"gaps":[]}'
        self.assertTrue(search.parse_response(self.search_output(text))['complete'])

    def test_multiple_batch_objects_are_rejected(self):
        text = '{"complete":true,"records":[],"gaps":[]}\n{"complete":true,"records":[],"gaps":[]}'
        with self.assertRaises(search.OutputFormatError):
            search.parse_response(self.search_output(text))

    def test_prose_without_batch_is_rejected(self):
        with self.assertRaises(search.OutputFormatError):
            search.parse_response(self.search_output('检索已完成，但没有JSON。'))

    def test_malformed_search_text_uses_format_pass(self):
        bad = self.search_output('{"complete":true, broken}')
        good = self.search_output('{"complete":true,"records":[],"gaps":[]}')
        with patch.object(search, 'response', side_effect=[bad, good]) as api:
            _, batch = search.request_batch({}, 'test-only')
        self.assertEqual(api.call_count, 2)
        self.assertEqual(batch['records'], [])
    def test_persistent_malformed_json_no_write(self):
        before = self.snapshot()
        with patch.object(search, 'response', return_value=self.search_output('{"complete":true,}')) as api:
            with self.assertRaises(search.OutputFormatError):
                search.request_batch({}, 'test-only')
        self.assertEqual(api.call_count, 4)
        self.assertEqual(before, self.snapshot())
    def test_format_pass_partial_coverage_is_reported_instead_of_failing(self):
        prose = self.search_output('检索完成，但部分官网无法访问。')
        partial = {'id': 'format-response', 'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text',
             'text': '{"complete":false,"records":[],"gaps":["广西医保局官网SSL错误"]}'}]}
        ]}
        with patch.object(search, 'response', side_effect=[prose, partial, prose, partial]) as api:
            _, batch = search.request_batch({}, 'test-only')
        self.assertEqual(api.call_count, 4)
        self.assertFalse(batch['complete'])
        self.assertEqual(batch['gaps'], ['广西医保局官网SSL错误'])

    def test_incomplete_batch_does_not_retry_as_empty_success(self):
        with patch.object(search, 'response', return_value=self.search_output('{"complete":false,"records":[],"gaps":[]}')) as api:
            _, batch = search.request_batch({}, 'test-only')
        self.assertEqual(api.call_count, 2)
        self.assertFalse(batch['complete'])

    def test_partial_batch_records_are_validated_before_acceptance(self):
        record = row()
        payload = json.dumps({'complete': False, 'records': [
            {'record': record, 'evidence_quote': '测试项目启动'}
        ], 'gaps': ['某官网超时']}, ensure_ascii=False)
        with patch.object(search, 'response', return_value=self.search_output(payload)):
            _, batch = search.request_batch({}, 'test-only')
        self.assertFalse(batch['complete'])
        self.assertEqual(len(batch['records']), 1)
        self.assertEqual(batch['gaps'], ['某官网超时'])

    def test_partial_batch_invalid_record_still_fails(self):
        payload = '{"complete":false,"records":[{"record":{},"evidence_quote":"测试"}],"gaps":["超时"]}'
        with patch.object(search, 'response', return_value=self.search_output(payload)) as api:
            with self.assertRaises(search.OutputFormatError):
                search.request_batch({}, 'test-only')
        self.assertEqual(api.call_count, 4)

    def test_incomplete_batch_logs_gap_and_can_recover(self):
        incomplete = self.search_output('{"complete":false,"records":[],"gaps":["某官网超时"]}')
        complete = self.search_output('{"complete":true,"records":[],"gaps":[]}')
        with patch.object(search, 'response', side_effect=[incomplete, complete]) as api:
            _, batch = search.request_batch({}, 'test-only')
        self.assertEqual(api.call_count, 2)
        self.assertTrue(batch['complete'])
    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(search.OutputFormatError):
            search.parse_response(self.search_output('{"complete":false,"complete":true,"records":[]}'))
    def test_schema_covers_all_22_fields(self):
        schema = search.batch_format()
        self.assertEqual(schema['type'], 'json_schema')
        record = schema['schema']['properties']['records']['items']['properties']['record']
        self.assertEqual(record['required'], p.FIELDS)
        self.assertFalse(record['additionalProperties'])
    def test_deepseek_endpoint(self):
        from unittest.mock import MagicMock
        context = MagicMock()
        context.__enter__.return_value.read.return_value = b'{"status":"completed","output":[]}'
        with patch.object(search, 'urlopen', return_value=context) as http:
            search.response({'model': 'deepseek-v4-flash'}, 'test-key')
        req = http.call_args.args[0]
        self.assertEqual(req.full_url, 'https://api.deepseek.com/responses')
        self.assertEqual(req.get_header('Authorization'), 'Bearer test-key')
    def test_deepseek_citations(self):
        cite = {'type': 'url_citation', 'url': 'https://www.nhsa.gov.cn/'}
        data = {'output': [{'type': 'message', 'content': [{'annotations': [cite]}]}]}
        self.assertEqual(search.search_sources(data), [cite])
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
