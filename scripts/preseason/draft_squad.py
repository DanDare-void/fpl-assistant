"""Early-season FPL squad draft optimizer (2026/27 preseason).

Projection: last season (25/26) points prorated by minutes reliability,
adjusted for GW1-6 fixture difficulty. Players without PL history last
season (promoted clubs, new signings from abroad) get a price-based prior.
Optimizes a 15-man squad: budget 100.0, 2/5/5/3, max 3 per club,
maximizing projected XI points + captain double + 0.15 * bench.

Data files (bootstrap/fixtures/history JSON) are fetched into this
directory on first run; delete them to refresh prices and flags.

Requires: pip install pulp
"""
import concurrent.futures
import json
import os
import urllib.request

import pulp

SP = os.path.dirname(os.path.abspath(__file__))
API = 'https://fantasy.premierleague.com/api'


def _load(name: str, fetch):
    path = f'{SP}/{name}.json'
    if not os.path.exists(path):
        print(f'fetching {name}...')
        json.dump(fetch(), open(path, 'w'))
    return json.load(open(path))


def _get(url: str):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def _fetch_history(bootstrap) -> dict:
    """Last-season (history_past) totals for a candidate pool of players."""
    pool = [
        e['id'] for e in bootstrap['elements']
        if e['status'] in ('a', 'd') and not e.get('removed')
        and (float(e['selected_by_percent']) >= 2.0 or e['now_cost'] >= 60)
    ]

    def one(pid):
        try:
            hp = _get(f'{API}/element-summary/{pid}/').get('history_past')
        except Exception:
            return pid, None
        return pid, hp[-1] if hp else None

    hist = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for pid, hp in ex.map(one, pool):
            if hp:
                hist[pid] = {
                    'season': hp['season_name'], 'pts': hp['total_points'],
                    'mins': hp['minutes'], 'gs': hp['goals_scored'],
                    'a': hp['assists'], 'cs': hp['clean_sheets'],
                    'xgi': hp.get('expected_goal_involvements'),
                    'defcon': hp.get('defensive_contribution'),
                    'start_cost': hp['start_cost'], 'end_cost': hp['end_cost'],
                    'bonus': hp['bonus'],
                }
    return hist


d = _load('bootstrap', lambda: _get(f'{API}/bootstrap-static/'))
fx = _load('fixtures', lambda: _get(f'{API}/fixtures/'))
hist = _load('history', lambda: _fetch_history(d))

teams = {t['id']: t['short_name'] for t in d['teams']}
pos = {et['id']: et['singular_name_short'] for et in d['element_types']}

# team avg FDR over GW1-6 -> fixture multiplier
fdr = {tid: [] for tid in teams}
for f in fx:
    if f['event'] and 1 <= f['event'] <= 6:
        fdr[f['team_h']].append(f['team_h_difficulty'])
        fdr[f['team_a']].append(f['team_a_difficulty'])
fmult = {tid: 1 + (3.0 - (sum(v)/len(v) if v else 3.0)) * 0.06 for tid, v in fdr.items()}

PROMOTED = {'COV', 'HUL', 'IPS'}  # no 25/26 PL data

players = []
for e in d['elements']:
    if e['status'] not in ('a', 'd') or e.get('removed'):
        continue
    price = e['now_cost'] / 10
    sel = float(e['selected_by_percent'])
    h = hist.get(str(e['id']))
    p = pos[e['element_type']]
    tm = teams[e['team']]
    if h and h['season'] == '2025/26' and h['mins'] >= 400:
        # shrink pts/90 toward a positional prior; low-minute players regress hard
        PRIOR90 = {'GKP': 3.4, 'DEF': 3.2, 'MID': 3.3, 'FWD': 3.5}[p]
        PRIOR_MINS = 1200
        pts90 = (h['pts'] + PRIOR90 / 90 * PRIOR_MINS) / (h['mins'] + PRIOR_MINS) * 90
        mins_share = min(h['mins'] / 3420, 1.0)
        exp_share = 0.20 + 0.70 * mins_share
        base = pts90 * 38 * exp_share
    elif sel >= 2.0 or price >= 6.0:
        # no meaningful PL history: price-based prior (FPL prices roughly track expectation)
        base = {'GKP': 17*price, 'DEF': 19*price, 'MID': 15*price, 'FWD': 14*price}.get(p, 14*price)
        base = min(base, 150)
    else:
        continue
    if e['status'] == 'd':
        base *= 0.85  # doubtful flag
    proj = base * fmult[e['team']]
    players.append({
        'id': e['id'], 'name': e['web_name'], 'pos': p, 'team': tm, 'tid': e['team'],
        'price': price, 'sel': sel, 'proj': round(proj, 1),
        'lastpts': h['pts'] if h else None, 'mins': h['mins'] if h else None,
        'status': e['status'],
    })

