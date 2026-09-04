"""Friday pre-deadline planner email — companion to gw_status_report.py.

Calls the FPL assistant's unauthenticated planner preview endpoint
(/api/manage/preview — one Sonnet call inside the app) and emails the
proposed transfers, captain and chip for the upcoming gameweek. This is a
PROPOSAL: nothing is submitted. Confirming happens in the Manage tab or via
the confirm endpoints with a fresh token.

Stdlib only; email creds from the environment (k8s Secret `haaland-smtp`)
with the usual ~/the-tissue/.env fallback.

Usage: python3 friday_planner_email.py [--print]   (--print skips the email)
"""
import json
import os
import smtplib
import sys
import traceback
import urllib.request
from email.message import EmailMessage
from pathlib import Path

APP_URL = os.environ.get('APP_URL', 'http://fpl-assistant.football.svc.cluster.local:8000')
FPL_API = 'https://fantasy.premierleague.com/api'
ENV_PATH = Path.home() / 'the-tissue' / '.env'


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
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


def build_report():
    boot = get(f'{FPL_API}/bootstrap-static/')
    nxt = next((e for e in boot['events'] if e['is_next']), None)
    if nxt is None:
        return 'season over', 'No upcoming gameweek — nothing to plan.'

    data = get(f'{APP_URL}/api/manage/preview')  # the slow bit: one Claude call
    recs = data['recommendations']

    lines = [
        f"GW{nxt['id']} plan — deadline {nxt['deadline_time']} (UTC)",
        f"~{data['free_transfers']} free transfer(s) · chips in window: "
        + (', '.join(data['available_chips']) or 'none'),
        '',
    ]

    cap, vice = recs.get('captain') or {}, recs.get('vice_captain') or {}
    lines.append(f"CAPTAIN: {cap.get('player_name', '?')} — {cap.get('reasoning', '')}")
    lines.append(f"VICE:    {vice.get('player_name', '?')} — {vice.get('reasoning', '')}")
    lines.append('')

    transfers = recs.get('transfers') or []
    lines.append('TRANSFERS PROPOSED:' if transfers else 'TRANSFERS PROPOSED: none — hold/bank.')
    for t in transfers:
        lines.append(
            f"  OUT {t.get('out_player_name')} ({t.get('out_selling_price_millions')}) -> "
            f"IN {t.get('in_player_name')} ({t.get('in_cost_millions')})"
        )
        if t.get('reasoning'):
            lines.append(f"      {t['reasoning']}")
    bc = recs.get('budget_check') or {}
    if bc:
        lines.append(f"  budget: bank {bc.get('bank_millions')} + sold {bc.get('total_sold_millions')} "
                     f"- bought {bc.get('total_bought_millions')} = {bc.get('remaining_bank_millions')} left")
    for key in ('_budget_warning', '_duplicate_warning'):
        if recs.get(key):
            lines.append(f"  !! {recs[key]}")
    lines.append('')

    chip = (recs.get('chip') or {})
    lines.append(f"CHIP: {chip.get('name') or 'none'}"
                 + (f" — {chip['reasoning']}" if chip.get('reasoning') else ''))
    if recs.get('summary'):
        lines.append('')
        lines.append(recs['summary'])
    lines += [
        '',
        f"({data.get('note', '')})",
        'This is a proposal only — nothing has been submitted. Confirm in the',
        'Manage tab, or via the confirm endpoints with a fresh token.',
    ]
    n_tr = len(transfers)
    verdict = f"GW{nxt['id']}: {n_tr} transfer(s), C {cap.get('player_name', '?')}"
    return verdict, '\n'.join(lines)


def main():
    print_only = '--print' in sys.argv
    try:
        verdict, body = build_report()
        subject = f'FPL Friday plan — {verdict}'
    except Exception:
        body = ('The Friday planner cron failed:\n\n' + traceback.format_exc()
                + '\nCheck: kubectl -n football logs job/<latest friday-planner job>')
        subject = 'FPL Friday plan — CRON FAILED'
    print(body)
    if not print_only:
        send_email(subject, body)
        print('\nemail sent')


if __name__ == '__main__':
    main()
