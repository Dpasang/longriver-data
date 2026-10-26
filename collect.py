"""Daily source-preserving LongRiver archive and current-observation snapshots."""

import argparse
import csv
import filecmp
import json
import math
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

LOCAL = timezone(timedelta(hours=8))
SOURCE_URL = 'http://www.cjh.com.cn/sqindex.html'
UPSTREAM_URL = 'https://github.com/cxumol/LongRiver'
MAX_AGE_HOURS = 48


def parse_page(html):
    match = re.search(r'var\s+sssq\s*=\s*(\[.*?\])\s*;', html, re.S)
    if not match:
        raise ValueError('Source page has no sssq JSON array')
    return json.loads(match.group(1))


def observed_at(row):
    tm = row.get('tm')
    if isinstance(tm, bool):
        raise ValueError('Boolean observation timestamp')
    try:
        millis = float(tm)
        if not math.isfinite(millis):
            raise ValueError('Non-finite timestamp')
        return datetime.fromtimestamp(millis / 1000, timezone.utc)
    except (TypeError, OverflowError, OSError) as error:
        raise ValueError('Invalid observation timestamp') from error


def validate_records(records, now, fresh=True):
    if not isinstance(records, list) or not records:
        raise ValueError('No station records')
    latest = {}
    for row in records:
        if not isinstance(row, dict) or not all(row.get(k) not in (None, '') for k in ('rvnm', 'stnm', 'tm')):
            raise ValueError('Station record missing required fields')
        date = observed_at(row)
        if date.year < 1990 or date > now + timedelta(hours=1):
            raise ValueError('Observation timestamp outside plausible range')
        key = str(row.get('stcd') or (str(row['rvnm']) + '/' + str(row['stnm'])))
        if key not in latest or date >= observed_at(latest[key]):
            latest[key] = row
    rows = [latest[key] for key in sorted(latest)]
    if fresh and any(now - observed_at(row) > timedelta(hours=MAX_AGE_HOURS) for row in rows):
        raise ValueError('At least one station is older than 48 hours')
    return rows


