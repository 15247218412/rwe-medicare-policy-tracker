"""Incremental merge with validation and staged legacy-script execution."""
import argparse, csv, hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FIELDS = 'record_id publish_date discovered_date province city organization title category domain stage summary change_summary source_url attachment_name attachment_url source_type official first_seen last_seen status confidence notes'.split()
CONTENT = 'publish_date province city organization title category domain stage summary attachment_name attachment_url source_type official confidence notes'.split()
CN = timezone(timedelta(hours=8))

def validate(rows):
    if not isinstance(rows, list):
        raise ValueError('records must be an array')
    result = []
    for raw in rows:
        if not isinstance(raw, dict) or set(raw) - set(FIELDS):
            raise ValueError('Unknown fields or malformed CSV')
        row = {}
        for k in FIELDS:
            v = raw.get(k, '')
            if not isinstance(v, str):
                raise ValueError('Fields must be strings')
            row[k] = ' '.join(v.replace('\u3000', ' ').split())
        u = urlsplit(row['source_url'])
        if not row['title'] or u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
            raise ValueError('title and valid source_url required')
        if row['status'] not in ('', '新增', '更新', '持续推进', '已完成', '待核实', '无变化') or row['confidence'] not in ('', 'high', 'medium', 'low'):
            raise ValueError('Invalid status/confidence')
        for k in ('publish_date', 'discovered_date', 'first_seen', 'last_seen'):
            if row[k]:
                datetime.strptime(row[k], '%Y-%m-%d')
        result.append(row)
    return result

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError('Invalid 22-column schema: ' + path.name)
        return validate(list(reader))

def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

def merge(old, incoming, day):
    rows = [r.copy() for r in old]
    urls, ids, changes = {}, {}, {}
    for r in rows:
        if r['source_url'] in urls or (r['record_id'] and r['record_id'] in ids):
            raise ValueError('Historical duplicate URL/ID; reconcile first')
        urls[r['source_url']] = r
        if r['record_id']:
            ids[r['record_id']] = r
    for item in incoming:
        r = urls.get(item['source_url'])
        if item['record_id'] in ids:
            matched = ids[item['record_id']]
            if r is not None and matched is not r:
                raise ValueError('Conflicting ID and URL')
            r = matched
        if r is None:
            keys = ('publish_date', 'province', 'organization', 'title')
            sig = tuple(item[k] for k in keys)
            if all(sig) and any(tuple(x[k] for k in keys) == sig for x in rows):
                continue
            r = item.copy()
            r['record_id'] = item['record_id'] or day.replace('-', '') + '-RWE-' + hashlib.sha256(item['source_url'].encode()).hexdigest()[:12]
            r.update(discovered_date=day, first_seen=day, last_seen=day)
            r['status'] = '待核实' if item['confidence'] == 'low' or item['status'] == '待核实' else '新增'
            r['change_summary'] = item['change_summary'] or item['summary'] or item['title']
            rows.append(r)
            urls[r['source_url']] = r
            ids[r['record_id']] = r
            changes[r['record_id']] = r
        else:
            changed = [k for k in CONTENT + ['source_url'] if item[k] and item[k] != r[k]]
            if changed:
                old_url = r['source_url']
                for k in changed:
                    r[k] = item[k]
                urls.pop(old_url, None)
                urls[r['source_url']] = r
                r['last_seen'] = day
                r['status'] = '待核实' if item['confidence'] == 'low' or item['status'] == '待核实' else '更新'
                r['change_summary'] = item['change_summary'] or '字段更新：' + '、'.join(changed)
                changes[r['record_id']] = r
    return rows, list(changes.values())

def apply_batch(root, batch, now=None):
    now = now or datetime.now(CN)
    day = now.astimezone(CN).date().isoformat()
    if not isinstance(batch, dict) or batch.get('complete') is not True:
        raise ValueError('Incomplete collection; database unchanged')
    incoming = validate(batch.get('records'))
    state = json.loads((root / 'data/run_state.json').read_text(encoding='utf-8-sig'))
    digest = hashlib.sha256(json.dumps(batch, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if digest in state.get('processed_batches', []):
        return {'replayed': True, 'new': 0, 'updated': 0}
    master, latest = merge(read_csv(root / 'data/master.csv'), incoming, day)
    with tempfile.TemporaryDirectory() as temp:
        stage = Path(temp) / 'project'
        shutil.copytree(root, stage, ignore=shutil.ignore_patterns('.git', '__pycache__', '.work'))
        write_csv(stage / 'data/master.csv', master)
        write_csv(stage / 'data/latest.csv', latest)
        (stage / 'data/collection.json').write_text(json.dumps(batch.get('coverage', {}), ensure_ascii=False, indent=2), encoding='utf-8')
        for name in ('normalize.py', 'deduplicate.py', 'build_report.py'):
            subprocess.run([sys.executable, str(stage / 'scripts' / name)], check=True,
                           env={**os.environ, 'MONITOR_DATE': day, 'PYTHONUTF8': '1'})
        read_csv(stage / 'data/master.csv')
        read_csv(stage / 'data/latest.csv')
        state.update(last_successful_run=now.isoformat(), processed_batches=(state.get('processed_batches', []) + [digest])[-100:])
        if not state.get('last_baseline_run'):
            state['last_baseline_run'] = now.isoformat()
        (stage / 'data/run_state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Publish only after all stages pass. Git commit is the multi-file transaction.
        for folder in ('data', 'reports', 'provinces'):
            for src in (stage / folder).glob('*'):
                if src.is_file():
                    dest = root / folder / src.name
                    dest.parent.mkdir(exist_ok=True)
                    if not dest.exists() or src.read_bytes() != dest.read_bytes():
                        temp_path = dest.with_suffix(dest.suffix + '.tmp')
                        shutil.copyfile(src, temp_path)
                        os.replace(temp_path, dest)
    return {'new': sum(r['status'] == '新增' for r in latest), 'updated': sum(r['status'] == '更新' for r in latest), 'pending': sum(r['status'] == '待核实' for r in latest)}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path)
    p.add_argument('--scheduled', action='store_true')
    args = p.parse_args()
    state = json.loads((ROOT / 'data/run_state.json').read_text(encoding='utf-8-sig'))
    if args.scheduled and state.get('last_successful_run'):
        previous = datetime.fromisoformat(state['last_successful_run'])
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=CN)
        if (datetime.now(CN).date() - previous.astimezone(CN).date()).days < 2:
            print('Not due: fewer than two calendar days since success')
            return
    if args.input:
        batch = {'complete': True, 'records': read_csv(args.input), 'coverage': {'mode': 'CSV import'}} if args.input.suffix.lower() == '.csv' else json.loads(args.input.read_text(encoding='utf-8-sig'))
    else:
        from search_updates import collect
        batch = collect(ROOT, state)
    print(json.dumps(apply_batch(ROOT, batch), ensure_ascii=False))

if __name__ == '__main__':
    main()
