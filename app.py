import streamlit as st
import pandas as pd
from data import fetch
from model import projections, team_profiles
from optimizer import optimize
from transfer_ui import render as render_transfers
from matchups import load as load_matchups, update as update_matchups
from fixture_bridge import forecasts, refresh_results
from comparison import record, score_finished, summaries, season_key

st.set_page_config(page_title='FPL Advisor',page_icon='⚽',layout='wide')
st.markdown('''<style>.stApp {background:#0b1220} [data-testid="stMetric"] {background:#142238;padding:18px;border-radius:12px} h1 {letter-spacing:-1px} .block-container {padding-top:2rem} </style>''',unsafe_allow_html=True)
st.title('⚽ FPL Advisor')
st.caption('Player research • Fixture intelligence • Squad planning')

with st.sidebar:
    st.header('Your planning desk')
    refresh = st.button('Refresh public data',use_container_width=True)
try:
    bootstrap, stamp, stale = fetch('bootstrap-static/',refresh)
    fixtures, fixture_stamp, fixture_stale = fetch('fixtures/',refresh)
except Exception as exc:
    st.error(f'Could not load FPL data: {exc}')
    st.info('Check your internet connection and retry. Once loaded, a local snapshot will be available during outages.')
    st.stop()
if stale or fixture_stale:
    st.warning('Source unavailable: displaying a saved snapshot. Check the timestamps before using recommendations.')
st.caption(f'Players fetched: {stamp} · Fixtures fetched: {fixture_stamp}')
events = [e for e in bootstrap['events'] if not e.get('finished') and not e.get('is_current')]
if not events:
    st.info('No upcoming gameweeks in this data snapshot. Refresh when the next season is available.')
    st.stop()
with st.sidebar:
    gw = st.selectbox('Starting gameweek',[e['id'] for e in events])
    horizon = st.slider('Gameweeks to inspect',1,6,1)
    st.caption('Multiweek points use current form and availability held constant. The builder selects a fixed XI across this horizon.')
    st.warning('Research baseline · Not yet backtested')
    st.caption('No account, password or API key needed for this version.')
enrichment,history_data=load_matchups()
with st.sidebar:
    advanced=st.checkbox('Use xGA and positional matchups',value=True)
    if st.button('Update matchup data'):
        try:
            with st.spinner('Loading player histories and four prior seasons. First load can take several minutes…'):
                enrichment,history_data=update_matchups(bootstrap,fixtures)
        except Exception as exc:
            st.error(f'Matchup update failed: {exc}')
    if enrichment:
        st.caption(f"Matchup snapshot: {enrichment['updated']}")
        if (pd.Timestamp.now(tz='UTC')-pd.Timestamp(enrichment['updated'])).total_seconds()>86400:
            st.warning('Matchup data is over 24 hours old. Update it for recent results.')
        st.caption('Historical coverage: '+', '.join(enrichment['coverage']))
        for failure in enrichment['failures']:
            st.warning('Missing historical season: '+failure)
    elif advanced:
        st.info('Click Update matchup data to enable these adjustments. Missing data has no effect on predictions.')
with st.sidebar:
    use_linked=st.checkbox('Use linked match predictor',value=True)
    if st.button('Refresh match results'):
        try:
            with st.spinner('Refreshing current-season match results…'):
                refresh_results(season_key(bootstrap))
        except Exception as exc:
            st.error(f'Match results refresh failed: {exc}')
forecast_meta={}
try:
    with st.spinner('Preparing shared fixture forecasts…'):
        forecast_meta=forecasts(bootstrap,fixtures,gw,horizon)
except Exception as exc:
    st.warning(f'Match link unavailable; using baseline: {exc}')
fixture_predictions=forecast_meta.get('fixtures',{}) if forecast_meta.get('usable') else {}
if forecast_meta:
    st.caption(f"Match model: {forecast_meta['model']} · Weights trained through {forecast_meta['trained_through']} · Results through {forecast_meta['data_through']} · {len(fixture_predictions)} linked fixtures · {'Cached batch' if forecast_meta['cache_hit'] else 'New batch'}")
    if forecast_meta.get('warning'): st.warning(forecast_meta['warning'])
    if forecast_meta.get('errors'):
        st.warning('Some fixtures use baseline adjustments: '+'; '.join(forecast_meta['errors'].values()))
