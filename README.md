# FPL Advisor

Working first milestone: public FPL data, SQLite snapshots, player comparison and history, fixtures, descriptive opponent form, role-based ICT comparisons, CSV export, and joint squad/XI/captain optimization.

## Start on Windows

```powershell
cd D:\ecm_simulator\fpl_advisor
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.port 8501
```

Open http://localhost:8501. No credentials or API key required. Reads public FPL endpoints only. Snapshots live in `data/snapshots.sqlite`, refresh after one hour, and are preserved on source failures with a visible warning. The refresh button requests new player and fixture data. History is loaded on demand.

## Forecast contract

This release is NOT a trained ML model, a reproduction of the papers, or a validated claim of best future performance. For each scheduled unfinished match:

`points = (0.6 * form + 0.4 * points_per_game) * fixture_multiplier * availability`

FDR multipliers for ratings 1..5 are 1.18, 1.09, 1.0, 0.91, 0.82. Opponent recent goals provide an additional adjustment capped at 8%, shrunk when fewer than five matches exist. Goalkeepers/defenders use opponent goals scored; midfielders/forwards use goals conceded. There is no learned calibration. xG/xA are displayed but are not yet forecast inputs. Current availability is held constant across the requested horizon. Blank gameweeks give zero; double gameweeks sum both fixtures. No current data is silently substituted for historical pre-deadline information.

