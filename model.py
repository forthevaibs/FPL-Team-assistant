"""Transparent heuristic v0.1. Not a trained or calibrated ML forecast."""
import pandas as pd
import math
from matchups import club, position_signal

POSITIONS = {1:'GK',2:'DEF',3:'MID',4:'FWD'}

def number(value, default=0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default

def team_profiles(teams, fixtures):
    profiles = {}
    for team in teams:
        matches = sorted([f for f in fixtures if f.get('finished') and team['id'] in (f['team_h'],f['team_a']) and f.get('team_h_score') is not None and f.get('team_a_score') is not None], key=lambda f:f.get('kickoff_time') or '')[-5:]
        scored, conceded = [], []
        for f in matches:
            home = f['team_h']==team['id']
            scored.append(f['team_h_score'] if home else f['team_a_score'])
            conceded.append(f['team_a_score'] if home else f['team_h_score'])
        profiles[team['id']] = {'Team':team['name'],'Matches':len(matches),'Goals for / match':sum(scored)/len(matches) if matches else None,'Goals against / match':sum(conceded)/len(matches) if matches else None}
    return profiles

def projections(bootstrap, fixtures, start, horizon, enrichment=None, history=None, fixture_forecasts=None):
    enrichment=enrichment or {}
    history=history if history is not None else pd.DataFrame()
    names={t['id']:club(t['name']) for t in bootstrap['teams']}
    cutoff=pd.Timestamp.now(tz='UTC')
    season_start=pd.Timestamp(min(e['deadline_time'] for e in bootstrap.get('events',[]))).year if bootstrap.get('events') else None
    if enrichment.get('season_start') != season_start:
        enrichment={}; history=pd.DataFrame()
    signals={}
    teams = {t['id']:t['short_name'] for t in bootstrap['teams']}
    profiles = team_profiles(bootstrap['teams'], fixtures)
    rows = []
    for p in bootstrap['elements']:
        if p['element_type'] not in POSITIONS:
            continue
        mins = number(p.get('minutes'))
        ppg = number(p.get('points_per_game'))
        form = number(p.get('form'))
        # Form and PPG already reflect actual playing time; do not apply minutes twice.
        base = .6*form+.4*ppg
        chance = p.get('chance_of_playing_next_round')
        availability = number(chance,100)/100 if p.get('status') in ('a','d') else 0
        games = [f for f in fixtures if f.get('event') in range(start,start+horizon) and p['team'] in (f['team_h'],f['team_a']) and not f.get('finished')]
        labels, estimates, factors, explanations = [], [], [], []
        linked_count = 0
        for f in games:
            home = f['team_h']==p['team']
            opponent = f['team_a'] if home else f['team_h']
            forecast = (fixture_forecasts or {}).get(str(f.get('id')))
            if forecast:
                # Replace ALL existing fixture multipliers, rather than stacking
                # match strength onto FDR, goals, xGA and head-to-head effects.
                gf = forecast['home_goals' if home else 'away_goals']
                cs = forecast['home_clean_sheet' if home else 'away_clean_sheet']
                attack_share = {1:0., 2:.15, 3:.5, 4:.6}[p['element_type']]
                defence_share = {1:.4, 2:.4, 3:.1, 4:0.}[p['element_type']]
                # Explicit conservative heuristic shares of total points. Not a
                # calibrated player model, and not extra clean-sheet points.
                factor = max(.75, min(1.25, 1 + attack_share*(gf/1.35-1)
                    + defence_share*(cs/math.exp(-1.35)-1)))
                explanations.append(f"{teams[opponent]}: linked goals {gf:.2f}, clean sheet {cs:.1%}; replaces FDR/goals/xGA/H2H; adjustment {factor-1:+.1%}")
                linked_count += 1
            else:
                difficulty = f.get('team_h_difficulty' if home else 'team_a_difficulty',3)
                factor = {1:1.18,2:1.09,3:1.,4:.91,5:.82}.get(difficulty,1.)
                # Small, shrunk opponent adjustment. It is descriptive, not causal.
                profile = profiles[opponent]
                stat = profile['Goals for / match'] if p['element_type'] in (1,2) else profile['Goals against / match']
                if stat is not None:
                    delta = (1.4-stat) if p['element_type'] in (1,2) else (stat-1.4)
                    factor *= 1+max(-.08,min(.08,delta*.05))*profile['Matches']/5
                defensive=p['element_type'] in (1,2)
                xga=enrichment.get('xga',{}).get(names[p['team'] if defensive else opponent])
                xfactor=1.
                if xga and xga['matches']:
                    league=list(enrichment['xga'].values())
                    average=sum(v['total'] for v in league)/sum(v['matches'] for v in league)
                    delta=(xga['per_match']/max(average,.1)-1)*(-1 if defensive else 1)
                    xfactor=1+max(-.10,min(.10,.15*delta))*xga['matches']/(xga['matches']+5)
                    factor*=xfactor
                key=(names[p['team']],names[opponent],POSITIONS[p['element_type']])
                if key not in signals:
                    signals[key]=position_signal(history,*key,cutoff)
                signal=signals[key]
                factor*=signal['multiplier']
                explanations.append(f"{teams[opponent]}: {'own' if defensive else 'opponent'} xGA {xga['per_match']:.2f}/match ({xga['matches']} matches), adjustment {xfactor-1:+.1%}" if xga else f'{teams[opponent]}: xGA unavailable; neutral adjustment')
                explanations.append(f"{POSITIONS[p['element_type']]} H2H: {signal['goals']} goals in {signal['meetings']} meetings; adjustment {signal['multiplier']-1:+.1%}")
            estimate = max(0,base*factor*availability)
            estimates.append(estimate)
            factors.append(factor)
            labels.append(f"GW{f['event']} {teams[opponent]} ({'H' if home else 'A'})")
        cost = number(p['now_cost'])/10
        rows.append({'ID':p['id'],'Player':p['web_name'],'Club':teams[p['team']],'Team ID':p['team'],'Position':POSITIONS[p['element_type']],'Price':cost,'Projected points':sum(estimates),'Value':sum(estimates)/cost if cost else 0,'Form':form,'Points / game':ppg,'Minutes':int(mins),'xG / 90':number(p.get('expected_goals_per_90')),'xA / 90':number(p.get('expected_assists_per_90')),'Influence / 90':number(p.get('influence'))*90/mins if mins else 0,'Creativity / 90':number(p.get('creativity'))*90/mins if mins else 0,'Threat / 90':number(p.get('threat'))*90/mins if mins else 0,'Availability':availability,'Eligible':p.get('can_select',True) and not p.get('removed',False) and availability>0,'Fixtures':'; '.join(labels) or 'No scheduled fixtures','News':p.get('news',''),'Base points':base,'Fixture multiplier':sum(factors)/len(factors) if factors else 0,'Evidence':'Limited minutes' if mins<270 else 'Established sample'})
        rows[-1]['Matchup evidence']=' | '.join(explanations) or 'No fixture'
        rows[-1]['Linked fixtures'] = linked_count
    return pd.DataFrame(rows)
