"""
Fetches fuel prices from FuelWatch WA.
- data/prices.json  → Cockburn/Aubin Grove area prices + history
- data/by_suburb.json → per-suburb prices for ALL Perth metro suburbs (for location lookup)
Run by GitHub Actions.
"""
import requests
import xml.etree.ElementTree as ET
import json
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Default area (Cockburn / Aubin Grove) ────────────────────────────────────
DEFAULT_SUBURBS = [
    'COCKBURN CENTRAL', 'HAMMOND PARK', 'JANDAKOT', 'SUCCESS',
    'SOUTH LAKE', 'MUNSTER', 'SPEARWOOD', 'HAMILTON HILL',
]

# ── All Perth metro suburbs for location-based lookup ────────────────────────
# Each is fetched with Surrounding=1, so nearby stations are included.
# Spread across the metro to give good coverage everywhere.
ALL_METRO_SUBURBS = [
    # South (Cockburn / Fremantle)
    'COCKBURN CENTRAL', 'HAMMOND PARK', 'JANDAKOT', 'SUCCESS', 'SOUTH LAKE',
    'MUNSTER', 'SPEARWOOD', 'HAMILTON HILL', 'FREMANTLE', 'BEELIAR',
    'AUBIN GROVE', 'ATWELL', 'HARRISDALE', 'TREEBY', 'YANGEBUP',
    # Southeast
    'CANNING VALE', 'GOSNELLS', 'MADDINGTON', 'THORNLIE', 'SOUTHERN RIVER',
    'LANGFORD', 'HUNTINGDALE', 'CAMILLO',
    # East
    'MIDLAND', 'MIDVALE', 'BELLEVUE', 'GUILDFORD', 'BASSENDEAN',
    'BAYSWATER', 'MORLEY', 'BEECHBORO', 'BALLAJURA', 'MALAGA',
    # North
    'JOONDALUP', 'CURRAMBINE', 'OCEAN REEF', 'HILLARYS', 'DUNCRAIG',
    'KARRINYUP', 'SCARBOROUGH', 'BALCATTA', 'OSBORNE PARK', 'WANGARA',
    'WANNEROO', 'CLARKSON', 'BUTLER', 'MINDARIE',
    # CBD / Inner
    'PERTH', 'NORTHBRIDGE', 'LEEDERVILLE', 'SUBIACO', 'NEDLANDS',
    'CLAREMONT', 'COTTESLOE', 'VICTORIA PARK', 'BENTLEY', 'COMO',
    'SOUTH PERTH', 'WELSHPOOL', 'BELMONT', 'REDCLIFFE',
    # Southwest
    'ROCKINGHAM', 'SECRET HARBOUR', 'PORT KENNEDY', 'BALDIVIS',
    'KWINANA', 'MANDURAH',
]

FUEL_TYPES = {'1': 'Unleaded 91', '2': 'Premium 95'}
FUELWATCH_RSS = 'https://www.fuelwatch.wa.gov.au/fuelwatch/fuelWatchRSS'
DATA_DIR = Path(__file__).parent.parent / 'data'


def fetch_suburb(suburb, product, day):
    params = {'Product': product, 'Suburb': suburb, 'Day': day, 'Surrounding': '1'}
    try:
        resp = requests.get(FUELWATCH_RSS, params=params, timeout=15,
                            headers={'User-Agent': 'FuelWatch-GHPages/1.0'})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        stations = []
        for item in root.findall('.//item'):
            def get(tag, _item=item):
                el = _item.find(tag)
                return el.text.strip() if el is not None and el.text else ''
            price_str = get('price')
            if not price_str:
                continue
            try:
                stations.append({
                    'price': float(price_str),
                    'name':  get('trading-name'),
                    'brand': get('brand'),
                    'address': get('address'),
                    'suburb': get('location'),
                    'lat': get('latitude'),
                    'lng': get('longitude'),
                })
            except ValueError:
                pass
        return stations
    except Exception as e:
        return []


def dedup_sort(stations):
    seen = {}
    for s in stations:
        key = (s['name'], s['address'])
        if key not in seen:
            seen[key] = s
    return sorted(seen.values(), key=lambda x: x['price'])


def get_stations(suburbs, product, day):
    all_stations = []
    with ThreadPoolExecutor(max_workers=min(len(suburbs), 20)) as ex:
        futures = {ex.submit(fetch_suburb, s, product, day): s for s in suburbs}
        for f in as_completed(futures):
            all_stations.extend(f.result())
    return dedup_sort(all_stations)


def summarise(stations):
    if not stations:
        return None
    prices = [s['price'] for s in stations]
    return {
        'min':      min(prices),
        'avg':      round(sum(prices) / len(prices), 1),
        'max':      max(prices),
        'count':    len(stations),
        'cheapest': stations[0],
        'stations': stations[:15],
    }


