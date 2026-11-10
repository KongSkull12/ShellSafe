"""
Build a labeled training CSV with all five ShellSafe probes plus salinity.

Source: USGS 01400500, Raritan River at Manville, New Jersey (public domain).
It is one of the few public stations whose sonde records every ShellSafe
probe (temperature, pH, specific conductance, turbidity and ORP) together
with chlorophyll. Data come from the USGS Water Data API:
https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous

The 15-minute record is averaged into local days. Salinity is calculated
from EC and temperature with app/salinity.py, the same PSS-78 formula the
web app and firmware use, so the model sees salinity exactly as the live
system computes it.

Label: a day is bloom when its mean chlorophyll fluorescence is at or above
CHL_BLOOM_RFU (see the constant for why). Chlorophyll is only used for the
label, never as a model input.

Caveat: this is fresh river water (EC about 190-1,800 uS/cm, salinity under
1 ppt). Coastal ShellSafe readings sit far above that range, so the model's
EC and salinity splits will not transfer to the station. The Model page
shows this note.

Output: ml/data/raritan_bloom.csv
Then:   python ml/train.py --dataset ml/data/raritan_bloom.csv \
            --features temperature,ph,ec,turbidity,orp,salinity
"""

import importlib.util
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'data', 'raritan_bloom.csv')
RAW = os.path.join(HERE, 'data', 'raw', 'raritan')
SITE = 'USGS-01400500'
API = 'https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items'
LOCAL_TZ = 'America/New_York'
# ORP has been recorded here since April 2022.
START = pd.Timestamp('2022-04-01')
END = pd.Timestamp.now().normalize()

PARAMS = {
    'temperature': '00010',   # degC
    'ec': '00095',            # specific conductance at 25 degC, uS/cm
    'ph': '00400',
    'turbidity': '63680',     # FNU (comparable to the probe's NTU)
    'orp': '00090',           # mV
    'chlorophyll_rfu': '32315',
    'phycocyanin_rfu': '32321',
}
VALID = {
    'temperature': (0, 40),
    'ec': (0, 5000),
    'ph': (5, 10.5),
    'turbidity': (0, 1000),
    'orp': (-500, 800),
    'chlorophyll_rfu': (0, 1000),
    'phycocyanin_rfu': (0, 1000),
}
# A day counts when every probe logged at least half a day of 15-minute values.
MIN_SAMPLES_PER_DAY = 48
# Chlorophyll here is fluorescence in RFU, which has no fixed ug/L conversion,
# so the WHO ug/L levels used for the Charles River cannot be applied. A day is
# labeled bloom when its mean is at least this many RFU: about three times the
# typical day (median 0.48 RFU over 2022-2026), roughly the top 6% of days.
CHL_BLOOM_RFU = 1.5
NOTE_TEMPLATE = (
    '# proxy: USGS 01400500 Raritan River at Manville NJ, daily means of the public '
    '15-minute sonde, {start} to {end}. All five probes (temperature, pH, EC, '
    'turbidity, ORP) are measured; salinity is calculated from EC and temperature '
    '(PSS-78).'
)


