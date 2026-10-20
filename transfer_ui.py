import streamlit as st
import pandas as pd
from transfers import recommend

def render(frame, context):
    st.subheader('Improve my existing team')
    st.write('Enter your squad, then compare keeping it with up to five immediate transfers. Recommendations maximize projected starting-XI and captain points after transfer hits.')
    st.caption('Normal transfers only: no Wildcard or Free Hit. Across multiple gameweeks this compares one set of transfers now and a fixed XI, not a sequence of future moves. Unused free transfers have no future value in this calculation.')
    labels={int(r.ID):f'{r.Player} · {r.Club} · £{r.Price:.1f}m' for r in frame.itertuples()}
    owned=[]
    columns=st.columns(4)
    for col,pos,count in zip(columns,['GK','DEF','MID','FWD'],[2,5,5,3]):
        owned+=col.multiselect(f'{pos}: choose {count}',frame.loc[frame.Position==pos,'ID'].tolist(),format_func=labels.get,max_selections=count,key='owned_'+pos)
    st.caption(f'{len(owned)}/15 players entered. Entries remain while this browser session is active.')
    if len(owned)!=15:
        st.info('Complete all four positions to enter selling prices and analyze changes.'); return
    selected=frame[frame.ID.isin(owned)]
    pricing=selected[['ID','Player','Club','Price']].copy().rename(columns={'Price':'Selling price'})
    st.write('**Actual selling prices (£m)**')
    st.caption('Defaults below are current market prices. Replace them with the selling prices shown in your FPL Transfers screen; these may be lower.')
    edited=st.data_editor(pricing,hide_index=True,disabled=['ID','Player','Club'],column_config={'Selling price':st.column_config.NumberColumn(min_value=.1,step=.1,format='%.1f')},key='selling_'+','.join(map(str,sorted(owned))),use_container_width=True)
    a,b,c=st.columns(3)
    bank=a.number_input('Money in bank (£m)',min_value=0.,max_value=100.,value=0.,step=.1)
    free=b.number_input('Free transfers remaining',min_value=0,max_value=5,value=1,step=1)
    maximum=c.slider('Maximum changes to consider',0,5,2)
    keep=st.multiselect('Keep these players',owned,format_func=labels.get)
    confirmed=st.checkbox('I have checked the selling prices against my FPL team')
    selling={int(r['ID']):float(r['Selling price']) if pd.notna(r['Selling price']) else float('nan') for _,r in edited.iterrows()}
    signature=(tuple(sorted(selling.items())),bank,free,maximum,tuple(sorted(keep)),context)
    if st.button('Suggest improvements',type='primary',disabled=not confirmed):
        st.session_state.pop('transfer_result',None)
        try:
            with st.spinner('Comparing hold and transfer options. This may take up to two minutes…'):
                best,options,skipped=recommend(frame,selling,bank,int(free),maximum,keep)
            st.session_state.transfer_result=(signature,best,options,skipped)
        except ValueError as exc: st.error(str(exc))
    stored=st.session_state.get('transfer_result')
    if not stored: return
    if stored[0]!=signature or not confirmed:
        st.info('Inputs changed. Run Suggest improvements again.'); return
    _,best,options,skipped=stored
    if best['Transfers']==0:
        st.success('Keep your squad. None of the evaluated transfers improves projected net points.')
    else:
        st.success(f"Recommend {best['Transfers']} transfer(s): +{best['Gain vs hold']:.2f} projected points after a {best['Hit']}-point hit.")
    a,b,c=st.columns(3)
    a.metric('Hold: best XI + captain',f"{options[0]['Net points']:.2f}")
    b.metric('Recommended net points',f"{best['Net points']:.2f}")
    c.metric('Bank after transfers',f"£{best['Bank left']:.1f}m")
    out_col,in_col=st.columns(2)
    out_col.write('**Sell**')
    out_col.dataframe(edited[edited.ID.isin(best['sold'])],hide_index=True,use_container_width=True)
    in_col.write('**Buy**')
    in_col.dataframe(frame[frame.ID.isin(best['bought'])][['Player','Club','Position','Price','Projected points']],hide_index=True,use_container_width=True)
    st.caption('Outgoing and incoming players are a combined plan, not necessarily paired one-for-one in display order. Gain includes lineup and captain changes.')
    st.write('**Recommended squad and lineup**')
    st.dataframe(best['squad'][['Player','Club','Position','Role','Price','Projected points','Fixtures']].sort_values('Role'),hide_index=True,use_container_width=True)
    st.download_button('Download improved squad',best['squad'].to_csv(index=False),'improved_squad.csv','text/csv')
    st.write('**Transfer-count comparison**')
    st.dataframe(pd.DataFrame([{k:o[k] for k in ['Transfers','Gross points','Hit','Net points','Gain vs hold','Bank left']} for o in options]).round(2),hide_index=True,use_container_width=True)
    with st.expander('Evidence and solver status'):
        st.dataframe(frame[frame.ID.isin(best['bought'])][['Player','Matchup evidence']],hide_index=True,use_container_width=True)
        for o in options: st.write(f"{o['Transfers']} transfers: {o['status']}")
        for warning in skipped: st.warning(warning)
        st.caption('A time-limited feasible solve may not be the global optimum. Forecast gains are estimates, not guaranteed returns. No bench auto-substitutions or vice-captain fallback are simulated.')
