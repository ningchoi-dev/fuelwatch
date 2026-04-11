"""
Fetches fuel prices from FuelWatch WA and saves them to data/prices.json.
Run by GitHub Actions every 4 hours.
"""
import requests
import xml.etree.ElementTree as ET
import json
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SUBURBS = [
    'COCKBURN CENTRAL',
    'HAMMOND PARK',
    'JANDAKOT',
    'SUCCESS',
    'SOUTH LAKE',
    'MUNSTER',
    'SPEARWOOD',
    'HAMILTON HILL',
]

FUEL_TYPES = {
    '1': 'Unleaded 91',
    '2': 'Premium 95',
}

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
                    'name': get('trading-name'),
                    'brand': get('brand'),
                    'address': get('address'),
                    'suburb': get('location'),
                })
            except ValueError:
                pass
        return stations
    except Exception as e:
        print(f'  Warning: {suburb} {day} failed: {e}')
        return []


def get_stations(product, day):
    seen = {}
    tasks = [(s, product, day) for s in SUBURBS]
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {ex.submit(fetch_suburb, s, p, d): (s, p, d) for s, p, d in tasks}
        for future in as_completed(futures):
            for station in future.result():
                key = (station['name'], station['address'])
                if key not in seen:
                    seen[key] = station
    return sorted(seen.values(), key=lambda x: x['price'])


def summarise(stations):
    if not stations:
        return None
    prices = [s['price'] for s in stations]
    return {
        'min': min(prices),
        'avg': round(sum(prices) / len(prices), 1),
        'max': max(prices),
        'count': len(stations),
        'cheapest': stations[0],
        'stations': stations[:15],
    }


def recommendation(today_min, tomorrow_min):
    if today_min is None or tomorrow_min is None:
        return None
    diff = round(tomorrow_min - today_min, 1)
    if diff <= -3:
        return {'action': 'wait', 'diff': diff,
                'text': f'Wait until tomorrow — prices drop {abs(diff)}c/L', 'icon': '⏳'}
    elif diff >= 3:
        return {'action': 'fill', 'diff': diff,
                'text': f'Fill up today — prices rise {diff}c/L tomorrow', 'icon': '⛽'}
    return {'action': 'neutral', 'diff': diff,
            'text': 'Prices are similar — fill up whenever suits you', 'icon': '✓'}


def update_history(history, fuel_name, today_summary):
    if fuel_name not in history:
        history[fuel_name] = []
    today = date.today().isoformat()
    # Only add once per day
    if not any(h['date'] == today for h in history[fuel_name]):
        history[fuel_name].append({
            'date': today,
            'min': today_summary['min'],
            'avg': today_summary['avg'],
            'station': today_summary['cheapest']['name'],
            'suburb': today_summary['cheapest']['suburb'],
        })
    # Keep last 90 days
    history[fuel_name] = sorted(history[fuel_name], key=lambda h: h['date'])[-90:]


def main():
    DATA_DIR.mkdir(exist_ok=True)

    # Load existing history
    history_path = DATA_DIR / 'history.json'
    history = json.loads(history_path.read_text()) if history_path.exists() else {}

    # Fetch all combinations in parallel
    combos = [(code, name, day)
              for code, name in FUEL_TYPES.items()
              for day in ('today', 'tomorrow')]

    fetched = {}
    with ThreadPoolExecutor(max_workers=len(combos) * len(SUBURBS)) as ex:
        futures = {ex.submit(get_stations, code, day): (name, day)
                   for code, name, day in combos}
        for future in as_completed(futures):
            name, day = futures[future]
            fetched[(name, day)] = future.result()

    # Build output
    result = {}
    for code, name in FUEL_TYPES.items():
        today_s = summarise(fetched.get((name, 'today'), []))
        tomorrow_s = summarise(fetched.get((name, 'tomorrow'), []))

        if today_s:
            update_history(history, name, today_s)

        result[name] = {
            'today': today_s,
            'tomorrow': tomorrow_s,
            'recommendation': recommendation(
                today_s['min'] if today_s else None,
                tomorrow_s['min'] if tomorrow_s else None,
            ),
            'fetched_at': datetime.utcnow().strftime('%d %b %Y %H:%M UTC'),
        }

    # Attach history
    for name in result:
        result[name]['history'] = history.get(name, [])

    # Save
    (DATA_DIR / 'prices.json').write_text(json.dumps(result, indent=2))
    history_path.write_text(json.dumps(history, indent=2))

    for name, data in result.items():
        td = data['today']
        if td:
            print(f"{name}: {td['min']}c/L min, {td['count']} stations")


if __name__ == '__main__':
    main()