def _salinity_fn():
    path = os.path.join(ROOT, 'app', 'salinity.py')
    spec = importlib.util.spec_from_file_location('shellsafe_salinity', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.salinity_psu


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={'User-Agent': 'ShellSafe-training'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                return json.load(resp)
        except Exception as exc:
            if attempt == 3:
                raise
            print(f'    retry after {exc.__class__.__name__}')
            time.sleep(5 * (attempt + 1))


def _quarter(name: str, code: str, start: pd.Timestamp) -> pd.DataFrame:
    end = min(start + pd.DateOffset(months=3), END)
    cached = os.path.join(RAW, f'{code}_{start:%Y-%m}.csv')
    if os.path.exists(cached):
        return pd.read_csv(cached)
    query = urllib.parse.urlencode({
        'f': 'json',
        'monitoring_location_id': SITE,
        'parameter_code': code,
        'time': f'{start:%Y-%m-%dT00:00:00Z}/{end:%Y-%m-%dT00:00:00Z}',
        'limit': 50000,
        'properties': 'time,value',
    })
    url, rows = f'{API}?{query}', []
    while url:
        page = _get_json(url)
        rows += [f['properties'] for f in page.get('features', [])]
        url = next((link['href'] for link in page.get('links', []) if link.get('rel') == 'next'), None)
    frame = pd.DataFrame(rows, columns=['time', 'value'])
    frame.to_csv(cached, index=False)
    # Only cache finished quarters; the current one keeps growing.
    if end >= END:
        os.remove(cached)
    print(f'  {name:16s} {start:%Y-%m}  {len(frame)} rows')
    return frame


def _daily(name: str, code: str) -> pd.DataFrame:
    parts, start = [], START
    while start < END:
        parts.append(_quarter(name, code, start))
        start += pd.DateOffset(months=3)
    raw = pd.concat(parts, ignore_index=True)
    raw['value'] = pd.to_numeric(raw['value'], errors='coerce')
    low, high = VALID[name]
    raw = raw[raw['value'].between(low, high)].copy()
    raw['day'] = pd.to_datetime(raw['time'], utc=True).dt.tz_convert(LOCAL_TZ).dt.strftime('%Y-%m-%d')
    daily = raw.groupby('day')['value'].agg(['mean', 'size'])
    daily = daily[daily['size'] >= MIN_SAMPLES_PER_DAY]['mean'].rename(name)
    print(f'{name}: {len(daily)} usable days')
    return daily


def main():
    os.makedirs(RAW, exist_ok=True)
    days = pd.concat([_daily(name, code) for name, code in PARAMS.items()], axis=1)
    days = days.dropna(subset=['temperature', 'ph', 'ec', 'turbidity', 'orp', 'chlorophyll_rfu'])
    salinity_psu = _salinity_fn()
    days['salinity'] = [salinity_psu(ec, t) for ec, t in zip(days['ec'], days['temperature'])]
    days = days.dropna(subset=['salinity'])

    chl = days['chlorophyll_rfu']
    print('\nDaily mean chlorophyll (RFU) percentiles:')
    print(chl.quantile([0.5, 0.75, 0.9, 0.95, 0.98, 0.99]).round(2).to_string())
    if CHL_BLOOM_RFU is None:
        sys.exit('\nSet CHL_BLOOM_RFU from the distribution above, then run again.')

    out = days.reset_index().rename(columns={'index': 'day'})
    stamp = pd.to_datetime(out['day']).dt.tz_localize(LOCAL_TZ) + pd.Timedelta(hours=12)
    out['time'] = stamp.dt.tz_convert('UTC').dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    # Hold out whole weeks: neighbouring days are nearly identical.
    iso = pd.to_datetime(out['day']).dt.isocalendar()
    out['group'] = iso['year'].astype(str) + '-W' + iso['week'].astype(str).str.zfill(2)
    out['label'] = (out['chlorophyll_rfu'] >= CHL_BLOOM_RFU).map({True: 'bloom', False: 'no_bloom'})
    cols = ['time', 'temperature', 'ph', 'ec', 'turbidity', 'orp', 'salinity',
            'chlorophyll_rfu', 'phycocyanin_rfu', 'label', 'group']
    out = out[cols].round(4)

    counts = out['label'].value_counts().to_dict()
    bloom_weeks = out.loc[out['label'] == 'bloom', 'group'].nunique()
    print(f"\nDays: {len(out)}  bloom {counts.get('bloom', 0)}  no_bloom {counts.get('no_bloom', 0)}"
          f"  bloom weeks {bloom_weeks}")
    if min(counts.get('bloom', 0), counts.get('no_bloom', 0)) < 10:
        sys.exit('Not enough days of both classes to train.')

    note = NOTE_TEMPLATE.format(start=out['time'].min()[:10], end=out['time'].max()[:10])
    with open(OUT, 'w', encoding='utf-8', newline='') as fh:
        fh.write(note + '\n')
        out.to_csv(fh, index=False)
    print(f'Wrote {OUT}')


if __name__ == '__main__':
    main()
