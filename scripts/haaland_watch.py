"""Weekly Haaland pivot-watch (2026/27 FPL) — runs on pi-a via cron.

We deliberately drafted the no-Haaland spread squad (football repo,
scripts/preseason/DRAFT.md). The optimizer only flips to a Haaland build if
he's tracking a ~263-pt season. This script pulls live FPL data every week
and emails a verdict:

  PIVOT SIGNAL — xG/90 and points pace both say monster season; start the
                 2-3 FT restructure (a FWD slot + a MCI slot must open).
  WATCH        — one of the two indicators is hot; keep banking FTs.
  HOLD         — normal-Haaland world; the spread squad thesis stands.
  TOO EARLY    — fewer than 3 finished GWs; sample is pure noise.

Decision window is GW4-5 with banked FTs; wildcard is the late escape hatch.

Stdlib only. Email creds are reused (read-only) from ~/the-tissue/.env
(EMAIL_USER / EMAIL_PASSWORD / EMAIL_TO, Gmail SMTP) — same channel as the
old Tissue cron emails.

Usage: python3 haaland_watch.py [--print]   (--print skips the email)
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

XG90_THRESHOLD = 1.00      # underlying elite-hot striker rate
PACE_THRESHOLD = 260       # season points pace where the optimizer flips (~263)
MIN_GWS_FOR_VERDICT = 3    # below this, any verdict is noise


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
    # Prefer environment (k8s Secret in-cluster); fall back to the .env file
    # (local run on pi-a). Same script works in both homes.
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
    d = get(f'{API}/bootstrap-static/')
    gws = sum(1 for e in d['events'] if e['finished'])

    def find(web_name):
        return next(e for e in d['elements'] if e['web_name'] == web_name)

    h = find('Haaland')
    bf = find('B.Fernandes')

    mins = h['minutes']
    xg = float(h['expected_goals'] or 0)
    xg90 = xg / mins * 90 if mins else 0.0
    pace = h['total_points'] / gws * 38 if gws else 0.0
    hot_xg, hot_pace = xg90 >= XG90_THRESHOLD, pace >= PACE_THRESHOLD

    if gws < MIN_GWS_FOR_VERDICT:
        verdict = f'TOO EARLY ({gws}/{MIN_GWS_FOR_VERDICT} GWs)'
        advice = 'Bank the free transfer; check again next week.'
    elif hot_xg and hot_pace:
        verdict = 'PIVOT SIGNAL'
        advice = ('Both indicators hot. Plan the restructure: a FWD slot and '
                  'a MCI slot must open (e.g. Joao Pedro + Anderson out, '
                  'Haaland + a ~6.0 mid in). Needs 2-3 banked FTs.')
    elif hot_xg or hot_pace:
        verdict = 'WATCH'
        advice = ('One indicator hot. Keep banking FTs; re-check next week '
                  'before committing.')
    else:
        verdict = 'HOLD'
        advice = 'Normal-Haaland world. The spread squad thesis stands; do nothing.'

    flag = f"  [{h['status']}: {h['news']}]" if h['news'] else ''
    body = '\n'.join([
        f'Haaland watch — after {gws} finished GW(s)',
        '',
        f"  price     GBP {h['now_cost'] / 10}m   owned {h['selected_by_percent']}%{flag}",
        f"  points    {h['total_points']}  ->  season pace {pace:.0f}  "
        f"(flip point ~{PACE_THRESHOLD}) {'HOT' if hot_pace else 'ok'}",
        f'  minutes   {mins}   xG {xg:.2f}  ->  xG/90 {xg90:.2f}  '
        f"(threshold {XG90_THRESHOLD:.2f}) {'HOT' if hot_xg else 'ok'}",
        f"  vs our captain: B.Fernandes {bf['total_points']} pts "
        f"(doubled: {bf['total_points'] * 2})",
        '',
        f'VERDICT: {verdict}',
        advice,
    ])
    return verdict.split(' (')[0], body


def main():
    print_only = '--print' in sys.argv
    try:
        verdict, body = build_report()
        subject = f'Haaland watch — {verdict}'
    except Exception:
        verdict = 'ERROR'
        body = ('The Haaland watch cron failed:\n\n' + traceback.format_exc()
                + "\nCheck: ssh pi-a 'tail -40 ~/fpl/haaland_watch.log'")
        subject = 'Haaland watch — CRON FAILED'
    print(body)
    if not print_only:
        send_email(subject, body)
        print('\nemail sent')


if __name__ == '__main__':
    main()
