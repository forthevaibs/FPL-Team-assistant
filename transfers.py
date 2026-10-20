"""Compare hold versus immediate transfers, using actual selling prices."""
import math
import pandas as pd
from optimizer import optimize

def score(squad):
    return float(squad.loc[squad.Starting,'Projected points'].sum()+squad.loc[squad.Captain,'Projected points'].sum())

def recommend(players, selling, bank, free_transfers, max_transfers, keep=()):
    owned=set(selling)
    if len(owned)!=15 or not owned.issubset(set(players.ID)):
        raise ValueError('Select exactly 15 different players from the current player list.')
    original=players[players.ID.isin(owned)]
    if original.Position.value_counts().to_dict()!={'GK':2,'DEF':5,'MID':5,'FWD':3}:
        raise ValueError('Your squad must contain 2 GK, 5 DEF, 5 MID and 3 FWD.')
    if original.groupby('Team ID').size().max()>3:
        raise ValueError('This version requires at most three owned players per club. Squads affected by a real-world club transfer need manual correction first.')
    if not math.isfinite(bank) or bank<0 or any(not math.isfinite(v) or v<=0 for v in selling.values()):
        raise ValueError('Enter valid selling prices and a nonnegative bank balance.')
    if not 0<=free_transfers<=5 or not 0<=max_transfers<=5:
        raise ValueError('Free transfers and maximum changes must be between 0 and 5.')
    if not set(keep).issubset(owned): raise ValueError('Only owned players can be marked keep.')
    market=players.set_index('ID').Price
    if any(round(v*10)>round(float(market.loc[i])*10) for i,v in selling.items()):
        raise ValueError('A selling price cannot exceed the current purchase price.')
    effective=players.copy()
    # Retaining an injured player is legal; unavailable new purchases stay excluded.
    effective.loc[effective.ID.isin(owned),'Eligible']=True
    effective['Price']=[selling.get(int(r.ID),r.Price) for r in effective.itertuples()]
    funds=(round(bank*10)+sum(round(v*10) for v in selling.values()))/10
    options=[]; skipped=[]
    for count in range(max_transfers+1):
        try:
            squad,status=optimize(effective,funds,locks=keep if count else owned,owned=owned,transfer_count=count,bench_weight=0)
        except ValueError as exc:
            if count==0: raise
            skipped.append(f'{count} transfers: {exc}'); continue
        bought=set(squad.ID)-owned; sold=owned-set(squad.ID)
        spend=sum(round(float(market.loc[i])*10) for i in bought)
        income=sum(round(selling[i]*10) for i in sold)
        remaining=(round(bank*10)+income-spend)/10
        hit=4*max(0,count-free_transfers)
        squad['Price']=squad.ID.map(market)
        options.append({'Transfers':count,'Gross points':score(squad),'Hit':hit,'Net points':score(squad)-hit,'Bank left':remaining,'squad':squad,'bought':bought,'sold':sold,'status':status})
    baseline=options[0]['Net points']
    for option in options: option['Gain vs hold']=option['Net points']-baseline
    # Fewer moves win ties; never recommend a negative-gain transfer over holding.
    best=max(options,key=lambda o:(round(o['Net points'],6),-o['Transfers']))
    return best,options,skipped
