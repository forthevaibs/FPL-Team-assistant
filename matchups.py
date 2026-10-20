"""Fixture-level xGA and recency-weighted FPL-position scoring evidence."""
from pathlib import Path
from io import StringIO
from concurrent.futures import ThreadPoolExecutor
import json
import requests
import pandas as pd
from data import fetch

ROOT = Path(__file__).parent / 'data'
ALIASES = {'Manchester City':'Man City','Manchester United':'Man Utd','Nottingham Forest':"Nott'm Forest",'Newcastle United':'Newcastle','Tottenham':'Spurs','Wolverhampton Wanderers':'Wolves'}

def club(name):
    return ALIASES.get(name,name)

def build_current(bootstrap, fixtures):
    """Sum attacking xG once per player-fixture, then reverse to obtain team xGA.

    Do not sum player xGC: that would count the same chances several times.
    Fixture/venue, rather than a player's current club, determines historical team.
    """
    by_id = {f['id']:f for f in fixtures if f.get('finished')}
    names = {t['id']:club(t['name']) for t in bootstrap['teams']}
    def read(p):
        payload,_,stale = fetch(f"element-summary/{p['id']}/")
        if stale:
            raise ValueError('A player history is stale; retaining the previous complete enrichment snapshot.')
        rows=[]
        for h in payload.get('history',[]):
            f=by_id.get(h['fixture'])
            if not f: continue
            team=f['team_h'] if h['was_home'] else f['team_a']
            opp=f['team_a'] if h['was_home'] else f['team_h']
            rows.append({'fixture':h['fixture'],'element':p['id'],'team':names[team],'opponent':names[opp],'position':{1:'GK',2:'DEF',3:'MID',4:'FWD'}.get(p['element_type'],'OTHER'),'minutes':h['minutes'],'goals_scored':h['goals_scored'],'xg':h.get('expected_goals'),'kickoff_time':h['kickoff_time']})
        return rows
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows=[r for group in pool.map(read,bootstrap['elements']) for r in group]
    frame=pd.DataFrame(rows)
    if frame.empty: return frame,{}
    frame=frame.drop_duplicates(['fixture','element'])
    frame['xg']=pd.to_numeric(frame.xg,errors='coerce')
    records=[]
    for (fixture,team,opponent),group in frame.groupby(['fixture','team','opponent']):
        active=group[group.minutes>0]
        # Only use complete team exposure; unknown/missing xG is not zero.
        if active.minutes.sum()<900 or active.xg.isna().any(): continue
        records.append({'team':opponent,'xga':active.xg.sum(),'fixture':fixture})
    xga={}
    if records:
        for team,g in pd.DataFrame(records).groupby('team'):
            xga[team]={'total':float(g.xga.sum()),'matches':len(g),'per_match':float(g.xga.mean())}
    return frame,xga

def historical(season):
    folder=ROOT/'history'; folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{season}.csv'
    if path.exists(): return pd.read_csv(path)
    base=f'https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{season}/'
    r=requests.get(base+'gws/merged_gw.csv',timeout=60); r.raise_for_status()
    df=pd.read_csv(StringIO(r.text))
    r=requests.get(base+'teams.csv',timeout=30); r.raise_for_status()
    teams=pd.read_csv(StringIO(r.text)).set_index('id')['name'].to_dict()
    df['opponent']=df.opponent_team.map(teams).map(club)
    df['team']=df.team.map(club)
    df=df[['fixture','element','team','opponent','position','minutes','goals_scored','kickoff_time']].drop_duplicates(['fixture','element'])
    df.to_csv(path,index=False)
    return df

def position_signal(history,team,opponent,position,cutoff):
    if history.empty or position=='GK': return {'multiplier':1.,'meetings':0,'goals':0,'rate':0.,'baseline':0.}
    dates=pd.to_datetime(history.kickoff_time,utc=True,errors='coerce')
    cutoff=pd.Timestamp(cutoff)
    if cutoff.tzinfo is None: cutoff=cutoff.tz_localize('UTC')
    valid=(dates<cutoff)&(dates>=cutoff-pd.Timedelta(days=1461))&(history.minutes>0)&(history.position==position)
    all_rows=history[valid].copy()
    all_rows['weight']=.5**((cutoff-dates[valid]).dt.total_seconds()/(86400*730))
    # Compare to this club's positional scoring rate against all opponents.
    own=all_rows[all_rows.team==team]
    pair=own[own.opponent==opponent]
    exposure=float((pair.minutes*pair.weight).sum()/90)
    base_exposure=float((own.minutes*own.weight).sum()/90)
    baseline=float((own.goals_scored*own.weight).sum()/base_exposure) if base_exposure else 0.
    goals=float((pair.goals_scored*pair.weight).sum())
    rate=(goals+8*baseline)/(exposure+8)
    meetings=len(pair[['season','fixture']].drop_duplicates()) if not pair.empty else 0
    # Need repeated evidence. +/-5% maximum influence on total fantasy points.
    adjustment=max(-.05,min(.05,.1*(rate/max(baseline,.1)-1))) if meetings>=3 else 0.
    return {'multiplier':1+adjustment,'meetings':meetings,'goals':int(pair.goals_scored.sum()),'rate':rate,'baseline':baseline}

def update(bootstrap,fixtures):
    ROOT.mkdir(exist_ok=True)
    dates=[e['deadline_time'] for e in bootstrap['events']]
    start=pd.Timestamp(min(dates)).year
    current,xga=build_current(bootstrap,fixtures)
    frames=[]; coverage=[]; failures=[]
    for year in range(start-4,start):
        season=f'{year}-{str(year+1)[2:]}'
        try:
            df=historical(season); df['season']=season; frames.append(df); coverage.append(season)
        except (requests.RequestException,ValueError,KeyError) as exc:
            failures.append(f'{season}: {exc}')
    if not current.empty:
        current['season']=f'{start}-{str(start+1)[2:]}'; frames.append(current)
    history=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
    stamp=pd.Timestamp.now(tz='UTC').isoformat()
    filename=f'matchup-history-{pd.Timestamp.now().value}.csv'
    history.to_csv(ROOT/filename,index=False)
    result={'season_start':start,'updated':stamp,'history_file':filename,'xga':xga,'coverage':coverage,'failures':failures}
    temporary=ROOT/'matchups.tmp'; temporary.write_text(json.dumps(result),encoding='utf-8'); temporary.replace(ROOT/'matchups.json')
    return result,history

def load():
    try:
        meta=json.loads((ROOT/'matchups.json').read_text(encoding='utf-8'))
        return meta,pd.read_csv(ROOT/meta['history_file'])
    except (OSError,ValueError,KeyError): return {},pd.DataFrame()