The binary solver (SciPy's bundled HiGHS, avoiding a separate solver installation) enforces 15 players, 2/5/5/3 positional counts, club maximum 3, budget in integer tenths, a legal XI and one starting captain. Objective: XI points + extra captain points + 5% bench utility. Headline points exclude bench utility. Solver status is exposed; timeout results are feasible recommendations, not certified optima. A fixed XI is optimized across a multiweek horizon. Automatic substitutions, vice-captain fallback, bench ordering, transfer hits, selling values and chips are not yet simulated.

## What the user needs to add

Nothing to run the initial dashboard beyond internet access and Python dependencies.

For personalized transfers later: current squad, actual selling prices, money in bank, free transfers and chip availability. Do not supply passwords or session cookies.

For tactical extensions: optionally provide access to a licensed event dataset covering the required Premier League seasons, including passes/carries, event locations and defensive actions. No data subscription is required for this milestone.

## Planned next milestones

1. Historical ingestion with source/season/player/fixture identity mapping and dataset coverage checks.
2. Deadline-safe feature construction: lagged rolling 3/5/10-match metrics, per-90 shrinkage, team/opponent xG, start/minutes modelling. Split train/validation/test chronologically, fit transformations on training only.
3. Compare recent-form baseline, Random Forest and XGBoost by position; report MAE/RMSE, calibration, availability errors and achievable squad returns net of transfers. Backtest current scoring only where historical event coverage supports it.
4. Calibrated forecast ranges, availability scenarios, multiweek transfers and event-data influence analysis.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests cover squad legality, locks/exclusions, impossible budgets, and blank/double gameweek aggregation. Live data and UI are also smoke-tested during development.


## v0.2: xGA and positional opponent history

Use the sidebar toggle to compare the enhanced and original baseline, and Update matchup data to refresh enrichment. The snapshot timestamp and any missing seasons are visible. The first refresh downloads all current player histories and four prior seasons; subsequent refreshes reuse cached historical CSVs.

Current-season team xGA is reconstructed by summing opposing player xG within each completed fixture, using fixture and venue to identify clubs even after player transfers. Player xGC is never summed, as this would duplicate chances. A team exposure below 900 recorded player-minutes or missing active-player xG causes that fixture to be excluded. This is a rounded FPL-derived estimate with explicit coverage, not an independent provider team xGA feed. Missing departed-player records can still reduce completeness.

Opponent xGA adjusts MID/FWD projections; own-team xGA adjusts GK/DEF projections relative to the covered league average. The raw adjustment is capped at 10% and shrunk by matches/(matches+5). It supplements, rather than replaces, recent actual goals and FDR.

Positional H2H compares club-versus-opponent goals per 90 player-minutes with the club positional rate against all opponents. It uses a trailing four-year window, two-year recency half-life and eight full player-match equivalents of prior evidence. At least three meetings are required; the final multiplier is capped at +/-5%. Zero-goal matches count. Fixture IDs are scoped by season. FPL positions are not tactical number-9 labels. GK H2H scoring adjustment is disabled. No xG or goals from after the analysis timestamp enter H2H. This is a live forecast feature, not a historical backtest interface.

The player detail screen shows fixture-level xGA, covered matches, positional goals/meetings and percentage adjustments. All weights are heuristic and unvalidated; the existing untrained-model warning remains.

## Existing team transfer planner

Use **Improve my team** to select exactly 2 GK, 5 DEF, 5 MID and 3 FWD. Enter actual selling prices, money in bank, free transfers remaining (0–5), maximum changes (0–5), and optional players to keep. The price editor starts at current market price; confirm your actual selling prices before analysis. Selections persist for the browser session; export the resulting squad as CSV.

Every transfer-count scenario jointly selects a legal squad, XI and captain, with no bench reward. The budget is bank plus proceeds from players actually sold minus current purchase prices of incoming players. Retained players do not incur a purchase cost. Injured owned players may be retained. Hold is always considered; extra transfers cost four points each beyond remaining free transfers. Equal net projections prefer fewer changes. Solver status and infeasible options are shown. Forecasts remain unvalidated estimates; time limits can prevent certified optimality.

This is an immediate-transfer planner, not a future transfer schedule. With a longer horizon it holds the chosen XI fixed and charges transfer hits once. It does not value rolling free transfers, model chips, forecast future prices, or simulate automatic substitutions. Current squads with more than three from a club due to real-world transfers are not supported. Changes to any input or data timestamp invalidate the previous result.

Transfer rules reference: https://www.premierleague.com/en/news/2174907
Live UI test: `python tests/smoke_transfers.py`
# Linked match predictor (v0.3)

The advisor now consumes batch forecasts from the sibling `../match_predictor` project. Enable **Use linked match predictor** in the sidebar. Squad building, transfer suggestions, captain selection and player rankings all use the selected projection method.

## Three integration steps

1. **Shared fixture forecasts.** `fixture_bridge.py` sends upcoming fixtures to `match_predictor/fixture_batch.py` using the match project's Python environment. This avoids module-name and dependency conflicts. The worker loads the trained bundle and replays known results once, then predicts all fixtures in one model batch. Team aliases explicitly cover Man Utd, Spurs, Ipswich Town, Hull City and Coventry City. Cache identity includes fixture IDs/kickoffs, source CSV and model/code modification signatures, and the UTC hour. No future fixture results are simulated. Same-day results are excluded because historical inputs are date-granular.
2. **Replace overlapping adjustments.** For covered fixtures, predicted team goals and clean-sheet probability replace FDR, recent goal averages, xGA and positional H2H multipliers. Player form, season points/game and availability remain unchanged. Uncovered fixtures use the original baseline. Results older than 14 days disable the link; freshness is measured at forecast time, not at a distant fixture date. **Refresh match results** fetches the current season; model weights are not automatically retrained. Both data and training cutoffs are shown.
3. **Prospective evaluation.** **Compare methods** shows forecast differences and records both methods before a one-gameweek deadline. Snapshots include all player forecasts, metadata, and two separately optimized £100m squads with XIs/captains. One immutable snapshot is allowed per season/gameweek. **Score finalized gameweeks** fetches FPL `event/{id}/live/` points only after the event is finished and data checked. Outputs include eligible-player MAE, MAE for players with at least 270 prior minutes, and actual fixed-XI-plus-captain returns. Missing actuals are not filled with zero. Autosubs, vice-captains, chips and transfer hits are excluded from this benchmark.

The current points adjustment is explicitly heuristic: `clip(1 + attack_share*(goals/1.35-1) + defence_share*(clean_sheet/exp(-1.35)-1), .75, 1.25)`. Attack shares for GK/DEF/MID/FWD are 0/.15/.5/.6; defence shares are .4/.4/.1/0. These are conservative fixed settings, not fitted player-point components. Clean-sheet probability is `exp(-opponent_goals)` under the independent Poisson model. Goal/clean-sheet probabilities are not added as extra points on top of the baseline. Playing time is already reflected in form/points per game; availability is applied once.

## Initial integration verification

- Refreshed 2026/27 results: latest included result 12 October 2026; deployed model weights trained through 24 May 2026.
- All 10 GW8 fixtures mapped; 668 players projected.
- Local timing: initial 10-fixture batch 12.25 seconds, cached retrieval 0.005 seconds. This is cache retrieval timing, not total UI/optimization time or proof of faster solver performance.
- First prospective GW8 baseline/linked snapshot saved before deadline. Realized results remain pending; higher projected points do not establish better recommendations.
- Unit tests cover fallback, replacement rather than double counting, venue orientation, blank/double gameweeks, availability, deadlines and immutable snapshots. Live UI squad generation also passed.

Use `python -m unittest discover -s tests -p 'test_*.py' -v` from this folder for advisor tests. Batch leakage tests are in the match predictor project. Comparison records live in `data/comparisons/`; cached fixture forecasts in `data/fixture_forecasts/`. Neither directory is committed.

---