matchup_key=(advanced,enrichment.get('updated'),use_linked,forecast_meta.get('cache_key'))
if st.session_state.get('matchup_key')!=matchup_key:
    st.session_state.pop('squad_result',None)
    st.session_state['matchup_key']=matchup_key
cached_projections=st.cache_data(ttl=300,show_spinner=False)(projections)
baseline = cached_projections(bootstrap,fixtures,gw,horizon,enrichment if advanced else None,history_data if advanced else None)
linked = cached_projections(bootstrap,fixtures,gw,horizon,enrichment if advanced else None,history_data if advanced else None,fixture_predictions)
frame = linked if use_linked else baseline
cols = st.columns(4)
cols[0].metric('Players',len(frame))
cols[1].metric('Clubs',len(bootstrap['teams']))
cols[2].metric('Planning window',f'GW {gw}–{gw+horizon-1}')
cols[3].metric('Projection method','Linked v0.3' if use_linked and fixture_predictions else 'Baseline v0.2')
builder,my_team,explorer,fixture_tab,influence,comparison_tab,methods = st.tabs(['Squad builder','Improve my team','Player explorer','Fixtures & opponents','Influence','Compare methods','Method & roadmap'])
display = ['Player','Club','Position','Price','Projected points','Value','Minutes','Fixtures']
labels = {int(r.ID):f'{r.Player} · {r.Club} · £{r.Price:.1f}m' for r in frame.itertuples()}

with my_team:
    render_transfers(frame,(gw,horizon,stamp,fixture_stamp,matchup_key))

with builder:
    st.subheader('Build an affordable squad')
    st.write('Choose your budget and must-have players. We select all 15 players, a legal starting XI and a captain together.')
    a,b,c = st.columns([1,2,2])
    budget = a.number_input('Budget (£m)',min_value=60.,max_value=150.,value=100.,step=.1)
    locks = b.multiselect('Lock into squad',frame.ID.tolist(),format_func=labels.get)
    excludes = c.multiselect('Exclude players',frame.ID.tolist(),format_func=labels.get)
    st.caption('Fresh squad mode: no existing ownership, transfers, chips or selling-price calculations. Bench utility is weighted at 5%; bench points are not included in the headline projection.')
    if st.button('Generate squad',type='primary'):
        try:
            with st.spinner('Solving budget, formation and club constraints…'):
                squad, message = optimize(frame,budget,locks,excludes)
            st.session_state['squad_result']=(gw,horizon,budget,tuple(locks),tuple(excludes),stamp,fixture_stamp,squad,message)
        except ValueError as exc:
            st.error(str(exc))
    stored = st.session_state.get('squad_result')
    if stored and stored[:7]==(gw,horizon,budget,tuple(locks),tuple(excludes),stamp,fixture_stamp):
        squad,message = stored[7:]
        xi = squad[squad.Starting]
        score = xi['Projected points'].sum()+squad.loc[squad.Captain,'Projected points'].sum()
        a,b,c = st.columns(3)
        a.metric('Squad price',f'£{squad.Price.sum():.1f}m')
        b.metric('XI + captain projection',f'{score:.1f} pts')
        c.metric('Money remaining',f'£{budget-squad.Price.sum():.1f}m')
        for pos in ['GK','DEF','MID','FWD']:
            players = xi[xi.Position==pos]
            columns=st.columns(len(players))
            for column,(_,player) in zip(columns,players.iterrows()):
                column.success(f"**{player.Player}{' ©' if player.Captain else ''}**\n\n{player.Club} · {pos}\n\n£{player.Price:.1f}m · {player['Projected points']:.1f} pts")
        st.markdown('**Bench**')
        st.dataframe(squad[~squad.Starting][display],hide_index=True,use_container_width=True)
        st.caption('Bench order and vice-captain are not modelled yet. Captain projection assumes the selected captain plays; automatic substitutions and captain fallback are not simulated.')
        st.download_button('Download squad CSV',squad[display+['Role']].to_csv(index=False),'fpl_squad.csv','text/csv')
        with st.expander('Solver details'):
            st.write(message)
            st.write('Best feasible result within the solver time limit; optimality is only established when the solver reports success.')
    elif stored:
        st.info('Settings or data changed. Generate a new squad to see matching recommendations.')

