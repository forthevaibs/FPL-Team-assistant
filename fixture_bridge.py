"""Cached batch integration without importing conflicting app modules."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parent
MATCH = ROOT.parent / 'match_predictor'
ALIASES = {'Man Utd': 'Man United', 'Manchester United': 'Man United',
    'Manchester City': 'Man City', 'Spurs': 'Tottenham',
    'Coventry City': 'Coventry', 'Hull City': 'Hull', 'Ipswich Town': 'Ipswich',
    'Nott\'m Forest': "Nott'm Forest", 'Nottingham Forest': "Nott'm Forest",
    'Wolverhampton Wanderers': 'Wolves', 'Newcastle United': 'Newcastle'}


def signature():
    files = [MATCH/'artifacts/model.joblib', MATCH/'fixture_batch.py', MATCH/'predictor.py', MATCH/'models.py']
    files += sorted((MATCH/'data').glob('[0-9][0-9][0-9][0-9].csv'))
    return [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files]


def refresh_results(season):
    interpreter=MATCH/'.venv/Scripts/python.exe'
    if not interpreter.exists(): interpreter=Path(sys.executable)
    run=subprocess.run([str(interpreter),str(MATCH/'predictor.py'),'download','--start',str(season),
        '--end',str(season),'--refresh'],cwd=MATCH,capture_output=True,text=True,timeout=120)
    if run.returncode: raise ValueError(run.stderr[-1500:])


def forecasts(bootstrap, fixtures, start, horizon, now=None):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='UTC')
    names = {t['id']: ALIASES.get(t['name'], t['name']) for t in bootstrap['teams']}
    wanted, errors = [], {}
    for f in fixtures:
        if f.get('event') not in range(start, start+horizon) or f.get('finished'):
            continue
        if not f.get('kickoff_time') or pd.Timestamp(f['kickoff_time']) <= now:
            errors[str(f['id'])] = 'Kickoff missing or fixture already started'; continue
        wanted.append(dict(id=f['id'], home=names[f['team_h']], away=names[f['team_a']], kickoff_time=f['kickoff_time']))
    # Refresh at least hourly; changes to fixtures, model, source data or code invalidate.
    identity = dict(fixtures=wanted, hour=now.floor('h').isoformat(), version=1, files=signature())
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    folder = ROOT/'data/fixture_forecasts'; folder.mkdir(parents=True, exist_ok=True)
    path = folder/f'{key}.json'
    if path.exists():
        result = json.loads(path.read_text())
        result['cache_hit'] = True
    else:
        interpreter = MATCH/'.venv/Scripts/python.exe'
        if not interpreter.exists(): interpreter = Path(sys.executable)
        request = dict(as_of=now.isoformat(), fixtures=wanted)
        completed = subprocess.run([str(interpreter), str(MATCH/'fixture_batch.py')],
            input=json.dumps(request), text=True, capture_output=True, timeout=120, cwd=MATCH)
        if completed.returncode:
            raise ValueError('Match forecast failed: '+completed.stderr[-1500:])
        result = json.loads(completed.stdout)
        path.write_text(json.dumps(result), encoding='utf-8')
        result['cache_hit'] = False
    result['errors'].update(errors)
    result['cache_key'] = key
    # Age is measured now, not against fixtures several weeks into the future.
    result['usable'] = result['data_age_days'] <= 14
    if not result['usable']:
        result['warning'] = 'Match results are over 14 days old; using baseline projections until data is refreshed.'
    return result
