"""Weekly FPL team status report (2026/27) — companion to haaland_watch.py.

Emails a post-gameweek debrief for the team: score vs average, who returned,
who blanked, injury flags, upcoming-fixture trouble spots, transfer-out
candidates, and the market's top movers. It is the standing input to the
Friday pre-deadline session, where the actual transfers get decided against
opposition and team news.

Everything is computed from public FPL API data — no judgment calls are baked
in beyond the thresholds below. Stdlib only. Email creds come from the
environment (k8s Secret `haaland-smtp` in-cluster) with a fallback to
~/the-tissue/.env, exactly like haaland_watch.py.

Usage: python3 gw_status_report.py [--print]   (--print skips the email)
"""
import json
import os
import smtplib
import sys
import traceback
import urllib.request
from email.message import EmailMessage
from pathlib import Path

API = 'https://fantasy.premierleague.com/api'
ENV_PATH = Path.home() / 'the-tissue' / '.env'
TEAM_ID = os.environ.get('FPL_TEAM_ID', '8201445')

RETURN_PTS = 6        # a starter at/above this "did"
BLANK_PTS = 2         # a starter at/below this "didn't"
BAD_RUN_FDR = 13      # sum of next-4 FDR at/above this = bad run
LOOKAHEAD_GWS = 4
MAX_MOVERS = 8


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_env(path):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def smtp_creds():
    if os.environ.get('EMAIL_USER') and os.environ.get('EMAIL_PASSWORD'):
        return {k: os.environ.get(k) for k in ('EMAIL_USER', 'EMAIL_PASSWORD', 'EMAIL_TO')}
    return load_env(ENV_PATH) if ENV_PATH.exists() else {}


def send_email(subject, body):
    env = smtp_creds()
    user, password = env.get('EMAIL_USER'), env.get('EMAIL_PASSWORD')
    if not user or not password:
        print('email not configured — skipping send')
        return
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = user
    msg['To'] = env.get('EMAIL_TO') or user
    msg.set_content(body)
    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)


def estimate_free_transfers(history_current):
    # 1 FT granted per GW from GW2, bankable to 5. Chips (WC/FH) not modelled;
    # this is an estimate — trust the site over this number.
    ft = 1
    for ev in history_current[1:]:
        ft = min(5, max(1, ft - ev['event_transfers'] + 1))
    return ft