with explorer:
    st.subheader('Find your next pick')
    a,b,c = st.columns(3)
    search = a.text_input('Search player')
    positions = b.multiselect('Positions',['GK','DEF','MID','FWD'],default=['GK','DEF','MID','FWD'])
    max_price = c.slider('Maximum price (£m)',3.,20.,15.,.5)
    filtered = frame[frame.Player.str.contains(search,case=False,regex=False)&frame.Position.isin(positions)&(frame.Price<=max_price)]
    st.dataframe(filtered[display+['xG / 90','xA / 90','Evidence']].sort_values('Projected points',ascending=False).round(2),hide_index=True,use_container_width=True)
    selected = st.multiselect('Compare up to four players',frame.ID.tolist(),format_func=labels.get,max_selections=4)
    if selected:
        st.dataframe(frame[frame.ID.isin(selected)][display+['Form','Points / game','xG / 90','xA / 90','Availability','News']].set_index('Player').T,use_container_width=True)
    player_id = st.selectbox('Inspect a player',frame.ID.tolist(),format_func=labels.get)
    player = frame[frame.ID==player_id].iloc[0]
    st.write('**Fixture-by-fixture evidence**')
    st.write(player['Matchup evidence'])
    st.caption('Positional history uses FPL position categories, not tactical number 9 roles. Matches with no goals count too. Older evidence receives less weight; fewer than three meetings gives no adjustment. These are unvalidated associations, not guarantees.')
    st.info(f"Base: 60% recent form + 40% season points/game = {player['Base points']:.2f}. Average fixture multiplier: {player['Fixture multiplier']:.2f}. Availability factor: {player.Availability:.0%}. Total: {player['Projected points']:.2f} points across scheduled fixtures.")
    st.caption('xG and xA are research indicators in this release; they are not yet inputs to the baseline projection. Availability is an FPL flag, not a calibrated start probability.')
    if player.News:
        st.warning(player.News)
    if st.button('Load match history'):
        try:
            history,history_stamp,history_stale = fetch(f'element-summary/{player_id}/')
            st.caption(f'History fetched: {history_stamp}'+(' · Saved snapshot' if history_stale else ''))
            matches = pd.DataFrame(history.get('history',[]))
            if matches.empty:
                st.info('No match history available.')
            else:
                wanted = ['round','kickoff_time','opponent_team','was_home','minutes','total_points','goals_scored','assists','expected_goals','expected_assists']
                st.dataframe(matches[[c for c in wanted if c in matches]],hide_index=True,use_container_width=True)
                st.line_chart(matches.set_index('kickoff_time')[['total_points']])
        except Exception as exc:
            st.error(f'History unavailable: {exc}')

with fixture_tab:
    st.subheader('The next opponents')
    teams = {t['id']:t['short_name'] for t in bootstrap['teams']}
    upcoming = [{'GW':f['event'],'Kickoff':f.get('kickoff_time'),'Home':teams[f['team_h']],'Away':teams[f['team_a']],'Home FDR':f.get('team_h_difficulty'),'Away FDR':f.get('team_a_difficulty')} for f in fixtures if f.get('event') in range(gw,gw+horizon) and not f.get('finished')]
    st.dataframe(pd.DataFrame(upcoming),hide_index=True,use_container_width=True)
    if fixture_predictions:
        st.markdown('**Shared match-model forecasts**')
        st.dataframe(pd.DataFrame([{'Home':v['home'],'Away':v['away'],'Home goals':v['home_goals'],
            'Away goals':v['away_goals'],'Home clean sheet':v['home_clean_sheet'],
            'Away clean sheet':v['away_clean_sheet']} for v in fixture_predictions.values()]).round(3),hide_index=True)
    st.markdown('**Last five completed league matches**')
    if enrichment.get('xga'):
        st.markdown('**Current-season expected goals against**')
        st.dataframe(pd.DataFrame.from_dict(enrichment['xga'],orient='index').rename(columns={'total':'Season xGA','matches':'Covered matches','per_match':'xGA / match'}).round(2),use_container_width=True)
        st.caption('Derived from the opposing players’ fixture xG, not by adding player xGC. Coverage can be incomplete when historical player records are missing. The previous five results remain a separate signal.')
    st.dataframe(pd.DataFrame(team_profiles(bootstrap['teams'],fixtures).values()).round(2),hide_index=True,use_container_width=True)
    st.caption('Recent goals are descriptive and not adjusted for schedule strength. FDR is the source fixture difficulty rating (1 easier, 5 harder). Unscheduled fixtures are excluded until assigned a gameweek.')

