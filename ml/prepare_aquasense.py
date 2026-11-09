"""
Turn AquaSense_Dataset.csv into the training file ml/train.py expects.

Bloom is the file's own incident_type value algal_bloom_crash. Other
incidents (cold front, ammonia spike, turbidity spike, dissolved-oxygen dip)
stay no_bloom, because this model is only for algal bloom.

Kept columns match ShellSafe probes used for bloom prediction: temperature,
pH, turbidity, and ORP. AquaSense has no ORP probe, so ORP is estimated from
dissolved oxygen (common redox/DO link) so the four-input model can train
until this station has labeled ORP field data. Salinity is left out (pond
~0.4 ppt is not coastal EC). A group column (pond + date) lets training
hold out a whole pond-day.

The source CSV belongs at ml/data/AquaSense_Dataset.csv.
"""

import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'data', 'AquaSense_Dataset.csv')
OUT = os.path.join(HERE, 'data', 'aquasense_bloom.csv')
NOTE = (
    '# proxy: AquaSense pond dataset, hourly, January 2026, 15 ponds. '
    'Bloom means incident_type algal_bloom_crash. Features: temperature, pH, '
    'turbidity, ORP (ORP estimated from DO for training transfer). '
    'Not this station.'
)


def main():
    if not os.path.exists(SRC):
        sys.exit(f'Missing {SRC}')
    df = pd.read_csv(SRC)
    needed = ['pond_id', 'timestamp', 'pH', 'Temperature_C', 'Turbidity_NTU', 'DO_mgL', 'incident_type']
    missing = [c for c in needed if c not in df.columns]
    if missing:
        sys.exit(f'{SRC} is missing columns: {", ".join(missing)}')

    temperature = pd.to_numeric(df['Temperature_C'], errors='coerce')
    ph = pd.to_numeric(df['pH'], errors='coerce')
    turbidity = pd.to_numeric(df['Turbidity_NTU'], errors='coerce')
    do = pd.to_numeric(df['DO_mgL'], errors='coerce')
    # Map DO (mg/L) into a plausible ORP band (mV) so ShellSafe's ORP input
    # can be used at inference. Typical healthy water sits ~200–400 mV.
    orp = (180.0 + 28.0 * do.clip(lower=0.0, upper=14.0) - 12.0 * (ph - 7.0)).clip(50.0, 550.0)

    out = pd.DataFrame({
        'time': pd.to_datetime(df['timestamp'], errors='coerce'),
        'temperature': temperature,
        'ph': ph,
        'turbidity': turbidity,
        'orp': orp,
        'pond_id': df['pond_id'].astype(str),
        'incident_type': df['incident_type'].fillna('').astype(str),
    }).dropna(subset=['time', 'temperature', 'ph', 'turbidity', 'orp'])
    out['label'] = out['incident_type'].str.strip().eq('algal_bloom_crash').map({True: 'bloom', False: 'no_bloom'})
    out['group'] = out['pond_id'] + ' ' + out['time'].dt.strftime('%Y-%m-%d')
    out['time'] = out['time'].dt.tz_localize('Asia/Manila').dt.tz_convert('UTC').dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    out = out[['time', 'temperature', 'ph', 'turbidity', 'orp', 'label', 'group']]

    counts = out['label'].value_counts().to_dict()
    bloom_groups = out.loc[out['label'] == 'bloom', 'group'].nunique()
    print(f"Rows: {len(out)}  bloom {counts.get('bloom', 0)}  no_bloom {counts.get('no_bloom', 0)}  bloom pond-days {bloom_groups}")
    if min(counts.get('bloom', 0), counts.get('no_bloom', 0)) < 10:
        sys.exit('Not enough rows of both classes to train.')

    with open(OUT, 'w', encoding='utf-8', newline='') as fh:
        fh.write(NOTE + '\n')
        out.to_csv(fh, index=False)
    print(f'Wrote {OUT}')


if __name__ == '__main__':
    main()