def recommendation(today_min, tomorrow_min):
    if today_min is None or tomorrow_min is None:
        return None
    diff = round(tomorrow_min - today_min, 1)
    if diff <= -3:
        return {'action': 'wait', 'diff': diff, 'icon': '⏳',
                'text': f'Wait until tomorrow — prices drop {abs(diff)}c/L'}
    if diff >= 3:
        return {'action': 'fill', 'diff': diff, 'icon': '⛽',
                'text': f'Fill up today — prices rise {diff}c/L tomorrow'}
    return {'action': 'neutral', 'diff': diff, 'icon': '✓',
            'text': 'Prices are similar — fill up whenever suits you'}


def update_history(history, fuel_name, today_summary):
    if fuel_name not in history:
        history[fuel_name] = []
    today = date.today().isoformat()
    if not any(h['date'] == today for h in history[fuel_name]):
        history[fuel_name].append({
            'date':    today,
            'min':     today_summary['min'],
            'avg':     today_summary['avg'],
            'station': today_summary['cheapest']['name'],
            'suburb':  today_summary['cheapest']['suburb'],
        })
    history[fuel_name] = sorted(history[fuel_name], key=lambda h: h['date'])[-90:]


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    DATA_DIR.mkdir(exist_ok=True)
    history_path = DATA_DIR / 'history.json'
    history = json.loads(history_path.read_text()) if history_path.exists() else {}

    fetched_at = datetime.utcnow().strftime('%d %b %Y %H:%M UTC')

    # 1. Default area prices (today + tomorrow for both fuels)
    print('Fetching default area prices…')
    combos = [(code, name, day)
              for code, name in FUEL_TYPES.items()
              for day in ('today', 'tomorrow')]

    default_fetched = {}
    with ThreadPoolExecutor(max_workers=len(combos) * len(DEFAULT_SUBURBS)) as ex:
        futures = {ex.submit(get_stations, DEFAULT_SUBURBS, code, day): (name, day)
                   for code, name, day in combos}
        for f in as_completed(futures):
            name, day = futures[f]
            default_fetched[(name, day)] = f.result()

    result = {}
    for code, name in FUEL_TYPES.items():
        today_s    = summarise(default_fetched.get((name, 'today'), []))
        tomorrow_s = summarise(default_fetched.get((name, 'tomorrow'), []))
        if today_s:
            update_history(history, name, today_s)
        result[name] = {
            'today':          today_s,
            'tomorrow':       tomorrow_s,
            'recommendation': recommendation(today_s['min'] if today_s else None,
                                             tomorrow_s['min'] if tomorrow_s else None),
            'fetched_at':     fetched_at,
        }
    for name in result:
        result[name]['history'] = history.get(name, [])

    (DATA_DIR / 'prices.json').write_text(json.dumps(result, indent=2))
    history_path.write_text(json.dumps(history, indent=2))
    print('prices.json saved.')

    # 2. Per-suburb lookup (today only, both fuels) for location feature
    print(f'Fetching per-suburb data for {len(ALL_METRO_SUBURBS)} suburbs…')
    by_suburb = {}

    suburb_combos = [(suburb, code, name)
                     for suburb in ALL_METRO_SUBURBS
                     for code, name in FUEL_TYPES.items()]

    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(fetch_suburb, suburb, code, 'today'): (suburb, name)
                   for suburb, code, name in suburb_combos}
        for f in as_completed(futures):
            suburb, fuel_name = futures[f]
            stations = f.result()
            key = suburb.title()  # normalise: "COCKBURN CENTRAL" → "Cockburn Central"
            if key not in by_suburb:
                by_suburb[key] = {}
            s = summarise(stations)
            if s:
                by_suburb[key][fuel_name] = {
                    'min':      s['min'],
                    'avg':      s['avg'],
                    'count':    s['count'],
                    'stations': s['stations'],
                }

    # Also fetch tomorrow for the by_suburb data
    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(fetch_suburb, suburb, code, 'tomorrow'): (suburb, name)
                   for suburb, code, name in suburb_combos}
        for f in as_completed(futures):
            suburb, fuel_name = futures[f]
            stations = f.result()
            key = suburb.title()
            if key not in by_suburb:
                by_suburb[key] = {}
            s = summarise(stations)
            if s:
                fuel_key = fuel_name + '_tomorrow'
                by_suburb[key][fuel_key] = {
                    'min':      s['min'],
                    'avg':      s['avg'],
                    'count':    s['count'],
                    'stations': s['stations'],
                }

    (DATA_DIR / 'by_suburb.json').write_text(json.dumps(by_suburb, indent=2))
    print(f'by_suburb.json saved — {len(by_suburb)} suburbs.')

    # Summary
    for name, data in result.items():
        td = data['today']
        if td:
            print(f"  {name}: {td['min']}c/L min, {td['count']} stations")


if __name__ == '__main__':
    main()
