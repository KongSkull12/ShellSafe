"""
Build a labeled training CSV when this station has no field observations yet.

Source: U.S. EPA Region 1 Charles River buoy, Boston (public domain).
https://www3.epa.gov/region1/buoys/charles/crbuoyYYYY.csv

Each file is a 15-minute sonde. This script keeps years that publish an
estimated chlorophyll-a in ug/L, averages each hour, and labels the hour:

  bloom     estimated chlorophyll-a >= 50 ug/L
  no_bloom  otherwise

50 ug/L is WHO Alert Level 2 for cyanobacteria in recreational water (a
moderate chance of adverse effects). On this eutrophic river, 10 ug/L is a
typical hour, so that lower cutoff would label most of the record as bloom.
The label is still a biomass stand-in, not a shellfish-toxin test and not a
reading from this project. Rows are 6-hour means so near-duplicate 15-minute
samples are not treated as separate observations.

Temperature, pH and turbidity are kept. ORP is not on this buoy. Specific
conductivity is river water (about 1-6 mS/cm), which does not overlap
coastal seawater, so EC is left out. A model that saw that EC would treat
every seawater reading as out of range.

Output: ml/data/public_bloom.csv
Then:   python ml/train.py --dataset ml/data/public_bloom.csv --features temperature,ph,turbidity
"""

import io
import os
import sys
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'data', 'public_bloom.csv')
RAW = os.path.join(HERE, 'data', 'raw')
URL = 'https://www3.epa.gov/region1/buoys/charles/crbuoy{year}.csv'
YEARS = range(2018, 2027)
# WHO recreational guidelines, cyanobacteria Alert Level 2.
CHL_BLOOM_UG_L = 50.0
NOTE = (
    '# proxy: EPA Region 1 Charles River buoy (Boston), 6-hour means of the public '
    '15-minute sonde, 2021-2026. Bloom means estimated chlorophyll-a >= 50 ug/L '
    '(WHO recreational Alert Level 2). Temperature, pH and turbidity only: '
    'this record has no ORP, and river conductivity is not comparable to coastal '
    'seawater. Not this station.'
)


def _find(columns, *needles, exclude=()):
    for col in columns:
        name = str(col).strip().lower()
        if any(bad in name for bad in exclude):
            continue
        if all(needle in name for needle in needles):
            return col
    return None


def _load_year(year: int) -> pd.DataFrame:
    os.makedirs(RAW, exist_ok=True)
    cached = os.path.join(RAW, f'crbuoy{year}.csv')
    if os.path.exists(cached) and os.path.getsize(cached) > 0:
        frame = pd.read_csv(cached)
    else:
        url = URL.format(year=year)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'ShellSafe-training'})
            raw = urllib.request.urlopen(request, timeout=90).read()
        except Exception as exc:
            print(f'{year}: skipped ({exc.__class__.__name__})')
            return pd.DataFrame()
        with open(cached, 'wb') as fh:
            fh.write(raw)
        frame = pd.read_csv(io.BytesIO(raw))
    cols = list(frame.columns)
    temp = _find(cols, 'temp')
    ph = next((c for c in cols if str(c).strip().lower() == 'ph'), None)
    turb = _find(cols, 'turbidity')
    chl = _find(cols, 'chl', 'ug', exclude=('rfu',))
    date = _find(cols, 'date')
    clock = _find(cols, 'time')
    if not all([temp, ph, turb, chl, date, clock]):
        print(f'{year}: skipped (no estimated chlorophyll-a column)')
        return pd.DataFrame()

    out = pd.DataFrame({
        'time_local': pd.to_datetime(
            frame[date].astype(str).str.strip() + ' ' + frame[clock].astype(str).str.strip(),
            format='mixed',
            errors='coerce',
        ),
        'temperature': pd.to_numeric(frame[temp], errors='coerce'),
        'ph': pd.to_numeric(frame[ph], errors='coerce'),
        'turbidity': pd.to_numeric(frame[turb], errors='coerce'),
        'chlorophyll_ug_l': pd.to_numeric(frame[chl], errors='coerce'),
    }).dropna()
    out = out[
        out['temperature'].between(0, 40)
        & out['ph'].between(5, 10.5)
        & out['turbidity'].between(0, 100)
        & out['chlorophyll_ug_l'].between(0, 500)
    ]
    print(f'{year}: {len(out)} usable 15-minute rows')
    return out


def main():
    parts = [frame for frame in (_load_year(year) for year in YEARS) if not frame.empty]
    if not parts:
        sys.exit('No buoy files with estimated chlorophyll-a could be downloaded.')
    raw = pd.concat(parts, ignore_index=True)
    raw['time_local'] = raw['time_local'].dt.tz_localize(
        'America/New_York', ambiguous='NaT', nonexistent='NaT'
    )
    raw = raw.dropna(subset=['time_local'])
    raw['block'] = raw['time_local'].dt.floor('6h')
    blocks = (
        raw.groupby('block', as_index=False)
        .agg(
            n=('chlorophyll_ug_l', 'size'),
            temperature=('temperature', 'mean'),
            ph=('ph', 'mean'),
            turbidity=('turbidity', 'mean'),
            chlorophyll_ug_l=('chlorophyll_ug_l', 'max'),
        )
    )
    # A block needs at least an hour of readings, and is a bloom if chlorophyll
    # reached the alert level at any point in those six hours.
    blocks = blocks[blocks['n'] >= 4].copy()
    blocks['label'] = (blocks['chlorophyll_ug_l'] >= CHL_BLOOM_UG_L).map({True: 'bloom', False: 'no_bloom'})
    blocks['time'] = blocks['block'].dt.tz_convert('UTC').dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    out = blocks[['time', 'temperature', 'ph', 'turbidity', 'chlorophyll_ug_l', 'label']]
    out = out.round({'temperature': 3, 'ph': 3, 'turbidity': 3, 'chlorophyll_ug_l': 3})

    counts = out['label'].value_counts().to_dict()
    print(f"Blocks: {len(out)}  bloom {counts.get('bloom', 0)}  no_bloom {counts.get('no_bloom', 0)}")
    if min(counts.get('bloom', 0), counts.get('no_bloom', 0)) < 10:
        sys.exit('Not enough hours of both classes to train.')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='') as fh:
        fh.write(NOTE + '\n')
        out.to_csv(fh, index=False)
    print(f'Wrote {OUT}')


if __name__ == '__main__':
    main()