def optimize(exclude=(), include=(), label=''):
    prob = pulp.LpProblem('fpl', pulp.LpMaximize)
    sq = {p['id']: pulp.LpVariable(f"s{p['id']}", cat='Binary') for p in players}
    st = {p['id']: pulp.LpVariable(f"x{p['id']}", cat='Binary') for p in players}
    cp = {p['id']: pulp.LpVariable(f"c{p['id']}", cat='Binary') for p in players}
    def by(f):
        return [p for p in players if f(p)]
    # captain doubles: objective = XI + captain again + 0.15*bench
    prob += pulp.lpSum(st[p['id']] * p['proj'] + cp[p['id']] * p['proj']
                       + (sq[p['id']] - st[p['id']]) * 0.15 * p['proj'] for p in players)
    prob += pulp.lpSum(cp.values()) == 1
    for p in players:
        prob += cp[p['id']] <= st[p['id']]
    prob += pulp.lpSum(sq[p['id']] * p['price'] for p in players) <= 100.0
    for pn, n in [('GKP', 2), ('DEF', 5), ('MID', 5), ('FWD', 3)]:
        prob += pulp.lpSum(sq[p['id']] for p in by(lambda q, pn=pn: q['pos'] == pn)) == n
    for tid in teams:
        prob += pulp.lpSum(sq[p['id']] for p in by(lambda q, tid=tid: q['tid'] == tid)) <= 3
    prob += pulp.lpSum(st.values()) == 11
    for p in players:
        prob += st[p['id']] <= sq[p['id']]
    prob += pulp.lpSum(st[p['id']] for p in by(lambda q: q['pos'] == 'GKP')) == 1
    prob += pulp.lpSum(st[p['id']] for p in by(lambda q: q['pos'] == 'DEF')) >= 3
    prob += pulp.lpSum(st[p['id']] for p in by(lambda q: q['pos'] == 'MID')) >= 2
    prob += pulp.lpSum(st[p['id']] for p in by(lambda q: q['pos'] == 'FWD')) >= 1
    for name in exclude:
        for p in players:
            if p['name'] == name:
                prob += sq[p['id']] == 0
    for name in include:
        for p in players:
            if p['name'] == name:
                prob += sq[p['id']] == 1
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    squad = [p for p in players if sq[p['id']].value() == 1]
    starters = {p['id'] for p in players if st[p['id']].value() == 1}
    captain = next((p['name'] for p in players if cp[p['id']].value() == 1), '?')
    order = {'GKP': 0, 'DEF': 1, 'MID': 2, 'FWD': 3}
    squad.sort(key=lambda p: (p['id'] not in starters, order[p['pos']], -p['proj']))
    cost = sum(p['price'] for p in squad)
    xi = sum(p['proj'] for p in squad if p['id'] in starters)
    print(f"\n=== {label} — cost £{cost:.1f}m, projected XI pts {xi:.0f}, captain: {captain} ===")
    for p in squad:
        role = 'XI ' if p['id'] in starters else 'bch'
        flag = ' ⚠' if p['status'] == 'd' else ''
        last = f"{p['lastpts']}pts/{p['mins']}m" if p['lastpts'] else 'no PL hist'
        print(f"  {role} {p['pos']:<4}{p['name']:<20}{p['team']:<5}£{p['price']:<5}proj {p['proj']:<6}sel {p['sel']:<5}% 25/26: {last}{flag}")
    return squad

if __name__ == '__main__':
    optimize(label='Draft A — unconstrained optimal')
    optimize(exclude=['Haaland'], label='Draft B — no Haaland (spread funds)')
    optimize(include=['Haaland', 'Palmer'], label='Draft C — Haaland + Palmer premium double')