def archive_upstream(source, destination, now):
    source = source / 'data'
    files = sorted(p for p in source.rglob('*') if p.is_file() and p.suffix in ('.json', '.csv'))
    if not files:
        raise ValueError('Upstream has no archive data')
    csv_rows = 0
    quality_files = []
    # Reject unreadable JSON before copying; preserve legacy CSV bytes with flags.
    for file in files:
        if file.is_symlink():
            raise ValueError('Symlink in upstream data')
        if file.suffix == '.json':
            payload = json.loads(file.read_text(encoding='utf-8-sig'))
            if not isinstance(payload, dict):
                raise ValueError('Archive JSON is not a station mapping')
            for rows in payload.values():
                validate_records(rows, now, fresh=False)
        else:
            with file.open(encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                header_valid = bool(reader.fieldnames) and {'rvnm', 'stnm', 'tm'}.issubset(reader.fieldnames)
                issues = 0
                first_line = None
                for row in reader:
                    invalid = not header_valid or None in row or any(row.get(k) in (None, '') for k in ('rvnm', 'stnm', 'tm'))
                    if not invalid:
                        try:
                            observed_at(row)
                        except ValueError:
                            invalid = True
                    if invalid:
                        issues += 1
                        first_line = first_line or reader.line_num
                    csv_rows += 1
                if issues or not header_valid:
                    quality_files.append({'path': file.relative_to(source).as_posix(),
                                          'issue_rows': issues, 'first_issue_line': first_line,
                                          'header_valid': header_valid})
    for file in files:
        target = destination / 'data' / file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and filecmp.cmp(file, target, shallow=False):
            continue
        temporary = target.with_name(target.name + '.tmp')
        shutil.copyfile(file, temporary)
        temporary.replace(target)
    issue_rows = sum(item['issue_rows'] for item in quality_files)
    write_json(destination / 'status/archive_quality.json', {
        'checked_at': now.astimezone(LOCAL).isoformat(timespec='seconds'),
        'upstream_commit': os.environ.get('UPSTREAM_COMMIT'),
        'csv_files_with_issues': len(quality_files),
        'csv_rows_with_issues': issue_rows,
        'policy': 'Preserve upstream bytes; flagged CSVs are not analysis-ready. Prefer corresponding JSON.',
        'files': quality_files,
    })
    return {
        'archive_file_count': len(files),
        'archive_bytes': sum(p.stat().st_size for p in files),
        'archive_csv_rows': csv_rows,
        'archive_validation': 'structural_warnings' if quality_files else 'passed',
        'archive_csv_files_with_issues': len(quality_files),
        'archive_csv_rows_with_issues': issue_rows,
        'archive_months': sorted({p.relative_to(source).parts[0] for p in files}),
    }


def latest_upstream(source, now):
    files = sorted((source / 'data').glob('20??-??/LongRiver.json'))
    if not files:
        raise ValueError('No upstream station mapping')
    payload = json.loads(files[-1].read_text(encoding='utf-8-sig'))
    if not isinstance(payload, dict):
        raise ValueError('Invalid upstream station mapping')
    # Only each station's newest record is needed for the fallback snapshot.
    records = [max(rows, key=observed_at) for rows in payload.values() if rows]
    return validate_records(records, now)


def fetch_page():
    request = Request(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html'})
    with urlopen(request, timeout=30) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Unexpectedly large source page')
    return raw.decode('utf-8-sig')


def write_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(file)


def write_csv(file, records):
    file.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in records for key in row))
    temporary = file.with_name(file.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    temporary.replace(file)


def run(root, upstream, fetch=fetch_page, now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(LOCAL)
    status = {
        'captured_at': local.isoformat(timespec='seconds'),
        'fresh': False,
        'source_url': SOURCE_URL,
        'upstream_repository': UPSTREAM_URL,
        'upstream_commit': os.environ.get('UPSTREAM_COMMIT'),
        'max_age_hours': MAX_AGE_HOURS,
    }
    try:
        status.update(archive_upstream(upstream, root, now))
        try:
            records = validate_records(parse_page(fetch()), now)
            status['source'] = 'official'
        except (OSError, ValueError, UnicodeError) as error:
            status['direct_source_error'] = type(error).__name__
            status['source'] = 'upstream_fallback'
            records = latest_upstream(upstream, now)
        times = [observed_at(row) for row in records]
        status.update({
            'fresh': True,
            'station_count': len(records),
            'oldest_observed_at': min(times).astimezone(LOCAL).isoformat(),
            'latest_observed_at': max(times).astimezone(LOCAL).isoformat(),
            'oldest_age_hours': round((now - min(times)).total_seconds() / 3600, 3),
            'station_ids': [str(row.get('stcd', '')) for row in records],
        })
        snapshot = dict(status, records=records)
        dated = root / 'snapshots' / local.strftime('%Y/%m/%Y-%m-%d')
        write_json(dated.with_suffix('.json'), snapshot)
        write_csv(dated.with_suffix('.csv'), records)
        write_json(root / 'latest/data.json', snapshot)
        write_csv(root / 'latest/data.csv', records)
        result = 0
    except (OSError, ValueError, UnicodeError) as error:
        status['error_type'] = type(error).__name__
        status['error'] = str(error)[:300]
        result = 1
    write_json(root / 'status/latest.json', status)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        summary = '\n'.join([
            '# LongRiver data update',
            f"- Fresh data obtained: {status['fresh']}",
            f"- Source: {status.get('source', 'unavailable')}",
            f"- Stations: {status.get('station_count', 0)}",
            f"- Latest observation: {status.get('latest_observed_at', 'unavailable')}",
            f"- Archive files: {status.get('archive_file_count', 0)}",
            f"- Direct source error: {status.get('direct_source_error', 'none')}",
        ])
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(summary + '\n')
    print(json.dumps(status, ensure_ascii=True))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', type=Path, default=Path('.upstream'))
    parser.add_argument('--root', type=Path, default=Path('.'))
    args = parser.parse_args()
    raise SystemExit(run(args.root, args.upstream))
