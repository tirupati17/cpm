import base64
import datetime
import os
import unittest

from apifake import ApiCase

FLAGS = {'flags': [
    {'id': 11, 'key': 'paywall_enabled', 'enabled': True, 'rolloutPercentage': 100, 'deployments': [1],
     'variants': [{'key': 'on'}]},
    {'id': 12, 'key': 'orphan_flag', 'enabled': True, 'rolloutPercentage': 100, 'deployments': []},
    {'id': 13, 'key': 'old_flag', 'enabled': False, 'archived': True, 'deployments': [1]},
]}


class AmplitudeTest(ApiCase):
    ENV = {'AMPLITUDE_API_KEY': 'apikey123', 'AMPLITUDE_SECRET_KEY': 'secretkey456',
           'AMPLITUDE_MANAGEMENT_KEY': 'mgmtkey789xyz'}

    def test_flags_table_marks_unreachable(self):
        self.route(('GET', 'experiment.amplitude.com/api/1/flags', 200, FLAGS))
        code, out, _ = self.run_cmd('amplitude', 'flags', [])
        self.assertEqual(code, 0)
        self.assertIn('paywall_enabled', out)
        self.assertIn('! no deployment', out)
        self.assertNotIn('old_flag', out)
        self.assertEqual(self.http.calls[0]['headers']['Authorization'], 'Bearer mgmtkey789xyz')

    def test_flags_follow_cursor_and_bare_list(self):
        self.route(('GET', 'cursor=c2', 200, [{'key': 'b'}]),
                   ('GET', '/api/1/flags', 200, {'flags': [{'key': 'a'}], 'nextCursor': 'c2'}))
        code, out, _ = self.run_cmd('amplitude', 'flags', ['--json'])
        self.assertIn('"a"', out)
        self.assertIn('"b"', out)

    def test_flags_without_management_key(self):
        del os.environ['AMPLITUDE_MANAGEMENT_KEY']
        code, _, err = self.run_cmd('amplitude', 'flags', [])
        self.assertEqual(code, 1)
        self.assertIn('cpm creds set AMPLITUDE_MANAGEMENT_KEY', err)
        self.assertEqual(self.http.calls, [])

    def test_flag_toggle_dry_run_then_commit_patches_by_id(self):
        self.route(('GET', '/api/1/flags', 200, FLAGS), ('PATCH', '/api/1/flags/11', 200, {}))
        code, out, _ = self.run_cmd('amplitude', 'flag', ['paywall_enabled', '--off'])
        self.assertIn('DRY RUN', out)
        self.assertEqual(self.http.by('PATCH'), [])
        code, out, _ = self.run_cmd('amplitude', 'flag', ['paywall_enabled', '--off', '--commit'])
        self.assertEqual(code, 0)
        self.assertEqual(self.http.by('PATCH')[0]['body'], {'enabled': False})

    def test_flag_missing_and_already_set(self):
        self.route(('GET', '/api/1/flags', 200, FLAGS))
        code, _, err = self.run_cmd('amplitude', 'flag', ['paywall', '--on'])
        self.assertEqual(code, 1)
        self.assertIn('local fallback', err)
        self.assertIn('paywall_enabled', err)
        code, out, _ = self.run_cmd('amplitude', 'flag', ['paywall_enabled', '--on', '--commit'])
        self.assertIn('Already', out)
        self.assertEqual(self.http.by('PATCH'), [])

    def test_eu_region_switches_hosts(self):
        os.environ['AMPLITUDE_REGION'] = 'EU'
        self.route(('GET', 'experiment.eu.amplitude.com/api/1/flags', 200, {'flags': []}),
                   ('GET', 'analytics.eu.amplitude.com/api/2/events/list', 200, {'data': []}))
        self.run_cmd('amplitude', 'flags', [])
        self.run_cmd('amplitude', 'events', [])
        self.assertEqual(len(self.http.calls), 2)

    def test_events_segmentation_totals_and_unknown_event(self):
        self.route(('GET', 'event_type%22%3A+%22nope', 400, b'Invalid event'),
                   ('GET', '/api/2/events/segmentation', 200, {'data': {
                       'series': [[3, 4, 5]], 'seriesCollapsed': [[{'setId': '', 'value': 12}]],
                       'xValues': ['2026-09-25', '2026-09-26', '2026-09-27']}}))
        today = datetime.date(2026, 9, 27)
        code, out, _ = self.run_cmd('amplitude', 'events', ['--event', 'app_opened', '--event', 'nope',
                                                            '--days', '3', '--daily'], today=today)
        self.assertEqual(code, 0)
        self.assertIn('12', out)
        self.assertIn('no such event', out)
        self.assertIn('09-26', out)
        call = self.http.calls[0]
        query = self.http.query(call)
        self.assertEqual((query['start'], query['end'], query['m']), ('20260925', '20260927', 'totals'))
        expected = 'Basic ' + base64.b64encode(b'apikey123:secretkey456').decode()
        self.assertEqual(call['headers']['Authorization'], expected)

    def test_events_list(self):
        self.route(('GET', '/api/2/events/list', 200, {'data': [
            {'value': 'a', 'totals': 5}, {'value': 'b', 'totals': 50}, {'value': 'gone', 'deleted': True}]}))
        code, out, _ = self.run_cmd('amplitude', 'events', [])
        self.assertLess(out.index('b '), out.index('a '))
        self.assertNotIn('gone', out)


if __name__ == '__main__':
    unittest.main()
