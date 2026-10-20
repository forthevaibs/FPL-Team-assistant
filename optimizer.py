"""Joint squad, XI and captain binary optimization using SciPy/HiGHS."""
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint

def optimize(players, budget=100, locks=(), excludes=(), owned=None, transfer_count=None, bench_weight=.05):
    if set(locks)&set(excludes):
        raise ValueError('A player cannot be both locked and excluded.')
    frame = players[players.Eligible & ~players.ID.isin(excludes)].reset_index(drop=True)
    if not set(locks).issubset(set(frame.ID)):
        raise ValueError('A locked player is unavailable or excluded. Remove that lock.')
    n = len(frame)
    if n<15:
        raise ValueError('Not enough eligible players to form a squad.')
    # Three binary blocks: squad membership, starting XI, captain.
    rows, lower, upper = [], [], []
    def constraint(indices, values, lo, hi):
        row = np.zeros(3*n)
        row[list(indices)] = values
        rows.append(row); lower.append(lo); upper.append(hi)
    constraint(range(n),1,15,15)
    constraint(range(n,2*n),1,11,11)
    constraint(range(2*n,3*n),1,1,1)
    constraint(range(n),np.rint(frame.Price.to_numpy()*10),0,round(budget*10))
    if owned is not None and transfer_count is not None:
        constraint(frame.index[~frame.ID.isin(owned)],1,transfer_count,transfer_count)
    for position, count, minimum, maximum in [('GK',2,1,1),('DEF',5,3,5),('MID',5,2,5),('FWD',3,1,3)]:
        ids = frame.index[frame.Position==position].to_numpy()
        constraint(ids,1,count,count)
        constraint(ids+n,1,minimum,maximum)
    for team in frame['Team ID'].unique():
        constraint(frame.index[frame['Team ID']==team],1,0,3)
    for i in range(n):
        constraint([i,i+n],[-1,1],-np.inf,0)
        constraint([i+n,i+2*n],[-1,1],-np.inf,0)
        if frame.iloc[i].ID in locks:
            constraint([i],1,1,1)
    pts = frame['Projected points'].to_numpy()
    # Small bench utility is explicit, not counted as expected scoring points.
    objective = -np.concatenate([bench_weight*pts,(1-bench_weight)*pts,pts])
    result = milp(objective,integrality=np.ones(3*n),bounds=Bounds(0,1),constraints=LinearConstraint(np.array(rows),lower,upper),options={'time_limit':20,'mip_rel_gap':.001})
    if result.x is None:
        raise ValueError('No valid squad found within the budget and player constraints. Increase budget or remove locks.')
    x = np.rint(result.x)
    if np.any(np.array(rows)@x < np.array(lower)-1e-6) or np.any(np.array(rows)@x > np.array(upper)+1e-6):
        raise ValueError('Solver returned an invalid squad; no recommendation displayed.')
    squad = frame[x[:n]>.5].copy()
    squad['Starting'] = x[n:2*n][x[:n]>.5].astype(bool)
    squad['Captain'] = x[2*n:][x[:n]>.5].astype(bool)
    squad['Role'] = np.where(squad.Captain,'Captain',np.where(squad.Starting,'Starting XI','Bench'))
    return squad, result.message
