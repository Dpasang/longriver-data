import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

import collect

NOW = datetime(2026, 10, 26, 14, tzinfo=timezone.utc)


def record(hours=1, station='60112200'):
    return {'q': '18000', 'rvnm': '长江干流', 'stcd': station, 'stnm': '汉口',
            'tm': int((NOW - timedelta(hours=hours)).timestamp() * 1000), 'wptn': '4', 'z': '17.340'}


def upstream(folder, rows=None):
    data = folder / 'data' / '2026-10'
    data.mkdir(parents=True)
    rows = rows if rows is not None else [record()]
    (data / 'LongRiver.json').write_text(json.dumps({'./data/2026-10/长江干流_汉口': rows}), encoding='utf-8')
    (data / '长江干流_汉口.csv').write_text('q,rvnm,stcd,stnm,tm,wptn,z\n18000,长江干流,60112200,汉口,1793019600000,4,17.340\n', encoding='utf-8')


class CollectorTests(unittest.TestCase):
    def setUp(self):
        # Offline scenarios must not populate the real GitHub run summary.
        self.environment = patch.dict('os.environ', {'GITHUB_STEP_SUMMARY': ''})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_extract_multiline_json_and_preserve_values(self):
        row = record()
        rows = collect.parse_page('<script>var sssq =\n' + json.dumps([row]) + ';\nvar x=1;</script>')
        self.assertEqual(rows, [row])
        self.assertEqual(rows[0]['z'], '17.340')

    def test_missing_variable_rejected(self):
        with self.assertRaises(ValueError):
            collect.parse_page('<html>temporarily unavailable</html>')

    def test_stale_or_future_station_rejected(self):
        for hours in [49, -2]:
            with self.assertRaises(ValueError):
                collect.validate_records([record(hours)], NOW)

    def test_empty_and_invalid_timestamp_rejected(self):
        for rows in [[], [{'stnm':'x','rvnm':'r','stcd':'1','tm':True}], [dict(record(), tm='nan')]]:
            with self.assertRaises(ValueError):
                collect.validate_records(rows, NOW)

    def test_same_station_keeps_latest_observation(self):
        rows = collect.validate_records([record(3), record(1)], NOW)
        self.assertEqual(rows, [record(1)])

    def test_direct_capture_and_history_are_saved_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, src = Path(tmp)/'out', Path(tmp)/'upstream'
            upstream(src)
            result = collect.run(root, src, lambda: 'var sssq = ' + json.dumps([record(0)]) + ';', NOW)
            self.assertEqual(result, 0)
            status = json.loads((root/'status/latest.json').read_text(encoding='utf-8'))
            self.assertEqual(status['source'], 'official')
            self.assertTrue(status['fresh'])
            self.assertEqual(status['archive_file_count'], 2)
            self.assertEqual((src/'data/2026-10/长江干流_汉口.csv').read_bytes(), (root/'data/2026-10/长江干流_汉口.csv').read_bytes())
            snapshot = json.loads((root/'snapshots/2026/10/2026-10-26.json').read_text(encoding='utf-8'))
            self.assertEqual(snapshot['records'], [record(0)])
            self.assertTrue((root/'latest/data.csv').exists())

    def test_upstream_fallback_is_explicit(self):
        def fail():
            raise TimeoutError('source unreachable')
        with tempfile.TemporaryDirectory() as tmp:
            root, src = Path(tmp)/'out', Path(tmp)/'upstream'
            upstream(src)
            self.assertEqual(collect.run(root, src, fail, NOW), 0)
            status = json.loads((root/'status/latest.json').read_text(encoding='utf-8'))
            self.assertEqual(status['source'], 'upstream_fallback')
            self.assertEqual(status['direct_source_error'], 'TimeoutError')

    def test_stale_fallback_does_not_replace_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, src = Path(tmp)/'out', Path(tmp)/'upstream'
            upstream(src, [record(80)])
            (root/'latest').mkdir(parents=True)
            (root/'latest/data.json').write_text('previous snapshot', encoding='utf-8')
            self.assertEqual(collect.run(root, src, lambda:'unavailable', NOW), 1)
            self.assertEqual((root/'latest/data.json').read_text(encoding='utf-8'), 'previous snapshot')
            self.assertFalse(json.loads((root/'status/latest.json').read_text(encoding='utf-8'))['fresh'])

    def test_invalid_archive_does_not_overwrite_existing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, src = Path(tmp)/'out', Path(tmp)/'upstream'
            upstream(src)
            (src/'data/2026-10/LongRiver.json').write_text('broken', encoding='utf-8')
            (root/'data').mkdir(parents=True)
            (root/'data/keep.txt').write_text('keep', encoding='utf-8')
            self.assertEqual(collect.run(root, src, lambda:'', NOW), 1)
            self.assertEqual((root/'data/keep.txt').read_text(encoding='utf-8'), 'keep')
            self.assertFalse((root/'data/2026-10/LongRiver.json').exists())

    def test_legacy_variable_width_csv_is_preserved_and_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, src = Path(tmp)/'out', Path(tmp)/'upstream'
            upstream(src)
            file = src/'data/2026-10/长江干流_汉口.csv'
            original = 'q,rvnm,stcd,stnm,tm,wptn,z\n6730,11000,长江,60106980,三峡水库,1664560800000,5,153.480\n'
            file.write_text(original, encoding='utf-8')
            result = collect.run(root, src, lambda:'var sssq = ' + json.dumps([record()]) + ';', NOW)
            self.assertEqual(result, 0)
            self.assertEqual((root/'data/2026-10/长江干流_汉口.csv').read_bytes(), file.read_bytes())
            report = json.loads((root/'status/archive_quality.json').read_text(encoding='utf-8'))
            self.assertEqual(report['csv_files_with_issues'], 1)
            self.assertEqual(report['csv_rows_with_issues'], 1)
            status = json.loads((root/'status/latest.json').read_text(encoding='utf-8'))
            self.assertEqual(status['archive_validation'], 'structural_warnings')
            self.assertTrue(status['fresh'])


if __name__ == '__main__':
    unittest.main()