def build_report():
    boot = get(f'{API}/bootstrap-static/')
    fixtures = get(f'{API}/fixtures/')
    history = get(f'{API}/entry/{TEAM_ID}/history/')

    players = {p['id']: p for p in boot['elements']}
    teams = {t['id']: t for t in boot['teams']}
    pos = {e['id']: e['singular_name_short'] for e in boot['element_types']}

    gw = max((e['id'] for e in boot['events'] if e['finished']), default=None)
    if gw is None:
        return 'season not started', 'No finished gameweek yet — nothing to report.'
    event = next(e for e in boot['events'] if e['id'] == gw)
    nxt = next((e for e in boot['events'] if e['is_next']), None)

    picks = get(f'{API}/entry/{TEAM_ID}/event/{gw}/picks/')
    live = {e['id']: e['stats'] for e in get(f'{API}/event/{gw}/live/')['elements']}

    eh = picks['entry_history']
    ft = estimate_free_transfers(history['current'])
    bank = eh['bank'] / 10

    # next-LOOKAHEAD fixtures per team
    runs = {}
    for f in fixtures:
        if f['event'] and gw < f['event'] <= gw + LOOKAHEAD_GWS:
            runs.setdefault(f['team_h'], []).append(
                (f['event'], teams[f['team_a']]['short_name'], 'H', f['team_h_difficulty']))
            runs.setdefault(f['team_a'], []).append(
                (f['event'], teams[f['team_h']]['short_name'], 'A', f['team_a_difficulty']))

    def run_str(tid):
        fl = sorted(runs.get(tid, []))
        return ' '.join(f'{o}({ha}{d})' for _, o, ha, d in fl), sum(d for _, _, _, d in fl)

    starters = [pk for pk in picks['picks'] if pk['position'] <= 11]
    bench = [pk for pk in picks['picks'] if pk['position'] > 11]
    cap = next(pk for pk in picks['picks'] if pk['is_captain'])

    lines = [
        f"GW{gw} debrief — {eh['points']} pts (avg {event['average_entry_score']}, "
        f"high {event['highest_score']})",
        f"overall rank {eh['overall_rank']:,} · bank {bank:.1f} · "
        f"team value {eh['value'] / 10:.1f} · ~{ft} free transfer(s)",
    ]
    if nxt:
        lines.append(f"next deadline: GW{nxt['id']} — {nxt['deadline_time']} (UTC)")
    lines.append('')

    def pname(pk):
        return players[pk['element']]['web_name']

    def ppts(pk):
        return live.get(pk['element'], {}).get('total_points', 0)

    def pmins(pk):
        return live.get(pk['element'], {}).get('minutes', 0)

    cp = players[cap['element']]
    lines.append(f"captain: {cp['web_name']} {ppts(cap)} pts "
                 f"(doubled {ppts(cap) * cap['multiplier']})")
    best = max(starters, key=ppts)
    if best['element'] != cap['element']:
        lines.append(f"best in XI was {pname(best)} with {ppts(best)}")
    subs = picks.get('automatic_subs') or []
    if subs:
        lines.append('auto subs: ' + ', '.join(
            f"{players[s['element_in']]['web_name']} for "
            f"{players[s['element_out']]['web_name']}" for s in subs))
    bench_pts = sum(ppts(pk) for pk in bench)
    lines.append(f'points left on bench: {bench_pts}')
    lines.append('')

    did = sorted((pk for pk in starters if ppts(pk) >= RETURN_PTS), key=ppts, reverse=True)
    didnt = sorted((pk for pk in starters if ppts(pk) <= BLANK_PTS), key=ppts)
    lines.append('WHO DID: ' + (', '.join(f'{pname(pk)} {ppts(pk)}' for pk in did) or 'nobody'))
    lines.append("WHO DIDN'T (<= %d pts): " % BLANK_PTS + (', '.join(
        f'{pname(pk)} {ppts(pk)} ({pmins(pk)}m)' for pk in didnt) or 'nobody'))
    ghosts = [pk for pk in bench if pmins(pk) == 0]
    if ghosts:
        lines.append('bench, no minutes: ' + ', '.join(pname(pk) for pk in ghosts))
    lines.append('')

    flagged = [players[pk['element']] for pk in picks['picks']
               if players[pk['element']]['status'] != 'a' or players[pk['element']]['news']]
    lines.append('FLAGS:')
    if flagged:
        for p in flagged:
            chance = p['chance_of_playing_next_round']
            lines.append(f"  {p['web_name']} [{p['status']}] {p['news']}"
                         + (f' ({chance}%)' if chance is not None else ''))
    else:
        lines.append('  none — clean bill of health')
    lines.append('')

    # exposure to teams with a bad upcoming run
    by_team = {}
    for pk in picks['picks']:
        by_team.setdefault(players[pk['element']]['team'], []).append(pk)
    lines.append(f'FIXTURE TROUBLE (next {LOOKAHEAD_GWS}, sum FDR >= {BAD_RUN_FDR}):')
    trouble_teams = set()
    for tid, pks in sorted(by_team.items(), key=lambda kv: -len(kv[1])):
        rs, tot = run_str(tid)
        if tot >= BAD_RUN_FDR:
            trouble_teams.add(tid)
            lines.append(f"  {teams[tid]['short_name']} x{len(pks)} "
                         f"({', '.join(pname(pk) for pk in pks)}): {rs} = {tot}")
    if not trouble_teams:
        lines.append('  none')
    lines.append('')

    # transfer-out candidates: flagged, or blanked starters on a bad run
    outs = []
    for pk in starters:
        p = players[pk['element']]
        why = []
        if p['status'] not in ('a',):
            why.append('flagged')
        if ppts(pk) <= BLANK_PTS and p['team'] in trouble_teams:
            why.append('blanked + bad run')
        if why:
            outs.append((pk, ', '.join(why)))
    lines.append('TRANSFER-OUT CANDIDATES:')
    if outs:
        for pk, why in outs:
            p = players[pk['element']]
            rs, tot = run_str(p['team'])
            lines.append(f"  {p['web_name']} ({pos[p['element_type']]} "
                         f"{teams[p['team']]['short_name']} {p['now_cost'] / 10:.1f}) — {why}; {rs}")
    else:
        lines.append('  none by the numbers — spend the Friday session on upside instead')
    lines.append('')

    owned = {pk['element'] for pk in picks['picks']}
    max_price = max((players[pk['element']]['now_cost'] for pk, _ in outs),
                    default=max(players[pk['element']]['now_cost'] for pk in picks['picks']))
    movers = sorted((p for p in boot['elements']
                     if p['id'] not in owned and p['status'] == 'a'
                     and p['now_cost'] <= max_price + eh['bank']),
                    key=lambda p: p['transfers_out_event'] - p['transfers_in_event'])[:MAX_MOVERS]
    lines.append('MARKET (top net transfers in, affordable):')
    for p in movers:
        net = p['transfers_in_event'] - p['transfers_out_event']
        gwp = live.get(p['id'], {}).get('total_points', 0)
        lines.append(f"  {p['web_name']:<16} {pos[p['element_type']]:<3} "
                     f"{teams[p['team']]['short_name']:<4} {p['now_cost'] / 10:>4.1f}  "
                     f"GW{gw} {gwp:>2}  net +{net:,}  owned {p['selected_by_percent']}%")
    lines.append('')
    lines.append('Decide actual moves in the Friday pre-deadline session, '
                 'against opposition and confirmed team news.')

    verdict = f"GW{gw}: {eh['points']} pts (avg {event['average_entry_score']})"
    return verdict, '\n'.join(lines)


def main():
    print_only = '--print' in sys.argv
    try:
        verdict, body = build_report()
        subject = f'FPL status — {verdict}'
    except Exception:
        body = ('The GW status report cron failed:\n\n' + traceback.format_exc()
                + '\nCheck: kubectl -n football logs job/<latest gw-status-report job>')
        subject = 'FPL status — CRON FAILED'
    print(body)
    if not print_only:
        send_email(subject, body)
        print('\nemail sent')


if __name__ == '__main__':
    main()
