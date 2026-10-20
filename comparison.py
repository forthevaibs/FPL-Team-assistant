"""Prospective comparison: freeze both methods before deadline, score after finalization."""
import json
from pathlib import Path
import pandas as pd
from optimizer import optimize
from data import fetch

ROOT = Path(__file__).resolve().parent/'data/comparisons'


def season_key(bootstrap):
    return pd.Timestamp(min(e['deadline_time'] for e in bootstrap['events'])).year


def record(bootstrap, event, baseline, linked, provenance, now=None, folder=ROOT):
    supplied_now = now
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='UTC')
    deadline = pd.Timestamp(event['deadline_time'])
    if now >= deadline:
        raise ValueError('Deadline has passed; cannot record a prospective comparison.')
    if not provenance.get('usable') or not provenance.get('fixtures'):
        raise ValueError('Fresh linked forecasts are required to record a comparison.')
    for key in ['players_fetched', 'fixtures_fetched', 'as_of']:
        stamp = pd.Timestamp(provenance[key])
        if stamp >= deadline or stamp > now or now-stamp > pd.Timedelta(hours=1):
            raise ValueError('Refresh data before recording: source timestamps must be recent and before deadline.')
    if provenance.get('source_stale'):
        raise ValueError('Cannot record a fair comparison from fallback source data.')
    season = season_key(bootstrap)
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    path = folder/f'{season}-gw{event["id"]}.json'
    if path.exists():
        return json.loads(path.read_text())
    squads = {}
    for name, frame in [('baseline', baseline), ('linked', linked)]:
        squad, message = optimize(frame, budget=100)
        squads[name] = dict(starting=[int(i) for i in squad.loc[squad.Starting, 'ID']],
            captain=int(squad.loc[squad.Captain, 'ID'].iloc[0]),
            predicted=float(squad.loc[squad.Starting, 'Projected points'].sum()+squad.loc[squad.Captain, 'Projected points'].sum()),
            solver=message)
    # Optimizing can take time: do not accept a snapshot completed after deadline.
    finished = pd.Timestamp.now(tz='UTC') if supplied_now is None else now
    if finished >= deadline:
        raise ValueError('Deadline passed during squad optimization; snapshot not saved.')
    base = baseline.set_index('ID')
    other = linked.set_index('ID')
    if set(base.index) != set(other.index):
        raise ValueError('Baseline and linked player pools must match.')
    rows = [dict(id=int(i), player=r.Player, position=r.Position, eligible=bool(r.Eligible),
        minutes=int(r.Minutes), baseline=float(r['Projected points']), linked=float(other.loc[i, 'Projected points'])) for i,r in base.iterrows()]
    snapshot = dict(version=1, season=season, event=event['id'], deadline=deadline.isoformat(),
        captured_at=now.isoformat(), players=rows, squads=squads, provenance=provenance,
        return_definition='Fixed starting XI plus captain; no autosubs, vice-captain, chips or transfer hits.')
    # Exclusive create: never silently replace an already recorded gameweek.
    with path.open('x', encoding='utf-8') as handle:
        json.dump(snapshot, handle, indent=2)
    return snapshot


def evaluate(snapshot, actual):
    rows = pd.DataFrame(snapshot['players'])
    rows['actual'] = rows.id.map(actual)
    eligible = rows[rows.eligible]
    covered = eligible[eligible.actual.notna()]
    report = dict(event=snapshot['event'], captured_at=snapshot['captured_at'],
        coverage=f'{len(covered)}/{len(eligible)} eligible players', methods={})
    for name in ['baseline', 'linked']:
        squad = snapshot['squads'][name]
        needed = squad['starting']+[squad['captain']]
        returns = float(sum(actual[i] for i in needed)) if all(i in actual for i in needed) else None
        established = covered[covered.minutes >= 270]
        report['methods'][name] = dict(mae=float((covered[name]-covered.actual).abs().mean()) if len(covered) else None,
            established_mae=float((established[name]-established.actual).abs().mean()) if len(established) else None,
            actual_xi_captain=returns, projected_xi_captain=squad['predicted'])
    return report


def score_finished(bootstrap, folder=ROOT):
    folder=Path(folder)
    events={e['id']:e for e in bootstrap['events']}
    season=season_key(bootstrap)
    for path in folder.glob(f'{season}-gw*.json'):
        if path.stem.endswith('-score'): continue
        snapshot=json.loads(path.read_text())
        event=events.get(snapshot['event'], {})
        if not event.get('finished') or not event.get('data_checked'): continue
        live, stamp, stale=fetch(f"event/{snapshot['event']}/live/",refresh=True)
        if stale: raise ValueError('Final player results are stale; retry scoring later.')
        actual={int(p['id']):float(p['stats']['total_points']) for p in live['elements'] if 'total_points' in p.get('stats',{})}
        report=evaluate(snapshot,actual)
        report['results_fetched']=stamp
        path.with_name(path.stem+'-score.json').write_text(json.dumps(report,indent=2))


def summaries(folder=ROOT):
    rows=[]
    for path in sorted(Path(folder).glob('*-gw*.json')):
        if path.stem.endswith('-score'): continue
        snapshot=json.loads(path.read_text())
        result_path=path.with_name(path.stem+'-score.json')
        report=json.loads(result_path.read_text()) if result_path.exists() else None
        for method in ['baseline','linked']:
            result=report['methods'][method] if report else {}
            rows.append({'Season':snapshot['season'],'GW':snapshot['event'],'Method':method,
                'Status':'Scored' if report else 'Awaiting finalized results',
                'Player MAE':result.get('mae'),'Established player MAE':result.get('established_mae'),
                'Actual XI + captain':result.get('actual_xi_captain'),
                'Projected XI + captain':snapshot['squads'][method]['predicted'],
                'Coverage':report.get('coverage') if report else None})
    return pd.DataFrame(rows)