with influence:
    st.subheader('Compare contributions within a position')
    st.write('These are FPL statistical indicators, not proof of causal influence or a complete measure of football ability.')
    a,b = st.columns(2)
    position = a.selectbox('Role group',['GK','DEF','MID','FWD'])
    minimum = b.slider('Minimum minutes',0,1800,270,90)
    group = frame[(frame.Position==position)&(frame.Minutes>=minimum)]
    st.dataframe(group[['Player','Club','Minutes','Influence / 90','Creativity / 90','Threat / 90','xG / 90','xA / 90']].sort_values('Influence / 90',ascending=False).round(2),hide_index=True,use_container_width=True)
    st.caption('Progressive passing, carries, pressing and flank-specific matchups need a suitable event-data source. They are not inferred from these scores.')

with comparison_tab:
    st.subheader('Baseline versus linked advisor')
    comparison=baseline[['ID','Player','Club','Position','Projected points']].rename(columns={'Projected points':'Baseline points'})
    comparison=comparison.merge(linked[['ID','Projected points','Linked fixtures']].rename(columns={'Projected points':'Linked points'}),on='ID',validate='one_to_one')
    comparison['Change']=comparison['Linked points']-comparison['Baseline points']
    st.dataframe(comparison.sort_values('Change',ascending=False).round(2),hide_index=True)
    st.caption('Differences are forecasts, not measured improvements. Linked fixtures replace FDR, goals, xGA and positional H2H multipliers; player form and availability remain unchanged.')
    st.write('Record both methods before the deadline, then score against finalized gameweek results. Both use the same player pool and £100m budget, with separate optimized XIs and captains.')
    if st.button('Record both methods before deadline',disabled=horizon!=1 or not fixture_predictions or stale or fixture_stale):
        try:
            with st.spinner('Saving forecasts and optimizing both squads…'):
                provenance={**forecast_meta,'players_fetched':stamp,'fixtures_fetched':fixture_stamp,
                    'source_stale':stale or fixture_stale,'advanced':advanced,'enrichment_updated':enrichment.get('updated')}
                snapshot=record(bootstrap,next(e for e in events if e['id']==gw),baseline,linked,provenance)
            st.success(f"GW{gw} comparison recorded at {snapshot['captured_at']}. Existing records are never overwritten.")
        except Exception as exc:
            st.error(f'Comparison not recorded: {exc}')
    if horizon!=1: st.info('Select a one-gameweek window to record a fair gameweek comparison.')
    if st.button('Score finalized gameweeks'):
        try:
            score_finished(bootstrap)
        except Exception as exc:
            st.error(f'Scoring unavailable: {exc}')
    results=summaries()
    if results.empty:
        st.info('No prospective comparisons recorded yet. Historical improvement cannot be inferred from current form snapshots.')
    else:
        st.dataframe(results.round(3),hide_index=True)
    st.caption('MAE uses covered, eligible players recorded before deadline; established-player MAE requires at least 270 prior minutes. Actual returns are the fixed XI plus captain, without autosubs, vice-captain, chips or transfer hits. Results require the FPL gameweek to be finished and data checked.')

with methods:
    st.subheader('What this version can tell you')
    st.info('Linked mode uses cached Poisson goals and clean-sheet probabilities from the match predictor. Position-specific shares adjust the baseline by at most ±25%. These shares are heuristic, not a trained player-points model. Missing/stale fixture forecasts fall back to the original advisor. Use Compare methods to measure prospective results.')
    st.markdown('''This is an operational research baseline, not a trained OpenFPL implementation. Forecasts use current form and season points/game, a modest fixture adjustment and the current availability flag. Opponent adjustments use up to five completed matches. Long-horizon estimates hold current form and availability constant.

**Next research steps:** historical player/fixture ID mapping; deadline-safe rolling features; a separate minutes model; position-specific training; chronological backtesting; defensive-contribution scoring by season; transfer and chip planning.

**You can provide later:** your existing 15 players, selling prices, bank balance and free transfers for personalized transfer planning. A licensed event-data source is optional for advanced tactical analysis. Never share your FPL password.

Sources: [FPL](https://fantasy.premierleague.com/) · [OpenFPL](https://github.com/daniegr/OpenFPL) · [Historical data](https://github.com/vaastav/Fantasy-Premier-League).
''')
