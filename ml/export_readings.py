"""
Export the per-minute reading log (/readings in the Realtime Database,
written by the firmware) to a CSV for training.

    python ml/export_readings.py                 # -> ml/data/readings.csv
    python ml/export_readings.py --out other.csv

Uses the same service account key as the web app (serviceAccountKey.json or
FIREBASE_KEY_PATH).
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from firebase_admin import db  # noqa: E402

from firebase_config import initialize_firebase  # noqa: E402

READINGS_PATH = '/readings'
FEATURES = ['temperature', 'ph', 'turbidity', 'orp', 'ec']
MANILA = timezone(timedelta(hours=8))

COLUMNS = (
    ['t', 'time_local']
    + FEATURES
    + [f'cal_{k}' for k in FEATURES]
    + ['battery_pct', 'lat', 'lon', 'via']
)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', default=os.path.join(ROOT, 'ml', 'data', 'readings.csv'))
    args = parser.parse_args()

    initialize_firebase()
    data = db.reference(READINGS_PATH).get() or {}
    rows = []
    for record in data.values():
        if not isinstance(record, dict) or not isinstance(record.get('t'), (int, float)):
            continue
        cal = record.get('cal') if isinstance(record.get('cal'), dict) else {}
        row = {
            't': int(record['t']),
            'time_local': datetime.fromtimestamp(record['t'] / 1000, MANILA).strftime('%Y-%m-%d %H:%M:%S'),
            'battery_pct': record.get('battery_pct'),
            'lat': record.get('lat'),
            'lon': record.get('lon'),
            'via': record.get('via'),
        }
        for key in FEATURES:
            row[key] = record.get(key)
            # The DS18B20 is factory calibrated, so temperature has no flag.
            row[f'cal_{key}'] = True if key == 'temperature' else cal.get(key)
        rows.append(row)

    rows.sort(key=lambda r: r['t'])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    if rows:
        print(f"Wrote {len(rows)} readings ({rows[0]['time_local']} to {rows[-1]['time_local']}) to {args.out}")
    else:
        print(f'No readings under {READINGS_PATH} yet. Flash the v5 firmware and let it run; '
              'it logs one reading per minute.')


if __name__ == '__main__':
    main()
